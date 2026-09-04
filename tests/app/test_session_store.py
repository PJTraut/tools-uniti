import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from uniti.app.session import (
    DocumentRecord,
    FindReplaceManifestRecord,
    HistoryPack,
    InputStateRecord,
    PaneRecord,
    SessionManifest,
    SessionSnapshot,
    UnsupportedSessionSchema,
    ViewRecord,
    WindowRecord,
    encode_history_pack,
)
from uniti.app.session_store import (
    MIN_FREE_BYTES,
    LocalStorageBackend,
    SessionStore,
    plan_saved_history_admission,
)
from uniti.core.file_identity import FileIdentity, SavedFileStamp
from uniti.core.history import EditHistory, EditOperation, EditTransaction


NOW = datetime(2026, 9, 4, 10, tzinfo=UTC)


class FakeBackend:
    def __init__(self, root: Path):
        self.root = root
        self.files: dict[Path, bytes] = {}
        self.directories = {root}
        self.operations: list[tuple[str, str]] = []
        self.reads: list[Path] = []
        self.free_bytes_value = 1 << 40
        self.fail_after: int | None = None
        self._mutation_count = 0

    def _relative(self, path: Path) -> str:
        relative = path.relative_to(self.root)
        return "." if not relative.parts else str(relative)

    def _mutate(self, operation: str, name: str, apply) -> None:
        self.operations.append((operation, name))
        self._mutation_count += 1
        apply()
        if self.fail_after == self._mutation_count:
            raise OSError(f"injected failure after {operation}")

    def reset_recording(self, *, fail_after: int | None = None) -> None:
        self.operations.clear()
        self.reads.clear()
        self._mutation_count = 0
        self.fail_after = fail_after

    def free_bytes(self, path: Path) -> int:
        return self.free_bytes_value

    def mkdir(self, path: Path) -> None:
        self.directories.add(path)

    def write_synced(self, path: Path, data: bytes) -> None:
        self._mutate(
            "write_synced",
            self._relative(path),
            lambda: self.files.__setitem__(path, bytes(data)),
        )

    def replace(self, source: Path, destination: Path) -> None:
        def apply() -> None:
            self.files[destination] = self.files.pop(source)

        self._mutate(
            "replace",
            self._relative(destination),
            apply,
        )

    def sync_directory(self, path: Path) -> None:
        self._mutate("sync_directory", self._relative(path), lambda: None)

    def unlink(self, path: Path) -> None:
        self._mutate("unlink", self._relative(path), lambda: self.files.pop(path, None))

    def iterdir(self, path: Path):
        names: set[str] = set()
        for candidate in set(self.files) | self.directories:
            try:
                relative = candidate.relative_to(path)
            except ValueError:
                continue
            if relative.parts:
                names.add(relative.parts[0])
        return tuple(path / name for name in sorted(names))

    def read_bytes(self, path: Path) -> bytes:
        self.reads.append(path)
        try:
            return self.files[path]
        except KeyError as exc:
            raise FileNotFoundError(path) from exc

    def exists(self, path: Path) -> bool:
        return path in self.files or path in self.directories


def _timestamp(value: datetime = NOW) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _find_state(target: str | None) -> FindReplaceManifestRecord:
    empty = InputStateRecord("", 0, 0)
    return FindReplaceManifestRecord(
        empty,
        empty,
        False,
        False,
        False,
        False,
        None,
        100,
        False,
        target,
        None,
    )


def _pack(
    document_id: str = "doc-1",
    *,
    text: str = "A",
    generation: str = "history-1",
    last_active_at: datetime = NOW,
    closed_at: datetime | None = None,
) -> HistoryPack:
    history = EditHistory()
    history.record(EditTransaction((EditOperation(0, "", text),)))
    history.mark_saved()
    payload = text.encode("utf-8")
    return HistoryPack(
        document_id=document_id,
        generation=generation,
        canonical_path=f"/tmp/{document_id}.txt",
        saved_stamp=SavedFileStamp(
            FileIdentity(len(payload), 100, 1, 1),
            hashlib.sha256(payload).hexdigest(),
        ),
        source_profile_key="utf-8",
        selected_output_profile_key="utf-8",
        selected_output_eol=None,
        saved_output_profile_key="utf-8",
        saved_output_eol=None,
        history=history.export_snapshot(),
        last_active_at=_timestamp(last_active_at),
        closed_at=None if closed_at is None else _timestamp(closed_at),
    )


