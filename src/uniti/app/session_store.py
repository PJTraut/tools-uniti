"""Crash-safe immutable publication for bounded UNITI session state."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from uniti.core.history import HistorySnapshot, HistoryTruncation, estimate_transaction_bytes

from .atomic_json import atomic_write_bytes, sync_directory_strict, utc_timestamp
from .cleanup import CleanupReport, is_durable_session_artifact_name
from .session import (
    MAX_MANIFEST_BYTES,
    FindReplaceHistoryPack,
    HistoryPack,
    HistoryPackReference,
    LoadedSession,
    PersistenceNotice,
    SessionManifest,
    SessionProblem,
    SessionSnapshot,
    UnsupportedSessionSchema,
    decode_find_replace_pack,
    decode_history_pack,
    encode_find_replace_pack,
    encode_history_pack,
    manifest_from_payload,
    manifest_to_payload,
)


MIN_FREE_BYTES = 512 << 20
AGGREGATE_HISTORY_BYTES = 256 << 20
HISTORY_RETENTION = timedelta(days=7)
MAX_GENERATIONS_INSPECTED = 200

_GENERATION_RE = re.compile(r"(?P<number>[0-9]{20})-[0-9a-f]{32}\Z")


class StorageBackend(Protocol):
    def free_bytes(self, path: Path) -> int: ...

    def mkdir(self, path: Path) -> None: ...

    def write_synced(self, path: Path, data: bytes) -> None: ...

    def replace(self, source: Path, destination: Path) -> None: ...

    def sync_directory(self, path: Path) -> None: ...

    def unlink(self, path: Path) -> None: ...

    def iterdir(self, path: Path) -> Iterable[Path]: ...

    def read_bytes(self, path: Path) -> bytes: ...

    def exists(self, path: Path) -> bool: ...


class LocalStorageBackend:
    """Strict filesystem backend confined to one UNITI-owned root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _owned(self, path: Path) -> Path:
        candidate = Path(path).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"session path is outside owned root: {path}") from exc
        return candidate

    def free_bytes(self, path: Path) -> int:
        return shutil.disk_usage(self._owned(path)).free

    def mkdir(self, path: Path) -> None:
        self._owned(path).mkdir(parents=True, exist_ok=True, mode=0o700)

    def write_synced(self, path: Path, data: bytes) -> None:
        atomic_write_bytes(
            self._owned(path),
            data,
            mode=0o600,
            strict_directory_sync=True,
        )

    def replace(self, source: Path, destination: Path) -> None:
        os.replace(self._owned(source), self._owned(destination))

    def sync_directory(self, path: Path) -> None:
        sync_directory_strict(self._owned(path))

    def unlink(self, path: Path) -> None:
        self._owned(path).unlink()

    def iterdir(self, path: Path) -> Iterable[Path]:
        return tuple(self._owned(path).iterdir())

    def read_bytes(self, path: Path) -> bytes:
        return self._owned(path).read_bytes()

    def exists(self, path: Path) -> bool:
        return self._owned(path).exists()


@dataclass(frozen=True, slots=True)
class PublicationResult:
    generation: str
    manifest_path: Path
    pack_paths: tuple[Path, ...]
    retained_previous: str | None
    truncations: tuple[PersistenceNotice, ...]


@dataclass(frozen=True, slots=True)
class _EncodedPack:
    kind: str
    owner_id: str
    generation: str
    data: bytes
    decoded_bytes: int

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def filename(self) -> str:
        return f"{self.sha256}.pack"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _physical_pack_bytes(
    packs: Iterable[HistoryPack],
    find_replace_pack: FindReplaceHistoryPack | None,
) -> int:
    unique: dict[str, int] = {}
    for pack in packs:
        data = encode_history_pack(pack)
        unique.setdefault(hashlib.sha256(data).hexdigest(), len(data))
    if find_replace_pack is not None:
        data = encode_find_replace_pack(find_replace_pack)
        unique.setdefault(hashlib.sha256(data).hexdigest(), len(data))
    return sum(unique.values())


def _physical_encoded_bytes(items: Iterable[bytes]) -> int:
    unique: dict[str, int] = {}
    for data in items:
        unique.setdefault(hashlib.sha256(data).hexdigest(), len(data))
    return sum(unique.values())


