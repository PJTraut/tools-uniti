"""EOL status and marker truth across pending, committed and aborted saves."""
import os
import time

import pytest


@pytest.fixture
def workspace(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from uniti.app.service import QuitChoice, UNITIService
    from uniti.app.session_store import SessionStore
    from uniti.app.settings import SettingsStore
    from uniti.resources import ResourceManager

    class Recovery:
        def attach(self, _document, **_kwargs):
            pass

        def detach(self, _document, *, clean):
            pass

        def shutdown(self):
            pass

    app = QApplication.instance() or QApplication([])
    service = UNITIService(
        resource_manager=ResourceManager(max_workers=2),
        settings_store=SettingsStore(tmp_path / "settings.json"),
        session_store=SessionStore(tmp_path / "sessions"),
        recovery_manager=Recovery(),
    )
    yield app, service
    service.request_quit(lambda _entry: QuitChoice.DISCARD)
    app.processEvents()


def _wait(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert predicate()


def _shared_views(service, path):
    left, right = service.new_window(), service.new_window()
    first = left.open_path(path)
    second = right.open_existing_document(first.document)
    assert first is not second
    assert first.document is second.document
    from PySide6.QtWidgets import QApplication
    _wait(QApplication.instance(), lambda: not left._eol_jobs and not right._eol_jobs)
    left.show()
    right.show()
    return (left, first), (right, second)


def _labels(app, monkeypatch, view):
    labels = []
    original = view._paint_whitespace_marker

    def observe(painter, kind, label, x1, x2, y):
        if kind == "eol":
            labels.append(label)
        original(painter, kind, label, x1, x2, y)

    with monkeypatch.context() as patch:
        patch.setattr(view, "_paint_whitespace_marker", observe)
        view.set_whitespace_mode("eol")
        app.processEvents()
        labels.clear()
        view.viewport().repaint()
    return labels


@pytest.mark.parametrize("source,kind", [(b"one\ntwo\n", "LF"), (b"one\rtwo\r", "CR"), (b"one\r\ntwo\r\n", "CRLF"), (b"one\ntwo\r\n", "Mixed")])
@pytest.mark.parametrize("target,ending", [("LF", b"\n"), ("CR", b"\r"), ("CRLF", b"\r\n")])
@pytest.mark.parametrize("progressive", [False, True])
def test_saved_eol_refreshes_every_window(workspace, tmp_path, monkeypatch, source, kind, target, ending, progressive):
    from uniti.core.document import Document

    app, service = workspace
    path = tmp_path / "eol.txt"
    path.write_bytes(source)
    pairs = _shared_views(service, path)
    window, view = pairs[0]
    app.processEvents()
    window.set_output_eol(target)
    app.processEvents()
    assert path.read_bytes() == source
    assert view.document.read(0, len(source)).encode() == source
    before = ["LF", "CRLF"] if kind == "Mixed" else [kind, kind]
    for _, candidate in pairs:
        assert _labels(app, monkeypatch, candidate) == before
    if progressive:
        handle = window.start_save_current()
        assert handle is not None
        _wait(app, lambda: not window._save_jobs)
    else:
        assert window.save_current() == path
    app.processEvents()
    expected = b"one" + ending + b"two" + ending
    assert path.read_bytes() == expected
    with Document.open(path, encoding="utf-8") as reopened:
        assert reopened.read(0, len(expected)).encode() == expected
    for owner, candidate in pairs:
        assert _labels(app, monkeypatch, candidate) == [target, target]
        assert owner._eol_reports[id(candidate)].kind == target
        assert owner._status.format_label.text() == f"UTF-8, {target}"
        assert id(candidate) not in owner._eol_dialogs


def test_pending_conversion_and_keep_source_are_explicit_in_every_window(workspace, tmp_path, monkeypatch):
    app, service = workspace
    path = tmp_path / "pending.txt"
    path.write_bytes(b"one\ntwo\n")
    pairs = _shared_views(service, path)
    pairs[0][0].set_output_eol("CRLF")
    app.processEvents()
    for owner, view in pairs:
        assert owner._status.format_label.text() == "UTF-8, LF (on save: UTF-8, CRLF)"
        assert _labels(app, monkeypatch, view) == ["LF", "LF"]
    pairs[0][0].set_output_eol(None)
    app.processEvents()
    for owner, view in pairs:
        assert owner._status.format_label.text() == "UTF-8, LF"
    assert pairs[0][0].save_current() == path
    assert path.read_bytes() == b"one\ntwo\n"


@pytest.mark.parametrize("cancel", [False, True])
def test_unsuccessful_save_keeps_source_markers_and_pending_target(workspace, tmp_path, monkeypatch, cancel):
    import uniti.ui.file_operations as operations

    app, service = workspace
    path = tmp_path / "abort.txt"
    path.write_bytes(b"one\ntwo\n")
    pairs = _shared_views(service, path)
    window, view = pairs[0]
    window.set_output_eol("CRLF")

    def fail_or_wait(request, context):
        if not cancel:
            raise OSError("synthetic write failure")
        while True:
            context.check_cancelled()
            time.sleep(0.001)

    errors = []
    monkeypatch.setattr(operations, "prepare_document_save", fail_or_wait)
    monkeypatch.setattr(window, "_show_save_error", errors.append)
    handle = window.start_save_current()
    assert handle is not None
    if cancel:
        handle.cancel()
    _wait(app, lambda: not window._save_jobs)
    assert bool(errors) is not cancel
    assert path.read_bytes() == b"one\ntwo\n"
    for owner, candidate in pairs:
        assert candidate.document.modified
        assert _labels(app, monkeypatch, candidate) == ["LF", "LF"]
        assert owner._status.format_label.text() == "UTF-8, LF (on save: UTF-8, CRLF)"


def test_keep_source_preserves_mixed_bytes_and_reports(workspace, tmp_path, monkeypatch):
    app, service = workspace
    path = tmp_path / "mixed.txt"
    original = b"one\ntwo\r\n"
    path.write_bytes(original)
    pairs = _shared_views(service, path)
    window, _ = pairs[0]
    window.set_output_eol("CR")
    window.set_output_eol(None)
    assert window.save_current() == path
    app.processEvents()
    assert path.read_bytes() == original
    for owner, candidate in pairs:
        assert _labels(app, monkeypatch, candidate) == ["LF", "CRLF"]
        assert owner._status.format_label.text() == "UTF-8, Mixed"
