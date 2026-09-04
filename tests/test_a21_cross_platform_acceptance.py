from __future__ import annotations

import os
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_a21_editor_docking_preserves_authority_layout_and_bytes(tmp_path: Path):
    from PySide6.QtWidgets import QApplication, QDockWidget

    from uniti.app.session import DockReturnRecord
    from uniti.app.session_store import SessionStore
    from uniti.app.service import QuitChoice, UNITIService
    from uniti.app.settings import SettingsStore
    from uniti.resources import ResourceManager

    class Recovery:
        def attach(self, _document, **_kwargs):
            return None

        def detach(self, _document, *, clean):
            return None

        def shutdown(self):
            return None

    app = QApplication.instance() or QApplication([])
    source_path = tmp_path / "docking-integrity.txt"
    original_bytes = b"alpha\nbeta\ngamma\n"
    source_path.write_bytes(original_bytes)
    service = UNITIService(
        resource_manager=ResourceManager(max_workers=2),
        settings_store=SettingsStore(tmp_path / "settings.json"),
        session_store=SessionStore(tmp_path / "sessions"),
        recovery_manager=Recovery(),
    )
    window = service.new_window()
    original = window.open_path(source_path)
    assert original is not None
    clone = window.split_right()
    assert clone is not None
    location = window.view_location(clone.view_id)
    try:
        assert clone.document is original.document
        assert service.documents.count == 1

        detached = service.undock_view(clone.view_id)

        expected_anchor = DockReturnRecord(
            window.window_id,
            location.pane_id,
            location.tab_index,
        )
        assert clone.dock_return == expected_anchor
        captured = service.capture_session(clean_shutdown=False)
        captured_view = next(
            item for item in captured.manifest.views if item.view_id == clone.view_id
        )
        assert captured_view.dock_return == expected_anchor
        assert all(
            not isinstance(parent, QDockWidget)
            for parent in _widget_ancestors(clone)
        )

        service.dock_view(clone.view_id)

        assert window.view_location(clone.view_id) == location
        assert detached not in service.windows.windows
        assert clone.dock_return is None
        assert source_path.read_bytes() == original_bytes
        assert clone.document.read(0, clone.document.total_chars()) == (
            original_bytes.decode("utf-8")
        )
    finally:
        if service.is_running:
            service.request_quit(lambda _entry: QuitChoice.DISCARD)
        app.processEvents()


def _widget_ancestors(widget):
    parent = widget.parentWidget()
    while parent is not None:
        yield parent
        parent = parent.parentWidget()
