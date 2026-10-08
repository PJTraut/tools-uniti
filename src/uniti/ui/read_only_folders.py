"""View > Read-Only Folders… (field test round 3, T7)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from uniti.app.read_only import with_folder


class ReadOnlyFoldersDialog(QDialog):
    """Edit the folders whose files open read-only."""

    def __init__(self, folders, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Read-Only Folders")
        self._folders: tuple[str, ...] = tuple(folders)
        intro = QLabel(
            "Files in these folders, and below them, open read-only: they can be read, searched and "
            "copied, and saved elsewhere with Save As…, but not changed. Use it for Paratext projects "
            "that Paratext keeps in sync.",
            self,
        )
        intro.setWordWrap(True)
        self.list = QListWidget(self)
        self.add_button = QPushButton("Add Folder…", self)
        self.remove_button = QPushButton("Remove", self)
        self.add_button.clicked.connect(lambda _checked=False: self.add_folder())
        self.remove_button.clicked.connect(lambda _checked=False: self.remove_selected())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.list, 1)
        layout.addLayout(row)
        layout.addWidget(buttons)
        self.resize(520, 320)
        self._populate()

    def folders(self) -> tuple[str, ...]:
        return self._folders

    def add_folder(self, folder: str | None = None) -> None:
        if folder is None:
            folder = QFileDialog.getExistingDirectory(self, "Add Read-Only Folder")
        if folder:
            self._folders = with_folder(self._folders, folder, True)
            self._populate()

    def remove_selected(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self._folders):
            self._folders = self._folders[:row] + self._folders[row + 1 :]
            self._populate()

    def _populate(self) -> None:
        self.list.clear()
        self.list.addItems(list(self._folders))
        self.remove_button.setEnabled(bool(self._folders))


__all__ = ["ReadOnlyFoldersDialog"]