def _drop_oldest_transaction(pack: HistoryPack) -> HistoryPack:
    snapshot = pack.history
    transactions = list(snapshot.transactions)
    if not transactions:
        return pack
    cursor = snapshot.cursor
    saved_cursor = snapshot.saved_cursor
    if cursor > 0:
        removed = transactions.pop(0)
        cursor -= 1
        if saved_cursor is not None:
            saved_cursor = saved_cursor - 1 if saved_cursor > 0 else None
    else:
        removed = transactions.pop()
        if saved_cursor is not None and saved_cursor > len(transactions):
            saved_cursor = None
    removed_bytes = estimate_transaction_bytes(removed)
    truncations = list(snapshot.truncations)
    if truncations and truncations[-1].reason == "aggregate_limit":
        previous = truncations[-1]
        truncations[-1] = HistoryTruncation(
            "aggregate_limit",
            previous.dropped_transactions + 1,
            previous.dropped_bytes + removed_bytes,
        )
    else:
        truncations.append(HistoryTruncation("aggregate_limit", 1, removed_bytes))
    coalesce = snapshot.coalesce
    if not transactions or cursor != len(transactions):
        coalesce = None
    trimmed = HistorySnapshot(
        transactions=tuple(transactions),
        cursor=cursor,
        saved_cursor=saved_cursor,
        coalesce=coalesce,
        decoded_bytes=sum(estimate_transaction_bytes(item) for item in transactions),
        persistable=True,
        truncations=tuple(truncations),
    )
    notices = list(pack.notices)
    if notices and notices[-1].reason == "aggregate_limit":
        previous_notice = notices[-1]
        notices[-1] = PersistenceNotice(
            previous_notice.scope,
            "aggregate_limit",
            previous_notice.dropped_count + 1,
            previous_notice.dropped_bytes + removed_bytes,
        )
    else:
        notices.append(
            PersistenceNotice(pack.document_id, "aggregate_limit", 1, removed_bytes)
        )
    return replace(pack, history=trimmed, notices=tuple(notices))


def _without_stale_references(manifest: SessionManifest) -> SessionManifest:
    return replace(
        manifest,
        packs=(),
        find_replace=replace(manifest.find_replace, history_pack=None),
    )


