import base64
import hashlib
import json
import zlib
from dataclasses import replace

import pytest

import uniti.app.session as session_module
from uniti.app.session import (
    SESSION_SCHEMA,
    DocumentRecord,
    FindReplaceHistoryPack,
    FindReplaceManifestRecord,
    HistoryPack,
    HistoryPackReference,
    InputHistoryRecord,
    InputStateRecord,
    PaneRecord,
    PersistenceNotice,
    SessionManifest,
    SessionSnapshot,
    UnsupportedSessionSchema,
    ViewRecord,
    WindowRecord,
    decode_find_replace_pack,
    decode_history_pack,
    encode_find_replace_pack,
    encode_history_pack,
    estimate_input_history_bytes,
    manifest_from_payload,
    manifest_to_payload,
)
from uniti.core.file_identity import FileIdentity, SavedFileStamp
from uniti.core.history import (
    EditHistory,
    EditOperation,
    EditTransaction,
)


NOW = "2026-09-04T10:00:00.000000Z"


def _state(text: str = "needle", position: int | None = None) -> InputStateRecord:
    cursor = len(text) if position is None else position
    return InputStateRecord(text, cursor, cursor)


def _input_history(
    text: str = "needle",
    *,
    undo: tuple[InputStateRecord, ...] = (),
    redo: tuple[InputStateRecord, ...] = (),
) -> InputHistoryRecord:
    current = _state(text)
    return InputHistoryRecord(
        current=current,
        undo=undo,
        redo=redo,
        decoded_bytes=estimate_input_history_bytes(current, undo, redo),
    )


def _find_manifest(
    history_pack: HistoryPackReference | None = None,
) -> FindReplaceManifestRecord:
    return FindReplaceManifestRecord(
        find_current=_state(),
        replace_current=_state("replacement"),
        regex=True,
        case_sensitive=False,
        whole_word=True,
        visible=True,
        geometry=(10, 20, 640, 320),
        zoom_percent=110,
        report_visible=True,
        last_target_view_id="view-1",
        history_pack=history_pack,
    )


def _manifest(**changes) -> SessionManifest:
    view = ViewRecord(
        view_id="view-1",
        document_id="doc-1",
        cursor=3,
        anchor=1,
        preferred_column=3,
        vertical_scroll=2,
        horizontal_scroll=0,
        wrap_viewport_row=0,
        soft_wrap=True,
        zoom_percent=100,
    )
    pane = PaneRecord(
        kind="leaf",
        pane_id="pane-1",
        view_ids=(view.view_id,),
        selected_view_id=view.view_id,
    )
    window = WindowRecord(
        window_id="window-1",
        geometry=(20, 30, 1024, 768),
        window_state="normal",
        root=pane,
    )
    document = DocumentRecord(
        document_id="doc-1",
        canonical_path="/tmp/document.txt",
        view_ids=(view.view_id,),
        last_active_at=NOW,
        closed_at=None,
    )
    values = {
        "schema": SESSION_SCHEMA,
        "generation": "generation-1",
        "service_id": "service-1",
        "build_identity": "0.001a20-test",
        "created_at": NOW,
        "updated_at": NOW,
        "clean_shutdown": False,
        "active_window_id": window.window_id,
        "active_view_id": view.view_id,
        "windows": (window,),
        "views": (view,),
        "documents": (document,),
        "find_replace": _find_manifest(),
        "packs": (),
    }
    values.update(changes)
    return SessionManifest(**values)


def _schema_one_payload_fixture() -> dict[str, object]:
    return {
        "active_view_id": "view-1",
        "active_window_id": "window-1",
        "build_identity": "0.001a20-test",
        "clean_shutdown": False,
        "created_at": NOW,
        "documents": [
            {
                "canonical_path": "/tmp/document.txt",
                "closed_at": None,
                "document_id": "doc-1",
                "last_active_at": NOW,
                "view_ids": ["view-1"],
            }
        ],
        "find_replace": {
            "case_sensitive": False,
            "find_current": {"anchor": 6, "position": 6, "text": "needle"},
            "geometry": [10, 20, 640, 320],
            "history_pack": None,
            "last_target_view_id": "view-1",
            "regex": True,
            "replace_current": {
                "anchor": 11,
                "position": 11,
                "text": "replacement",
            },
            "report_visible": True,
            "visible": True,
            "whole_word": True,
            "zoom_percent": 110,
        },
        "generation": "generation-1",
        "notices": [],
        "packs": [],
        "schema": 1,
        "service_id": "service-1",
        "updated_at": NOW,
        "views": [
            {
                "anchor": 1,
                "cursor": 3,
                "document_id": "doc-1",
                "horizontal_scroll": 0,
                "preferred_column": 3,
                "soft_wrap": True,
                "vertical_scroll": 2,
                "view_id": "view-1",
                "wrap_viewport_row": 0,
                "zoom_percent": 100,
            }
        ],
        "windows": [
            {
                "geometry": [20, 30, 1024, 768],
                "root": {
                    "children": [],
                    "kind": "leaf",
                    "orientation": None,
                    "pane_id": "pane-1",
                    "proportions": None,
                    "selected_view_id": "view-1",
                    "view_ids": ["view-1"],
                },
                "window_id": "window-1",
                "window_state": "normal",
            }
        ],
    }


