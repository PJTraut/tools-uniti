from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest


@pytest.fixture
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait(app, predicate, timeout: float = 5.0) -> None:
    deadline = time.perf_counter() + timeout
    while not predicate() and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert predicate()


def test_progressive_save_as_locks_only_source_and_cancel_preserves_target(
    app,
    tmp_path: Path,
    monkeypatch,
):
    from PySide6.QtWidgets import QMessageBox

    import uniti.ui.file_operations as file_operations
    from uniti.ui.main_window import UNITIMainWindow

    source_path = tmp_path / "source.txt"
    other_path = tmp_path / "other.txt"
    target = tmp_path / "target.txt"
    source_path.write_bytes(b"new text\n" * 100_000)
    other_path.write_text("other\n", encoding="utf-8", newline="")
    target.write_bytes(b"original")
    window = UNITIMainWindow()
    observations = []
    window._file_operations.set_dogfood_observer(
        lambda operation, outcome, **facts: observations.append(
            (operation, outcome, facts)
        )
    )
    source = window.open_path(source_path)
    other = window.open_path(other_path)
    window.panes.active_leaf.tabs.setCurrentWidget(source)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    real_prepare = file_operations.prepare_document_save
    started = threading.Event()

    def delayed_prepare(request, context):
        context.report("Writing", 1, 10)
        started.set()
        while True:
            context.check_cancelled()
            time.sleep(0.005)

    monkeypatch.setattr(file_operations, "prepare_document_save", delayed_prepare)
    try:
        handle = window.start_save_current_as(
            target,
            source.document.output_format,
        )
        assert handle is not None
        assert started.wait(1.0)
        _wait(app, lambda: window.statusBar().active_task is not None)
        assert source.isEnabled() is False
        assert other.isEnabled() is True
        assert window.statusBar().task_label.text() == "Writing: 10%"

        handle.cancel()
        _wait(app, lambda: handle.done)
        _wait(app, lambda: source.isEnabled())
        _wait(app, lambda: window.statusBar().active_task is None)

        assert target.read_bytes() == b"original"
        assert list(tmp_path.glob(".target.txt.*.uniti-tmp")) == []
        from uniti.app.dogfood import Operation, Outcome

        assert (Operation.SAVE_AS, Outcome.CANCELLED) in {
            (operation, outcome)
            for operation, outcome, _facts in observations
        }
    finally:
        monkeypatch.setattr(file_operations, "prepare_document_save", real_prepare)
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_progressive_save_as_commits_and_opens_target_tab(
    app,
    tmp_path: Path,
):
    from uniti.ui.main_window import UNITIMainWindow

    source_path = tmp_path / "source.txt"
    target = tmp_path / "target.txt"
    source_path.write_text("exported\n", encoding="utf-8", newline="")
    window = UNITIMainWindow()
    observations = []
    window._file_operations.set_dogfood_observer(
        lambda operation, outcome, **facts: observations.append(
            (operation, outcome, facts)
        )
    )
    source = window.open_path(source_path)
    try:
        handle = window.start_save_current_as(
            target,
            source.document.output_format,
        )
        assert handle is not None
        _wait(app, lambda: handle.done)
        _wait(app, lambda: source.isEnabled() and target.exists())

        assert target.read_text(encoding="utf-8") == "exported\n"
        assert source.document.path == source_path
        assert window.current_view is not source
        assert window.current_view.document.path == target
        assert window.panes.active_leaf.tabs.count() == 2
        from uniti.app.dogfood import Durability, Operation, Outcome

        saved = next(
            call for call in observations if call[0] is Operation.SAVE_AS
        )
        assert saved[1] is Outcome.SUCCESS
        assert saved[2]["durability"] is Durability.FULL
        assert str(source_path) not in repr(saved)
        assert str(target) not in repr(saved)
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_file_menu_uses_progressive_handlers():
    source = Path("src/uniti/ui/main_window.py").read_text(encoding="utf-8")

    assert '"file.save", self.start_save_current' in source
    assert '"file.save_as", self.start_save_current_as' in source


def test_post_save_format_inspection_is_bounded(monkeypatch, tmp_path: Path):
    import uniti.ui.main_window as main_window

    path = tmp_path / "saved.txt"
    path.write_text("text\n", encoding="utf-8", newline="")
    seen = {}

    def inspect(source, **kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(main_window, "inspect_source", inspect)
    result = main_window.UNITIMainWindow._inspect_known_output(
        path,
        main_window.encoding_profile("utf-8"),
    )

    assert result is not None
    assert seen["eol_max_bytes"] == 65_536


def test_progressive_save_refuses_external_change_and_records_fixed_outcome(
    app,
    tmp_path: Path,
    monkeypatch,
):
    from PySide6.QtWidgets import QMessageBox

    from uniti.app.dogfood import Operation, Outcome
    from uniti.ui.main_window import UNITIMainWindow

    source_path = tmp_path / "external.txt"
    source_path.write_text("original", encoding="utf-8")
    window = UNITIMainWindow()
    observations = []
    window._file_operations.set_dogfood_observer(
        lambda operation, outcome, **facts: observations.append(
            (operation, outcome, facts)
        )
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: None)
    view = window.open_path(source_path)
    view.document.insert(0, "edited ")
    try:
        handle = window.start_save_current()
        assert handle is not None
        deadline = time.monotonic() + 5.0
        while not handle.done and time.monotonic() < deadline:
            time.sleep(0.001)
        assert handle.done
        source_path.write_text("external", encoding="utf-8")
        _wait(app, lambda: view.isEnabled())

        assert source_path.read_text(encoding="utf-8") == "external"
        assert (Operation.SAVE, Outcome.REFUSED_EXTERNAL_CHANGE) in {
            (operation, outcome)
            for operation, outcome, _facts in observations
        }
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_progressive_save_records_success_and_full_durability(
    app,
    tmp_path: Path,
):
    from uniti.app.dogfood import Durability, Operation, Outcome
    from uniti.ui.main_window import UNITIMainWindow

    source_path = tmp_path / "save.txt"
    source_path.write_text("before", encoding="utf-8")
    window = UNITIMainWindow()
    observations = []
    window._file_operations.set_dogfood_observer(
        lambda operation, outcome, **facts: observations.append(
            (operation, outcome, facts)
        )
    )
    view = window.open_path(source_path)
    view.document.insert(view.document.total_chars(), " after")
    try:
        handle = window.start_save_current()
        assert handle is not None
        _wait(app, lambda: handle.done and view.isEnabled())

        saved = next(call for call in observations if call[0] is Operation.SAVE)
        assert saved[1] is Outcome.SUCCESS
        assert saved[2]["durability"] is Durability.FULL
        assert source_path.read_text(encoding="utf-8") == "before after"
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()
