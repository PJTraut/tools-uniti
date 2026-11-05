"""The management window (N32, N33): the default window when no document
window is open. It shows stats of the UNITI ecosystem, read-only, and the
ways to open a file, start an environment window or quit."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from uniti.app.ecosystem_stats import (
    EcosystemStats,
    collect_stats,
    directory_size,
    format_bytes,
    format_remaining,
)

REFRESH_MS = 2000
RECOVERY_SIZE_SECONDS = 30.0  # walking the recovery folder is cached this long


class ManagementWindow(QWidget):
    def __init__(self, service) -> None:
        super().__init__()
        self._service = service
        self.setWindowTitle("UNITI")
        self.setObjectName("managementWindow")
        self.resize(560, 520)
        self._recovery: tuple[float, int | None] | None = None

        layout = QVBoxLayout(self)
        title = QLabel("UNITI", self)
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)

        actions = QHBoxLayout()
        self.open_button = QPushButton("Open File…", self)
        self.open_button.clicked.connect(self._open_file)
        self.new_text_button = QPushButton("New Text Window", self)
        self.new_text_button.clicked.connect(self._new_text_window)
        self.quit_button = QPushButton("Quit", self)
        self.quit_button.clicked.connect(self._quit)
        for button in (self.open_button, self.new_text_button):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(self.quit_button)
        layout.addLayout(actions)

        self.stats = QLabel(self)
        self.stats.setTextFormat(Qt.TextFormat.RichText)
        self.stats.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.stats.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.stats.setAccessibleName("UNITI stats")
        layout.addWidget(self.stats, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    # --- stats ------------------------------------------------------------------

    def _recovery_bytes(self) -> int | None:
        now = time.monotonic()
        if self._recovery is None or now - self._recovery[0] >= RECOVERY_SIZE_SECONDS:
            directory = getattr(self._service.recovery, "directory", None)
            self._recovery = (now, directory_size(Path(directory)) if directory else None)
        return self._recovery[1]

    def refresh(self) -> None:
        try:
            stats = collect_stats(self._service, recovery_bytes=self._recovery_bytes())
        except Exception as error:  # a stats panel must never break the app
            self.stats.setText(f"Stats unavailable: {error}")
            return
        self.stats.setText(render_stats(stats, datetime.now(timezone.utc)))

    def showEvent(self, event) -> None:
        self._recovery = None
        self.refresh()
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    # --- actions ------------------------------------------------------------------

    def _document_window(self):
        window = self._service.most_recent_window or self._service.new_window()
        window.show()
        window.raise_()
        window.activateWindow()
        return window

    def _open_file(self) -> None:
        self._document_window().open_dialog()

    def _new_text_window(self) -> None:
        window = self._service.new_window()
        window.show()
        window.raise_()
        window.activateWindow()

    def _quit(self) -> None:
        window = self._service.most_recent_window
        if window is not None:
            window.request_quit()
        else:
            QApplication.quit()

    def closeEvent(self, event) -> None:
        """Closing it hides it while a document window shows; closing the
        last window of the app quits."""

        if any(w.isVisible() for _id, w in self._service.windows.items):
            event.accept()
            return
        window = self._service.most_recent_window
        if window is not None and not window.request_quit():
            event.ignore()
            return
        event.accept()


def render_stats(stats: EcosystemStats, now: datetime) -> str:
    rows = [
        ("Open files", str(stats.open_files)),
        ("Windows", str(stats.windows)),
    ]
    for count in stats.environments:
        detail = f"{count.files} file{'s' if count.files != 1 else ''}"
        if count.projects:
            detail += f", {count.projects} project{'s' if count.projects != 1 else ''}"
        rows.append((count.key, detail))
    rows.append(("Memory (this app)", format_bytes(stats.process_rss)))
    cache = format_bytes(stats.cache_used)
    if stats.cache_budget:
        cache += f" of {format_bytes(stats.cache_budget)}"
    rows.append(("Cache", cache))
    rows.append(("Recovery data", format_bytes(stats.recovery_bytes)))
    body = "".join(f"<tr><td style='padding-right:18px'><b>{name}</b></td><td>{value}</td></tr>" for name, value in rows)
    html = f"<table>{body}</table>"
    if stats.undo_caches:
        items = "".join(
            f"<tr><td style='padding-right:18px'>{cache.name}</td><td>{format_remaining(cache.expires_at, now)}</td></tr>"
            for cache in stats.undo_caches[:12]
        )
        more = len(stats.undo_caches) - 12
        extra = f"<tr><td>… {more} more</td><td></td></tr>" if more > 0 else ""
        html += f"<p><b>Undo caches of closed files</b></p><table>{items}{extra}</table>"
    else:
        html += "<p><b>Undo caches of closed files</b>: none</p>"
    return html
