from __future__ import annotations

import hashlib
import os
import time
import threading
from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from uniti.app.session import (
    SESSION_SCHEMA,
    DocumentRecord,
    FindReplaceHistoryPack,
    FindReplaceManifestRecord,
    HistoryPack,
    InputHistoryRecord,
    InputStateRecord,
    PaneRecord,
    SessionManifest,
    SessionSnapshot,
    ViewRecord,
    WindowRecord,
    estimate_input_history_bytes,
)
from uniti.app.session_store import SessionStore
from uniti.app.service import UNITIService
from uniti.app.settings import SettingsStore
from uniti.core.file_identity import FileIdentity, SavedFileStamp
from uniti.resources import ResourceManager, TaskKind, WorkPriority


class _SessionSink:
    def __init__(self):
        self.publications = []

    def publish(self, snapshot):
        self.publications.append(snapshot)
        return snapshot


class _RecoverySink:
    def __init__(self):
        self.detached = []

    def attach(self, _document, **_kwargs) -> None:
        return None

    def detach(self, _document, *, clean: bool) -> None:
        self.detached.append((_document, clean))

    def shutdown(self) -> None:
        return None


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _saved_stamp(path: Path) -> SavedFileStamp:
    return SavedFileStamp(
        FileIdentity.from_path(path),
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def _input_history(
    current: InputStateRecord,
    *,
    undo: tuple[InputStateRecord, ...] = (),
    redo: tuple[InputStateRecord, ...] = (),
) -> InputHistoryRecord:
    return InputHistoryRecord(
        current,
        undo,
        redo,
        estimate_input_history_bytes(current, undo, redo),
    )


def _published_session(
    tmp_path: Path,
    *,
    document_count: int,
) -> tuple[SessionStore, object, tuple[Path, ...]]:
    timestamp = "2026-09-04T12:00:00Z"
    paths: list[Path] = []
    documents = []
    views = []
    packs = []
    view_ids = []
    from uniti.core.document import Document

    for index in range(document_count):
        document_id = f"document-{index}"
        view_id = f"view-{index}"
        path = tmp_path / f"document-{index}.txt"
        path.write_text(f"base {index}", encoding="utf-8")
        document = Document.open(path)
        document.insert(document.total_chars(), " saved")
        document.save()
        stamp = _saved_stamp(path)
        document.insert(document.total_chars(), " redo")
        document.undo()
        history = document.export_history()
        document.close()
        paths.append(path)
        view_ids.append(view_id)
        documents.append(
            DocumentRecord(document_id, str(path), (view_id,), timestamp, None)
        )
        views.append(
            ViewRecord(view_id, document_id, index, 0, None, 0, 0, 0, False, 100)
        )
        packs.append(
            HistoryPack(
                document_id,
                f"history-{index}",
                str(path),
                stamp,
                "utf-8",
                "utf-8",
                None,
                "utf-8",
                None,
                history,
                timestamp,
                None,
            )
        )
    empty = InputStateRecord("", 0, 0)
    manifest = SessionManifest(
        schema=SESSION_SCHEMA,
        generation="capture-generation",
        service_id="original-service",
        build_identity="test-build",
        created_at=timestamp,
        updated_at=timestamp,
        clean_shutdown=True,
        active_window_id="window-one",
        active_view_id="view-0",
        windows=(
            WindowRecord(
                "window-one",
                (20, 30, 700, 500),
                "normal",
                PaneRecord(
                    "leaf",
                    "pane-one",
                    view_ids=tuple(view_ids),
                    selected_view_id="view-0",
                ),
            ),
        ),
        views=tuple(views),
        documents=tuple(documents),
        find_replace=FindReplaceManifestRecord(
            empty,
            empty,
            False,
            False,
            False,
            False,
            None,
            100,
            False,
            "view-0",
            None,
        ),
        packs=(),
    )
    store = SessionStore(tmp_path / "sessions")
    store.publish(SessionSnapshot(manifest, tuple(packs), None))
    return store, store.load_latest(), tuple(paths)


def _restoring_service(tmp_path: Path, store: SessionStore) -> UNITIService:
    return UNITIService(
        resource_manager=ResourceManager(max_workers=2),
        settings_store=SettingsStore(tmp_path / "restored-settings.json"),
        session_store=store,
        recovery_manager=_RecoverySink(),
    )


def _wait_until(qapp, predicate, *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    qapp.processEvents()
    assert predicate()


def test_fresh_session_restore_normalizes_the_stored_canonical_path(tmp_path: Path):
    from uniti.app.session_runtime import restore_fresh_document

    source = tmp_path / "saved document Ω.txt"
    source.write_text("saved bytes", encoding="utf-8")
    (tmp_path / "unused").mkdir()
    raw_path = str(tmp_path / "unused" / ".." / source.name)
    resources = ResourceManager(max_workers=1)
    result = None
    try:
        result = restore_fresh_document(
            "document-one",
            raw_path,
            ("view-one",),
            resource_manager=resources,
        )

        assert result.canonical_path == str(source.resolve())
        assert result.document.path == source.resolve()
    finally:
        if result is not None:
            result.document.close()
        resources.shutdown()


def test_fresh_session_controller_accepts_a_normalized_record_identity(
    qapp,
    tmp_path: Path,
):
    store, loaded, paths = _published_session(tmp_path, document_count=1)
    assert loaded.manifest is not None
    (tmp_path / "unused").mkdir()
    raw_path = str(tmp_path / "unused" / ".." / paths[0].name)
    record = replace(loaded.manifest.documents[0], canonical_path=raw_path)
    manifest = replace(loaded.manifest, documents=(record,), packs=())
    service = _restoring_service(tmp_path, store)
    service.restore_shell(manifest, packs=())

    restored = service.restore_active()

    assert restored is not None
    assert restored.canonical_path == paths[0].resolve()
    assert restored.document.path == paths[0].resolve()
    service.request_quit(lambda _entry: None)
    qapp.processEvents()


def test_history_pack_restore_normalizes_its_canonical_path(tmp_path: Path):
    from uniti.app.session_runtime import restore_document_pack

    _store, loaded, paths = _published_session(tmp_path, document_count=1)
    (tmp_path / "unused").mkdir()
    raw_path = str(tmp_path / "unused" / ".." / paths[0].name)
    pack = replace(loaded.packs[0], canonical_path=raw_path)
    resources = ResourceManager(max_workers=1)
    result = None
    try:
        result = restore_document_pack(
            pack,
            ("view-0",),
            resource_manager=resources,
        )

        assert result.pack.canonical_path == str(paths[0].resolve())
        assert result.document is not None
        assert result.document.path == paths[0].resolve()
    finally:
        if result is not None and result.document is not None:
            result.document.close()
        resources.shutdown()


def test_capture_session_collects_complete_immutable_runtime_state_without_io(
    qapp,
    tmp_path: Path,
    monkeypatch,
):
    first_path = tmp_path / "first.txt"
    second_path = tmp_path / "second.txt"
    first_path.write_text("alpha beta gamma", encoding="utf-8")
    second_path.write_text("second document", encoding="utf-8")
    resources = ResourceManager(max_workers=2)
    service = UNITIService(
        resource_manager=resources,
        settings_store=SettingsStore(tmp_path / "settings.json"),
        session_store=_SessionSink(),
        recovery_manager=_RecoverySink(),
        service_id="service-one",
        build_identity="test-build",
    )
    first_window = service.new_window()
    first_view = first_window.open_path(first_path)
    assert first_view is not None
    first_entry = service.documents.entry_for_view(first_view.view_id)
    assert first_entry is not None
    first_entry.saved_stamp = _saved_stamp(first_path)
    first_view.document.insert(first_view.document.total_chars(), " saved")
    first_view.document.save()
    first_entry.saved_stamp = _saved_stamp(first_path)
    first_view.document.insert(first_view.document.total_chars(), " redo")
    first_view.document.undo()

    shared_view = first_window.split_current(Qt.Orientation.Horizontal)
    assert shared_view is not None
    first_view.state.move_to(2)
    first_view.state.move_to(7, selecting=True)
    first_view.set_zoom_percent(120)
    shared_view.state.move_to(11)
    shared_view.set_soft_wrap(True)
    shared_view.set_zoom_percent(140)

    second_window = service.new_window()
    second_view = second_window.open_path(second_path)
    assert second_view is not None
    second_entry = service.documents.entry_for_view(second_view.view_id)
    assert second_entry is not None
    second_entry.saved_stamp = _saved_stamp(second_path)
    service.set_active_view(second_window.window_id, second_view.view_id)

    panel = service.find_replace
    panel.show()
    panel.find_input.setFocus()
    QTest.keyClicks(panel.find_input, "alpha")
    panel.replace_input.setFocus()
    QTest.keyClicks(panel.replace_input, "omega")
    assert panel.replace_input.undo_input() is True
    panel.regex_checkbox.setChecked(True)
    panel.set_zoom_percent(130)
    panel.set_report_location("Right")
    qapp.processEvents()

    expected_windows = tuple(
        window.export_window_record() for window in (first_window, second_window)
    )
    expected_views = tuple(
        view.export_state(
            service.documents.entry_for_view(view.view_id).document_id  # type: ignore[union-attr]
        )
        for view in (first_view, shared_view, second_view)
    )
    expected_find = panel.export_state(second_view.view_id)
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda _path: (_ for _ in ()).throw(AssertionError("capture performed disk I/O")),
    )

    snapshot = service.capture_session(clean_shutdown=True)

    assert snapshot.manifest.clean_shutdown is True
    assert snapshot.manifest.service_id == "service-one"
    assert snapshot.manifest.build_identity == "test-build"
    assert snapshot.manifest.active_window_id == second_window.window_id
    assert snapshot.manifest.active_view_id == second_view.view_id
    assert snapshot.manifest.windows == expected_windows
    assert snapshot.manifest.views == expected_views
    assert tuple(item.document_id for item in snapshot.manifest.documents) == (
        first_entry.document_id,
        second_entry.document_id,
    )
    assert snapshot.manifest.find_replace.find_current == expected_find.find.current
    assert snapshot.manifest.find_replace.replace_current == expected_find.replace.current
    assert snapshot.manifest.find_replace.visible is True
    assert snapshot.manifest.find_replace.report_visible is True
    assert snapshot.find_replace_pack is not None
    assert snapshot.find_replace_pack.find == expected_find.find
    assert snapshot.find_replace_pack.replace == expected_find.replace
    assert tuple(pack.document_id for pack in snapshot.packs) == (
        first_entry.document_id,
        second_entry.document_id,
    )
    assert snapshot.packs[0].history == first_view.document.export_history()
    assert snapshot.packs[0].saved_stamp == first_entry.saved_stamp
    assert snapshot.packs[0].history.cursor == snapshot.packs[0].history.saved_cursor
    assert first_view.document.can_undo is True
    assert first_view.document.can_redo is True

    monkeypatch.undo()
    for _window_id, window in service.windows.items:
        window.close_all_documents(force=True)
        window.close()
    qapp.processEvents()
    service.request_quit(lambda _entry: None)


def test_open_hashes_saved_bytes_off_gui_thread_before_history_publication(
    qapp,
    tmp_path: Path,
    monkeypatch,
):
    from uniti.app import session_runtime

    path = tmp_path / "hashed.txt"
    path.write_text("saved bytes", encoding="utf-8")
    calling_thread = threading.get_ident()
    worker_threads: list[int] = []
    real_hash = session_runtime.sha256_file

    def record_hash(selected_path, **kwargs):
        worker_threads.append(threading.get_ident())
        return real_hash(selected_path, **kwargs)

    monkeypatch.setattr(session_runtime, "sha256_file", record_hash)
    service = UNITIService(
        resource_manager=ResourceManager(max_workers=2),
        settings_store=SettingsStore(tmp_path / "settings.json"),
        session_store=_SessionSink(),
        recovery_manager=_RecoverySink(),
    )
    window = service.new_window()

    view = window.open_path(path)
    assert view is not None
    entry = service.documents.entry_for_view(view.view_id)
    assert entry is not None
    _wait_until(qapp, lambda: entry.saved_stamp is not None)

    assert worker_threads
    assert all(worker != calling_thread for worker in worker_threads)
    assert entry.saved_stamp == _saved_stamp(path)
    assert tuple(pack.document_id for pack in service.capture_session().packs) == (
        entry.document_id,
    )

    service.request_quit(lambda _entry: None)
    qapp.processEvents()


def test_saved_recovery_base_is_rebased_only_after_session_publication(
    qapp,
    tmp_path: Path,
):
    events: list[str] = []

    class Sessions(_SessionSink):
        def publish(self, snapshot):
            events.append("session-published")
            return super().publish(snapshot)

    class Recovery(_RecoverySink):
        def rebase_after_save(self, document, **kwargs):
            events.append("recovery-rebased")
            future = Future()
            future.set_result(True)
            return future

    path = tmp_path / "save-transition.txt"
    path.write_text("base", encoding="utf-8")
    sessions = Sessions()
    service = UNITIService(
        resource_manager=ResourceManager(max_workers=2),
        settings_store=SettingsStore(tmp_path / "settings.json"),
        session_store=sessions,
        recovery_manager=Recovery(),
    )
    window = service.new_window()
    view = window.open_path(path)
    assert view is not None
    entry = service.documents.entry_for_view(view.view_id)
    assert entry is not None
    _wait_until(qapp, lambda: bool(sessions.publications))
    events.clear()

    view.document.insert(view.document.total_chars(), " saved")
    view.document.save()
    _wait_until(qapp, lambda: "recovery-rebased" in events)

    assert events[:2] == ["session-published", "recovery-rebased"]
    service.request_quit(lambda _entry: None)
    qapp.processEvents()


def test_restore_shell_then_active_document_round_trips_history_views_and_panel(
    qapp,
    tmp_path: Path,
):
    path = tmp_path / "restored.txt"
    path.write_text("base", encoding="utf-8")
    document = __import__("uniti.core.document", fromlist=["Document"]).Document.open(path)
    document.insert(document.total_chars(), " saved")
    document.save()
    stamp = _saved_stamp(path)
    document.insert(document.total_chars(), " redo")
    document.undo()
    history = document.export_history()
    assert document.can_undo is True and document.can_redo is True
    document.close()

    timestamp = "2026-09-04T12:00:00Z"
    find_current = InputStateRecord("needle", 6, 1)
    replace_current = InputStateRecord("replac", 6, 0)
    find_history = _input_history(
        find_current,
        undo=(InputStateRecord("needl", 5, 5),),
    )
    replace_history = _input_history(
        replace_current,
        undo=(InputStateRecord("replace", 7, 0),),
        redo=(InputStateRecord("replacement", 11, 0),),
    )
    view_record = ViewRecord(
        "active-view",
        "shared-doc",
        4,
        1,
        3,
        0,
        0,
        0,
        False,
        120,
    )
    manifest = SessionManifest(
        schema=SESSION_SCHEMA,
        generation="capture-generation",
        service_id="original-service",
        build_identity="test-build",
        created_at=timestamp,
        updated_at=timestamp,
        clean_shutdown=True,
        active_window_id="window-one",
        active_view_id="active-view",
        windows=(
            WindowRecord(
                "window-one",
                (20, 30, 700, 500),
                "normal",
                PaneRecord(
                    "leaf",
                    "pane-one",
                    view_ids=("active-view",),
                    selected_view_id="active-view",
                ),
            ),
        ),
        views=(view_record,),
        documents=(
            DocumentRecord("shared-doc", str(path), ("active-view",), timestamp, None),
        ),
        find_replace=FindReplaceManifestRecord(
            find_current,
            replace_current,
            True,
            False,
            False,
            True,
            (40, 50, 640, 360),
            130,
            True,
            "active-view",
            None,
        ),
        packs=(),
    )
    pack = HistoryPack(
        "shared-doc",
        "history-generation",
        str(path),
        stamp,
        "utf-8",
        "utf-8",
        None,
        "utf-8",
        None,
        history,
        timestamp,
        None,
    )
    find_pack = FindReplaceHistoryPack(
        "find-generation",
        find_history,
        replace_history,
    )
    store = SessionStore(tmp_path / "sessions")
    store.publish(SessionSnapshot(manifest, (pack,), find_pack))
    loaded = store.load_latest()
    assert loaded.manifest is not None

    resources = ResourceManager(max_workers=2)
    service = UNITIService(
        resource_manager=resources,
        settings_store=SettingsStore(tmp_path / "restored-settings.json"),
        session_store=store,
        recovery_manager=_RecoverySink(),
    )

    service.restore_shell(
        loaded.manifest,
        packs=loaded.packs,
        find_replace_pack=loaded.find_replace_pack,
    )

    restored_window = service.windows.windows[0]
    assert service.window_count == 1
    assert restored_window.views == ()
    assert restored_window.panes.export_state() == loaded.manifest.windows[0].root
    assert service.documents.count == 0
    service.restore_active()

    restored = service.documents.get("shared-doc").document
    assert restored.read(0, restored.total_chars()) == "base saved"
    assert restored.can_undo is True
    assert restored.can_redo is True
    assert service.active_view is not None
    assert service.active_view.view_id == "active-view"
    assert service.active_view.state.selection == (1, 4)
    assert service.active_view.zoom_percent == 120
    assert service.find_replace.export_state("active-view").find == find_history
    assert service.find_replace.export_state("active-view").replace == replace_history
    assert service.capture_session(clean_shutdown=True) == SessionSnapshot(
        loaded.manifest,
        loaded.packs,
        loaded.find_replace_pack,
    )

    service.request_quit(lambda _entry: None)
    qapp.processEvents()


def test_lazy_restore_queues_inactive_documents_and_placeholder_focus_promotes(
    qapp,
    tmp_path: Path,
):
    store, loaded, _paths = _published_session(tmp_path, document_count=2)
    assert loaded.manifest is not None
    service = _restoring_service(tmp_path, store)
    service.restore_shell(
        loaded.manifest,
        packs=loaded.packs,
        find_replace_pack=loaded.find_replace_pack,
    )
    service.resources.tasks.pause_background(True)

    service.restore_active()
    handles = service.schedule_lazy_restore()

    assert service.documents.count == 1
    assert len(handles) == 1
    assert handles[0].spec.kind is TaskKind.SESSION
    assert handles[0].spec.priority is WorkPriority.PREFETCH
    assert handles[0].done is False
    window = service.windows.windows[0]
    window.panes.activate_view("view-1")
    _wait_until(qapp, lambda: service.documents.count == 2)
    assert service.active_view is not None
    assert service.active_view.view_id == "view-1"

    service.resources.tasks.pause_background(False)
    service.request_quit(lambda _entry: None)
    qapp.processEvents()


def test_document_packs_are_loaded_active_first_then_lazily_on_workers(
    qapp,
    tmp_path: Path,
):
    store, _loaded, _paths = _published_session(tmp_path, document_count=2)
    manifest_only = store.load_manifest()
    assert manifest_only.manifest is not None
    loaded_ids: list[str] = []
    worker_ids: list[int] = []
    gui_thread = threading.get_ident()

    def load_pack(document_id: str):
        loaded_ids.append(document_id)
        worker_ids.append(threading.get_ident())
        return store.load_document_pack(manifest_only.manifest, document_id)

    service = _restoring_service(tmp_path, store)
    service.restore_shell(
        manifest_only.manifest,
        pack_loader=load_pack,
    )

    service.restore_active()
    service.schedule_lazy_restore()
    _wait_until(qapp, lambda: service.documents.count == 2)

    assert loaded_ids == ["document-0", "document-1"]
    assert all(worker_id != gui_thread for worker_id in worker_ids)
    service.request_quit(lambda _entry: None)
    qapp.processEvents()


def test_restore_hash_accepts_metadata_change_but_preserves_changed_bytes_as_conflict(
    qapp,
    tmp_path: Path,
):
    exact_root = tmp_path / "exact"
    exact_root.mkdir()
    exact_store, exact_loaded, exact_paths = _published_session(
        exact_root,
        document_count=1,
    )
    assert exact_loaded.manifest is not None
    exact_path = exact_paths[0]
    stat = exact_path.stat()
    os.utime(exact_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
    exact_service = _restoring_service(exact_root, exact_store)
    exact_service.restore_shell(
        exact_loaded.manifest,
        packs=exact_loaded.packs,
        find_replace_pack=exact_loaded.find_replace_pack,
    )

    assert exact_service.restore_active() is not None
    assert exact_service.documents.get("document-0").document.can_redo is True
    exact_service.request_quit(lambda _entry: None)
    qapp.processEvents()

    changed_root = tmp_path / "changed"
    changed_root.mkdir()
    changed_store, changed_loaded, changed_paths = _published_session(
        changed_root,
        document_count=1,
    )
    assert changed_loaded.manifest is not None
    changed_paths[0].write_text("external bytes", encoding="utf-8")
    changed_service = _restoring_service(changed_root, changed_store)
    changed_service.restore_shell(
        changed_loaded.manifest,
        packs=changed_loaded.packs,
        find_replace_pack=changed_loaded.find_replace_pack,
    )

    assert changed_service.restore_active() is None
    assert changed_service.documents.count == 0
    assert changed_service.windows.windows[0].views == ()
    assert tuple(problem.kind for problem in changed_service.restore_problems) == (
        "changed_source",
    )

    from uniti.ui.recovery_center import RecoveryAction, RecoveryDecision

    problem = changed_service.restore_problems[0]
    assert len(
        changed_service.recovery_entries(session_problems=(problem, problem))
    ) == 1
    recovery_entry = changed_service.recovery_entries(
        session_problems=(problem,)
    )[0]
    assert changed_service.apply_recovery_decisions(
        (RecoveryDecision(recovery_entry.entry_id, RecoveryAction.OPEN_DISK),),
        session_problems=(problem,),
        target=changed_service.most_recent_window,
    ) == 1
    opened = changed_service.documents.get("document-0").document
    assert opened.read(0, opened.total_chars()) == "external bytes"
    assert opened.can_undo is False
    assert changed_service.restore_problems == ()

    changed_service.request_quit(lambda _entry: None)
    qapp.processEvents()


def test_restore_completion_is_rejected_when_history_generation_changed(
    qapp,
    tmp_path: Path,
):
    from uniti.app.session_runtime import restore_document_pack

    store, loaded, _paths = _published_session(tmp_path, document_count=1)
    assert loaded.manifest is not None
    service = _restoring_service(tmp_path, store)
    service.restore_shell(
        loaded.manifest,
        packs=loaded.packs,
        find_replace_pack=loaded.find_replace_pack,
    )
    original_pack = loaded.packs[0]
    result = restore_document_pack(
        original_pack,
        ("view-0",),
        resource_manager=service.resources,
    )
    assert result.document is not None
    service._session_controller.packs["document-0"] = replace(
        original_pack,
        generation="newer-history",
    )

    assert service._session_controller.apply_restore_result(result) is None
    assert service.documents.count == 0
    with pytest.raises(ValueError, match="closed"):
        result.document.read(0, 1)

    service.request_quit(lambda _entry: None)


def test_restore_completion_is_rejected_when_canonical_source_changed(
    qapp,
    tmp_path: Path,
):
    from uniti.app.session_runtime import restore_document_pack

    store, loaded, paths = _published_session(tmp_path, document_count=1)
    assert loaded.manifest is not None
    impostor = tmp_path / "same-bytes-different-file.txt"
    impostor.write_bytes(paths[0].read_bytes())
    forged_pack = replace(
        loaded.packs[0],
        canonical_path=str(impostor),
        saved_stamp=_saved_stamp(impostor),
    )
    service = _restoring_service(tmp_path, store)
    service.restore_shell(
        loaded.manifest,
        packs=loaded.packs,
        find_replace_pack=loaded.find_replace_pack,
    )
    result = restore_document_pack(
        forged_pack,
        ("view-0",),
        resource_manager=service.resources,
    )
    assert result.document is not None

    assert service._session_controller.apply_restore_result(result) is None
    assert service.documents.count == 0
    with pytest.raises(ValueError, match="closed"):
        result.document.read(0, 1)

    service.request_quit(lambda _entry: None)


def test_restore_without_admitted_history_opens_saved_document_with_fresh_history(
    qapp,
    tmp_path: Path,
    monkeypatch,
):
    store, loaded, _paths = _published_session(tmp_path, document_count=1)
    assert loaded.manifest is not None
    assert loaded.packs
    monkeypatch.setattr(store.backend, "free_bytes", lambda _path: 0)
    store.publish(SessionSnapshot(loaded.manifest, loaded.packs, None))
    from uniti.app.application import _load_session_surface

    surfaced = _load_session_surface(store)
    assert {problem.kind for problem in surfaced.problems} == {
        "find_history_truncated",
        "recovery_degraded",
    }
    pruned = store.load_manifest()
    assert pruned.manifest is not None
    assert pruned.manifest.packs == ()

    service = _restoring_service(tmp_path, store)
    service.restore_shell(
        pruned.manifest,
        pack_loader=lambda document_id: store.load_document_pack(
            pruned.manifest,
            document_id,
        ),
    )

    restored = service.restore_active()

    assert restored is not None
    assert restored.document.read(0, restored.document.total_chars()) == "base 0 saved"
    assert restored.document.can_undo is False
    assert service.windows.windows[0].view_for_id("view-0") is not None
    service.request_quit(lambda _entry: None)
    qapp.processEvents()


def test_startup_surface_discovers_inactive_source_conflicts_before_restore(
    tmp_path: Path,
):
    from uniti.app.application import _load_session_surface

    store, loaded, paths = _published_session(tmp_path, document_count=2)
    assert loaded.manifest is not None
    paths[1].write_text("changed while UNITI was closed", encoding="utf-8")

    surfaced = _load_session_surface(store)

    conflicts = tuple(
        problem
        for problem in surfaced.problems
        if problem.kind == "changed_source"
    )
    assert len(conflicts) == 1
    assert conflicts[0].document_id == "document-1"


def test_missing_session_source_restores_history_only_from_exact_located_file(
    qapp,
    tmp_path: Path,
):
    from uniti.ui.recovery_center import RecoveryAction, RecoveryDecision

    store, loaded, paths = _published_session(tmp_path, document_count=1)
    assert loaded.manifest is not None
    matching = tmp_path / "relocated.txt"
    matching.write_bytes(paths[0].read_bytes())
    paths[0].unlink()
    service = _restoring_service(tmp_path, store)
    service.restore_shell(loaded.manifest, packs=loaded.packs)
    assert service.restore_active() is None
    problem = service.restore_problems[0]
    entry = service.recovery_entries(session_problems=(problem,))[0]

    restored = service.apply_recovery_decisions(
        (
            RecoveryDecision(
                entry.entry_id,
                RecoveryAction.LOCATE_MATCH,
                matching,
            ),
        ),
        session_problems=(problem,),
        target=service.most_recent_window,
    )

    assert restored == 1
    document = service.documents.get("document-0").document
    assert document.path == matching.resolve()
    assert document.can_redo is True
    service.request_quit(lambda _entry: None)
    qapp.processEvents()


def test_discard_session_conflict_prunes_durable_evidence_and_placeholder(
    qapp,
    tmp_path: Path,
):
    from uniti.ui.recovery_center import RecoveryAction, RecoveryDecision

    store, loaded, paths = _published_session(tmp_path, document_count=1)
    assert loaded.manifest is not None
    paths[0].write_text("external bytes", encoding="utf-8")
    service = _restoring_service(tmp_path, store)
    service.restore_shell(loaded.manifest, packs=loaded.packs)
    assert service.restore_active() is None
    problem = service.restore_problems[0]
    entry = service.recovery_entries(session_problems=(problem,))[0]

    assert service.apply_recovery_decisions(
        (RecoveryDecision(entry.entry_id, RecoveryAction.DISCARD),),
        session_problems=(problem,),
        target=service.most_recent_window,
    ) == 0

    retained = store.load_latest()
    assert retained.manifest is not None
    assert retained.manifest.documents == ()
    assert service.windows.windows[0].view_ids == ()
    service.request_quit(lambda _entry: None)
    qapp.processEvents()


def test_invalid_active_history_pack_preserves_shell_and_reports_problem(
    qapp,
    tmp_path: Path,
):
    store, loaded, _paths = _published_session(tmp_path, document_count=1)
    assert loaded.manifest is not None
    manifest = store.load_manifest().manifest
    assert manifest is not None
    reference = next(item for item in manifest.packs if item.kind == "document")
    (store.packs_dir / reference.filename).write_bytes(b"invalid pack")
    service = _restoring_service(tmp_path, store)
    service.restore_shell(
        manifest,
        pack_loader=lambda document_id: store.load_document_pack(
            manifest,
            document_id,
        ),
    )

    assert service.restore_active() is None
    assert service.documents.count == 0
    assert service.windows.windows[0].view_ids == ("view-0",)
    assert tuple(item.kind for item in service.restore_problems) == (
        "restore_failed",
    )
    service.request_quit(lambda _entry: None)
    qapp.processEvents()


def test_quit_saves_and_hashes_once_then_excludes_confirmed_discard(
    qapp,
    tmp_path: Path,
):
    from uniti.app.service import QuitChoice

    saved_path = tmp_path / "saved.txt"
    discarded_path = tmp_path / "discarded.txt"
    saved_path.write_text("saved", encoding="utf-8")
    discarded_path.write_text("discarded", encoding="utf-8")
    sessions = _SessionSink()
    recovery = _RecoverySink()
    service = UNITIService(
        resource_manager=ResourceManager(max_workers=2),
        settings_store=SettingsStore(tmp_path / "settings.json"),
        session_store=sessions,
        recovery_manager=recovery,
    )
    window = service.new_window()
    saved_view = window.open_path(saved_path)
    discarded_view = window.open_path(discarded_path)
    assert saved_view is not None and discarded_view is not None
    _wait_until(
        qapp,
        lambda: all(entry.saved_stamp is not None for entry in service.documents.entries),
    )
    saved_view.document.insert(saved_view.document.total_chars(), " changed")
    discarded_view.document.insert(
        discarded_view.document.total_chars(),
        " local",
    )
    prompts = []

    assert service.request_quit(
        lambda entry: prompts.append(entry.document_id)
        or (
            QuitChoice.SAVE
            if entry.canonical_path == saved_path
            else QuitChoice.DISCARD
        )
    ) is True

    clean = sessions.publications[-1]
    assert clean.manifest.clean_shutdown is True
    assert tuple(item.canonical_path for item in clean.manifest.documents) == (
        str(saved_path),
    )
    assert tuple(pack.canonical_path for pack in clean.packs) == (str(saved_path),)
    assert clean.packs[0].saved_stamp == _saved_stamp(saved_path)
    assert saved_path.read_text(encoding="utf-8") == "saved changed"
    assert discarded_path.read_text(encoding="utf-8") == "discarded"
    assert len(prompts) == 2
    assert service.window_count == 0
    assert service.is_running is False
    assert all(clean is True for _document, clean in recovery.detached)
    qapp.processEvents()


def test_quit_save_failure_preserves_windows_and_previous_session(
    qapp,
    tmp_path: Path,
    monkeypatch,
):
    from uniti.app.service import QuitChoice
    from uniti.core.document import Document

    path = tmp_path / "failure.txt"
    path.write_text("disk", encoding="utf-8")
    sessions = _SessionSink()
    service = UNITIService(
        resource_manager=ResourceManager(max_workers=2),
        settings_store=SettingsStore(tmp_path / "settings.json"),
        session_store=sessions,
        recovery_manager=_RecoverySink(),
    )
    window = service.new_window()
    view = window.open_path(path)
    assert view is not None
    _wait_until(
        qapp,
        lambda: service.documents.entry_for_view(view.view_id).saved_stamp is not None,
    )
    view.document.insert(0, "local ")
    publication_count = len(sessions.publications)
    monkeypatch.setattr(
        Document,
        "save",
        lambda self: (_ for _ in ()).throw(OSError("injected save failure")),
    )

    assert service.request_quit(lambda _entry: QuitChoice.SAVE) is False

    assert service.is_running is True
    assert service.window_count == 1
    assert window.view_for_id(view.view_id) is view
    assert view.document.modified is True
    assert len(sessions.publications) == publication_count
    assert service.last_quit_error == "Could not save failure.txt; Quit was cancelled."

    monkeypatch.undo()
    window.close_all_documents(force=True)
    window.close()
    qapp.processEvents()
    service.request_quit(lambda _entry: QuitChoice.DISCARD)
