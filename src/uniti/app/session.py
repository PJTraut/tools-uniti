"""Bounded immutable records and codecs for durable UNITI sessions."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from uniti.core.file_identity import FileIdentity, SavedFileStamp
from uniti.core.history import (
    EditHistory,
    EditOperation,
    EditTransaction,
    HistorySnapshot,
    HistoryTruncation,
)


SESSION_SCHEMA = 2
HISTORY_PACK_SCHEMA = 1
MAX_MANIFEST_BYTES = 1 << 20
MAX_PACK_ENCODED_BYTES = 32 << 20
MAX_PACK_DECODED_BYTES = 32 << 20
MAX_FIND_REPLACE_DECODED_BYTES = 4 << 20
MAX_WINDOWS = 32
MAX_LEAF_PANES = 128
MAX_VIEWS = 256
MAX_DOCUMENTS = 128
MAX_INPUT_HISTORY_STATES = 50

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_EOL_VALUES = frozenset({None, "LF", "CRLF", "CR"})
_WINDOW_STATES = frozenset({"normal", "maximized", "fullscreen", "minimized"})
_FIND_REPLACE_PLACEMENTS = frozenset({"attached", "detached"})


class UnsupportedSessionSchema(ValueError):
    """Raised when persisted state uses a newer or unknown schema."""


def _require_identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError(f"{field} must be a non-empty bounded string")
    return value


def _require_timestamp(value: object, field: str) -> str:
    text = _require_identifier(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return text


def _require_sha256(value: object, field: str = "SHA-256") -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be 64 lowercase hex characters")
    return value


def _require_plain_int(
    value: object,
    field: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{field} must be an integer of at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field} must be no more than {maximum}")
    return value


def _require_bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field} must be a boolean")
    return value


def _require_tuple(value: object, field: str) -> tuple:
    if not isinstance(value, tuple):
        raise ValueError(f"{field} must be an immutable tuple")
    return value


def _validate_geometry(
    geometry: tuple[int, int, int, int] | None,
    *,
    optional: bool,
) -> None:
    if geometry is None:
        if optional:
            return
        raise ValueError("geometry is required")
    if not isinstance(geometry, tuple) or len(geometry) != 4:
        raise ValueError("geometry must contain x, y, width, and height")
    x, y, width, height = geometry
    if any(type(item) is not int for item in geometry):
        raise ValueError("geometry values must be integers")
    if width <= 0 or height <= 0:
        raise ValueError("geometry width and height must be positive")
    if abs(x) > 10_000_000 or abs(y) > 10_000_000:
        raise ValueError("geometry origin is outside the supported range")


@dataclass(frozen=True, slots=True)
class PersistenceNotice:
    scope: str
    reason: str
    dropped_count: int = 0
    dropped_bytes: int = 0

    def __post_init__(self) -> None:
        _require_identifier(self.scope, "notice scope")
        _require_identifier(self.reason, "notice reason")
        _require_plain_int(self.dropped_count, "notice dropped_count")
        _require_plain_int(self.dropped_bytes, "notice dropped_bytes")


@dataclass(frozen=True, slots=True)
class InputStateRecord:
    text: str
    position: int
    anchor: int

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ValueError("input text must be a string")
        _require_plain_int(self.position, "input position", maximum=len(self.text))
        _require_plain_int(self.anchor, "input anchor", maximum=len(self.text))


def estimate_input_history_bytes(
    current: InputStateRecord,
    undo: tuple[InputStateRecord, ...],
    redo: tuple[InputStateRecord, ...],
) -> int:
    """Return conservative decoded UTF-8 storage for one input history."""

    states = (current, *undo, *redo)
    return 16 + sum(24 + len(state.text.encode("utf-8")) for state in states)


@dataclass(frozen=True, slots=True)
class InputHistoryRecord:
    current: InputStateRecord
    undo: tuple[InputStateRecord, ...]
    redo: tuple[InputStateRecord, ...]
    decoded_bytes: int
    notices: tuple[PersistenceNotice, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.current, InputStateRecord):
            raise ValueError("input history current state is invalid")
        _require_tuple(self.undo, "input undo history")
        _require_tuple(self.redo, "input redo history")
        if len(self.undo) + len(self.redo) > MAX_INPUT_HISTORY_STATES:
            raise ValueError("input history exceeds 50 retained states")
        if any(not isinstance(item, InputStateRecord) for item in self.undo + self.redo):
            raise ValueError("input history contains an invalid state")
        expected = estimate_input_history_bytes(self.current, self.undo, self.redo)
        if self.decoded_bytes != expected:
            raise ValueError("input history decoded byte count does not match")
        _validate_notices(self.notices)


@dataclass(frozen=True, slots=True)
class FindReplaceRecord:
    find: InputHistoryRecord
    replace: InputHistoryRecord
    regex: bool
    case_sensitive: bool
    whole_word: bool
    visible: bool
    geometry: tuple[int, int, int, int] | None
    zoom_percent: int
    report_visible: bool
    last_target_view_id: str | None
    placement: Literal["attached", "detached"] = "detached"

    def __post_init__(self) -> None:
        if not isinstance(self.find, InputHistoryRecord) or not isinstance(
            self.replace, InputHistoryRecord
        ):
            raise ValueError("find/replace input histories are invalid")
        _validate_find_replace_options(self)


def _input_history_with_states(
    history: InputHistoryRecord,
    undo: list[InputStateRecord],
    redo: list[InputStateRecord],
    *,
    dropped_count: int,
    dropped_bytes: int,
) -> InputHistoryRecord:
    undo_value = tuple(undo)
    redo_value = tuple(redo)
    notices = history.notices
    if dropped_count:
        notices += (
            PersistenceNotice(
                "find_replace",
                "field_history_byte_limit",
                dropped_count,
                dropped_bytes,
            ),
        )
    return InputHistoryRecord(
        history.current,
        undo_value,
        redo_value,
        estimate_input_history_bytes(
            history.current,
            undo_value,
            redo_value,
        ),
        notices,
    )


def bound_find_replace_histories(
    find: InputHistoryRecord,
    replace: InputHistoryRecord,
    *,
    max_bytes: int = MAX_FIND_REPLACE_DECODED_BYTES,
) -> tuple[InputHistoryRecord, InputHistoryRecord]:
    """Prune convenience field history while preserving current values."""

    if not isinstance(find, InputHistoryRecord) or not isinstance(
        replace, InputHistoryRecord
    ):
        raise TypeError("find and replace must be InputHistoryRecord values")
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    histories = (find, replace)
    undo = [list(item.undo) for item in histories]
    redo = [list(item.redo) for item in histories]
    dropped_count = [0, 0]
    dropped_bytes = [0, 0]
    total = find.decoded_bytes + replace.decoded_bytes
    for stacks in (undo, redo):
        while total > max_bytes and any(stacks):
            for index, stack in enumerate(stacks):
                if total <= max_bytes:
                    break
                if not stack:
                    continue
                state = stack.pop(0)
                size = 24 + len(state.text.encode("utf-8"))
                total -= size
                dropped_count[index] += 1
                dropped_bytes[index] += size
    if total > max_bytes:
        raise ValueError(
            "current Find/Replace values exceed the persistence byte limit"
        )
    bounded = tuple(
        _input_history_with_states(
            history,
            undo[index],
            redo[index],
            dropped_count=dropped_count[index],
            dropped_bytes=dropped_bytes[index],
        )
        for index, history in enumerate(histories)
    )
    return bounded[0], bounded[1]


@dataclass(frozen=True, slots=True)
class FindReplaceManifestRecord:
    find_current: InputStateRecord
    replace_current: InputStateRecord
    regex: bool
    case_sensitive: bool
    whole_word: bool
    visible: bool
    geometry: tuple[int, int, int, int] | None
    zoom_percent: int
    report_visible: bool
    last_target_view_id: str | None
    history_pack: HistoryPackReference | None
    placement: Literal["attached", "detached"] = "detached"

    def __post_init__(self) -> None:
        if not isinstance(self.find_current, InputStateRecord) or not isinstance(
            self.replace_current, InputStateRecord
        ):
            raise ValueError("find/replace current input states are invalid")
        _validate_find_replace_options(self)
        if self.history_pack is not None and (
            not isinstance(self.history_pack, HistoryPackReference)
            or self.history_pack.kind != "find_replace"
        ):
            raise ValueError("find/replace history pack reference is invalid")


def _validate_find_replace_options(record: object) -> None:
    for field in ("regex", "case_sensitive", "whole_word", "visible", "report_visible"):
        _require_bool(getattr(record, field), f"find/replace {field}")
    _validate_geometry(getattr(record, "geometry"), optional=True)
    _require_plain_int(
        getattr(record, "zoom_percent"),
        "find/replace zoom_percent",
        minimum=25,
        maximum=500,
    )
    target = getattr(record, "last_target_view_id")
    if target is not None:
        _require_identifier(target, "find/replace target view ID")
    _require_placement(getattr(record, "placement"))


def _require_placement(value: object) -> str:
    if value not in _FIND_REPLACE_PLACEMENTS:
        raise ValueError("find/replace placement must be attached or detached")
    return value


@dataclass(frozen=True, slots=True)
class DockReturnRecord:
    window_id: str
    pane_id: str
    tab_index: int

    def __post_init__(self) -> None:
        _require_identifier(self.window_id, "dock return window ID")
        _require_identifier(self.pane_id, "dock return pane ID")
        _require_plain_int(
            self.tab_index,
            "dock return tab index",
            maximum=MAX_VIEWS,
        )


@dataclass(frozen=True, slots=True)
class ViewRecord:
    view_id: str
    document_id: str
    cursor: int
    anchor: int
    preferred_column: int | None
    vertical_scroll: int
    horizontal_scroll: int
    wrap_viewport_row: int
    soft_wrap: bool
    zoom_percent: int
    dock_return: DockReturnRecord | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.view_id, "view ID")
        _require_identifier(self.document_id, "view document ID")
        _require_plain_int(self.cursor, "view cursor")
        _require_plain_int(self.anchor, "view anchor")
        if self.preferred_column is not None:
            _require_plain_int(self.preferred_column, "view preferred_column")
        _require_plain_int(self.vertical_scroll, "view vertical_scroll")
        _require_plain_int(self.horizontal_scroll, "view horizontal_scroll")
        _require_plain_int(self.wrap_viewport_row, "view wrap_viewport_row")
        _require_bool(self.soft_wrap, "view soft_wrap")
        _require_plain_int(
            self.zoom_percent, "view zoom_percent", minimum=25, maximum=500
        )
        if self.dock_return is not None and not isinstance(
            self.dock_return, DockReturnRecord
        ):
            raise ValueError("view dock return is invalid")


@dataclass(frozen=True, slots=True)
class PaneRecord:
    kind: Literal["leaf", "split"]
    pane_id: str
    orientation: Literal["horizontal", "vertical"] | None = None
    proportions: tuple[float, float] | None = None
    children: tuple[PaneRecord, ...] = ()
    view_ids: tuple[str, ...] = ()
    selected_view_id: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.pane_id, "pane ID")
        _require_tuple(self.children, "pane children")
        _require_tuple(self.view_ids, "pane view IDs")
        if self.kind == "leaf":
            if self.orientation is not None or self.proportions is not None or self.children:
                raise ValueError("leaf pane cannot have split fields")
            if any(not isinstance(item, str) or not item for item in self.view_ids):
                raise ValueError("leaf pane view IDs are invalid")
            if len(set(self.view_ids)) != len(self.view_ids):
                raise ValueError("leaf pane contains duplicate view IDs")
            if self.selected_view_id is not None and self.selected_view_id not in self.view_ids:
                raise ValueError("leaf pane selected view is not in its view IDs")
            return
        if self.kind != "split":
            raise ValueError("pane kind must be leaf or split")
        if self.orientation not in ("horizontal", "vertical"):
            raise ValueError("split pane orientation is invalid")
        if self.proportions is None or len(self.proportions) != 2:
            raise ValueError("split pane proportions must contain two values")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
            for value in self.proportions
        ) or not math.isclose(sum(self.proportions), 1.0, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError("split pane proportions must be positive and sum to one")
        if len(self.children) != 2 or any(
            not isinstance(child, PaneRecord) for child in self.children
        ):
            raise ValueError("split pane must contain exactly two child panes")
        if self.view_ids or self.selected_view_id is not None:
            raise ValueError("split pane cannot contain leaf view fields")


@dataclass(frozen=True, slots=True)
class WindowRecord:
    window_id: str
    geometry: tuple[int, int, int, int]
    window_state: str
    root: PaneRecord

    def __post_init__(self) -> None:
        _require_identifier(self.window_id, "window ID")
        _validate_geometry(self.geometry, optional=False)
        if self.window_state not in _WINDOW_STATES:
            raise ValueError("window state is invalid")
        if not isinstance(self.root, PaneRecord):
            raise ValueError("window root pane is invalid")


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    document_id: str
    canonical_path: str
    view_ids: tuple[str, ...]
    last_active_at: str
    closed_at: str | None

    def __post_init__(self) -> None:
        _require_identifier(self.document_id, "document ID")
        _require_identifier(self.canonical_path, "document canonical path")
        _require_tuple(self.view_ids, "document view IDs")
        if any(not isinstance(item, str) or not item for item in self.view_ids):
            raise ValueError("document view IDs are invalid")
        if len(set(self.view_ids)) != len(self.view_ids):
            raise ValueError("document contains duplicate view IDs")
        _require_timestamp(self.last_active_at, "document last_active_at")
        if self.closed_at is not None:
            _require_timestamp(self.closed_at, "document closed_at")


@dataclass(frozen=True, slots=True)
class HistoryPackReference:
    kind: Literal["document", "find_replace"]
    owner_id: str
    generation: str
    filename: str
    encoded_bytes: int
    decoded_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        if self.kind not in ("document", "find_replace"):
            raise ValueError("history pack kind is invalid")
        _require_identifier(self.owner_id, "history pack owner ID")
        _require_identifier(self.generation, "history pack generation")
        _require_identifier(self.filename, "history pack filename")
        if (
            Path(self.filename).name != self.filename
            or "/" in self.filename
            or "\\" in self.filename
        ):
            raise ValueError("history pack filename must be a safe basename")
        _require_plain_int(
            self.encoded_bytes,
            "history pack encoded_bytes",
            maximum=MAX_PACK_ENCODED_BYTES * 2,
        )
        _require_plain_int(
            self.decoded_bytes,
            "history pack decoded_bytes",
            maximum=MAX_PACK_DECODED_BYTES,
        )
        _require_sha256(self.sha256)


@dataclass(frozen=True, slots=True)
class HistoryPack:
    document_id: str
    generation: str
    canonical_path: str
    saved_stamp: SavedFileStamp
    source_profile_key: str
    selected_output_profile_key: str
    selected_output_eol: str | None
    saved_output_profile_key: str
    saved_output_eol: str | None
    history: HistorySnapshot
    last_active_at: str
    closed_at: str | None
    notices: tuple[PersistenceNotice, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.document_id, "history document ID")
        _require_identifier(self.generation, "history generation")
        _require_identifier(self.canonical_path, "history canonical path")
        if not isinstance(self.saved_stamp, SavedFileStamp):
            raise ValueError("history saved file stamp is invalid")
        _require_identifier(self.source_profile_key, "history source profile")
        _require_identifier(
            self.selected_output_profile_key, "history selected output profile"
        )
        _require_identifier(
            self.saved_output_profile_key, "history saved output profile"
        )
        if self.selected_output_eol not in _EOL_VALUES:
            raise ValueError("history selected output EOL is invalid")
        if self.saved_output_eol not in _EOL_VALUES:
            raise ValueError("history saved output EOL is invalid")
        _validate_history_snapshot(self.history)
        if self.history.decoded_bytes > MAX_PACK_DECODED_BYTES:
            raise ValueError("history exceeds the decoded pack limit")
        if not self.history.persistable:
            raise ValueError("non-persistable document history cannot form a pack")
        _require_timestamp(self.last_active_at, "history last_active_at")
        if self.closed_at is not None:
            _require_timestamp(self.closed_at, "history closed_at")
        _validate_notices(self.notices)


@dataclass(frozen=True, slots=True)
class FindReplaceHistoryPack:
    generation: str
    find: InputHistoryRecord
    replace: InputHistoryRecord
    notices: tuple[PersistenceNotice, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.generation, "find/replace history generation")
        if not isinstance(self.find, InputHistoryRecord) or not isinstance(
            self.replace, InputHistoryRecord
        ):
            raise ValueError("find/replace history inputs are invalid")
        if self.find.decoded_bytes + self.replace.decoded_bytes > MAX_FIND_REPLACE_DECODED_BYTES:
            raise ValueError("find/replace history exceeds the 4 MiB decoded limit")
        _validate_notices(self.notices)


@dataclass(frozen=True, slots=True)
class SessionManifest:
    schema: int
    generation: str
    service_id: str
    build_identity: str
    created_at: str
    updated_at: str
    clean_shutdown: bool
    active_window_id: str | None
    active_view_id: str | None
    windows: tuple[WindowRecord, ...]
    views: tuple[ViewRecord, ...]
    documents: tuple[DocumentRecord, ...]
    find_replace: FindReplaceManifestRecord
    packs: tuple[HistoryPackReference, ...]
    notices: tuple[PersistenceNotice, ...] = ()

    def __post_init__(self) -> None:
        if type(self.schema) is not int or self.schema != SESSION_SCHEMA:
            raise UnsupportedSessionSchema(f"unsupported session schema: {self.schema}")
        _require_identifier(self.generation, "session generation")
        _require_identifier(self.service_id, "session service ID")
        _require_identifier(self.build_identity, "session build identity")
        _require_timestamp(self.created_at, "session created_at")
        _require_timestamp(self.updated_at, "session updated_at")
        _require_bool(self.clean_shutdown, "session clean_shutdown")
        for field, values, maximum in (
            ("windows", self.windows, MAX_WINDOWS),
            ("views", self.views, MAX_VIEWS),
            ("documents", self.documents, MAX_DOCUMENTS),
        ):
            _require_tuple(values, f"session {field}")
            if len(values) > maximum:
                raise ValueError(f"session exceeds {maximum} {field}")
        _require_tuple(self.packs, "session packs")
        if len(self.packs) > MAX_DOCUMENTS + 1:
            raise ValueError("session contains too many history pack references")
        if not isinstance(self.find_replace, FindReplaceManifestRecord):
            raise ValueError("session find/replace state is invalid")
        _validate_notices(self.notices)
        _validate_manifest_structure(self)


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    manifest: SessionManifest
    packs: tuple[HistoryPack, ...]
    find_replace_pack: FindReplaceHistoryPack | None

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, SessionManifest):
            raise ValueError("session snapshot manifest is invalid")
        _require_tuple(self.packs, "session snapshot packs")
        if any(not isinstance(item, HistoryPack) for item in self.packs):
            raise ValueError("session snapshot contains an invalid document history pack")
        document_by_id = {
            item.document_id: item for item in self.manifest.documents
        }
        pack_ids = [item.document_id for item in self.packs]
        if len(set(pack_ids)) != len(pack_ids):
            raise ValueError("session snapshot contains duplicate document history packs")
        for pack in self.packs:
            document = document_by_id.get(pack.document_id)
            if document is None:
                raise ValueError("session snapshot history references an unknown document")
            if (
                pack.canonical_path != document.canonical_path
                or pack.closed_at != document.closed_at
            ):
                raise ValueError("session snapshot history does not match its document")
        if self.find_replace_pack is not None and not isinstance(
            self.find_replace_pack, FindReplaceHistoryPack
        ):
            raise ValueError("session snapshot find/replace pack is invalid")


@dataclass(frozen=True, slots=True)
class SessionProblem:
    kind: str
    evidence_path: Path
    safe_message: str
    document_id: str | None = None


@dataclass(frozen=True, slots=True)
class LoadedSession:
    manifest: SessionManifest | None
    packs: tuple[HistoryPack, ...]
    find_replace_pack: FindReplaceHistoryPack | None
    problems: tuple[SessionProblem, ...]


def _validate_notices(notices: tuple[PersistenceNotice, ...]) -> None:
    _require_tuple(notices, "persistence notices")
    if any(not isinstance(item, PersistenceNotice) for item in notices):
        raise ValueError("persistence notices contain an invalid record")


def _validate_history_snapshot(snapshot: HistorySnapshot) -> None:
    if not isinstance(snapshot, HistorySnapshot):
        raise ValueError("document history snapshot is invalid")
    validator = EditHistory()
    validator.restore(snapshot)


def _walk_panes(root: PaneRecord) -> tuple[list[PaneRecord], list[PaneRecord]]:
    all_panes: list[PaneRecord] = []
    leaves: list[PaneRecord] = []
    pending: list[tuple[PaneRecord, int]] = [(root, 1)]
    while pending:
        pane, depth = pending.pop()
        if depth > MAX_LEAF_PANES * 2:
            raise ValueError("pane tree is too deep")
        all_panes.append(pane)
        if pane.kind == "leaf":
            leaves.append(pane)
        else:
            pending.extend((child, depth + 1) for child in pane.children)
    return all_panes, leaves


def _unique_ids(records: Sequence[object], attribute: str, label: str) -> set[str]:
    values = [getattr(item, attribute) for item in records]
    if len(set(values)) != len(values):
        raise ValueError(f"session contains a duplicate {label}")
    return set(values)


def _validate_manifest_structure(manifest: SessionManifest) -> None:
    if any(not isinstance(item, WindowRecord) for item in manifest.windows):
        raise ValueError("session contains an invalid window")
    if any(not isinstance(item, ViewRecord) for item in manifest.views):
        raise ValueError("session contains an invalid view")
    if any(not isinstance(item, DocumentRecord) for item in manifest.documents):
        raise ValueError("session contains an invalid document")
    if any(not isinstance(item, HistoryPackReference) for item in manifest.packs):
        raise ValueError("session contains an invalid pack reference")

    window_ids = _unique_ids(manifest.windows, "window_id", "window ID")
    view_ids = _unique_ids(manifest.views, "view_id", "view ID")
    document_ids = _unique_ids(manifest.documents, "document_id", "document ID")

    panes: list[PaneRecord] = []
    leaves: list[PaneRecord] = []
    for window in manifest.windows:
        window_panes, window_leaves = _walk_panes(window.root)
        panes.extend(window_panes)
        leaves.extend(window_leaves)
    if len(leaves) > MAX_LEAF_PANES:
        raise ValueError(f"session exceeds {MAX_LEAF_PANES} leaf panes")
    _unique_ids(panes, "pane_id", "pane ID")

    pane_view_ids = [view_id for leaf in leaves for view_id in leaf.view_ids]
    if len(set(pane_view_ids)) != len(pane_view_ids):
        raise ValueError("session assigns a view to more than one pane")
    unknown_pane_views = set(pane_view_ids) - view_ids
    if unknown_pane_views:
        raise ValueError("pane references an unknown view")
    if set(pane_view_ids) != view_ids:
        raise ValueError("session view is not assigned to a pane")

    views_by_document: dict[str, set[str]] = {item: set() for item in document_ids}
    for view in manifest.views:
        if view.document_id not in document_ids:
            raise ValueError("view references an unknown document")
        views_by_document[view.document_id].add(view.view_id)
    for document in manifest.documents:
        if set(document.view_ids) != views_by_document[document.document_id]:
            raise ValueError("document view references do not match session views")

    if manifest.active_window_id is not None:
        _require_identifier(manifest.active_window_id, "active window ID")
        if manifest.active_window_id not in window_ids:
            raise ValueError("active window references an unknown window")
    if manifest.active_view_id is not None:
        _require_identifier(manifest.active_view_id, "active view ID")
        if manifest.active_view_id not in view_ids:
            raise ValueError("active view references an unknown view")
    target = manifest.find_replace.last_target_view_id
    if target is not None and target not in view_ids:
        raise ValueError("find/replace panel references an unknown view")

    pack_keys: set[tuple[str, str]] = set()
    filenames: set[str] = set()
    for reference in manifest.packs:
        key = (reference.kind, reference.owner_id)
        if key in pack_keys:
            raise ValueError("session contains a duplicate history pack reference")
        pack_keys.add(key)
        if reference.filename in filenames:
            raise ValueError("session contains a duplicate history pack filename")
        filenames.add(reference.filename)
        if reference.kind == "document" and reference.owner_id not in document_ids:
            raise ValueError("history pack references an unknown document")
    find_reference = manifest.find_replace.history_pack
    find_references = [item for item in manifest.packs if item.kind == "find_replace"]
    if len(find_references) > 1:
        raise ValueError("session contains multiple find/replace history references")
    if find_reference is None and find_references:
        raise ValueError("session has an unclaimed find/replace history reference")
    if find_reference is not None and find_reference not in manifest.packs:
        raise ValueError("find/replace history reference is absent from session packs")


def _canonical_json(payload: object) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("session payload is not JSON-compatible") from exc


def _notice_to_payload(notice: PersistenceNotice) -> dict[str, object]:
    return {
        "dropped_bytes": notice.dropped_bytes,
        "dropped_count": notice.dropped_count,
        "reason": notice.reason,
        "scope": notice.scope,
    }


def _state_to_payload(state: InputStateRecord) -> dict[str, object]:
    return {"anchor": state.anchor, "position": state.position, "text": state.text}


def _reference_to_payload(reference: HistoryPackReference) -> dict[str, object]:
    return {
        "decoded_bytes": reference.decoded_bytes,
        "encoded_bytes": reference.encoded_bytes,
        "filename": reference.filename,
        "generation": reference.generation,
        "kind": reference.kind,
        "owner_id": reference.owner_id,
        "sha256": reference.sha256,
    }


def _pane_to_payload(pane: PaneRecord) -> dict[str, object]:
    return {
        "children": [_pane_to_payload(child) for child in pane.children],
        "kind": pane.kind,
        "orientation": pane.orientation,
        "pane_id": pane.pane_id,
        "proportions": list(pane.proportions) if pane.proportions is not None else None,
        "selected_view_id": pane.selected_view_id,
        "view_ids": list(pane.view_ids),
    }


def manifest_to_payload(manifest: SessionManifest) -> dict[str, object]:
    if not isinstance(manifest, SessionManifest):
        raise TypeError("manifest must be a SessionManifest")
    payload: dict[str, object] = {
        "active_view_id": manifest.active_view_id,
        "active_window_id": manifest.active_window_id,
        "build_identity": manifest.build_identity,
        "clean_shutdown": manifest.clean_shutdown,
        "created_at": manifest.created_at,
        "documents": [
            {
                "canonical_path": item.canonical_path,
                "closed_at": item.closed_at,
                "document_id": item.document_id,
                "last_active_at": item.last_active_at,
                "view_ids": list(item.view_ids),
            }
            for item in manifest.documents
        ],
        "find_replace": {
            "case_sensitive": manifest.find_replace.case_sensitive,
            "find_current": _state_to_payload(manifest.find_replace.find_current),
            "geometry": (
                list(manifest.find_replace.geometry)
                if manifest.find_replace.geometry is not None
                else None
            ),
            "history_pack": (
                _reference_to_payload(manifest.find_replace.history_pack)
                if manifest.find_replace.history_pack is not None
                else None
            ),
            "last_target_view_id": manifest.find_replace.last_target_view_id,
            "placement": manifest.find_replace.placement,
            "regex": manifest.find_replace.regex,
            "replace_current": _state_to_payload(manifest.find_replace.replace_current),
            "report_visible": manifest.find_replace.report_visible,
            "visible": manifest.find_replace.visible,
            "whole_word": manifest.find_replace.whole_word,
            "zoom_percent": manifest.find_replace.zoom_percent,
        },
        "generation": manifest.generation,
        "notices": [_notice_to_payload(item) for item in manifest.notices],
        "packs": [_reference_to_payload(item) for item in manifest.packs],
        "schema": manifest.schema,
        "service_id": manifest.service_id,
        "updated_at": manifest.updated_at,
        "views": [
            {
                "anchor": item.anchor,
                "cursor": item.cursor,
                "document_id": item.document_id,
                "dock_return": (
                    None
                    if item.dock_return is None
                    else {
                        "pane_id": item.dock_return.pane_id,
                        "tab_index": item.dock_return.tab_index,
                        "window_id": item.dock_return.window_id,
                    }
                ),
                "horizontal_scroll": item.horizontal_scroll,
                "preferred_column": item.preferred_column,
                "soft_wrap": item.soft_wrap,
                "vertical_scroll": item.vertical_scroll,
                "view_id": item.view_id,
                "wrap_viewport_row": item.wrap_viewport_row,
                "zoom_percent": item.zoom_percent,
            }
            for item in manifest.views
        ],
        "windows": [
            {
                "geometry": list(item.geometry),
                "root": _pane_to_payload(item.root),
                "window_id": item.window_id,
                "window_state": item.window_state,
            }
            for item in manifest.windows
        ],
    }
    if len(_canonical_json(payload)) > MAX_MANIFEST_BYTES:
        raise ValueError("session manifest exceeds the 1 MiB decoded limit")
    return payload


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object")
    return value


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _keys(
    payload: Mapping[str, object],
    required: set[str],
    field: str,
) -> None:
    if set(payload) != required:
        raise ValueError(f"{field} has missing or unknown fields")


def _state_from_payload(value: object) -> InputStateRecord:
    payload = _mapping(value, "input state")
    _keys(payload, {"text", "position", "anchor"}, "input state")
    return InputStateRecord(payload["text"], payload["position"], payload["anchor"])


def _notice_from_payload(value: object) -> PersistenceNotice:
    payload = _mapping(value, "persistence notice")
    _keys(
        payload,
        {"scope", "reason", "dropped_count", "dropped_bytes"},
        "persistence notice",
    )
    return PersistenceNotice(
        payload["scope"],
        payload["reason"],
        payload["dropped_count"],
        payload["dropped_bytes"],
    )


def _reference_from_payload(value: object) -> HistoryPackReference:
    payload = _mapping(value, "history pack reference")
    _keys(
        payload,
        {
            "kind",
            "owner_id",
            "generation",
            "filename",
            "encoded_bytes",
            "decoded_bytes",
            "sha256",
        },
        "history pack reference",
    )
    return HistoryPackReference(
        payload["kind"],
        payload["owner_id"],
        payload["generation"],
        payload["filename"],
        payload["encoded_bytes"],
        payload["decoded_bytes"],
        payload["sha256"],
    )


def _pane_from_payload(value: object, *, depth: int = 1) -> PaneRecord:
    if depth > MAX_LEAF_PANES * 2:
        raise ValueError("pane tree is too deep")
    payload = _mapping(value, "pane")
    _keys(
        payload,
        {
            "kind",
            "pane_id",
            "orientation",
            "proportions",
            "children",
            "view_ids",
            "selected_view_id",
        },
        "pane",
    )
    proportions_value = payload["proportions"]
    proportions = (
        None
        if proportions_value is None
        else tuple(_list(proportions_value, "pane proportions"))
    )
    return PaneRecord(
        payload["kind"],
        payload["pane_id"],
        payload["orientation"],
        proportions,
        tuple(
            _pane_from_payload(child, depth=depth + 1)
            for child in _list(payload["children"], "pane children")
        ),
        tuple(_list(payload["view_ids"], "pane view IDs")),
        payload["selected_view_id"],
    )


def _dock_return_from_payload(value: object) -> DockReturnRecord | None:
    if value is None:
        return None
    payload = _mapping(value, "dock return")
    _keys(payload, {"window_id", "pane_id", "tab_index"}, "dock return")
    return DockReturnRecord(
        payload["window_id"],
        payload["pane_id"],
        payload["tab_index"],
    )


def manifest_from_payload(value: object) -> SessionManifest:
    if len(_canonical_json(value)) > MAX_MANIFEST_BYTES:
        raise ValueError("session manifest exceeds the 1 MiB decoded limit")
    payload = _mapping(value, "session manifest")
    required = {
        "schema",
        "generation",
        "service_id",
        "build_identity",
        "created_at",
        "updated_at",
        "clean_shutdown",
        "active_window_id",
        "active_view_id",
        "windows",
        "views",
        "documents",
        "find_replace",
        "packs",
        "notices",
    }
    _keys(payload, required, "session manifest")
    source_schema = payload.get("schema")
    if type(source_schema) is not int or source_schema not in {1, SESSION_SCHEMA}:
        raise UnsupportedSessionSchema(
            f"unsupported session schema: {source_schema}"
        )

    windows_payload = _list(payload["windows"], "session windows")
    views_payload = _list(payload["views"], "session views")
    documents_payload = _list(payload["documents"], "session documents")
    packs_payload = _list(payload["packs"], "session packs")
    notices_payload = _list(payload["notices"], "session notices")
    if len(windows_payload) > MAX_WINDOWS:
        raise ValueError(f"session exceeds {MAX_WINDOWS} windows")
    if len(views_payload) > MAX_VIEWS:
        raise ValueError(f"session exceeds {MAX_VIEWS} views")
    if len(documents_payload) > MAX_DOCUMENTS:
        raise ValueError(f"session exceeds {MAX_DOCUMENTS} documents")

    windows = []
    for value in windows_payload:
        item = _mapping(value, "window")
        _keys(item, {"window_id", "geometry", "window_state", "root"}, "window")
        windows.append(
            WindowRecord(
                item["window_id"],
                tuple(_list(item["geometry"], "window geometry")),
                item["window_state"],
                _pane_from_payload(item["root"]),
            )
        )

    views = []
    view_fields_v1 = {
        "view_id",
        "document_id",
        "cursor",
        "anchor",
        "preferred_column",
        "vertical_scroll",
        "horizontal_scroll",
        "wrap_viewport_row",
        "soft_wrap",
        "zoom_percent",
    }
    view_fields = (
        view_fields_v1
        if source_schema == 1
        else view_fields_v1 | {"dock_return"}
    )
    for value in views_payload:
        item = _mapping(value, "view")
        _keys(item, view_fields, "view")
        view_values = dict(item)
        view_values["dock_return"] = (
            None
            if source_schema == 1
            else _dock_return_from_payload(item["dock_return"])
        )
        views.append(ViewRecord(**view_values))

    documents = []
    for value in documents_payload:
        item = _mapping(value, "document")
        _keys(
            item,
            {"document_id", "canonical_path", "view_ids", "last_active_at", "closed_at"},
            "document",
        )
        documents.append(
            DocumentRecord(
                item["document_id"],
                item["canonical_path"],
                tuple(_list(item["view_ids"], "document view IDs")),
                item["last_active_at"],
                item["closed_at"],
            )
        )

    find_payload = _mapping(payload["find_replace"], "find/replace manifest")
    find_fields_v1 = {
        "find_current",
        "replace_current",
        "regex",
        "case_sensitive",
        "whole_word",
        "visible",
        "geometry",
        "zoom_percent",
        "report_visible",
        "last_target_view_id",
        "history_pack",
    }
    find_fields = (
        find_fields_v1
        if source_schema == 1
        else find_fields_v1 | {"placement"}
    )
    _keys(find_payload, find_fields, "find/replace manifest")
    find_geometry = find_payload["geometry"]
    find_replace = FindReplaceManifestRecord(
        _state_from_payload(find_payload["find_current"]),
        _state_from_payload(find_payload["replace_current"]),
        find_payload["regex"],
        find_payload["case_sensitive"],
        find_payload["whole_word"],
        find_payload["visible"],
        None
        if find_geometry is None
        else tuple(_list(find_geometry, "find/replace geometry")),
        find_payload["zoom_percent"],
        find_payload["report_visible"],
        find_payload["last_target_view_id"],
        None
        if find_payload["history_pack"] is None
        else _reference_from_payload(find_payload["history_pack"]),
        "detached" if source_schema == 1 else find_payload["placement"],
    )

    return SessionManifest(
        schema=SESSION_SCHEMA,
        generation=payload["generation"],
        service_id=payload["service_id"],
        build_identity=payload["build_identity"],
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
        clean_shutdown=payload["clean_shutdown"],
        active_window_id=payload["active_window_id"],
        active_view_id=payload["active_view_id"],
        windows=tuple(windows),
        views=tuple(views),
        documents=tuple(documents),
        find_replace=find_replace,
        packs=tuple(_reference_from_payload(item) for item in packs_payload),
        notices=tuple(_notice_from_payload(item) for item in notices_payload),
    )


def _history_to_payload(snapshot: HistorySnapshot) -> dict[str, object]:
    return {
        "coalesce": snapshot.coalesce,
        "cursor": snapshot.cursor,
        "decoded_bytes": snapshot.decoded_bytes,
        "persistable": snapshot.persistable,
        "saved_cursor": snapshot.saved_cursor,
        "transactions": [
            [
                {
                    "deleted_text": operation.deleted_text,
                    "inserted_text": operation.inserted_text,
                    "start": operation.start,
                }
                for operation in transaction.operations
            ]
            for transaction in snapshot.transactions
        ],
        "truncations": [
            {
                "dropped_bytes": item.dropped_bytes,
                "dropped_transactions": item.dropped_transactions,
                "reason": item.reason,
            }
            for item in snapshot.truncations
        ],
    }


def _history_from_payload(value: object) -> HistorySnapshot:
    payload = _mapping(value, "document history")
    _keys(
        payload,
        {
            "transactions",
            "cursor",
            "saved_cursor",
            "coalesce",
            "decoded_bytes",
            "persistable",
            "truncations",
        },
        "document history",
    )
    transactions = []
    for transaction_value in _list(payload["transactions"], "history transactions"):
        operations = []
        for operation_value in _list(transaction_value, "history transaction"):
            operation = _mapping(operation_value, "history operation")
            _keys(operation, {"start", "deleted_text", "inserted_text"}, "history operation")
            operations.append(
                EditOperation(
                    operation["start"],
                    operation["deleted_text"],
                    operation["inserted_text"],
                )
            )
        transactions.append(EditTransaction(tuple(operations)))
    truncations = []
    for value in _list(payload["truncations"], "history truncations"):
        item = _mapping(value, "history truncation")
        _keys(
            item,
            {"reason", "dropped_transactions", "dropped_bytes"},
            "history truncation",
        )
        truncations.append(
            HistoryTruncation(
                item["reason"], item["dropped_transactions"], item["dropped_bytes"]
            )
        )
    snapshot = HistorySnapshot(
        tuple(transactions),
        payload["cursor"],
        payload["saved_cursor"],
        payload["coalesce"],
        payload["decoded_bytes"],
        payload["persistable"],
        tuple(truncations),
    )
    _validate_history_snapshot(snapshot)
    return snapshot


def _identity_to_payload(identity: FileIdentity) -> dict[str, object]:
    return {
        "device": identity.device,
        "inode": identity.inode,
        "mtime_ns": identity.mtime_ns,
        "size": identity.size,
    }


def _identity_from_payload(value: object) -> FileIdentity:
    payload = _mapping(value, "file identity")
    _keys(payload, {"size", "mtime_ns", "inode", "device"}, "file identity")
    for field in ("size", "mtime_ns"):
        _require_plain_int(payload[field], f"file identity {field}")
    for field in ("inode", "device"):
        if payload[field] is not None:
            _require_plain_int(payload[field], f"file identity {field}")
    return FileIdentity(
        payload["size"], payload["mtime_ns"], payload["inode"], payload["device"]
    )


def _history_pack_to_payload(pack: HistoryPack) -> dict[str, object]:
    return {
        "canonical_path": pack.canonical_path,
        "closed_at": pack.closed_at,
        "document_id": pack.document_id,
        "generation": pack.generation,
        "history": _history_to_payload(pack.history),
        "last_active_at": pack.last_active_at,
        "notices": [_notice_to_payload(item) for item in pack.notices],
        "saved_output_eol": pack.saved_output_eol,
        "saved_output_profile_key": pack.saved_output_profile_key,
        "saved_stamp": {
            "identity": _identity_to_payload(pack.saved_stamp.identity),
            "sha256": pack.saved_stamp.sha256,
        },
        "selected_output_eol": pack.selected_output_eol,
        "selected_output_profile_key": pack.selected_output_profile_key,
        "source_profile_key": pack.source_profile_key,
    }


def _history_pack_from_payload(value: object) -> HistoryPack:
    payload = _mapping(value, "document history pack")
    fields = {
        "document_id",
        "generation",
        "canonical_path",
        "saved_stamp",
        "source_profile_key",
        "selected_output_profile_key",
        "selected_output_eol",
        "saved_output_profile_key",
        "saved_output_eol",
        "history",
        "last_active_at",
        "closed_at",
        "notices",
    }
    _keys(payload, fields, "document history pack")
    stamp = _mapping(payload["saved_stamp"], "saved file stamp")
    _keys(stamp, {"identity", "sha256"}, "saved file stamp")
    return HistoryPack(
        document_id=payload["document_id"],
        generation=payload["generation"],
        canonical_path=payload["canonical_path"],
        saved_stamp=SavedFileStamp(
            _identity_from_payload(stamp["identity"]), stamp["sha256"]
        ),
        source_profile_key=payload["source_profile_key"],
        selected_output_profile_key=payload["selected_output_profile_key"],
        selected_output_eol=payload["selected_output_eol"],
        saved_output_profile_key=payload["saved_output_profile_key"],
        saved_output_eol=payload["saved_output_eol"],
        history=_history_from_payload(payload["history"]),
        last_active_at=payload["last_active_at"],
        closed_at=payload["closed_at"],
        notices=tuple(
            _notice_from_payload(item)
            for item in _list(payload["notices"], "history pack notices")
        ),
    )


def _state_delta(base: InputStateRecord, target: InputStateRecord) -> dict[str, object]:
    prefix = 0
    limit = min(len(base.text), len(target.text))
    while prefix < limit and base.text[prefix] == target.text[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < len(base.text) - prefix
        and suffix < len(target.text) - prefix
        and base.text[len(base.text) - suffix - 1]
        == target.text[len(target.text) - suffix - 1]
    ):
        suffix += 1
    insert_end = len(target.text) - suffix if suffix else len(target.text)
    return {
        "anchor": target.anchor,
        "insert": target.text[prefix:insert_end],
        "position": target.position,
        "prefix": prefix,
        "suffix": suffix,
    }


def _state_from_delta(base: InputStateRecord, value: object) -> InputStateRecord:
    payload = _mapping(value, "input history delta")
    _keys(payload, {"prefix", "suffix", "insert", "position", "anchor"}, "input delta")
    prefix = _require_plain_int(payload["prefix"], "input delta prefix")
    suffix = _require_plain_int(payload["suffix"], "input delta suffix")
    if prefix + suffix > len(base.text):
        raise ValueError("input history delta is outside its base text")
    if not isinstance(payload["insert"], str):
        raise ValueError("input history delta insert must be text")
    tail = base.text[len(base.text) - suffix :] if suffix else ""
    text = base.text[:prefix] + payload["insert"] + tail
    return InputStateRecord(text, payload["position"], payload["anchor"])


def _input_history_to_payload(history: InputHistoryRecord) -> dict[str, object]:
    return {
        "current": _state_to_payload(history.current),
        "decoded_bytes": history.decoded_bytes,
        "notices": [_notice_to_payload(item) for item in history.notices],
        "redo": [_state_delta(history.current, item) for item in history.redo],
        "undo": [_state_delta(history.current, item) for item in history.undo],
    }


def _input_history_from_payload(value: object) -> InputHistoryRecord:
    payload = _mapping(value, "input history")
    _keys(
        payload,
        {"current", "undo", "redo", "decoded_bytes", "notices"},
        "input history",
    )
    current = _state_from_payload(payload["current"])
    undo_values = _list(payload["undo"], "input undo history")
    redo_values = _list(payload["redo"], "input redo history")
    if len(undo_values) + len(redo_values) > MAX_INPUT_HISTORY_STATES:
        raise ValueError("input history exceeds 50 retained states")
    return InputHistoryRecord(
        current,
        tuple(_state_from_delta(current, item) for item in undo_values),
        tuple(_state_from_delta(current, item) for item in redo_values),
        payload["decoded_bytes"],
        tuple(
            _notice_from_payload(item)
            for item in _list(payload["notices"], "input history notices")
        ),
    )


def _find_pack_to_payload(pack: FindReplaceHistoryPack) -> dict[str, object]:
    return {
        "find": _input_history_to_payload(pack.find),
        "generation": pack.generation,
        "notices": [_notice_to_payload(item) for item in pack.notices],
        "replace": _input_history_to_payload(pack.replace),
    }


def _find_pack_from_payload(value: object) -> FindReplaceHistoryPack:
    payload = _mapping(value, "find/replace history pack")
    _keys(payload, {"generation", "find", "replace", "notices"}, "find/replace pack")
    return FindReplaceHistoryPack(
        payload["generation"],
        _input_history_from_payload(payload["find"]),
        _input_history_from_payload(payload["replace"]),
        tuple(
            _notice_from_payload(item)
            for item in _list(payload["notices"], "find/replace pack notices")
        ),
    )


def _encode_envelope(
    kind: str,
    payload: Mapping[str, object],
    *,
    decoded_limit: int,
) -> bytes:
    raw = _canonical_json(payload)
    if len(raw) > decoded_limit:
        raise ValueError("history pack exceeds its decoded limit")
    compressed = zlib.compress(raw, level=6)
    if len(compressed) > MAX_PACK_ENCODED_BYTES:
        raise ValueError("history pack exceeds its encoded limit")
    envelope = {
        "compression": "zlib",
        "decoded_bytes": len(raw),
        "encoded_bytes": len(compressed),
        "kind": kind,
        "payload": base64.b64encode(compressed).decode("ascii"),
        "schema": HISTORY_PACK_SCHEMA,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return _canonical_json(envelope)


def _decompress_bounded(compressed: bytes, maximum: int) -> bytes:
    decompressor = zlib.decompressobj()
    output = bytearray()
    try:
        for offset in range(0, len(compressed), 64 << 10):
            pending = compressed[offset : offset + (64 << 10)]
            while pending:
                block = decompressor.decompress(pending, maximum - len(output) + 1)
                if len(output) + len(block) > maximum:
                    raise ValueError("history pack decompression expansion exceeds limit")
                output.extend(block)
                pending = decompressor.unconsumed_tail
                if pending and len(output) >= maximum:
                    raise ValueError("history pack decompression expansion exceeds limit")
        block = decompressor.flush(maximum - len(output) + 1)
    except zlib.error as exc:
        raise ValueError("history pack contains invalid compressed data") from exc
    if len(output) + len(block) > maximum:
        raise ValueError("history pack decompression expansion exceeds limit")
    output.extend(block)
    if decompressor.unused_data:
        raise ValueError("history pack contains trailing compressed data")
    if not decompressor.eof:
        raise ValueError("history pack compressed stream is incomplete")
    return bytes(output)


def _decode_envelope(
    data: bytes,
    expected_kind: str,
    *,
    decoded_limit: int,
) -> Mapping[str, object]:
    if not isinstance(data, bytes):
        raise TypeError("encoded history pack must be bytes")
    maximum_envelope = (MAX_PACK_ENCODED_BYTES * 4 // 3) + 4096
    if len(data) > maximum_envelope:
        raise ValueError("history pack envelope exceeds its encoded limit")
    try:
        envelope_value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("history pack envelope is invalid JSON") from exc
    envelope = _mapping(envelope_value, "history pack envelope")
    _keys(
        envelope,
        {
            "schema",
            "kind",
            "compression",
            "encoded_bytes",
            "decoded_bytes",
            "sha256",
            "payload",
        },
        "history pack envelope",
    )
    if (
        type(envelope["schema"]) is not int
        or envelope["schema"] != HISTORY_PACK_SCHEMA
    ):
        raise UnsupportedSessionSchema(
            f"unsupported history pack schema: {envelope['schema']}"
        )
    if envelope["kind"] != expected_kind:
        raise ValueError("history pack kind does not match decoder")
    if envelope["compression"] != "zlib":
        raise ValueError("history pack compression is unsupported")
    encoded_bytes = _require_plain_int(
        envelope["encoded_bytes"],
        "history pack encoded length",
        maximum=MAX_PACK_ENCODED_BYTES,
    )
    decoded_bytes = _require_plain_int(
        envelope["decoded_bytes"],
        "history pack decoded length",
        maximum=decoded_limit,
    )
    _require_sha256(envelope["sha256"], "history pack SHA-256")
    if not isinstance(envelope["payload"], str):
        raise ValueError("history pack payload must be base64 text")
    try:
        compressed = base64.b64decode(envelope["payload"], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("history pack payload is invalid base64") from exc
    if len(compressed) != encoded_bytes:
        raise ValueError("history pack encoded length does not match")
    raw = _decompress_bounded(compressed, decoded_limit)
    if len(raw) != decoded_bytes:
        raise ValueError("history pack decoded length does not match")
    if hashlib.sha256(raw).hexdigest() != envelope["sha256"]:
        raise ValueError("history pack checksum does not match")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("history pack payload is invalid JSON") from exc
    return _mapping(payload, "history pack payload")


def encode_history_pack(pack: HistoryPack) -> bytes:
    if not isinstance(pack, HistoryPack):
        raise TypeError("pack must be a HistoryPack")
    return _encode_envelope(
        "document_history",
        _history_pack_to_payload(pack),
        decoded_limit=MAX_PACK_DECODED_BYTES,
    )


def decode_history_pack(data: bytes) -> HistoryPack:
    return _history_pack_from_payload(
        _decode_envelope(
            data,
            "document_history",
            decoded_limit=MAX_PACK_DECODED_BYTES,
        )
    )


def encode_find_replace_pack(pack: FindReplaceHistoryPack) -> bytes:
    if not isinstance(pack, FindReplaceHistoryPack):
        raise TypeError("pack must be a FindReplaceHistoryPack")
    return _encode_envelope(
        "find_replace_history",
        _find_pack_to_payload(pack),
        decoded_limit=MAX_FIND_REPLACE_DECODED_BYTES,
    )


def decode_find_replace_pack(data: bytes) -> FindReplaceHistoryPack:
    return _find_pack_from_payload(
        _decode_envelope(
            data,
            "find_replace_history",
            decoded_limit=MAX_FIND_REPLACE_DECODED_BYTES,
        )
    )
