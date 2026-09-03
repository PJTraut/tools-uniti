"""Model-backed presentation for immutable regex capture reports."""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from uniti.regex.captures import CaptureGroupRow, CaptureReport


_SEPARATOR = "─────────────────"


def _occurrence_suffix(count: int) -> str:
    if count <= 1:
        return ""
    return f" ({count:,} occurrences)"


def _format_group(row: CaptureGroupRow) -> str:
    label = str(row.number)
    if row.name:
        label += f" {row.name}"
    if row.state == "not_matched":
        value = "not matched"
    else:
        value = " | ".join(
            f"empty at {preview.start:,}" if preview.empty else preview.text
            for preview in row.previews
        )
    if row.occurrence_count > len(row.previews):
        value += " …"
    return f"{label} │ {value}{_occurrence_suffix(row.occurrence_count)}"


class CaptureReportModel(QAbstractListModel):
    """Flatten bounded capture report records into accessible display rows."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: tuple[str, ...] = ()
        self.current_index: int | None = None

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if (
            index.isValid()
            and 0 <= index.row() < len(self._rows)
            and role
            in (
                Qt.ItemDataRole.DisplayRole,
                Qt.ItemDataRole.AccessibleTextRole,
            )
        ):
            return self._rows[index.row()]
        return None

    def rows(self) -> tuple[str, ...]:
        return self._rows

    def _reset(self, rows: tuple[str, ...], current_index: int | None) -> None:
        self.beginResetModel()
        self._rows = rows
        self.current_index = current_index
        self.endResetModel()

    def set_loading(self) -> None:
        self._reset(("loading captures…",), None)

    def set_report(self, report: CaptureReport) -> None:
        rows: list[str] = []
        for position, match in enumerate(report.matches):
            if position:
                rows.append(_SEPARATOR)
            rows.append(f"Match {match.index + 1:,} of {match.total:,}")
            if match.unavailable_reason is not None:
                rows.append(match.unavailable_reason)
                continue
            rows.extend(
                _format_group(group)
                for group in match.groups
                if group.number != 0
            )
        self._reset(tuple(rows), report.request.requested_index)

    def clear(self) -> None:
        self._reset((), None)
