"""Character-level Unicode and encoding inspection for UNITI (BF-003/004),
extended to a whole-selection per-character property table (BF-065, in the
style of r12a's Uniview: https://r12a.github.io/uniview/)."""

from __future__ import annotations

import unicodedataplus as unicodedata

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

# A per-character table beyond this size stops being useful UI regardless of
# how fast it renders — mirrors the app's general bounded-work philosophy
# (e.g. the whitespace-marker paint budget) rather than being a performance
# limit as such.
MAX_INSPECT_SELECTION_CHARACTERS = 4096

_TABLE_COLUMNS = ("Code Point", "Character", "Name", "Category", "Script", "Block", "Bidi Class")


def _encoded_hex(character: str, encoding: str) -> str:
    try:
        payload = character.encode(encoding, errors="strict")
    except UnicodeEncodeError:
        return "not representable"
    return " ".join(f"{byte:02X}" for byte in payload)


def _display_glyph(character: str) -> str:
    # A control/format character (category Cc/Cf, e.g. tab, newline, ZWJ)
    # renders as nothing or corrupts the row's line height — show its
    # code point notation instead, matching how the single-character form
    # already only ever shows a real, printable character.
    if unicodedata.category(character) in ("Cc", "Cf") or character in "\r\n":
        return f"U+{ord(character):04X}"
    return character


class CharacterInspectorDialog(QDialog):
    """A single character's Unicode/encoding properties, or (BF-065) a
    per-character property table for a whole multi-character selection."""

    def __init__(
        self,
        text: str,
        *,
        output_encoding: str,
        invalid_bytes: bytes | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if not text:
            raise ValueError("character inspector requires at least one character")
        layout = QVBoxLayout(self)
        if len(text) == 1:
            self.setWindowTitle("UNITI — Character Inspector")
            layout.addLayout(
                self._single_character_form(text, output_encoding, invalid_bytes)
            )
        else:
            self.setWindowTitle("UNITI — Inspect Selection")
            truncated = text[:MAX_INSPECT_SELECTION_CHARACTERS]
            if len(truncated) < len(text):
                layout.addWidget(
                    QLabel(
                        f"Showing the first {len(truncated)} of {len(text)} characters."
                    )
                )
            layout.addWidget(self._selection_table(truncated))
            self.resize(640, 420)

        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

    @staticmethod
    def _single_character_form(
        character: str,
        output_encoding: str,
        invalid_bytes: bytes | None,
    ) -> QFormLayout:
        codepoint = f"U+{ord(character):04X}"
        name = unicodedata.name(character, "<unknown>")
        form = QFormLayout()
        form.addRow("Character", QLabel(character))
        form.addRow("Unicode", QLabel(codepoint))
        form.addRow("Name", QLabel(name))
        if invalid_bytes is not None:
            raw = " ".join(f"{byte:02X}" for byte in invalid_bytes)
            form.addRow("Decode error bytes", QLabel(raw))
        form.addRow("UTF-8", QLabel(_encoded_hex(character, "utf-8")))
        form.addRow("Windows-1252", QLabel(_encoded_hex(character, "windows-1252")))
        form.addRow("UTF-16LE", QLabel(_encoded_hex(character, "utf-16-le")))
        form.addRow("UTF-16BE", QLabel(_encoded_hex(character, "utf-16-be")))
        form.addRow(output_encoding, QLabel(_encoded_hex(character, output_encoding)))
        return form

    @staticmethod
    def _selection_table(text: str) -> QTableWidget:
        table = QTableWidget(len(text), len(_TABLE_COLUMNS))
        table.setHorizontalHeaderLabels(_TABLE_COLUMNS)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, character in enumerate(text):
            values = (
                f"U+{ord(character):04X}",
                _display_glyph(character),
                unicodedata.name(character, "<unknown>"),
                unicodedata.category(character),
                unicodedata.script(character),
                unicodedata.block(character) or "No_Block",
                unicodedata.bidirectional(character),
            )
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        return table
