"""Operational status bar for the UNITI desktop shell."""

from __future__ import annotations

from uniti.core.eol import EOLReport
from PySide6.QtWidgets import QLabel, QStatusBar


class UNITIStatusBar(QStatusBar):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._encoding = QLabel("—")
        self._eol = QLabel("—")
        self._position = QLabel("Ln 1:1")
        self._zoom = QLabel("—")
        self._wrap = QLabel("—")
        self._size = QLabel("0 B")
        self._eol_report: EOLReport | None = None
        for label in (
            self._encoding,
            self._eol,
            self._position,
            self._zoom,
            self._wrap,
        ):
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

    def update_eol_report(self, report: EOLReport | None) -> None:
        self._eol_report = report

    def update_document(self, document, eol_report: EOLReport | None = None) -> None:
        if eol_report is not None:
            self._eol_report = eol_report
        detected = document.encoding_info.detected
        output_encoding = document.output_encoding
        self._encoding.setText(
            detected if output_encoding == detected else f"{detected} → {output_encoding}"
        )

        report = self._eol_report
        if report is None:
            eol_text = "EOL: analyzing…"
        elif report.kind == "MIXED":
            eol_text = (
                f"MIXED (LF {report.lf} / CRLF {report.crlf} / CR {report.cr})"
            )
        else:
            eol_text = report.kind
        if document.output_eol is not None:
            eol_text = f"{eol_text} → {document.output_eol}"
        self._eol.setText(eol_text)

        try:
            size = document.path.stat().st_size
        except OSError:
            size = document.source.size
        self._size.setText(self._format_size(size))

    def update_cursor(self, line: int, column: int) -> None:
        self._position.setText(f"Ln {line + 1}:{column + 1}")

    def update_view(self, zoom_percent: int, *, soft_wrap: bool) -> None:
        self._zoom.setText(f"{zoom_percent}%")
        self._wrap.setText("Wrap" if soft_wrap else "No Wrap")

    def clear_document(self) -> None:
        self._eol_report = None
        self._encoding.setText("—")
        self._eol.setText("—")
        self._position.setText("Ln 1:1")
        self._zoom.setText("—")
        self._wrap.setText("—")
        self._size.setText("0 B")