def plan_saved_history_admission(
    snapshot: SessionSnapshot,
    *,
    now: datetime,
    aggregate_limit: int = AGGREGATE_HISTORY_BYTES,
    retention: timedelta = HISTORY_RETENTION,
) -> SessionSnapshot:
    """Apply deterministic retention and aggregate history policy without I/O."""

    if not isinstance(snapshot, SessionSnapshot):
        raise TypeError("snapshot must be a SessionSnapshot")
    if type(aggregate_limit) is not int or aggregate_limit < 0:
        raise ValueError("aggregate_limit must be a non-negative integer")
    if retention < timedelta(0):
        raise ValueError("retention must be non-negative")
    current = _as_utc(now)
    notices = list(snapshot.manifest.notices)
    original_notice_lengths = {
        pack.document_id: len(pack.notices) for pack in snapshot.packs
    }
    packs = list(snapshot.packs)
    find_replace_pack = snapshot.find_replace_pack

    retained = []
    for pack in packs:
        if pack.closed_at is not None and current >= _parse_timestamp(pack.closed_at) + retention:
            notices.append(
                PersistenceNotice(
                    pack.document_id,
                    "closed_history_expired",
                    len(pack.history.transactions),
                    pack.history.decoded_bytes,
                )
            )
        else:
            retained.append(pack)
    packs = retained
    encoded_documents = {
        pack.document_id: encode_history_pack(pack) for pack in packs
    }
    encoded_find = (
        None
        if find_replace_pack is None
        else encode_find_replace_pack(find_replace_pack)
    )

    def total() -> int:
        items = list(encoded_documents.values())
        if encoded_find is not None:
            items.append(encoded_find)
        return _physical_encoded_bytes(items)

    closed = sorted(
        (pack for pack in packs if pack.closed_at is not None),
        key=lambda item: (item.closed_at or "", item.last_active_at, item.document_id),
    )
    for candidate in closed:
        if total() <= aggregate_limit:
            break
        packs.remove(candidate)
        encoded_documents.pop(candidate.document_id, None)
        notices.append(
            PersistenceNotice(
                candidate.document_id,
                "aggregate_closed_history_removed",
                len(candidate.history.transactions),
                candidate.history.decoded_bytes,
            )
        )

    active_document_id = None
    if snapshot.manifest.active_view_id is not None:
        active_view = next(
            (
                view
                for view in snapshot.manifest.views
                if view.view_id == snapshot.manifest.active_view_id
            ),
            None,
        )
        if active_view is not None:
            active_document_id = active_view.document_id

    open_ids = {item.document_id for item in packs if item.closed_at is None}
    inactive_ids = sorted(
        open_ids - ({active_document_id} if active_document_id is not None else set()),
        key=lambda document_id: (
            next(item.last_active_at for item in packs if item.document_id == document_id),
            document_id,
        ),
    )
    ordered_ids = inactive_ids
    if active_document_id in open_ids:
        ordered_ids.append(active_document_id)

    for document_id in ordered_ids:
        if total() <= aggregate_limit:
            break
        index = next(
            index for index, item in enumerate(packs) if item.document_id == document_id
        )
        original = packs[index]
        transaction_count = len(original.history.transactions)
        if not transaction_count:
            continue
        low = 1
        high = transaction_count
        best: tuple[HistoryPack, bytes] | None = None
        while low <= high:
            count = (low + high) // 2
            candidate = original
            for _ in range(count):
                candidate = _drop_oldest_transaction(candidate)
            data = encode_history_pack(candidate)
            trial_items = [
                data if owner_id == document_id else existing
                for owner_id, existing in encoded_documents.items()
            ]
            if encoded_find is not None:
                trial_items.append(encoded_find)
            if _physical_encoded_bytes(trial_items) <= aggregate_limit:
                best = (candidate, data)
                high = count - 1
            else:
                low = count + 1
        if best is None:
            candidate = original
            for _ in range(transaction_count):
                candidate = _drop_oldest_transaction(candidate)
            best = (candidate, encode_history_pack(candidate))
        packs[index], encoded_documents[document_id] = best

    if total() > aggregate_limit and find_replace_pack is not None:
        notices.append(
            PersistenceNotice(
                "find_replace",
                "aggregate_limit",
                len(find_replace_pack.find.undo)
                + len(find_replace_pack.find.redo)
                + len(find_replace_pack.replace.undo)
                + len(find_replace_pack.replace.redo),
                find_replace_pack.find.decoded_bytes
                + find_replace_pack.replace.decoded_bytes,
            )
        )
        find_replace_pack = None
        encoded_find = None

    for pack in packs:
        start = original_notice_lengths.get(pack.document_id, 0)
        notices.extend(pack.notices[start:])

    for document_id in ordered_ids:
        if total() <= aggregate_limit:
            break
        candidate = next(
            (item for item in packs if item.document_id == document_id), None
        )
        if candidate is None:
            continue
        packs.remove(candidate)
        encoded_documents.pop(document_id, None)
        notices.append(
            PersistenceNotice(
                document_id,
                "history_pack_suppressed",
                len(candidate.history.transactions),
                candidate.history.decoded_bytes,
            )
        )

    manifest = replace(
        _without_stale_references(snapshot.manifest),
        notices=tuple(notices),
    )
    return SessionSnapshot(manifest, tuple(packs), find_replace_pack)


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _envelope_decoded_bytes(data: bytes) -> int:
    value = json.loads(data)
    if not isinstance(value, dict) or type(value.get("decoded_bytes")) is not int:
        raise ValueError("encoded pack has no decoded byte declaration")
    return value["decoded_bytes"]