def _snapshot(
    *packs: HistoryPack,
    active_document_id: str | None = "doc-1",
) -> SessionSnapshot:
    documents = []
    views = []
    view_ids = []
    for pack in packs:
        is_open = pack.closed_at is None
        document_view_ids = (f"view-{pack.document_id}",) if is_open else ()
        documents.append(
            DocumentRecord(
                pack.document_id,
                pack.canonical_path,
                document_view_ids,
                pack.last_active_at,
                pack.closed_at,
            )
        )
        if is_open:
            view_id = document_view_ids[0]
            view_ids.append(view_id)
            views.append(
                ViewRecord(view_id, pack.document_id, 0, 0, None, 0, 0, 0, False, 100)
            )
    windows = ()
    active_view_id = None
    active_window_id = None
    if views:
        active_view_id = (
            f"view-{active_document_id}"
            if active_document_id is not None
            else views[0].view_id
        )
        root = PaneRecord(
            "leaf",
            "pane-1",
            view_ids=tuple(view_ids),
            selected_view_id=active_view_id,
        )
        windows = (WindowRecord("window-1", (0, 0, 800, 600), "normal", root),)
        active_window_id = "window-1"
    manifest = SessionManifest(
        schema=1,
        generation="capture",
        service_id="service-1",
        build_identity="test",
        created_at=_timestamp(),
        updated_at=_timestamp(),
        clean_shutdown=False,
        active_window_id=active_window_id,
        active_view_id=active_view_id,
        windows=windows,
        views=tuple(views),
        documents=tuple(documents),
        find_replace=_find_state(active_view_id),
        packs=(),
    )
    return SessionSnapshot(manifest, tuple(packs), None)


def test_publish_syncs_packs_then_manifest_then_pointer():
    root = Path("/owned/session")
    backend = FakeBackend(root)
    store = SessionStore(root, backend=backend)

    result = store.publish(_snapshot(_pack()))

    assert backend.operations == [
        ("write_synced", str(result.pack_paths[0].relative_to(store.root))),
        ("write_synced", f"manifests/{result.generation}.json"),
        ("write_synced", f"pointers/{result.generation}.json"),
        ("replace", "current.json"),
        ("sync_directory", "."),
    ]
    loaded = store.load_latest()
    assert loaded.manifest is not None
    assert loaded.manifest.generation == result.generation
    assert loaded.packs[0].document_id == "doc-1"


def test_manifest_only_load_defers_history_pack_read_and_decode():
    root = Path("/owned/session")
    backend = FakeBackend(root)
    store = SessionStore(root, backend=backend)
    result = store.publish(_snapshot(_pack()))
    backend.reset_recording()

    loaded = store.load_manifest()

    assert loaded.manifest is not None
    assert loaded.manifest.generation == result.generation
    assert loaded.packs == ()
    assert not any(path.suffix == ".pack" for path in backend.reads)

    pack = store.load_document_pack(loaded.manifest, "doc-1")

    assert pack.document_id == "doc-1"
    assert any(path.suffix == ".pack" for path in backend.reads)


@pytest.mark.parametrize("failure_after", range(1, 6))
def test_interrupted_publication_keeps_old_or_complete_new_generation(failure_after: int):
    root = Path("/owned/session")
    backend = FakeBackend(root)
    store = SessionStore(root, backend=backend)
    first = store.publish(_snapshot(_pack(text="old", generation="history-old")))
    backend.reset_recording(fail_after=failure_after)

    with pytest.raises(OSError, match="injected failure"):
        store.publish(_snapshot(_pack(text="new", generation="history-new")))

    backend.fail_after = None
    loaded = store.load_latest()
    assert loaded.manifest is not None
    assert loaded.manifest.generation == first.generation or any(
        pack.generation == "history-new" for pack in loaded.packs
    )
    assert store.manifest_path(first.generation) in backend.files


