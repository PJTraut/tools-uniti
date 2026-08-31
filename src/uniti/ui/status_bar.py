"""Operational status bar for the UNITI desktop shell."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QStatusBar


class UNITIStatusBar(QStatusBar):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._encoding = QLabel("—")
        self._eol = QLabel("—")
        self._position = QLabel("Ln 1:1")
        self._size = QLabel("0 B")
        for label in (self._encoding, self._eol, self._position):
            self.addWidget(label)
        self.addPermanentWidget(self._size)

    @staticmethod
    def _format_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
            if value < 1024.0 or unit == "TiB":
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024.0
        return f"{size} B"

    def update_document(self, document) -> None:
        encoding = document.encoding_info.output_encoding or document.encoding_info.detected
        self._encoding.setText(encoding)
        self._eol.setText(document.output_eol or "EOL: source")
        try:
            size = document.path.stat().st_size
        except OSError:
            size = document.source.size
        self._size.setText(self._format_size(size))

    def update_cursor(self, line: int, column: int) -> None:
        self._position.setText(f"Ln {line + 1}:{column + 1}")

    def clear_document(self) -> None:
        self._encoding.setText("—")
        self._eol.setText("—")
        self._position.setText("Ln 1:1")
        self._size.setText("0 B")