class SessionStore:
    """Publish and select complete immutable session generations."""

    def __init__(
        self,
        root: Path,
        *,
        backend: StorageBackend | None = None,
    ) -> None:
        self.root = Path(root)
        self.backend = backend or LocalStorageBackend(self.root)
        self.manifests_dir = self.root / "manifests"
        self.packs_dir = self.root / "packs"
        self.pointers_dir = self.root / "pointers"
        self.invalid_dir = self.root / "invalid"
        for directory in (
            self.root,
            self.manifests_dir,
            self.packs_dir,
            self.pointers_dir,
            self.invalid_dir,
        ):
            self.backend.mkdir(directory)

    def manifest_path(self, generation: str) -> Path:
        return self.manifests_dir / f"{generation}.json"

    @property
    def current_path(self) -> Path:
        return self.root / "current.json"

    def _next_generation(self) -> str:
        highest = 0
        for path in self.backend.iterdir(self.manifests_dir):
            match = _GENERATION_RE.fullmatch(path.stem)
            if match is not None:
                highest = max(highest, int(match.group("number")))
        return f"{highest + 1:020d}-{uuid.uuid4().hex}"

    def _encode_packs(self, snapshot: SessionSnapshot) -> list[_EncodedPack]:
        encoded = [
            _EncodedPack(
                "document",
                pack.document_id,
                pack.generation,
                data,
                _envelope_decoded_bytes(data),
            )
            for pack in snapshot.packs
            for data in (encode_history_pack(pack),)
        ]
        if snapshot.find_replace_pack is not None:
            pack = snapshot.find_replace_pack
            data = encode_find_replace_pack(pack)
            encoded.append(
                _EncodedPack(
                    "find_replace",
                    "find-replace",
                    pack.generation,
                    data,
                    _envelope_decoded_bytes(data),
                )
            )
        return encoded

    @staticmethod
    def _reference(pack: _EncodedPack) -> HistoryPackReference:
        return HistoryPackReference(
            kind=pack.kind,
            owner_id=pack.owner_id,
            generation=pack.generation,
            filename=pack.filename,
            encoded_bytes=len(pack.data),
            decoded_bytes=pack.decoded_bytes,
            sha256=pack.sha256,
        )

    def _previous_complete(self) -> LoadedSession:
        return self.load_latest()

    def publish(self, snapshot: SessionSnapshot) -> PublicationResult:
        previous = self._previous_complete()
        if any(
            problem.kind in {"unsupported_pointer", "unsupported_manifest"}
            for problem in previous.problems
        ):
            raise UnsupportedSessionSchema(
                "refusing to replace newer or unsupported session state"
            )
        retained_previous = (
            previous.manifest.generation if previous.manifest is not None else None
        )
        before_notice_count = len(snapshot.manifest.notices)
        admitted = plan_saved_history_admission(snapshot, now=datetime.now(UTC))

        if self.backend.free_bytes(self.root) < MIN_FREE_BYTES:
            notice = PersistenceNotice(
                "session",
                "low_space_history_suppressed",
                len(admitted.packs) + (admitted.find_replace_pack is not None),
                _physical_pack_bytes(admitted.packs, admitted.find_replace_pack),
            )
            admitted = SessionSnapshot(
                replace(
                    _without_stale_references(admitted.manifest),
                    notices=admitted.manifest.notices + (notice,),
                ),
                (),
                None,
            )

        encoded = self._encode_packs(admitted)
        previous_references = (
            previous.manifest.packs if previous.manifest is not None else ()
        )
        previous_sizes = {
            item.sha256: item.encoded_bytes for item in previous_references
        }
        union = dict(previous_sizes)
        for item in encoded:
            union.setdefault(item.sha256, len(item.data))
        if sum(union.values()) > AGGREGATE_HISTORY_BYTES:
            duplicate_bytes = sum(
                len(item.data) for item in encoded if item.sha256 in previous_sizes
            )
            available = max(
                0,
                AGGREGATE_HISTORY_BYTES - sum(previous_sizes.values()) + duplicate_bytes,
            )
            admitted = plan_saved_history_admission(
                admitted,
                now=datetime.now(UTC),
                aggregate_limit=available,
            )
            encoded = self._encode_packs(admitted)
            final_union = dict(previous_sizes)
            for item in encoded:
                final_union.setdefault(item.sha256, len(item.data))
            if sum(final_union.values()) > AGGREGATE_HISTORY_BYTES:
                reusable = {
                    (item.kind, item.owner_id, item.generation)
                    for item in encoded
                    if item.sha256 in previous_sizes
                }
                suppressed = len(encoded) - len(reusable)
                encoded = [
                    item
                    for item in encoded
                    if (item.kind, item.owner_id, item.generation) in reusable
                ]
                admitted = SessionSnapshot(
                    replace(
                        _without_stale_references(admitted.manifest),
                        notices=admitted.manifest.notices
                        + (
                            PersistenceNotice(
                                "session",
                                "aggregate_union_history_suppressed",
                                suppressed,
                                0,
                            ),
                        ),
                    ),
                    tuple(
                        pack
                        for pack in admitted.packs
                        if ("document", pack.document_id, pack.generation) in reusable
                    ),
                    (
                        admitted.find_replace_pack
                        if admitted.find_replace_pack is not None
                        and (
                            "find_replace",
                            "find-replace",
                            admitted.find_replace_pack.generation,
                        )
                        in reusable
                        else None
                    ),
                )

        generation = self._next_generation()
        references = tuple(self._reference(item) for item in encoded)
        find_reference = next(
            (item for item in references if item.kind == "find_replace"), None
        )
        manifest = replace(
            admitted.manifest,
            generation=generation,
            updated_at=utc_timestamp(),
            packs=references,
            find_replace=replace(
                admitted.manifest.find_replace,
                history_pack=find_reference,
            ),
        )
        manifest_bytes = _canonical_json(manifest_to_payload(manifest))
        if len(manifest_bytes) > MAX_MANIFEST_BYTES:
            raise ValueError("published manifest exceeds the decoded limit")

        pack_paths = tuple(self.packs_dir / item.filename for item in encoded)
        for item, path in zip(encoded, pack_paths, strict=True):
            if not self.backend.exists(path):
                self.backend.write_synced(path, item.data)

        manifest_path = self.manifest_path(generation)
        self.backend.write_synced(manifest_path, manifest_bytes)
        pointer = {
            "generation": generation,
            "manifest": f"manifests/{generation}.json",
            "schema": 1,
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        }
        pointer_path = self.pointers_dir / f"{generation}.json"
        self.backend.write_synced(pointer_path, _canonical_json(pointer))
        self.backend.replace(pointer_path, self.current_path)
        self.backend.sync_directory(self.root)

        truncations = admitted.manifest.notices[before_notice_count:]
        return PublicationResult(
            generation,
            manifest_path,
            pack_paths,
            retained_previous,
            truncations,
        )

    def _problem(
        self,
        kind: str,
        path: Path,
        message: str,
        *,
        document_id: str | None = None,
    ) -> SessionProblem:
        return SessionProblem(kind, path, message, document_id)

    def _preserve_invalid(self, path: Path, data: bytes) -> None:
        digest = hashlib.sha256(data).hexdigest()[:16]
        suffix = f".{digest}.invalid"
        try:
            if any(
                item.name.endswith(suffix)
                for item in tuple(self.backend.iterdir(self.invalid_dir))[:200]
            ):
                return
        except OSError:
            return
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        evidence = self.invalid_dir / f"{path.name}.{timestamp}.{digest}.invalid"
        try:
            self.backend.write_synced(evidence, data)
        except (OSError, ValueError):
            pass

    def _load_manifest_path(
        self,
        path: Path,
        *,
        expected_sha256: str | None,
    ) -> tuple[LoadedSession | None, tuple[SessionProblem, ...]]:
        problems: list[SessionProblem] = []
        try:
            data = self.backend.read_bytes(path)
        except FileNotFoundError:
            problems.append(
                self._problem("missing_manifest", path, "Session manifest is missing.")
            )
            return None, tuple(problems)
        if len(data) > MAX_MANIFEST_BYTES:
            self._preserve_invalid(path, data)
            problems.append(
                self._problem(
                    "oversized_manifest",
                    path,
                    "Session manifest exceeds its safe limit.",
                )
            )
            return None, tuple(problems)
        if expected_sha256 is not None and hashlib.sha256(data).hexdigest() != expected_sha256:
            self._preserve_invalid(path, data)
            problems.append(
                self._problem(
                    "manifest_checksum",
                    path,
                    "Session manifest checksum does not match.",
                )
            )
            return None, tuple(problems)
        try:
            manifest = manifest_from_payload(json.loads(data))
        except UnsupportedSessionSchema:
            self._preserve_invalid(path, data)
            problems.append(
                self._problem(
                    "unsupported_manifest",
                    path,
                    "Session schema is newer or unsupported.",
                )
            )
            return None, tuple(problems)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            self._preserve_invalid(path, data)
            problems.append(
                self._problem("invalid_manifest", path, "Session manifest is invalid.")
            )
            return None, tuple(problems)

        document_packs: list[HistoryPack] = []
        find_pack: FindReplaceHistoryPack | None = None
        complete = True
        for reference in manifest.packs:
            pack_path = self.packs_dir / reference.filename
            try:
                pack_data = self.backend.read_bytes(pack_path)
            except FileNotFoundError:
                problems.append(
                    self._problem(
                        "missing_pack",
                        pack_path,
                        "A referenced session history pack is missing.",
                        document_id=(
                            reference.owner_id if reference.kind == "document" else None
                        ),
                    )
                )
                complete = False
                continue
            if (
                len(pack_data) != reference.encoded_bytes
                or hashlib.sha256(pack_data).hexdigest() != reference.sha256
            ):
                self._preserve_invalid(pack_path, pack_data)
                problems.append(
                    self._problem(
                        "pack_checksum",
                        pack_path,
                        "A session history pack failed size or checksum validation.",
                        document_id=(
                            reference.owner_id if reference.kind == "document" else None
                        ),
                    )
                )
                complete = False
                continue
            try:
                if reference.kind == "document":
                    pack = decode_history_pack(pack_data)
                    if (
                        pack.document_id != reference.owner_id
                        or pack.generation != reference.generation
                    ):
                        raise ValueError("document pack reference does not match payload")
                    document_packs.append(pack)
                else:
                    candidate = decode_find_replace_pack(pack_data)
                    if candidate.generation != reference.generation:
                        raise ValueError("find/replace pack reference does not match payload")
                    find_pack = candidate
            except (TypeError, ValueError):
                self._preserve_invalid(pack_path, pack_data)
                problems.append(
                    self._problem(
                        "invalid_pack",
                        pack_path,
                        "A session history pack is invalid.",
                        document_id=(
                            reference.owner_id if reference.kind == "document" else None
                        ),
                    )
                )
                complete = False
        if not complete:
            return None, tuple(problems)
        return (
            LoadedSession(manifest, tuple(document_packs), find_pack, ()),
            tuple(problems),
        )

    def _pointer_target(
        self,
    ) -> tuple[Path | None, str | None, tuple[SessionProblem, ...]]:
        if not self.backend.exists(self.current_path):
            return None, None, ()
        try:
            data = self.backend.read_bytes(self.current_path)
            if len(data) > 64 << 10:
                raise ValueError("pointer is oversized")
            payload = json.loads(data)
            if not isinstance(payload, dict):
                raise ValueError("pointer must be an object")
            if type(payload.get("schema")) is int and payload["schema"] != 1:
                raise UnsupportedSessionSchema("unsupported pointer schema")
            if set(payload) != {
                "schema",
                "generation",
                "manifest",
                "sha256",
            }:
                raise ValueError("pointer fields are invalid")
            if payload["schema"] != 1:
                raise ValueError("pointer schema is invalid")
            generation = payload["generation"]
            if not isinstance(generation, str) or _GENERATION_RE.fullmatch(generation) is None:
                raise ValueError("pointer generation is invalid")
            expected_manifest = f"manifests/{generation}.json"
            if payload["manifest"] != expected_manifest:
                raise ValueError("pointer manifest path is invalid")
            sha256 = payload["sha256"]
            if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
                raise ValueError("pointer checksum is invalid")
            return self.manifest_path(generation), sha256, ()
        except UnsupportedSessionSchema:
            try:
                self._preserve_invalid(
                    self.current_path, self.backend.read_bytes(self.current_path)
                )
            except FileNotFoundError:
                pass
            problem = self._problem(
                "unsupported_pointer",
                self.current_path,
                "Session pointer schema is newer or unsupported.",
            )
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            try:
                self._preserve_invalid(
                    self.current_path, self.backend.read_bytes(self.current_path)
                )
            except FileNotFoundError:
                pass
            problem = self._problem(
                "invalid_pointer", self.current_path, "Session pointer is invalid."
            )
        return None, None, (problem,)

    def load_latest(self) -> LoadedSession:
        accumulated: list[SessionProblem] = []
        pointer_path, pointer_sha, pointer_problems = self._pointer_target()
        accumulated.extend(pointer_problems)
        attempted: set[Path] = set()
        if pointer_path is not None:
            attempted.add(pointer_path)
            loaded, problems = self._load_manifest_path(
                pointer_path,
                expected_sha256=pointer_sha,
            )
            accumulated.extend(problems)
            if loaded is not None:
                return replace(loaded, problems=tuple(accumulated))

        manifests = sorted(
            (
                path
                for path in self.backend.iterdir(self.manifests_dir)
                if path.suffix == ".json" and _GENERATION_RE.fullmatch(path.stem)
            ),
            key=lambda item: item.name,
            reverse=True,
        )[:MAX_GENERATIONS_INSPECTED]
        for path in manifests:
            if path in attempted:
                continue
            loaded, problems = self._load_manifest_path(path, expected_sha256=None)
            accumulated.extend(problems)
            if loaded is not None:
                return replace(loaded, problems=tuple(accumulated))
        return LoadedSession(None, (), None, tuple(accumulated))

    def discard(self, document_id: str) -> None:
        loaded = self.load_latest()
        if loaded.manifest is None:
            return
        retained_packs = tuple(
            pack for pack in loaded.packs if pack.document_id != document_id
        )
        snapshot = SessionSnapshot(
            _without_stale_references(loaded.manifest),
            retained_packs,
            loaded.find_replace_pack,
        )
        self.publish(snapshot)

    def cleanup(
        self,
        *,
        now: datetime,
        max_inspected: int = 200,
        max_removed: int = 100,
    ) -> CleanupReport:
        if max_inspected < 0 or max_removed < 0:
            raise ValueError("cleanup limits must be non-negative")
        _as_utc(now)
        loaded = self.load_latest()
        keep_manifests: set[Path] = set()
        keep_packs: set[Path] = set()
        if loaded.manifest is not None:
            keep_manifests.add(self.manifest_path(loaded.manifest.generation))
            keep_packs.update(
                self.packs_dir / reference.filename
                for reference in loaded.manifest.packs
            )
        candidates = sorted(
            (
                path
                for path in self.backend.iterdir(self.manifests_dir)
                if path.suffix == ".json" and _GENERATION_RE.fullmatch(path.stem)
                and path not in keep_manifests
            ),
            key=lambda item: item.name,
            reverse=True,
        )
        for path in candidates:
            previous, _ = self._load_manifest_path(path, expected_sha256=None)
            if previous is not None:
                keep_manifests.add(path)
                keep_packs.update(
                    self.packs_dir / reference.filename
                    for reference in previous.manifest.packs
                )
                break

        inspected = 0
        removed: list[Path] = []
        retained = 0
        errors: list[str] = []
        groups = (
            (
                self.manifests_dir,
                keep_manifests,
                lambda item: is_durable_session_artifact_name(item.name)
                and (item.suffix in {".json", ".tmp"}),
            ),
            (
                self.packs_dir,
                keep_packs,
                lambda item: is_durable_session_artifact_name(item.name)
                and (item.suffix in {".pack", ".tmp"}),
            ),
            (
                self.pointers_dir,
                set(),
                lambda item: is_durable_session_artifact_name(item.name)
                and (item.suffix in {".json", ".tmp"}),
            ),
        )
        for directory, keep, recognized in groups:
            for path in sorted(self.backend.iterdir(directory), key=lambda item: item.name):
                if inspected >= max_inspected:
                    return CleanupReport(inspected, tuple(removed), retained, tuple(errors))
                inspected += 1
                if path in keep or not recognized(path) or len(removed) >= max_removed:
                    retained += 1
                    continue
                try:
                    self.backend.unlink(path)
                except (OSError, ValueError):
                    errors.append(f"could not remove {path.name}")
                else:
                    removed.append(path)
        return CleanupReport(inspected, tuple(removed), retained, tuple(errors))
