"""Runtime capture and restore helpers for immutable UNITI sessions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from uniti.core.document import Document
from uniti.core.file_identity import (
    FileIdentity,
    FileMatch,
    SavedFileStamp,
    sha256_file,
    verify_saved_file,
)
from uniti.core.text_format import EOLPolicy, OutputFormat, encoding_profile

from .platform_policy import normalize_native_path
from .session import (
    SESSION_SCHEMA,
    DocumentRecord,
    FindReplaceHistoryPack,
    FindReplaceManifestRecord,
    HistoryPack,
    PaneRecord,
    PersistenceNotice,
    SessionManifest,
    SessionSnapshot,
    ViewRecord,
)


@dataclass(frozen=True, slots=True)
class RestoreSeal:
    document_id: str
    expected_hash: str
    history_generation: str
    requested_view_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.document_id:
            raise ValueError("restore document ID must be nonempty")
        if len(self.expected_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.expected_hash
        ):
            raise ValueError("restore expected hash must be lowercase SHA-256")
        if not self.history_generation:
            raise ValueError("restore history generation must be nonempty")
        if not isinstance(self.requested_view_ids, tuple) or any(
            not isinstance(view_id, str) or not view_id
            for view_id in self.requested_view_ids
        ):
            raise ValueError("restore view IDs must be a nonempty-string tuple")


@dataclass(frozen=True, slots=True)
class RestoreDocumentResult:
    seal: RestoreSeal
    match: FileMatch
    pack: HistoryPack
    document: Document | None

    def __post_init__(self) -> None:
        if not isinstance(self.seal, RestoreSeal):
            raise TypeError("restore result seal is invalid")
        if not isinstance(self.match, FileMatch):
            raise TypeError("restore result file match is invalid")
        if not isinstance(self.pack, HistoryPack):
            raise TypeError("restore result history pack is invalid")
        if self.match in {FileMatch.EXACT_FAST, FileMatch.EXACT_HASH}:
            if not isinstance(self.document, Document):
                raise ValueError("an exact restore result requires a document")
        elif self.document is not None:
            raise ValueError("a conflicted restore result cannot contain a document")


@dataclass(frozen=True, slots=True)
class FreshDocumentResult:
    document_id: str
    canonical_path: str
    requested_view_ids: tuple[str, ...]
    document: Document
    saved_stamp: SavedFileStamp

    def __post_init__(self) -> None:
        if not self.document_id or not self.canonical_path:
            raise ValueError("fresh restore identity must be nonempty")
        if not isinstance(self.requested_view_ids, tuple):
            raise TypeError("fresh restore view IDs must be a tuple")
        if not isinstance(self.document, Document):
            raise TypeError("fresh restore document is invalid")
        if not isinstance(self.saved_stamp, SavedFileStamp):
            raise TypeError("fresh restore saved stamp is invalid")


def stamp_saved_file(
    path: Path,
    expected_identity: FileIdentity,
) -> SavedFileStamp | None:
    """Hash one stable saved-file identity without accepting a raced source."""

    digest = sha256_file(path)
    try:
        actual_identity = FileIdentity.from_path(path)
    except FileNotFoundError:
        return None
    if actual_identity != expected_identity:
        return None
    return SavedFileStamp(actual_identity, digest)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _eol_name(output_format: OutputFormat) -> str | None:
    return (
        None
        if output_format.eol is EOLPolicy.PRESERVE
        else output_format.eol.value
    )


def _history_generation(
    service_id: str,
    document_id: str,
    document: object,
    history: object,
) -> str:
    output_format = getattr(document, "output_format")
    saved_output_format = getattr(document, "saved_output_format")
    signature = "\0".join(
        (
            service_id,
            document_id,
            str(getattr(document, "revision")),
            str(getattr(history, "cursor")),
            str(getattr(history, "saved_cursor")),
            str(len(getattr(history, "transactions"))),
            str(getattr(history, "decoded_bytes")),
            output_format.encoding.key,
            output_format.eol.value,
            saved_output_format.encoding.key,
            saved_output_format.eol.value,
        )
    )
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


def capture_service_session(
    service: object,
    *,
    clean_shutdown: bool,
    generation: str,
    service_id: str,
    build_identity: str,
    created_at: str,
    updated_at: str,
    history_generations: dict[str, str] | None = None,
    previous_pack_references: tuple[object, ...] = (),
    previous_find_pack: FindReplaceHistoryPack | None = None,
    excluded_document_ids: frozenset[str] = frozenset(),
) -> SessionSnapshot:
    """Capture live GUI state into immutable records without filesystem I/O."""

    window_items = tuple(getattr(service, "windows").items)
    views = []
    for _window_id, window in window_items:
        for view in window.views:
            entry = getattr(service, "documents").entry_for_view(view.view_id)
            if entry is None:
                raise RuntimeError("live view is not bound to a document")
            if entry.document_id in excluded_document_ids:
                continue
            views.append(view.export_state(entry.document_id))

    retained_view_ids = frozenset(view.view_id for view in views)
    window_records = tuple(
        (window_id, window.export_window_record())
        for window_id, window in window_items
    )
    windows = tuple(
        replace(
            record,
            root=_filter_pane_views(record.root, retained_view_ids),
        )
        for _window_id, record in window_records
    )

    documents = []
    packs = []
    retained_generations = history_generations or {}
    notices: list[PersistenceNotice] = []
    for entry in getattr(service, "documents").entries:
        if entry.document_id in excluded_document_ids:
            continue
        documents.append(
            DocumentRecord(
                entry.document_id,
                str(entry.canonical_path),
                entry.view_ids,
                _timestamp(entry.last_active_at),
                None if entry.closed_at is None else _timestamp(entry.closed_at),
            )
        )
        if entry.saved_stamp is None:
            notices.append(
                PersistenceNotice(entry.document_id, "saved_hash_pending")
            )
            continue
        history = entry.document.export_history()
        if not history.persistable:
            notices.append(
                PersistenceNotice(
                    entry.document_id,
                    "history_not_persistable",
                    len(history.transactions),
                    history.decoded_bytes,
                )
            )
            continue
        output_format = entry.document.output_format
        saved_output_format = entry.document.saved_output_format
        packs.append(
            HistoryPack(
                document_id=entry.document_id,
                generation=retained_generations.get(entry.document_id)
                or _history_generation(
                    service_id,
                    entry.document_id,
                    entry.document,
                    history,
                ),
                canonical_path=str(entry.canonical_path),
                saved_stamp=entry.saved_stamp,
                source_profile_key=entry.document.source_profile.key,
                selected_output_profile_key=output_format.encoding.key,
                selected_output_eol=_eol_name(output_format),
                saved_output_profile_key=saved_output_format.encoding.key,
                saved_output_eol=_eol_name(saved_output_format),
                history=history,
                last_active_at=_timestamp(entry.last_active_at),
                closed_at=(
                    None if entry.closed_at is None else _timestamp(entry.closed_at)
                ),
            )
        )

    active_view_id = getattr(service, "windows").active_view_id
    if active_view_id not in retained_view_ids:
        active_view_id = views[0].view_id if views else None
    active_window_id = getattr(service, "windows").active_window_id
    active_window_record = next(
        (
            record
            for window_id, record in window_records
            if window_id == active_window_id
        ),
        None,
    )
    if active_view_id is not None and (
        active_window_record is None
        or not _pane_contains_view(active_window_record.root, active_view_id)
    ):
        active_window_id = next(
            window_id
            for window_id, record in window_records
            if _pane_contains_view(record.root, active_view_id)
        )
    find_state = getattr(service, "find_replace").export_state(active_view_id)
    find_generation = (
        previous_find_pack.generation
        if previous_find_pack is not None
        and previous_find_pack.find == find_state.find
        and previous_find_pack.replace == find_state.replace
        else generation
    )
    find_pack = FindReplaceHistoryPack(
        generation=find_generation,
        find=find_state.find,
        replace=find_state.replace,
    )
    pack_generations = {
        ("document", pack.document_id): pack.generation for pack in packs
    }
    pack_generations[("find_replace", "find-replace")] = find_pack.generation
    references = tuple(
        reference
        for reference in previous_pack_references
        if pack_generations.get((reference.kind, reference.owner_id))
        == reference.generation
    )
    find_reference = next(
        (reference for reference in references if reference.kind == "find_replace"),
        None,
    )
    find_manifest = FindReplaceManifestRecord(
        find_current=find_state.find.current,
        replace_current=find_state.replace.current,
        regex=find_state.regex,
        case_sensitive=find_state.case_sensitive,
        whole_word=find_state.whole_word,
        visible=find_state.visible,
        geometry=find_state.geometry,
        zoom_percent=find_state.zoom_percent,
        report_visible=find_state.report_visible,
        last_target_view_id=find_state.last_target_view_id,
        history_pack=find_reference,
    )
    manifest = SessionManifest(
        schema=SESSION_SCHEMA,
        generation=generation,
        service_id=service_id,
        build_identity=build_identity,
        created_at=created_at,
        updated_at=updated_at,
        clean_shutdown=clean_shutdown,
        active_window_id=active_window_id,
        active_view_id=active_view_id,
        windows=windows,
        views=tuple(views),
        documents=tuple(documents),
        find_replace=find_manifest,
        packs=references,
        notices=tuple(notices),
    )
    return SessionSnapshot(manifest, tuple(packs), find_pack)


def _filter_pane_views(
    pane: PaneRecord,
    retained_view_ids: frozenset[str],
) -> PaneRecord:
    if pane.kind == "leaf":
        view_ids = tuple(
            view_id for view_id in pane.view_ids if view_id in retained_view_ids
        )
        selected = (
            pane.selected_view_id
            if pane.selected_view_id in view_ids
            else (view_ids[0] if view_ids else None)
        )
        return replace(pane, view_ids=view_ids, selected_view_id=selected)
    children = tuple(
        _filter_pane_views(child, retained_view_ids) for child in pane.children
    )
    return replace(pane, children=children)


def _pane_contains_view(pane: PaneRecord, view_id: str) -> bool:
    if pane.kind == "leaf":
        return view_id in pane.view_ids
    return any(_pane_contains_view(child, view_id) for child in pane.children)


def restore_document_pack(
    pack: HistoryPack,
    requested_view_ids: tuple[str, ...],
    *,
    resource_manager: object,
) -> RestoreDocumentResult:
    """Verify exact source bytes, then open and import one saved history pack."""

    normalized_path = normalize_native_path(pack.canonical_path).path
    selected_pack = replace(pack, canonical_path=str(normalized_path))
    seal = RestoreSeal(
        pack.document_id,
        pack.saved_stamp.sha256,
        pack.generation,
        requested_view_ids,
    )
    match = verify_saved_file(normalized_path, pack.saved_stamp)
    if match not in {FileMatch.EXACT_FAST, FileMatch.EXACT_HASH}:
        return RestoreDocumentResult(seal, match, selected_pack, None)
    document = Document.open(
        normalized_path,
        profile=encoding_profile(pack.source_profile_key),
        resource_manager=resource_manager,
    )
    try:
        selected_eol = (
            EOLPolicy.PRESERVE
            if pack.selected_output_eol is None
            else EOLPolicy(pack.selected_output_eol)
        )
        document.set_output_format(
            OutputFormat(
                encoding_profile(pack.selected_output_profile_key),
                selected_eol,
            )
        )
        document.restore_history(pack.history)
    except Exception:
        document.close()
        raise
    return RestoreDocumentResult(seal, match, selected_pack, document)


def restore_fresh_document(
    document_id: str,
    canonical_path: str,
    requested_view_ids: tuple[str, ...],
    *,
    resource_manager: object,
) -> FreshDocumentResult:
    """Open a saved document whose convenience history was not admitted."""

    normalized_path = normalize_native_path(canonical_path).path
    document = Document.open(normalized_path, resource_manager=resource_manager)
    try:
        stamp = stamp_saved_file(normalized_path, document.disk_identity)
        if stamp is None:
            raise OSError("saved file changed while opening")
        return FreshDocumentResult(
            document_id,
            str(normalized_path),
            requested_view_ids,
            document,
            stamp,
        )
    except Exception:
        document.close()
        raise


def merge_find_replace_history(manifest_record, history_pack):
    """Reconstitute the panel record from manifest state and optional history."""

    from .session import FindReplaceRecord, InputHistoryRecord, estimate_input_history_bytes

    if history_pack is None:
        find = InputHistoryRecord(
            manifest_record.find_current,
            (),
            (),
            estimate_input_history_bytes(manifest_record.find_current, (), ()),
        )
        replace_history = InputHistoryRecord(
            manifest_record.replace_current,
            (),
            (),
            estimate_input_history_bytes(manifest_record.replace_current, (), ()),
        )
    else:
        find = replace(history_pack.find, current=manifest_record.find_current)
        replace_history = replace(
            history_pack.replace,
            current=manifest_record.replace_current,
        )
    return FindReplaceRecord(
        find=find,
        replace=replace_history,
        regex=manifest_record.regex,
        case_sensitive=manifest_record.case_sensitive,
        whole_word=manifest_record.whole_word,
        visible=manifest_record.visible,
        geometry=manifest_record.geometry,
        zoom_percent=manifest_record.zoom_percent,
        report_visible=manifest_record.report_visible,
        last_target_view_id=manifest_record.last_target_view_id,
    )


__all__ = [
    "FreshDocumentResult",
    "RestoreDocumentResult",
    "RestoreSeal",
    "capture_service_session",
    "merge_find_replace_history",
    "restore_document_pack",
    "restore_fresh_document",
    "stamp_saved_file",
]
