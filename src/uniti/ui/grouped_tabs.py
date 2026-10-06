"""BF-082 grouped tab bar (opt-in: View > Grouped Tabs).

Implements the interaction model agreed on 2026-09-22, per split (`PaneLeaf`):

1. **Group slots** — one button per document group with files open in this
   split, plus an unnamed/uncolored **Ungrouped** slot. Clicking a slot
   always opens a dropdown of that group's files; picking one makes it the
   active ("top") file.
2. **Recent strip** — the split's own tab bar, showing only the last
   `RECENT_LIMIT` individually-active files (plus the current one) as
   ordinary flat tabs, independent of grouping; a file can be both there
   and in its group's dropdown.
3. Ungrouped files use the same slot/dropdown mechanic as real groups.
4. No `[<][>]` paging control (dropped in the 2026-09-22 refinement).
5. Drag along the strip reorders and dragging a tab off it detaches that
   file into a new window (the existing `_DetachableTabBar` behavior);
   dragging a *group slot* off the bar moves the whole group, in this
   split, into one new window (`UNITIService.undock_views`).

Built on the existing `QTabWidget` model instead of replacing it: every tab
still exists (hidden tabs are `setTabVisible(False)`), so session capture,
Find/Replace, splits and detach keep working exactly as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QIcon, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMenu, QTabBar, QToolButton, QWidget

if TYPE_CHECKING:
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.panes import PaneLeaf

RECENT_LIMIT = 5
_SAVED_ELIDE = "unitiUngroupedElideMode"
UNGROUPED = ""


class GroupSlotButton(QToolButton):
    """A group slot: click opens its file dropdown; dragging it off the bar
    detaches the whole group (refinement 5's group half)."""

    detachRequested = Signal(str)

    def __init__(self, group_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.group_id = group_id
        self._press: QPoint | None = None
        self._dragging = False

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            self._dragging = False
            self.setDown(True)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            self._press is not None
            and (event.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance()
        ):
            self._dragging = True
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._press is None:
            super().mouseReleaseEvent(event)
            return
        self.setDown(False)
        dragging, self._press, self._dragging = self._dragging, None, False
        bar = self.parentWidget()
        inside_bar = bar is not None and bar.rect().contains(self.mapTo(bar, event.position().toPoint()))
        if dragging and not inside_bar:
            self.detachRequested.emit(self.group_id)
        elif self.menu() is not None:
            self.showMenu()
        event.accept()


class GroupSlotBar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("groupSlotBar")
        self.slot_layout = QHBoxLayout(self)
        self.slot_layout.setContentsMargins(2, 0, 6, 0)
        self.slot_layout.setSpacing(2)
        self.buttons: dict[str, QToolButton] = {}

    def clear(self) -> None:
        while self.slot_layout.count():
            item = self.slot_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.buttons = {}


class GroupedTabsController:
    def __init__(self, window: "UNITIMainWindow") -> None:
        self._window = window
        self._recent: dict[str, list[str]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self._window._settings.grouped_tabs)

    def set_enabled(self, enabled: bool) -> None:
        from dataclasses import replace

        window = self._window
        window._settings = replace(window._settings, grouped_tabs=bool(enabled))
        window._save_settings()
        self.refresh_all()

    # --- model --------------------------------------------------------------

    def _group_of(self, view_id: str) -> str:
        service = self._window._service
        if service is None:
            return UNGROUPED
        entry = service.documents.entry_for_view(view_id)
        if entry is None or entry.group_id is None:
            return UNGROUPED
        return entry.group_id if self._window._group_by_id(entry.group_id) is not None else UNGROUPED

    def slots_for(self, leaf: "PaneLeaf") -> list[tuple[str, list[str]]]:
        """[(group id or UNGROUPED, [view ids in tab order])], groups in the
        window's group order, Ungrouped last."""

        members: dict[str, list[str]] = {}
        for view_id in leaf.view_ids:
            members.setdefault(self._group_of(view_id), []).append(view_id)
        ordered = [group.id for group in self._window._groups if group.id in members]
        if UNGROUPED in members:
            ordered.append(UNGROUPED)
        return [(group_id, members[group_id]) for group_id in ordered]

    def recent_for(self, leaf: "PaneLeaf") -> list[str]:
        present = set(leaf.view_ids)
        recent = [view_id for view_id in self._recent.get(leaf.pane_id, []) if view_id in present]
        self._recent[leaf.pane_id] = recent
        return recent

    def note_active(self, view_id: str | None) -> None:
        if view_id is None:
            return
        leaf = self._window._panes.leaf_for_view(view_id)
        if leaf is None:
            return
        recent = [item for item in self._recent.get(leaf.pane_id, []) if item != view_id]
        recent.insert(0, view_id)
        self._recent[leaf.pane_id] = recent[:RECENT_LIMIT]
        if self.enabled:
            self.refresh_leaf(leaf)

    # --- presentation -----------------------------------------------------------

    def refresh_all(self) -> None:
        panes = self._window._panes
        for pane_id in panes.pane_ids:
            self.refresh_leaf(panes.leaf(pane_id))

    def refresh_leaf(self, leaf: "PaneLeaf") -> None:
        tab_bar = leaf.tabBar()
        if not self.enabled:
            for index in range(leaf.count()):
                tab_bar.setTabVisible(index, True)
            bar = leaf.cornerWidget(Qt.Corner.TopLeftCorner)
            if isinstance(bar, GroupSlotBar):
                leaf.setCornerWidget(None, Qt.Corner.TopLeftCorner)
                bar.deleteLater()
            saved = tab_bar.property(_SAVED_ELIDE)
            if saved is not None:
                tab_bar.setElideMode(Qt.TextElideMode(saved))
                tab_bar.setProperty(_SAVED_ELIDE, None)
            return
        if tab_bar.property(_SAVED_ELIDE) is None:
            tab_bar.setProperty(_SAVED_ELIDE, tab_bar.elideMode().value)
        # "Show longer part of filenames": full names, scrolling on overflow.
        tab_bar.setElideMode(Qt.TextElideMode.ElideNone)
        tab_bar.setUsesScrollButtons(True)
        selected = leaf.selected_view_id
        visible = set(self.recent_for(leaf))
        if selected is not None:
            visible.add(selected)
        if not visible and leaf.count():
            visible.add(leaf.view_ids[0])
        for index, view_id in enumerate(leaf.view_ids):
            tab_bar.setTabVisible(index, view_id in visible)
        bar = leaf.cornerWidget(Qt.Corner.TopLeftCorner)
        if not isinstance(bar, GroupSlotBar):
            bar = GroupSlotBar(leaf)
            leaf.setCornerWidget(bar, Qt.Corner.TopLeftCorner)
        self._populate_slots(bar, leaf, selected)
        bar.adjustSize()
        bar.show()
        # QTabWidget lays out its corner widgets only on set/resize, and
        # skips hidden ones; with the bar now visible at its new size, a
        # synthetic resize makes it reserve the space.
        QApplication.sendEvent(leaf, QResizeEvent(leaf.size(), leaf.size()))

    def _populate_slots(self, bar: GroupSlotBar, leaf: "PaneLeaf", selected: str | None) -> None:
        bar.clear()
        helpers = self._window._groups_and_recent_files
        for group_id, view_ids in self.slots_for(leaf):
            group = self._window._group_by_id(group_id) if group_id else None
            button = GroupSlotButton(group_id, bar)
            button.detachRequested.connect(lambda group_id, leaf=leaf: self.detach_group(leaf, group_id))
            name = group.name if group is not None else "Ungrouped"
            button.setText(f"{name} ({len(view_ids)})")
            button.setToolTip(f"{name}: click to choose a file; drag off the bar to move the group to a new window")
            button.setIcon(helpers._group_swatch_icon(group.color) if group is not None else QIcon())
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setCheckable(True)
            button.setChecked(selected in view_ids)
            menu = QMenu(button)
            for view_id in view_ids:
                index = leaf.index_of(view_id)
                action = menu.addAction(leaf.tabText(index))
                action.setCheckable(True)
                action.setChecked(view_id == selected)
                action.triggered.connect(lambda _checked=False, view_id=view_id: self.bring_to_front(view_id))
            button.setMenu(menu)
            bar.slot_layout.addWidget(button)
            button.show()
            bar.buttons[group_id] = button

    def detach_group(self, leaf: "PaneLeaf", group_id: str):
        """Move every file of `group_id` in this split into one new window."""

        service = self._window._service
        if service is None:
            return None
        view_ids = next((ids for slot, ids in self.slots_for(leaf) if slot == group_id), [])
        if not view_ids:
            return None
        return service.undock_views(view_ids)

    def bring_to_front(self, view_id: str) -> None:
        """A dropdown pick: make `view_id` the split's active, top file."""

        self._window.panes.activate_view(view_id)
        self.note_active(view_id)


def visible_tab_texts(leaf: "PaneLeaf") -> list[str]:
    tab_bar: QTabBar = leaf.tabBar()
    return [leaf.tabText(index) for index in range(leaf.count()) if tab_bar.isTabVisible(index)]


__all__ = ["GroupSlotBar", "GroupedTabsController", "RECENT_LIMIT", "UNGROUPED", "visible_tab_texts"]
