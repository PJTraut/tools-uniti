"""Model-backed presentation for immutable regex capture reports."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from uniti.regex.captures import CaptureGroupRow, CaptureReport


_SEPARATOR = "─────────────────"


@dataclass(frozen=True, slots=True)
class _ReportRow:
    display: str
    label: str | None = None
    content: str | None = None


def _occurrence_suffix(count: int) -> str:
    if count <= 1:
        return ""
    return f" ({count:,} occurrences)"


def _format_group(row: CaptureGroupRow) -> _ReportRow:
    label = f"\\{row.number} :"
    if row.state == "not_matched":
        value = "not matched"
    else:
        value = " | ".join(
            f"empty at {preview.start:,}" if preview.empty else preview.text
            for preview in row.previews
        )
    if row.occurrence_count > len(row.previews):
        value += " …"
    content = f"{value}{_occurrence_suffix(row.occurrence_count)}"
    if row.name:
        content += f" [{row.name}]"
    return _ReportRow(f"{label} {content}", label, content)


class CaptureReportModel(QAbstractListModel):
    """Flatten bounded capture report records into accessible display rows."""

    LabelRole = int(Qt.ItemDataRole.UserRole) + 1
    ContentRole = int(Qt.ItemDataRole.UserRole) + 2

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: tuple[_ReportRow, ...] = ()
        self.current_index: int | None = None
        self.layout_revision = 0

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role in (
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.AccessibleTextRole,
        ):
            return row.display
        if role == self.LabelRole:
            return row.label
        if role == self.ContentRole:
            return row.content
        return None

    def rows(self) -> tuple[str, ...]:
        return tuple(row.display for row in self._rows)

    def roleNames(self):
        roles = super().roleNames()
        roles[self.LabelRole] = b"label"
        roles[self.ContentRole] = b"content"
        return roles

    def _reset(
        self,
        rows: tuple[_ReportRow, ...],
        current_index: int | None,
    ) -> None:
        self.beginResetModel()
        self._rows = rows
        self.current_index = current_index
        self.layout_revision += 1
        self.endResetModel()

    def set_loading(self) -> None:
        self._reset((_ReportRow("loading captures…"),), None)

    def set_report(self, report: CaptureReport) -> None:
        rows: list[_ReportRow] = []
        for position, match in enumerate(report.matches):
            if position:
                rows.append(_ReportRow(_SEPARATOR))
            rows.append(_ReportRow(f"Match {match.index + 1:,} of {match.total:,}"))
            if match.unavailable_reason is not None:
                rows.append(_ReportRow(match.unavailable_reason))
                continue
            rows.extend(
                _format_group(group)
                for group in match.groups
                if group.number != 0
            )
        self._reset(tuple(rows), report.request.requested_index)

    def clear(self) -> None:
        self._reset((), None)
