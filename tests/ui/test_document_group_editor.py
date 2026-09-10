import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QColorDialog, QInputDialog, QMessageBox

from uniti.app.document_groups import DocumentGroup, MAX_GROUPS
from uniti.ui.document_group_editor import DocumentGroupEditor


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _starting_groups():
    return (
        DocumentGroup("A", "A", "#e06c75"),
        DocumentGroup("B", "B", "#61afef"),
    )


def test_editor_starts_with_the_supplied_groups(qapp):
    editor = DocumentGroupEditor(_starting_groups())
    try:
        assert editor.groups() == _starting_groups()
        assert editor._list.count() == 2
    finally:
        editor.close()


def test_add_appends_a_validated_group(qapp, monkeypatch):
    editor = DocumentGroupEditor(_starting_groups())
    try:
        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *a, **k: ("Drafts", True))
        )
        monkeypatch.setattr(
            QColorDialog,
            "getColor",
            staticmethod(lambda *a, **k: QColor("#8888ff")),
        )

        editor._add()

        names = [group.name for group in editor.groups()]
        assert names == ["A", "B", "Drafts"]
        assert editor.groups()[-1].color == "#8888ff"
    finally:
        editor.close()


def test_add_is_cancelled_when_the_name_dialog_is_dismissed(qapp, monkeypatch):
    editor = DocumentGroupEditor(_starting_groups())
    try:
        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False))
        )

        editor._add()

        assert editor.groups() == _starting_groups()
    finally:
        editor.close()


def test_add_refuses_past_the_group_bound(qapp, monkeypatch):
    editor = DocumentGroupEditor(
        tuple(DocumentGroup(f"g{n}", f"g{n}", "#123456") for n in range(MAX_GROUPS))
    )
    try:
        called = []
        monkeypatch.setattr(
            QInputDialog,
            "getText",
            staticmethod(lambda *a, **k: called.append(1) or ("x", True)),
        )
        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))

        editor._add()

        assert len(editor.groups()) == MAX_GROUPS
        assert called == []
    finally:
        editor.close()


def test_rename_updates_the_selected_group_name_only(qapp, monkeypatch):
    editor = DocumentGroupEditor(_starting_groups())
    try:
        editor._list.setCurrentRow(0)
        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *a, **k: ("Reviewed", True))
        )

        editor._rename()

        renamed = editor.groups()[0]
        assert renamed.name == "Reviewed"
        assert renamed.id == "A"
        assert renamed.color == "#e06c75"
    finally:
        editor.close()


def test_recolor_updates_the_selected_group_color_only(qapp, monkeypatch):
    editor = DocumentGroupEditor(_starting_groups())
    try:
        editor._list.setCurrentRow(1)
        monkeypatch.setattr(
            QColorDialog,
            "getColor",
            staticmethod(lambda *a, **k: QColor("#ff00ff")),
        )

        editor._recolor()

        recolored = editor.groups()[1]
        assert recolored.color == "#ff00ff"
        assert recolored.name == "B"
    finally:
        editor.close()


def test_remove_deletes_the_selected_group(qapp):
    editor = DocumentGroupEditor(_starting_groups())
    try:
        editor._list.setCurrentRow(0)

        editor._remove()

        assert [group.id for group in editor.groups()] == ["B"]
    finally:
        editor.close()


def test_no_selection_leaves_rename_recolor_remove_as_no_ops(qapp):
    editor = DocumentGroupEditor(_starting_groups())
    try:
        editor._list.setCurrentRow(-1)

        editor._rename()
        editor._recolor()
        editor._remove()

        assert editor.groups() == _starting_groups()
    finally:
        editor.close()
