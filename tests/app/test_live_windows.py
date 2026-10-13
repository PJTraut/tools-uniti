"""Only the active window follows edits live; the others are frozen until
they're activated (2026-10-13)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from usfm_project_fixture import ensure_project  # noqa: E402
from test_service import _desktop_service, _stop_desktop_service  # noqa: E402

from PySide6.QtCore import Qt  # noqa: E402

_GEN = "\\id GEN\n\\c 1\n\\p\n\\v 1 In the beginning.\n"


@pytest.fixture
def desktop(tmp_path: Path):
    app, service, _recovery = _desktop_service(tmp_path)
    yield app, service
    for _window_id, window in service.windows.items:
        window.close_all_documents(force=True)
        window.close()
    app.processEvents()
    _stop_desktop_service(app, service)


def _two_windows(app, service, tmp_path: Path):
    """NIV GEN in USFM A and, as a second view, in USFM B shown in Preview."""

    niv = ensure_project(tmp_path / "niv", name="NIV")
    (niv / "01GEN.usfm").write_text(_GEN, encoding="utf-8")
    main = service.new_window()
    source = main.open_path(niv / "01GEN.usfm")
    window_a = main.move_to_environment_window(source)
    window_b = service.new_environment_window("usfm")
    other = window_b.open_path(niv / "01GEN.usfm")
    assert other is not source and other.document is source.document
    for window in (window_a, window_b):
        window.show()
    window_b._rich_views.show("sfm.preview", other)
    app.processEvents()
    return window_a, window_b, source, other


def _activate(service, window, view) -> None:
    service.set_active_view(window.window_id, view.view_id)


def test_an_inactive_windows_preview_waits_until_the_window_is_activated(desktop, tmp_path: Path):
    app, service = desktop
    window_a, window_b, source, other = _two_windows(app, service, tmp_path)
    pane = window_b._rich_views.pane_for(other)
    _activate(service, window_a, source)
    assert window_a.is_live_window and not window_b.is_live_window

    source.document.insert(source.document.total_chars(), "\\v 2 Formless.\n")
    app.processEvents()

    assert "Formless" not in pane.projection.text  # frozen
    assert pane.stale

    _activate(service, window_b, other)

    assert "Formless" in pane.projection.text
    assert not pane.stale


def test_the_active_windows_splits_follow_edits_live(desktop, tmp_path: Path):
    app, service = desktop
    window_a, window_b, source, other = _two_windows(app, service, tmp_path)
    _activate(service, window_b, other)
    split = window_b.split_right()
    assert split is not None and split.document is other.document
    pane = window_b._rich_views.pane_for(other)

    split.document.insert(split.document.total_chars(), "\\v 2 Formless.\n")
    app.processEvents()

    assert "Formless" in pane.projection.text
    assert not pane.stale
