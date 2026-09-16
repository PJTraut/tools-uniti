import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from uniti.ui.character_inspector import (
    MAX_INSPECT_SELECTION_CHARACTERS,
    CharacterInspectorDialog,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_single_character_shows_the_character_inspector_form(qapp):
    dialog = CharacterInspectorDialog("A", output_encoding="utf-8")
    try:
        assert dialog.windowTitle() == "UNITI — Character Inspector"
        tables = [
            child
            for child in dialog.children()
            if type(child).__name__ == "QTableWidget"
        ]
        assert tables == []
    finally:
        dialog.close()


def test_selection_table_has_one_row_per_character_with_expected_columns(qapp):
    from uniti.ui.character_inspector import _TABLE_COLUMNS

    dialog = CharacterInspectorDialog("A1", output_encoding="utf-8")
    try:
        tables = [
            child
            for child in dialog.children()
            if type(child).__name__ == "QTableWidget"
        ]
        assert len(tables) == 1
        table = tables[0]
        assert table.rowCount() == 2
        assert table.columnCount() == len(_TABLE_COLUMNS)
        assert table.item(0, 0).text() == "U+0041"
        assert table.item(0, 2).text() == "LATIN CAPITAL LETTER A"
        assert table.item(0, 3).text() == "Lu"
        assert table.item(0, 4).text() == "Latin"
        assert table.item(1, 0).text() == "U+0031"
    finally:
        dialog.close()


def test_control_character_shows_its_code_point_instead_of_a_raw_glyph(qapp):
    dialog = CharacterInspectorDialog("A\tB", output_encoding="utf-8")
    try:
        tables = [
            child
            for child in dialog.children()
            if type(child).__name__ == "QTableWidget"
        ]
        table = tables[0]
        assert table.item(1, 1).text() == "U+0009"
    finally:
        dialog.close()


def test_long_selection_is_truncated_with_a_notice(qapp):
    text = "A" * (MAX_INSPECT_SELECTION_CHARACTERS + 50)
    dialog = CharacterInspectorDialog(text, output_encoding="utf-8")
    try:
        labels = [
            child.text()
            for child in dialog.children()
            if type(child).__name__ == "QLabel"
        ]
        assert any("first" in label.lower() for label in labels)
        tables = [
            child
            for child in dialog.children()
            if type(child).__name__ == "QTableWidget"
        ]
        assert tables[0].rowCount() == MAX_INSPECT_SELECTION_CHARACTERS
    finally:
        dialog.close()


def test_empty_text_is_rejected(qapp):
    with pytest.raises(ValueError):
        CharacterInspectorDialog("", output_encoding="utf-8")
