"""Binary editor split tree and detachable tab groups."""

from __future__ import annotations

from dataclasses import dataclass
import math
import uuid

from PySide6.QtCore import QPoint, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QSplitter,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from uniti.app.session import MAX_LEAF_PANES, MAX_VIEWS, PaneRecord


_PANE_ID_PROPERTY = "unitiPaneId"
_VIEW_ID_PROPERTY = "unitiViewId"


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty string")
    return value


class _ShellView(QWidget):
    """Lightweight tab restored before its document and real view exist."""

    def __init__(self, view_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.view_id = _identifier(view_id, "view ID")
        self.setProperty(_VIEW_ID_PROPERTY, self.view_id)


class _DetachableTabBar(QTabBar):
    detachRequested = Signal(str, QPoint)
    groupMenuRequested = Signal(str, QPoint)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pressed_view_id: str | None = None
        self._pressed_position = QPoint()
        self._dragging = False

    def contextMenuEvent(self, event) -> None:
        index = self.tabAt(event.pos())
        data = self.tabData(index) if index >= 0 else None
        if isinstance(data, str):
            self.groupMenuRequested.emit(data, event.globalPos())
            return
        super().contextMenuEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.tabAt(event.position().toPoint())
            data = self.tabData(index) if index >= 0 else None
            self._pressed_view_id = data if isinstance(data, str) else None
            self._pressed_position = event.position().toPoint()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._pressed_view_id is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (
                event.position().toPoint() - self._pressed_position
            ).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._dragging = True
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        view_id = self._pressed_view_id
        detach = (
            view_id is not None
            and self._dragging
            and not self.rect().contains(event.position().toPoint())
        )
        global_position = event.globalPosition().toPoint()
        self._pressed_view_id = None
        self._dragging = False
        super().mouseReleaseEvent(event)
        if detach:
            self.detachRequested.emit(view_id, global_position)


class PaneControlBar(QWidget):
    """Compact, accessible controls sharing a pane's native tab row."""

    splitRequested = Signal(Qt.Orientation)
    assignmentRequested = Signal(QPoint)
    dockToggleRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        self.dock_button = self._button("Undock Document", "↗")
        self.split_right_button = self._button("Split Right", "⇹")
        self.split_down_button = self._button("Split Down", "⇳")
        self.assign_button = self._button("Assign Document", "+")
        for button in (
            self.dock_button,
            self.split_right_button,
            self.split_down_button,
            self.assign_button,
        ):
            layout.addWidget(button)
        self.dock_button.clicked.connect(self.dockToggleRequested)
        self.split_right_button.clicked.connect(
            lambda: self.splitRequested.emit(Qt.Orientation.Horizontal)
        )
        self.split_down_button.clicked.connect(
            lambda: self.splitRequested.emit(Qt.Orientation.Vertical)
        )
        self.assign_button.clicked.connect(self._request_assignment)
        self.set_view_available(False)

    @staticmethod
    def _button(accessible_name: str, text: str) -> QToolButton:
        button = QToolButton()
        button.setAutoRaise(True)
        button.setText(text)
        button.setAccessibleName(accessible_name)
        button.setToolTip(accessible_name)
        return button

    def _request_assignment(self) -> None:
        position = self.assign_button.mapToGlobal(
            QPoint(0, self.assign_button.height())
        )
        self.assignmentRequested.emit(position)

    def set_view_available(self, available: bool) -> None:
        self.dock_button.setEnabled(available)
        self.split_right_button.setEnabled(available)
        self.split_down_button.setEnabled(available)

    def set_dock_mode(self, mode: str) -> None:
        labels = {"dock": "Dock Document", "undock": "Undock Document"}
        label = labels.get(mode, "Dock Document")
        self.dock_button.setEnabled(mode in labels)
        self.dock_button.setAccessibleName(label)
        self.dock_button.setToolTip(label)


class PaneLeaf(QTabWidget):
    """One tab group. It publishes intent and never owns document lifetime."""

    activeViewChanged = Signal(object)
    viewCloseRequested = Signal(str)
    viewDetachRequested = Signal(str, QPoint)
    splitRequested = Signal(str, Qt.Orientation)
    assignmentRequested = Signal(str, QPoint)
    dockToggleRequested = Signal(str)
    groupMenuRequested = Signal(str, QPoint)

    def __init__(
        self,
        pane_id: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.pane_id = _identifier(pane_id or uuid.uuid4().hex, "pane ID")
        self.setProperty(_PANE_ID_PROPERTY, self.pane_id)
        self._parent_branch: _SplitNode | None = None
        self._selection_suppressed = False
        self._dock_modes: dict[str, str] = {}
        tab_bar = _DetachableTabBar(self)
        self.setTabBar(tab_bar)
        self.controls = PaneControlBar(self)
        self.setCornerWidget(self.controls, Qt.Corner.TopRightCorner)
        self.setMovable(True)
        self.setTabsClosable(True)
        self.currentChanged.connect(self._publish_active_view)
        self.tabCloseRequested.connect(self._publish_close_request)
        tab_bar.detachRequested.connect(self.viewDetachRequested)
        tab_bar.groupMenuRequested.connect(self.groupMenuRequested)
        self.controls.splitRequested.connect(
            lambda orientation: self.splitRequested.emit(self.pane_id, orientation)
        )
        self.controls.assignmentRequested.connect(
            lambda position: self.assignmentRequested.emit(self.pane_id, position)
        )
        self.controls.dockToggleRequested.connect(self._publish_dock_request)

    @property
    def tabs(self) -> QTabWidget:
        return self

    @property
    def parent_split_id(self) -> str | None:
        parent = self._parent_branch
        return None if parent is None else parent.split_id

    @property
    def view_ids(self) -> tuple[str, ...]:
        return tuple(self._view_id_at(index) for index in range(self.count()))

    @property
    def selected_view_id(self) -> str | None:
        if self._selection_suppressed:
            return None
        index = self.currentIndex()
        return None if index < 0 else self._view_id_at(index)

    @property
    def active_view(self) -> QWidget | None:
        if self._selection_suppressed:
            return None
        widget = self.currentWidget()
        return None if isinstance(widget, _ShellView) else widget

    def _view_id_at(self, index: int) -> str:
        data = self.tabBar().tabData(index)
        if not isinstance(data, str) or not data:
            raise RuntimeError("pane tab has no stable view ID")
        return data

    def index_of(self, view_id: str) -> int:
        for index in range(self.count()):
            if self._view_id_at(index) == view_id:
                return index
        return -1

    def select_view(self, view_id: str) -> None:
        index = self.index_of(view_id)
        if index < 0:
            raise KeyError(view_id)
        unchanged = index == self.currentIndex()
        self._selection_suppressed = False
        self.setCurrentIndex(index)
        if unchanged:
            self._publish_active_view()

    def add_view(
        self,
        view: QWidget,
        *,
        index: int | None = None,
        select: bool = True,
        title: str | None = None,
    ) -> int:
        if not isinstance(view, QWidget):
            raise TypeError("view must be a QWidget")
        view_id = _identifier(getattr(view, "view_id", None), "view ID")
        if self.index_of(view_id) >= 0:
            raise ValueError(f"duplicate view ID: {view_id}")
        view.setProperty(_VIEW_ID_PROPERTY, view_id)
        position = self.count() if index is None else index
        if not 0 <= position <= self.count():
            raise IndexError("tab index is outside the pane")
        label = title or self._title_for(view, view_id)
        blocker = QSignalBlocker(self)
        inserted = self.insertTab(position, view, label)
        self.tabBar().setTabData(inserted, view_id)
        self._dock_modes[view_id] = "undock"
        if select:
            self._selection_suppressed = False
            self.setCurrentIndex(inserted)
        del blocker
        if select or self.count() == 1:
            self._publish_active_view()
        else:
            self._refresh_controls()
        return inserted

    def add_placeholder(
        self,
        view_id: str,
        *,
        select: bool = False,
    ) -> int:
        return self.add_view(
            _ShellView(view_id),
            select=select,
            title=view_id,
        )

    def replace_placeholder(self, view: QWidget) -> int:
        view_id = _identifier(getattr(view, "view_id", None), "view ID")
        index = self.index_of(view_id)
        if index < 0 or not isinstance(self.widget(index), _ShellView):
            raise ValueError(f"no shell placeholder for view ID: {view_id}")
        selected = self.selected_view_id == view_id
        placeholder = self.widget(index)
        self.removeTab(index)
        placeholder.deleteLater()
        return self.add_view(view, index=index, select=selected)

    def take_view(self, view_id: str) -> tuple[QWidget, str, bool]:
        index = self.index_of(view_id)
        if index < 0:
            raise KeyError(view_id)
        widget = self.widget(index)
        title = self.tabText(index)
        selected = index == self.currentIndex()
        self.removeTab(index)
        self._dock_modes.pop(view_id, None)
        widget.setParent(None)
        self._refresh_controls()
        return widget, title, selected

    def set_dock_mode(self, view_id: str, mode: str) -> None:
        if mode not in {"dock", "undock"}:
            raise ValueError("dock mode must be dock or undock")
        if self.index_of(view_id) < 0:
            raise KeyError(view_id)
        self._dock_modes[view_id] = mode
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        selected = self.selected_view_id
        available = selected is not None
        self.controls.set_view_available(available)
        self.controls.set_dock_mode(
            "" if selected is None else self._dock_modes.get(selected, "undock")
        )

    def _publish_dock_request(self) -> None:
        view_id = self.selected_view_id
        if view_id is not None:
            self.dockToggleRequested.emit(view_id)

    @staticmethod
    def _title_for(view: QWidget, view_id: str) -> str:
        document = getattr(view, "document", None)
        path = getattr(document, "path", None)
        name = getattr(path, "name", None)
        return name if isinstance(name, str) and name else view_id

    def _publish_active_view(self, _index: int = -1) -> None:
        self._selection_suppressed = False
        self._refresh_controls()
        self.activeViewChanged.emit(self.active_view)

    def suppress_selection(self) -> None:
        self._selection_suppressed = True
        self._refresh_controls()
        self.activeViewChanged.emit(None)

    def _publish_close_request(self, index: int) -> None:
        if 0 <= index < self.count():
            self.viewCloseRequested.emit(self._view_id_at(index))

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self._publish_active_view()


@dataclass(slots=True)
class _SplitNode:
    split_id: str
    orientation: Qt.Orientation
    widget: QSplitter
    children: list[PaneLeaf | _SplitNode]
    proportions: tuple[float, float]
    parent: _SplitNode | None = None


class EditorPaneTree(QWidget):
    """A binary tree of tab leaves that only moves existing view widgets."""

    activeViewChanged = Signal(object)
    viewSelected = Signal(str)
    viewCloseRequested = Signal(str)
    viewDetachRequested = Signal(str, QPoint)
    splitRequested = Signal(str, Qt.Orientation)
    assignmentRequested = Signal(str, QPoint)
    dockToggleRequested = Signal(str)
    groupMenuRequested = Signal(str, QPoint)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        pane_id: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._root: PaneLeaf | _SplitNode = self._make_leaf(pane_id)
        self._active_leaf = self._root
        self._layout.addWidget(self._root)

    def _make_leaf(self, pane_id: str | None = None) -> PaneLeaf:
        leaf = PaneLeaf(pane_id)
        leaf.activeViewChanged.connect(
            lambda view, current=leaf: self._on_leaf_active(current, view)
        )
        leaf.viewCloseRequested.connect(self.viewCloseRequested)
        leaf.viewDetachRequested.connect(self.viewDetachRequested)
        leaf.splitRequested.connect(self.splitRequested)
        leaf.assignmentRequested.connect(self.assignmentRequested)
        leaf.dockToggleRequested.connect(self.dockToggleRequested)
        leaf.groupMenuRequested.connect(self.groupMenuRequested)
        return leaf

    def _make_split(
        self,
        orientation: Qt.Orientation,
        first: PaneLeaf | _SplitNode,
        second: PaneLeaf | _SplitNode,
        *,
        split_id: str | None = None,
        proportions: tuple[float, float] = (0.5, 0.5),
    ) -> _SplitNode:
        widget = QSplitter(orientation)
        node = _SplitNode(
            _identifier(split_id or uuid.uuid4().hex, "split ID"),
            orientation,
            widget,
            [first, second],
            proportions,
        )
        self._set_parent(first, node)
        self._set_parent(second, node)
        widget.addWidget(self._widget(first))
        widget.addWidget(self._widget(second))
        widget.setSizes([max(1, round(value * 10_000)) for value in proportions])
        widget.splitterMoved.connect(lambda _position, _index: self._sync_sizes(node))
        return node

    @staticmethod
    def _widget(node: PaneLeaf | _SplitNode) -> QWidget:
        return node if isinstance(node, PaneLeaf) else node.widget

    @staticmethod
    def _set_parent(
        node: PaneLeaf | _SplitNode,
        parent: _SplitNode | None,
    ) -> None:
        if isinstance(node, PaneLeaf):
            node._parent_branch = parent
        else:
            node.parent = parent

    def _leaves(
        self,
        node: PaneLeaf | _SplitNode | None = None,
    ) -> tuple[PaneLeaf, ...]:
        current = self._root if node is None else node
        if isinstance(current, PaneLeaf):
            return (current,)
        return self._leaves(current.children[0]) + self._leaves(current.children[1])

    @property
    def first_leaf(self) -> PaneLeaf:
        return self._leaves()[0]

    @property
    def active_leaf(self) -> PaneLeaf:
        return self._active_leaf

    @property
    def leaf_count(self) -> int:
        return len(self._leaves())

    @property
    def view_ids(self) -> tuple[str, ...]:
        return tuple(view_id for leaf in self._leaves() for view_id in leaf.view_ids)

    @property
    def pane_ids(self) -> tuple[str, ...]:
        return tuple(leaf.pane_id for leaf in self._leaves())

    @property
    def active_view(self) -> QWidget | None:
        return self._active_leaf.active_view

    def contains_view(self, view_id: str) -> bool:
        return self.leaf_for_view(view_id) is not None

    def leaf_for_view(self, view_id: str) -> PaneLeaf | None:
        for leaf in self._leaves():
            if leaf.index_of(view_id) >= 0:
                return leaf
        return None

    def activate_view(self, view_id: str) -> None:
        if self.leaf_for_view(view_id) is None:
            raise KeyError(view_id)
        self._activate_view(view_id)

    def remove_shell_view(self, view_id: str) -> None:
        """Remove one unresolved session placeholder without document effects."""

        leaf = self.leaf_for_view(view_id)
        if leaf is None:
            raise KeyError(view_id)
        widget = leaf.widget(leaf.index_of(view_id))
        if not isinstance(widget, _ShellView):
            raise ValueError("only a session shell placeholder can be removed")
        leaf.take_view(view_id)
        widget.deleteLater()
        if leaf.count() == 0 and self.leaf_count > 1:
            self.close_leaf(leaf.pane_id)

    def _leaf(self, pane_id: str) -> PaneLeaf:
        return self.leaf(pane_id)

    def leaf(self, pane_id: str) -> PaneLeaf:
        for leaf in self._leaves():
            if leaf.pane_id == pane_id:
                return leaf
        raise KeyError(pane_id)

    def set_dock_mode(self, view_id: str, mode: str) -> None:
        leaf = self.leaf_for_view(view_id)
        if leaf is None:
            raise KeyError(view_id)
        leaf.set_dock_mode(view_id, mode)

    def add_view(
        self,
        view: QWidget,
        *,
        pane_id: str | None = None,
        index: int | None = None,
        select: bool = True,
        title: str | None = None,
    ) -> PaneLeaf:
        view_id = _identifier(getattr(view, "view_id", None), "view ID")
        existing = self.leaf_for_view(view_id)
        if existing is not None:
            existing_widget = existing.widget(existing.index_of(view_id))
            if not isinstance(existing_widget, _ShellView):
                raise ValueError(f"duplicate view ID: {view_id}")
            if pane_id is not None and existing.pane_id != pane_id:
                raise ValueError("view placeholder belongs to another pane")
            existing.replace_placeholder(view)
            self._connect_view_focus(view)
            if select:
                existing.select_view(view_id)
            return existing
        if len(self.view_ids) >= MAX_VIEWS:
            raise ValueError(f"pane tree cannot exceed {MAX_VIEWS} views")
        leaf = self._active_leaf if pane_id is None else self._leaf(pane_id)
        leaf.add_view(view, index=index, select=select, title=title)
        self._connect_view_focus(view)
        return leaf

    def _connect_view_focus(self, view: QWidget) -> None:
        signal = getattr(view, "viewFocused", None)
        if signal is not None:
            previous = getattr(view, "_uniti_pane_focus_callback", None)
            if previous is not None:
                try:
                    signal.disconnect(previous)
                except RuntimeError:
                    pass
            callback = lambda view_id: self._activate_view(view_id)
            signal.connect(callback)
            view._uniti_pane_focus_callback = callback

    def _activate_view(self, view_id: str) -> None:
        leaf = self.leaf_for_view(view_id)
        if leaf is None:
            return
        leaf.select_view(view_id)

    def _on_leaf_active(self, leaf: PaneLeaf, view: QWidget | None) -> None:
        self._active_leaf = leaf
        selected = leaf.selected_view_id
        if selected is not None:
            self.viewSelected.emit(selected)
        self.activeViewChanged.emit(view)

    def split_view(
        self,
        view_id: str,
        orientation: Qt.Orientation,
    ) -> PaneLeaf:
        if orientation not in (
            Qt.Orientation.Horizontal,
            Qt.Orientation.Vertical,
        ):
            raise ValueError("split orientation must be horizontal or vertical")
        leaf = self.leaf_for_view(view_id)
        if leaf is None:
            raise KeyError(view_id)
        if self.leaf_count >= MAX_LEAF_PANES:
            raise ValueError(
                f"pane tree cannot exceed {MAX_LEAF_PANES} leaf panes"
            )
        new_leaf = self._make_leaf()
        parent = leaf._parent_branch
        if parent is None:
            self._layout.removeWidget(leaf)
            leaf.setParent(None)
            branch = self._make_split(orientation, leaf, new_leaf)
            self._root = branch
            self._layout.addWidget(branch.widget)
        else:
            index = parent.children.index(leaf)
            leaf.setParent(None)
            branch = self._make_split(orientation, leaf, new_leaf)
            branch.parent = parent
            parent.children[index] = branch
            parent.widget.insertWidget(index, branch.widget)
        self._active_leaf = new_leaf
        self.activeViewChanged.emit(None)
        return new_leaf

    def close_leaf(self, pane_id: str) -> bool:
        leaf = self._leaf(pane_id)
        parent = leaf._parent_branch
        if parent is None or leaf.count() != 0:
            return False
        sibling = parent.children[1 - parent.children.index(leaf)]
        grandparent = parent.parent
        sibling_widget = self._widget(sibling)
        sibling_widget.setParent(None)
        parent.widget.setParent(None)
        self._set_parent(sibling, grandparent)
        if grandparent is None:
            self._root = sibling
            self._layout.addWidget(sibling_widget)
        else:
            index = grandparent.children.index(parent)
            grandparent.children[index] = sibling
            grandparent.widget.insertWidget(index, sibling_widget)
        if self._active_leaf is leaf:
            self._active_leaf = self._leaves(sibling)[0]
            self.activeViewChanged.emit(self._active_leaf.active_view)
        parent.widget.deleteLater()
        return True

    def move_view(
        self,
        view_id: str,
        pane_id: str,
        *,
        index: int | None = None,
    ) -> PaneLeaf:
        source = self.leaf_for_view(view_id)
        if source is None:
            raise KeyError(view_id)
        target = self._leaf(pane_id)
        if source is target:
            current = source.index_of(view_id)
            destination = source.count() - 1 if index is None else index
            if not 0 <= destination < source.count():
                raise IndexError("tab index is outside the pane")
            source.tabBar().moveTab(current, destination)
            source.setCurrentIndex(destination)
            return source
        widget, title, _selected = source.take_view(view_id)
        target.add_view(widget, index=index, select=True, title=title)
        self._active_leaf = target
        return target

    def detach_view(self, view_id: str, global_position: QPoint) -> None:
        if self.leaf_for_view(view_id) is None:
            raise KeyError(view_id)
        if not isinstance(global_position, QPoint):
            raise TypeError("global_position must be a QPoint")
        self.viewDetachRequested.emit(view_id, global_position)

    def _split(self, split_id: str) -> _SplitNode:
        def visit(node: PaneLeaf | _SplitNode) -> _SplitNode | None:
            if isinstance(node, PaneLeaf):
                return None
            if node.split_id == split_id:
                return node
            return visit(node.children[0]) or visit(node.children[1])

        found = visit(self._root)
        if found is None:
            raise KeyError(split_id)
        return found

    def set_split_proportions(
        self,
        split_id: str,
        proportions: tuple[float, float],
    ) -> None:
        if not isinstance(proportions, tuple) or len(proportions) != 2:
            raise ValueError("split proportions must contain two values")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
            for value in proportions
        ):
            raise ValueError("split proportions must be positive finite values")
        total = float(sum(proportions))
        normalized = (float(proportions[0]) / total, float(proportions[1]) / total)
        node = self._split(split_id)
        node.proportions = normalized
        node.widget.setSizes(
            [max(1, round(value * 10_000)) for value in normalized]
        )

    @staticmethod
    def _sync_sizes(node: _SplitNode) -> None:
        sizes = node.widget.sizes()
        if len(sizes) != 2 or any(size <= 0 for size in sizes):
            return
        total = sum(sizes)
        node.proportions = (sizes[0] / total, sizes[1] / total)

    def export_state(self) -> PaneRecord:
        def export(node: PaneLeaf | _SplitNode) -> PaneRecord:
            if isinstance(node, PaneLeaf):
                return PaneRecord(
                    "leaf",
                    node.pane_id,
                    view_ids=node.view_ids,
                    selected_view_id=node.selected_view_id,
                )
            orientation = (
                "horizontal"
                if node.orientation == Qt.Orientation.Horizontal
                else "vertical"
            )
            return PaneRecord(
                "split",
                node.split_id,
                orientation,
                node.proportions,
                tuple(export(child) for child in node.children),
            )

        return export(self._root)

    def restore_shell(self, record: PaneRecord) -> None:
        if not isinstance(record, PaneRecord):
            raise TypeError("record must be a PaneRecord")
        if any(
            not isinstance(leaf.widget(index), _ShellView)
            for leaf in self._leaves()
            for index in range(leaf.count())
        ):
            raise ValueError("cannot replace a pane tree containing live views")
        pane_ids: set[str] = set()
        view_ids: set[str] = set()
        leaf_count = 0
        pending = [(record, 1)]
        while pending:
            node, depth = pending.pop()
            if depth > MAX_LEAF_PANES * 2:
                raise ValueError("pane tree is too deep")
            if node.pane_id in pane_ids:
                raise ValueError(f"duplicate pane ID: {node.pane_id}")
            pane_ids.add(node.pane_id)
            if node.kind == "leaf":
                leaf_count += 1
                if leaf_count > MAX_LEAF_PANES:
                    raise ValueError(
                        f"pane tree exceeds {MAX_LEAF_PANES} leaf panes"
                    )
            for view_id in node.view_ids:
                if view_id in view_ids:
                    raise ValueError(f"duplicate view ID: {view_id}")
                view_ids.add(view_id)
                if len(view_ids) > MAX_VIEWS:
                    raise ValueError(f"pane tree exceeds {MAX_VIEWS} views")
            pending.extend((child, depth + 1) for child in node.children)

        def restore(node: PaneRecord) -> PaneLeaf | _SplitNode:
            if node.kind == "leaf":
                leaf = self._make_leaf(node.pane_id)
                for view_id in node.view_ids:
                    leaf.add_placeholder(
                        view_id,
                        select=view_id == node.selected_view_id,
                    )
                if node.selected_view_id is None:
                    leaf.suppress_selection()
                return leaf
            orientation = (
                Qt.Orientation.Horizontal
                if node.orientation == "horizontal"
                else Qt.Orientation.Vertical
            )
            assert node.proportions is not None
            first = restore(node.children[0])
            second = restore(node.children[1])
            return self._make_split(
                orientation,
                first,
                second,
                split_id=node.pane_id,
                proportions=node.proportions,
            )

        old_widget = self._widget(self._root)
        self._layout.removeWidget(old_widget)
        old_widget.setParent(None)
        self._root = restore(record)
        self._set_parent(self._root, None)
        self._layout.addWidget(self._widget(self._root))
        self._active_leaf = self.first_leaf
        old_widget.deleteLater()
        self.activeViewChanged.emit(None)