def _history_pack() -> HistoryPack:
    history = EditHistory()
    history.record(EditTransaction((EditOperation(3, "", "X"),)))
    history.mark_saved()
    return HistoryPack(
        document_id="doc-1",
        generation="history-1",
        canonical_path="/tmp/document.txt",
        saved_stamp=SavedFileStamp(
            FileIdentity(size=4, mtime_ns=123, inode=7, device=8),
            hashlib.sha256(b"abcX").hexdigest(),
        ),
        source_profile_key="utf-8",
        selected_output_profile_key="utf-8",
        selected_output_eol=None,
        saved_output_profile_key="utf-8",
        saved_output_eol=None,
        history=history.export_snapshot(),
        last_active_at=NOW,
        closed_at=None,
        notices=(PersistenceNotice("document", "bounded"),),
    )


def _find_pack() -> FindReplaceHistoryPack:
    return FindReplaceHistoryPack(
        generation="find-history-1",
        find=_input_history(
            undo=(_state("need"), _state("nee")),
            redo=(_state("needles"),),
        ),
        replace=_input_history(
            "replacement",
            undo=(_state("replace"),),
        ),
    )


def _canonical_envelope(envelope: dict[str, object]) -> bytes:
    return json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def test_manifest_payload_round_trips_complete_structural_state():
    anchor = session_module.DockReturnRecord("window-a", "pane-left", 3)
    manifest = _manifest(
        views=(replace(_manifest().views[0], dock_return=anchor),),
        find_replace=replace(_find_manifest(), placement="attached"),
    )

    payload = manifest_to_payload(manifest)

    assert manifest_from_payload(payload) == manifest
    assert payload["views"][0]["dock_return"] == {
        "window_id": "window-a",
        "pane_id": "pane-left",
        "tab_index": 3,
    }
    assert payload["find_replace"]["placement"] == "attached"
    assert len(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ) <= (1 << 20)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"window_id": "", "pane_id": "pane", "tab_index": 0},
        {"window_id": "window", "pane_id": "", "tab_index": 0},
        {"window_id": "window", "pane_id": "pane", "tab_index": -1},
        {"window_id": "window", "pane_id": "pane", "tab_index": True},
    ],
)
def test_dock_return_record_rejects_untrusted_values(kwargs):
    with pytest.raises(ValueError):
        session_module.DockReturnRecord(**kwargs)


def test_schema_one_manifest_migrates_new_presentation_fields():
    restored = manifest_from_payload(_schema_one_payload_fixture())

    assert restored.schema == SESSION_SCHEMA == 2
    assert all(view.dock_return is None for view in restored.views)
    assert restored.find_replace.placement == "detached"


@pytest.mark.parametrize(
    "dock_return",
    [
        {},
        {"window_id": "window", "pane_id": "pane", "tab_index": 0, "extra": 1},
        {"window_id": "window", "pane_id": "pane"},
    ],
)
def test_schema_two_manifest_rejects_malformed_dock_return(dock_return):
    payload = manifest_to_payload(_manifest())
    payload["views"][0]["dock_return"] = dock_return

    with pytest.raises(ValueError, match="dock return"):
        manifest_from_payload(payload)


def test_schema_two_manifest_rejects_invalid_find_replace_placement():
    payload = manifest_to_payload(_manifest())
    payload["find_replace"]["placement"] = "sidebar"

    with pytest.raises(ValueError, match="placement"):
        manifest_from_payload(payload)


