"""N32/N33: the management window and the ecosystem stats it shows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from test_service import _desktop_service, _stop_desktop_service

from uniti.app.ecosystem_stats import collect_stats, format_bytes, format_remaining
from uniti.ui.management_window import render_stats


@pytest.fixture
def desktop(tmp_path: Path):
    app, service, _recovery = _desktop_service(tmp_path)
    yield app, service
    for _window_id, window in service.windows.items:
        window.close_all_documents(force=True)
        window.close()
    app.processEvents()
    _stop_desktop_service(app, service)


def test_formatting():
    assert format_bytes(None) == "unknown" and format_bytes(512) == "512 B"
    assert format_bytes(3 * 1024 * 1024) == "3.0 MB"
    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    assert format_remaining(now + timedelta(days=2, hours=3), now) == "expires in 2 d 3 h"
    assert format_remaining(now - timedelta(seconds=1), now) == "expires now"


def test_stats_count_open_files_and_list_undo_caches(desktop, tmp_path: Path):
    _app, service = desktop
    window = service.new_window()
    first = tmp_path / "a.txt"
    second = tmp_path / "b.md"
    first.write_text("one\n")
    second.write_text("two\n")
    window.open_path(first)
    view = window.open_path(second)

    stats = collect_stats(service, recovery_bytes=2048)
    assert stats.open_files == 2 and stats.windows == 1 and stats.recovery_bytes == 2048
    assert stats.process_rss is None or stats.process_rss > 0
    assert not stats.undo_caches

    window.close_view_discarding(view)
    stats = collect_stats(service)
    assert stats.open_files == 1
    assert [cache.name for cache in stats.undo_caches] == ["b.md"]
    cache = stats.undo_caches[0]
    assert cache.expires_at - cache.closed_at == service.documents.closed_history_retention

    html = render_stats(stats, datetime.now(timezone.utc))
    assert "Open files" in html and "b.md" in html and "expires in" in html


def test_closing_the_last_window_shows_the_management_window(desktop, tmp_path: Path):
    app, service = desktop
    window = service.new_window()
    window.show()
    window.close()
    app.processEvents()

    management = service._management_window
    assert management.isVisible() and not window.isVisible()
    assert service.window_count == 1  # the window lives on, hidden, to open files into
    assert "Open files" in management.stats.text()
    management.hide()
