import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from uniti.ui.extension_profile_editor import ExtensionProfileEditor, MAX_OVERRIDES


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_editor_starts_with_the_supplied_overrides(qapp):
    editor = ExtensionProfileEditor({"usj": "json"})
    try:
        assert editor.overrides() == {"usj": "json"}
        assert editor._list.count() == 1
        assert editor._list.item(0).text() == ".usj → JSON"
    finally:
        editor.close()


def test_add_assigns_a_new_extension_to_a_chosen_profile(qapp, monkeypatch):
    editor = ExtensionProfileEditor({})
    try:
        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *a, **k: ("usx", True))
        )
        monkeypatch.setattr(
            QInputDialog, "getItem", staticmethod(lambda *a, **k: ("XML", True))
        )
        editor._add()
        assert editor.overrides() == {"usx": "xml"}
    finally:
        editor.close()


def test_add_normalizes_a_leading_dot_and_uppercase(qapp, monkeypatch):
    editor = ExtensionProfileEditor({})
    try:
        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *a, **k: (".USX", True))
        )
        monkeypatch.setattr(
            QInputDialog, "getItem", staticmethod(lambda *a, **k: ("XML", True))
        )
        editor._add()
        assert editor.overrides() == {"usx": "xml"}
    finally:
        editor.close()


def test_add_rejects_an_invalid_extension(qapp, monkeypatch):
    editor = ExtensionProfileEditor({})
    try:
        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *a, **k: ("has space", True))
        )
        monkeypatch.setattr(
            QMessageBox, "warning", staticmethod(lambda *a, **k: None)
        )
        editor._add()
        assert editor.overrides() == {}
    finally:
        editor.close()


def test_add_rejects_beyond_the_max_override_count(qapp, monkeypatch):
    overrides = {f"ext{i}": "json" for i in range(MAX_OVERRIDES)}
    editor = ExtensionProfileEditor(overrides)
    try:
        warned = []
        monkeypatch.setattr(
            QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a))
        )
        editor._add()
        assert warned
        assert editor.overrides() == overrides
    finally:
        editor.close()


def test_change_reassigns_the_selected_extensions_profile(qapp, monkeypatch):
    editor = ExtensionProfileEditor({"usj": "json"})
    try:
        editor._list.setCurrentRow(0)
        monkeypatch.setattr(
            QInputDialog, "getItem", staticmethod(lambda *a, **k: ("Markdown", True))
        )
        editor._change()
        assert editor.overrides() == {"usj": "markdown"}
    finally:
        editor.close()


def test_remove_deletes_the_selected_extension(qapp):
    editor = ExtensionProfileEditor({"usj": "json", "usx": "xml"})
    try:
        editor._list.setCurrentRow(0)
        editor._remove()
        assert editor.overrides() == {"usx": "xml"}
    finally:
        editor.close()