def test_document_history_pack_round_trips_deterministically():
    pack = _history_pack()

    first = encode_history_pack(pack)
    second = encode_history_pack(pack)

    assert first == second
    assert decode_history_pack(first) == pack


def test_find_replace_history_pack_round_trips_prefix_suffix_deltas():
    pack = _find_pack()

    encoded = encode_find_replace_pack(pack)

    assert decode_find_replace_pack(encoded) == pack
    assert b'"needle"' not in encoded


def test_manifest_rejects_more_than_one_mib_decoded():
    oversized = "x" * (1 << 20)
    manifest = _manifest(
        find_replace=replace(
            _find_manifest(),
            find_current=InputStateRecord(oversized, len(oversized), len(oversized)),
        )
    )

    with pytest.raises(ValueError, match="manifest.*limit"):
        manifest_to_payload(manifest)


def test_manifest_rejects_top_level_collection_limits():
    manifest = _manifest()
    window = manifest.windows[0]
    view = manifest.views[0]
    document = manifest.documents[0]

    with pytest.raises(ValueError, match="32 windows"):
        replace(
            manifest,
            windows=tuple(replace(window, window_id=f"window-{i}") for i in range(33)),
        )
    with pytest.raises(ValueError, match="256 views"):
        replace(
            manifest,
            views=tuple(replace(view, view_id=f"view-{i}") for i in range(257)),
        )
    with pytest.raises(ValueError, match="128 documents"):
        replace(
            manifest,
            documents=tuple(
                replace(document, document_id=f"doc-{i}") for i in range(129)
            ),
        )


def _leaf_tree(count: int) -> PaneRecord:
    panes = [PaneRecord(kind="leaf", pane_id=f"leaf-{index}") for index in range(count)]
    split_index = 0
    while len(panes) > 1:
        next_level = []
        for index in range(0, len(panes), 2):
            pair = panes[index : index + 2]
            if len(pair) == 1:
                next_level.append(pair[0])
                continue
            next_level.append(
                PaneRecord(
                    kind="split",
                    pane_id=f"split-{split_index}",
                    orientation="horizontal",
                    proportions=(0.5, 0.5),
                    children=(pair[0], pair[1]),
                )
            )
            split_index += 1
        panes = next_level
    return panes[0]


def test_manifest_rejects_more_than_128_leaf_panes():
    with pytest.raises(ValueError, match="128 leaf panes"):
        _manifest(
            windows=(
                WindowRecord(
                    "window-tree",
                    (0, 0, 800, 600),
                    "normal",
                    _leaf_tree(129),
                ),
            ),
            views=(),
            documents=(),
            active_window_id="window-tree",
            active_view_id=None,
            find_replace=replace(_find_manifest(), last_target_view_id=None),
        )


def test_manifest_rejects_invalid_references_and_duplicate_ids():
    manifest = _manifest()
    bad_root = replace(
        manifest.windows[0].root,
        view_ids=("missing-view",),
        selected_view_id="missing-view",
    )
    with pytest.raises(ValueError, match="unknown view"):
        replace(
            manifest,
            windows=(replace(manifest.windows[0], root=bad_root),),
        )

    duplicate = replace(manifest.views[0])
    with pytest.raises(ValueError, match="duplicate view"):
        replace(manifest, views=(manifest.views[0], duplicate))


@pytest.mark.parametrize(
    "factory, message",
    [
        (
            lambda: InputStateRecord("abc", 4, 0),
            "position",
        ),
        (
            lambda: ViewRecord("view", "doc", -1, 0, None, 0, 0, 0, False, 100),
            "cursor",
        ),
        (
            lambda: WindowRecord(
                "window", (0, 0, 0, 600), "normal", PaneRecord("leaf", "pane")
            ),
            "geometry",
        ),
        (
            lambda: PaneRecord(
                "split",
                "pane",
                "horizontal",
                (1.0, 0.0),
                (PaneRecord("leaf", "a"), PaneRecord("leaf", "b")),
            ),
            "proportions",
        ),
    ],
)
def test_records_reject_invalid_cursors_geometry_and_proportions(factory, message):
    with pytest.raises(ValueError, match=message):
        factory()


def test_input_histories_are_limited_to_fifty_states():
    current = _state()
    undo = tuple(_state(str(index)) for index in range(51))

    with pytest.raises(ValueError, match="50"):
        InputHistoryRecord(
            current,
            undo,
            (),
            estimate_input_history_bytes(current, undo, ()),
        )


