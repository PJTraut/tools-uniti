"""The opt-in list of a multi-file Replace All (book-lock plan L4, D2).

Replace All in a group or in all open documents first lists every file with
matches; only the ticked ones are changed, and a ticked locked book is
unlocked first. `choose` is the one question, so tests can replace it."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)


@dataclass(frozen=True, slots=True)
class FileRow:
    """One file with matches: what the list shows."""

    name: str
    detail: str
    count: int
    locked: bool = False
    read_only: bool = False


class ReplaceFilesDialog(QDialog):
    """Every file with matches, each with a checkbox, all unticked."""

    def __init__(self, rows: list[FileRow], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Replace All: Choose Files")
        self._rows = rows
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Tick the files to change. Nothing else is touched.", self))
        self.tree = QTreeWidget(self)
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels(["File", "Folder", "Matches"])
        for row in rows:
            item = QTreeWidgetItem([("🔒 " if row.locked else "") + row.name, row.detail, f"{row.count:,}"])
            flags = item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            if row.read_only:
                flags &= ~Qt.ItemFlag.ItemIsEnabled
                item.setToolTip(0, "In a read-only folder: it is never changed")
            item.setFlags(flags)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight)
            self.tree.addTopLevelItem(item)
        self.tree.itemChanged.connect(lambda *_: self._refresh())
        layout.addWidget(self.tree)
        self.note = QLabel(self)
        layout.addWidget(self.note)
        self.buttons = QDialogButtonBox(self)
        self.replace_button = self.buttons.addButton("Replace in Chosen Files", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.resize(640, 360)
        self._refresh()

    def chosen(self) -> set[int]:
        return {
            index
            for index in range(self.tree.topLevelItemCount())
            if self.tree.topLevelItem(index).checkState(0) == Qt.CheckState.Checked
        }

    def _refresh(self) -> None:
        chosen = self.chosen()
        locked = sum(1 for index in chosen if self._rows[index].locked)
        self.note.setText(f"{locked} locked book{'s' if locked != 1 else ''} will be unlocked" if locked else "")
        self.replace_button.setEnabled(bool(chosen))


def choose(parent, rows: list[FileRow]) -> set[int] | None:
    """The indexes of the rows the user ticked, or None when they cancel."""

    dialog = ReplaceFilesDialog(rows, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.chosen()
