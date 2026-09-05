from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from uniti.app.session import SessionSnapshot
from uniti.app.session_store import SessionStore
from uniti.app.service import UNITIService
from uniti.app.settings import SettingsStore
from uniti.core.file_identity import FileIdentity, SavedFileStamp
from uniti.resources import ResourceManager


class _Recovery:
    def attach(self, _document, **_kwargs) -> None:
        return None

    def detach(self, _document, *, clean: bool) -> None:
        return None

    def shutdown(self) -> None:
        return None


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _stamp(path: Path) -> SavedFileStamp:
    return SavedFileStamp(
        FileIdentity.from_path(path),
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def _wait(qapp, predicate, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    qapp.processEvents()
    assert predicate()


def _service(root: Path, store: SessionStore, name: str) -> UNITIService:
    return UNITIService(
        resource_manager=ResourceManager(max_workers=3),
        settings_store=SettingsStore(root / f"{name}-settings.json"),
        session_store=store,
        recovery_manager=_Recovery(),
        service_id=f"{name}-service",
        build_identity="roundtrip-build",
    )


def test_complete_clean_session_round_trips_two_windows_nested_splits_and_histories(
    qapp,
    tmp_path: Path,
):
    paths = tuple(tmp_path / f"document-{index}.txt" for index in range(3))
    for index, path in enumerate(paths):
        path.write_text(f"document {index}", encoding="utf-8")
    store = SessionStore(tmp_path / "sessions")
    original = _service(tmp_path, store, "original")

    first_window = original.new_window()
    shared_first = first_window.open_path(paths[0])
    assert shared_first is not None
    shared_second = first_window.split_right()
    assert shared_second is not None
    second_document_view = first_window.open_path(paths[1])
    assert second_document_view is not None
    retained_second_view = first_window.split_down()
    assert retained_second_view is not None
    assert first_window._close_view_id(second_document_view.view_id, force=True)
    assert first_window.panes.export_state().orientation == "horizontal"
    assert first_window.panes.export_state().children[1].orientation == "vertical"

    second_window = original.new_window()
    third_document_view = second_window.open_path(paths[2])
    assert third_document_view is not None
    _wait(
        qapp,
        lambda: all(entry.saved_stamp is not None for entry in original.documents.entries),
    )

    shared_first.document.insert(shared_first.document.total_chars(), " saved")
    shared_first.document.save()
    shared_first.document.insert(shared_first.document.total_chars(), " redo")
    shared_first.document.undo()
    shared_first.state.move_to(2)
    shared_first.state.move_to(7, selecting=True)
    shared_first.set_zoom_percent(120)
    shared_second.state.move_to(4)
    shared_second.set_soft_wrap(True)
    shared_second.set_zoom_percent(140)
    retained_second_view.state.move_to(5)
    retained_second_view.set_zoom_percent(110)
    third_document_view.state.move_to(3)
    third_document_view.set_zoom_percent(130)
    _wait(
        qapp,
        lambda: original.documents.find_path(paths[0]).saved_stamp == _stamp(paths[0]),
    )
    original.set_active_view(first_window.window_id, shared_second.view_id)

    panel = original.find_replace
    panel.show()
    panel.setGeometry(40, 50, 720, 320)
    panel.find_input.setFocus()
    QTest.keyClicks(panel.find_input, "needleX")
    assert panel.find_input.undo_input()
    panel.replace_input.setFocus()
    QTest.keyClicks(panel.replace_input, "replacementY")
    assert panel.replace_input.undo_input()
    panel.case_sensitive_checkbox.setChecked(True)
    panel.regex_checkbox.setChecked(True)
    panel.set_zoom_percent(130)
    panel.set_report_location("Right")
    qapp.processEvents()
    expected_find = panel.export_state(shared_second.view_id)

    assert original.request_quit(
        lambda _entry: pytest.fail("clean session unexpectedly prompted on Quit")
    )
    qapp.processEvents()
    loaded = store.load_latest()
    assert loaded.manifest is not None
    assert loaded.manifest.clean_shutdown is True
    expected = SessionSnapshot(
        loaded.manifest,
        loaded.packs,
        loaded.find_replace_pack,
    )

    restored = _service(tmp_path, store, "restored")
    restored.restore_shell(
        loaded.manifest,
        find_replace_pack=loaded.find_replace_pack,
        pack_loader=lambda document_id: store.load_document_pack(
            loaded.manifest,
            document_id,
        ),
    )
    assert all(window.views == () for window in restored.windows.windows)
    restored.restore_active()
    restored.schedule_lazy_restore()
    _wait(qapp, lambda: restored.documents.count == 3)

    assert restored.capture_session(clean_shutdown=True) == expected
    assert restored.active_view.view_id == shared_second.view_id
    assert restored.documents.count == 3
    assert restored.window_count == 2
    assert restored.find_replace.export_state(shared_second.view_id) == expected_find
    shared_entry = restored.documents.find_path(paths[0])
    assert shared_entry is not None
    assert shared_entry.document.can_undo is True
    assert shared_entry.document.can_redo is True
    assert shared_entry.document.read(0, shared_entry.document.total_chars()) == (
        paths[0].read_text(encoding="utf-8")
    )
    restored.request_quit(lambda _entry: None)
    qapp.processEvents()