def test_pack_reference_rejects_bad_hash_and_unsafe_filename():
    with pytest.raises(ValueError, match="SHA-256"):
        HistoryPackReference(
            "document", "doc", "gen", "pack.pack", 1, 1, "bad"
        )
    with pytest.raises(ValueError, match="filename"):
        HistoryPackReference(
            "document", "doc", "gen", "../pack.pack", 1, 1, "0" * 64
        )


@pytest.mark.parametrize("field", ["encoded_bytes", "decoded_bytes"])
def test_pack_decoder_rejects_excessive_declared_lengths(field: str):
    envelope = json.loads(encode_history_pack(_history_pack()))
    envelope[field] = (32 << 20) + 1

    with pytest.raises(ValueError, match="limit|no more"):
        decode_history_pack(_canonical_envelope(envelope))


def test_pack_decoder_rejects_checksum_mismatch():
    envelope = json.loads(encode_history_pack(_history_pack()))
    envelope["sha256"] = "0" * 64

    with pytest.raises(ValueError, match="checksum"):
        decode_history_pack(_canonical_envelope(envelope))


def test_manifest_and_pack_reject_unsupported_schemas():
    manifest_payload = manifest_to_payload(_manifest())
    manifest_payload["schema"] = 3
    with pytest.raises(UnsupportedSessionSchema):
        manifest_from_payload(manifest_payload)

    envelope = json.loads(encode_history_pack(_history_pack()))
    envelope["schema"] = 2
    with pytest.raises(UnsupportedSessionSchema):
        decode_history_pack(_canonical_envelope(envelope))


def test_history_pack_decoder_keeps_accepting_schema_one_after_manifest_upgrade():
    envelope = json.loads(encode_history_pack(_history_pack()))
    envelope["schema"] = 1

    assert decode_history_pack(_canonical_envelope(envelope)) == _history_pack()


def test_pack_decoder_rejects_trailing_compressed_stream():
    envelope = json.loads(encode_history_pack(_history_pack()))
    compressed = base64.b64decode(envelope["payload"], validate=True)
    compressed += zlib.compress(b"{}")
    envelope["payload"] = base64.b64encode(compressed).decode("ascii")
    envelope["encoded_bytes"] = len(compressed)

    with pytest.raises(ValueError, match="trailing"):
        decode_history_pack(_canonical_envelope(envelope))


def test_pack_decoder_rejects_incomplete_stream_and_length_mismatch():
    envelope = json.loads(encode_history_pack(_history_pack()))
    compressed = base64.b64decode(envelope["payload"], validate=True)
    envelope["payload"] = base64.b64encode(compressed[:-1]).decode("ascii")
    envelope["encoded_bytes"] = len(compressed) - 1
    with pytest.raises(ValueError, match="incomplete|invalid compressed"):
        decode_history_pack(_canonical_envelope(envelope))

    envelope = json.loads(encode_history_pack(_history_pack()))
    envelope["decoded_bytes"] -= 1
    with pytest.raises(ValueError, match="decoded length"):
        decode_history_pack(_canonical_envelope(envelope))


def test_pack_decoder_rejects_decompression_expansion(monkeypatch):
    monkeypatch.setattr(session_module, "MAX_PACK_DECODED_BYTES", 64)
    raw = b"x" * 65
    compressed = zlib.compress(raw)
    envelope = {
        "schema": 1,
        "kind": "document_history",
        "compression": "zlib",
        "encoded_bytes": len(compressed),
        "decoded_bytes": 64,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "payload": base64.b64encode(compressed).decode("ascii"),
    }

    with pytest.raises(ValueError, match="expansion"):
        decode_history_pack(_canonical_envelope(envelope))


def test_session_snapshot_keeps_manifest_current_state_separate_from_histories():
    history_pack = _history_pack()
    encoded = encode_history_pack(history_pack)
    reference = HistoryPackReference(
        kind="document",
        owner_id="doc-1",
        generation=history_pack.generation,
        filename="history.pack",
        encoded_bytes=len(encoded),
        decoded_bytes=history_pack.history.decoded_bytes,
        sha256=hashlib.sha256(encoded).hexdigest(),
    )
    manifest = _manifest(packs=(reference,))
    snapshot = SessionSnapshot(manifest, (history_pack,), _find_pack())

    assert snapshot.manifest.documents[0].canonical_path == "/tmp/document.txt"
    assert snapshot.packs == (history_pack,)
    assert snapshot.find_replace_pack is not None