def test_incomplete_current_generation_falls_back_to_previous_complete():
    root = Path("/owned/session")
    backend = FakeBackend(root)
    store = SessionStore(root, backend=backend)
    first = store.publish(_snapshot(_pack(text="old", generation="history-old")))
    second = store.publish(_snapshot(_pack(text="new", generation="history-new")))
    second_pack = second.pack_paths[0]
    backend.files.pop(second_pack)

    loaded = store.load_latest()

    assert loaded.manifest is not None
    assert loaded.manifest.generation == first.generation
    assert loaded.problems


def test_identical_pack_is_content_addressed_and_reused():
    root = Path("/owned/session")
    backend = FakeBackend(root)
    store = SessionStore(root, backend=backend)
    snapshot = _snapshot(_pack())
    first = store.publish(snapshot)
    backend.reset_recording()

    second = store.publish(snapshot)

    assert second.pack_paths == first.pack_paths
    assert not any(
        operation == "write_synced" and name.endswith(".pack")
        for operation, name in backend.operations
    )


def test_local_backend_publishes_and_loads_complete_generation(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "session"
    backend = LocalStorageBackend(root)
    monkeypatch.setattr(backend, "free_bytes", lambda path: 1 << 40)
    store = SessionStore(root, backend=backend)

    result = store.publish(_snapshot(_pack()))
    loaded = store.load_latest()

    assert result.manifest_path.is_file()
    assert loaded.manifest is not None
    assert loaded.manifest.generation == result.generation
    assert loaded.packs[0].document_id == "doc-1"


def test_discard_evidence_removes_only_selected_owned_session_artifact(
    tmp_path: Path,
):
    root = tmp_path / "session"
    store = SessionStore(root)
    selected = store.invalid_dir / "future.json.20260904.invalid"
    retained = store.invalid_dir / "other.json.20260904.invalid"
    selected.write_bytes(b"selected")
    retained.write_bytes(b"retained")

    store.discard_evidence(selected)

    assert selected.exists() is False
    assert retained.read_bytes() == b"retained"


def test_discard_evidence_rejects_paths_outside_session_storage(tmp_path: Path):
    store = SessionStore(tmp_path / "session")
    outside = tmp_path / "outside.invalid"
    outside.write_bytes(b"not UNITI-owned")

    with pytest.raises(ValueError, match="outside owned session storage"):
        store.discard_evidence(outside)

    assert outside.read_bytes() == b"not UNITI-owned"


def test_discard_document_prunes_only_its_manifest_views_and_history():
    root = Path("/owned/session")
    backend = FakeBackend(root)
    store = SessionStore(root, backend=backend)
    store.publish(_snapshot(_pack("doc-1"), _pack("doc-2", text="B")))

    store.discard("doc-1")

    loaded = store.load_latest()
    assert loaded.manifest is not None
    assert tuple(item.document_id for item in loaded.manifest.documents) == ("doc-2",)
    assert tuple(item.view_id for item in loaded.manifest.views) == ("view-doc-2",)
    assert loaded.manifest.windows[0].root.view_ids == ("view-doc-2",)
    assert loaded.manifest.active_view_id == "view-doc-2"
    assert loaded.manifest.find_replace.last_target_view_id == "view-doc-2"
    assert tuple(item.document_id for item in loaded.packs) == ("doc-2",)


def test_low_space_is_injected_and_writes_no_nonessential_history():
    root = Path("/owned/session")
    backend = FakeBackend(root)
    backend.free_bytes_value = MIN_FREE_BYTES - 1
    store = SessionStore(root, backend=backend)

    result = store.publish(_snapshot(_pack()))

    assert result.truncations[-1].reason == "low_space_history_suppressed"
    assert all(
        not name.endswith(".pack")
        for operation, name in backend.operations
        if operation == "write_synced"
    )
    loaded = store.load_latest()
    assert loaded.manifest is not None
    assert loaded.manifest.documents[0].document_id == "doc-1"
    assert loaded.packs == ()


def test_closed_history_expires_at_exact_seven_day_boundary():
    closed = NOW
    snapshot = _snapshot(
        _pack(closed_at=closed, last_active_at=closed),
        active_document_id=None,
    )

    retained = plan_saved_history_admission(
        snapshot,
        now=closed + timedelta(days=7) - timedelta(microseconds=1),
    )
    expired = plan_saved_history_admission(
        snapshot,
        now=closed + timedelta(days=7),
    )

    assert len(retained.packs) == 1
    assert expired.packs == ()
    assert expired.manifest.documents == snapshot.manifest.documents
    assert expired.manifest.notices[-1].reason == "closed_history_expired"


def test_aggregate_admission_trims_inactive_before_active_history():
    text = "".join(hashlib.sha256(str(index).encode()).hexdigest() for index in range(200))
    inactive = _pack(
        "doc-old",
        text=text,
        generation="old-history",
        last_active_at=NOW - timedelta(days=1),
    )
    active = _pack(
        "doc-active",
        text=text[::-1],
        generation="active-history",
    )
    snapshot = _snapshot(inactive, active, active_document_id="doc-active")
    aggregate = sum(len(encode_history_pack(pack)) for pack in snapshot.packs) - 1

    admitted = plan_saved_history_admission(snapshot, now=NOW, aggregate_limit=aggregate)

    by_id = {pack.document_id: pack for pack in admitted.packs}
    assert by_id["doc-old"].history.transactions == ()
    assert len(by_id["doc-active"].history.transactions) == 1
    assert by_id["doc-old"].notices[-1].reason == "aggregate_limit"
    assert admitted.manifest.notices[-1].reason == "aggregate_limit"


def test_load_preserves_one_copy_of_invalid_pointer_evidence():
    root = Path("/owned/session")
    backend = FakeBackend(root)
    store = SessionStore(root, backend=backend)
    first = store.publish(_snapshot(_pack()))
    backend.files[store.current_path] = b"not-json"
    backend.reset_recording()

    loaded = store.load_latest()
    store.load_latest()

    assert loaded.manifest is not None
    assert loaded.manifest.generation == first.generation
    evidence = [path for path in backend.files if path.parent == store.invalid_dir]
    assert len(evidence) == 1
    assert backend.files[evidence[0]] == b"not-json"


def test_future_schema_pointer_is_preserved_and_blocks_publication():
    root = Path("/owned/session")
    backend = FakeBackend(root)
    store = SessionStore(root, backend=backend)
    original = b'{"schema":2}'
    backend.files[store.current_path] = original

    loaded = store.load_latest()
    with pytest.raises(UnsupportedSessionSchema, match="refusing"):
        store.publish(_snapshot(_pack()))

    assert loaded.manifest is None
    assert loaded.problems[0].kind == "unsupported_pointer"
    assert backend.files[store.current_path] == original


def test_cleanup_retains_current_previous_and_invalid_but_removes_older_orphans():
    root = Path("/owned/session")
    backend = FakeBackend(root)
    store = SessionStore(root, backend=backend)
    first = store.publish(_snapshot(_pack(text="one", generation="history-one")))
    second = store.publish(_snapshot(_pack(text="two", generation="history-two")))
    third = store.publish(_snapshot(_pack(text="three", generation="history-three")))
    evidence = store.invalid_dir / "pointer.20260904.invalid"
    backend.files[evidence] = b"evidence"
    temporary = store.manifests_dir / ".orphan.abc123.tmp"
    backend.files[temporary] = b"partial"
    backend.reset_recording()

    report = store.cleanup(now=NOW)

    assert first.manifest_path in report.removed
    assert temporary in report.removed
    assert second.manifest_path in backend.files
    assert third.manifest_path in backend.files
    assert evidence in backend.files


def test_local_backend_rejects_paths_outside_owned_root_and_symlink_escape(tmp_path: Path):
    root = tmp_path / "session"
    backend = LocalStorageBackend(root)

    with pytest.raises(ValueError, match="outside"):
        backend.write_synced(tmp_path / "outside.pack", b"x")

    outside = tmp_path / "outside-dir"
    outside.mkdir()
    root.mkdir(exist_ok=True)
    link = root / "escape"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")
    with pytest.raises(ValueError, match="outside"):
        backend.write_synced(link / "pack", b"x")
