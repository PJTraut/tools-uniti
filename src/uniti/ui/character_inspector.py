"""Character-level Unicode and encoding inspection for UNITI."""

from __future__ import annotations

import unicodedata

from PySide6.QtWidgets import QDialog, QFormLayout, QLabel, QPushButton, QVBoxLayout


def _encoded_hex(character: str, encoding: str) -> str:
    try:
        payload = character.encode(encoding, errors="strict")
    except UnicodeEncodeError:
        return "not representable"
    return " ".join(f"{byte:02X}" for byte in payload)


class CharacterInspectorDialog(QDialog):
    """Small operational dialog showing one logical Unicode character."""

    def __init__(
        self,
        character: str,
        *,
        output_encoding: str,
        invalid_bytes: bytes | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if len(character) != 1:
            raise ValueError("character inspector requires exactly one character")
        self.setWindowTitle("UNITI — Character Inspector")

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

        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(close_button)
