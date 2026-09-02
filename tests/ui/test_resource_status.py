from __future__ import annotations

import os
from dataclasses import replace

from uniti.resources import ResourceState, TaskKind


def test_resource_status_is_text_accessible_and_notices_are_coalesced():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    try:
        constrained = replace(
            window._resources.status,
            state=ResourceState.CONSTRAINED,
            available_memory=2 << 30,
            process_rss=200 << 20,
            cache_used=32 << 20,
            active_workers=2,
            queued_tasks=3,
        )

        window._apply_resource_status(constrained)

        assert window.statusBar().resource_label.text() == "Resources: Constrained"
        tooltip = window.statusBar().resource_label.toolTip()
        assert "Available memory" in tooltip
        assert "Cache" in tooltip
        assert "Active/queued" in tooltip
        assert window._resource_notice_count == 1

        window._apply_resource_status(constrained)
        assert window._resource_notice_count == 1

        window._apply_resource_status(
            replace(constrained, state=ResourceState.NORMAL)
        )
        window._apply_resource_status(constrained)
        assert window._resource_notice_count == 2
    finally:
        window.close()
        app.processEvents()


def test_pause_background_command_does_not_pause_foreground_save():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    try:
        action = window._command_actions["view.pause_background"]
        assert action.isCheckable()

        action.trigger()

        assert window._resources.tasks.snapshot().background_paused
        assert window._resources.tasks.kind_is_paused(TaskKind.INDEX)
        assert not window._resources.tasks.kind_is_paused(TaskKind.SAVE)
        assert window.statusBar().resource_label.text().endswith("Paused")
    finally:
        window.close()
        app.processEvents()


def test_status_bar_formats_determinate_and_indeterminate_task_progress():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.resources import TaskProgress
    from uniti.ui.status_bar import UNITIStatusBar

    app = QApplication.instance() or QApplication([])
    status = UNITIStatusBar()
    progress = TaskProgress("save-1", "Writing", 25, 100, 1.0, True)

    status.update_task(progress)
    assert status.task_label.text() == "Writing: 25%"
    assert status.active_task == progress

    status.update_task(TaskProgress("save-1", "Verifying", 5, None, 2.0, True))
    assert status.task_label.text() == "Verifying"
    status.clear_task("save-1")
    assert status.task_label.text() == ""
    assert status.active_task is None
    app.processEvents()
