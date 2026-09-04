import os
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QWidget

from uniti.app.editor_state import EditorState
from uniti.app.session import PaneRecord
from uniti.core.document import Document
from uniti.ui.panes import EditorPaneTree
from uniti.ui.text_view import UNITITextView


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def three_views(qapp, tmp_path: Path):
    path = tmp_path / "shared.txt"
    path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    document = Document.open(path, encoding="utf-8")
    views = tuple(
        UNITITextView(EditorState(document), view_id=f"view-{index}")
        for index in range(3)
    )
    yield document, views
    for view in views:
        try:
            view.setParent(None)
            view.dispose()
            view.deleteLater()
        except RuntimeError:
            pass
    qapp.processEvents()
    document.close()


def _leaf_count(record: PaneRecord) -> int:
    if record.kind == "leaf":
        return 1
    return sum(_leaf_count(child) for child in record.children)


def test_every_leaf_exposes_accessible_title_row_controls(qapp, three_views):
    _document, views = three_views
    tree = EditorPaneTree(pane_id="left")
    tree.add_view(views[0])

    controls = tree.first_leaf.controls

    assert controls.dock_button.accessibleName() == "Undock Document"
    assert controls.split_right_button.accessibleName() == "Split Right"
    assert controls.split_down_button.accessibleName() == "Split Down"
    assert controls.assign_button.accessibleName() == "Assign Document"
    tree.set_dock_mode(views[0].view_id, "dock")
    assert controls.dock_button.accessibleName() == "Dock Document"


def test_control_requests_use_stable_pane_and_view_ids(qapp, three_views):
    _document, views = three_views
    tree = EditorPaneTree(pane_id="left")
    tree.add_view(views[0])
    split = QSignalSpy(tree.splitRequested)
    dock = QSignalSpy(tree.dockToggleRequested)
    assignment = QSignalSpy(tree.assignmentRequested)

    tree.first_leaf.controls.split_right_button.click()
    tree.first_leaf.controls.dock_button.click()
    tree.first_leaf.controls.assign_button.click()

    assert tree.pane_ids == ("left",)
    assert tree.leaf("left") is tree.first_leaf
    assert list(split.at(0)) == ["left", Qt.Orientation.Horizontal]
    assert list(dock.at(0)) == [views[0].view_id]
    assert assignment.at(0)[0] == "left"
    assert isinstance(assignment.at(0)[1], QPoint)


def test_split_tree_round_trip_and_empty_leaf_collapse(qapp, three_views):
    _document, views = three_views
    tree = EditorPaneTree(pane_id="left")
    tree.add_view(views[0])
    right = tree.split_view(views[0].view_id, Qt.Orientation.Horizontal)
    tree.add_view(views[1], pane_id=right.pane_id)
    bottom = tree.split_view(views[1].view_id, Qt.Orientation.Vertical)
    tree.add_view(views[2], pane_id=bottom.pane_id)
    vertical_split_id = right.parent_split_id
    assert vertical_split_id is not None
    tree.set_split_proportions(vertical_split_id, (2, 3))

    record = tree.export_state()

    assert record.kind == "split"
    assert record.orientation == "horizontal"
    assert record.children[1].orientation == "vertical"
    assert record.children[1].proportions == pytest.approx((0.4, 0.6))
    assert _leaf_count(record) == 3

    tree.move_view(views[2].view_id, tree.first_leaf.pane_id)
    assert tree.close_leaf(bottom.pane_id)

    assert tree.leaf_count == 2
    assert tree.contains_view(views[2].view_id)
    assert tree.first_leaf.view_ids == (views[0].view_id, views[2].view_id)
    assert right.parent_split_id == record.pane_id


def test_tab_order_and_selected_tab_round_trip_through_shell(qapp, three_views):
    _document, views = three_views
    tree = EditorPaneTree(pane_id="tabs")
    for view in views:
        tree.add_view(view)
    tree.first_leaf.setCurrentIndex(1)
    record = tree.export_state()

    restored = EditorPaneTree()
    restored.restore_shell(record)

    assert restored.export_state() == record
    assert restored.first_leaf.view_ids == tuple(view.view_id for view in views)
    assert restored.first_leaf.selected_view_id == views[1].view_id
    assert restored.active_view is None

    restored_view, _title, _selected = tree.first_leaf.take_view(views[1].view_id)
    restored.add_view(restored_view)

    assert restored.first_leaf.view_ids == tuple(view.view_id for view in views)
    assert restored.active_view is views[1]


def test_shell_round_trip_preserves_an_explicitly_unselected_leaf(qapp):
    record = PaneRecord(
        "leaf",
        "unselected",
        view_ids=("view-a", "view-b"),
        selected_view_id=None,
    )
    tree = EditorPaneTree()

    tree.restore_shell(record)

    assert tree.export_state() == record


def test_leaf_removal_requires_empty_nonfinal_leaf(qapp, three_views):
    _document, views = three_views
    tree = EditorPaneTree(pane_id="only")
    assert not tree.close_leaf("only")

    tree.add_view(views[0])
    empty = tree.split_view(views[0].view_id, Qt.Orientation.Horizontal)
    assert not tree.close_leaf("only")
    assert tree.close_leaf(empty.pane_id)
    assert tree.leaf_count == 1
    assert tree.first_leaf.pane_id == "only"


def test_move_and_detach_preserve_the_view_and_document(qapp, three_views):
    document, views = three_views
    tree = EditorPaneTree(pane_id="source")
    tree.add_view(views[0])
    target = tree.split_view(views[0].view_id, Qt.Orientation.Horizontal)
    close_spy = QSignalSpy(tree.viewCloseRequested)
    detach_spy = QSignalSpy(tree.viewDetachRequested)

    tree.move_view(views[0].view_id, target.pane_id)
    tree.first_leaf.add_view(views[1])
    tree.first_leaf.tabCloseRequested.emit(0)
    tree.detach_view(views[0].view_id, QPoint(17, 23))

    assert tree.leaf_for_view(views[0].view_id) is target
    assert close_spy.count() == 1
    assert list(close_spy.at(0)) == [views[1].view_id]
    assert detach_spy.count() == 1
    assert detach_spy.at(0)[0] == views[0].view_id
    assert detach_spy.at(0)[1] == QPoint(17, 23)
    assert tree.contains_view(views[0].view_id)
    assert document.read(0, 5) == "alpha"


def test_split_proportions_must_be_positive_and_are_normalized(qapp, three_views):
    _document, views = three_views
    tree = EditorPaneTree()
    tree.add_view(views[0])
    new_leaf = tree.split_view(views[0].view_id, Qt.Orientation.Vertical)
    split_id = new_leaf.parent_split_id
    assert split_id is not None

    with pytest.raises(ValueError, match="positive"):
        tree.set_split_proportions(split_id, (1, 0))

    tree.set_split_proportions(split_id, (3, 1))
    assert tree.export_state().proportions == pytest.approx((0.75, 0.25))


def test_restore_shell_rejects_duplicate_pane_and_view_ids(qapp):
    duplicate_panes = PaneRecord(
        "split",
        "root",
        "horizontal",
        (0.5, 0.5),
        (PaneRecord("leaf", "same"), PaneRecord("leaf", "same")),
    )
    duplicate_views = PaneRecord(
        "split",
        "root",
        "horizontal",
        (0.5, 0.5),
        (
            PaneRecord("leaf", "left", view_ids=("view",)),
            PaneRecord("leaf", "right", view_ids=("view",)),
        ),
    )

    with pytest.raises(ValueError, match="duplicate pane"):
        EditorPaneTree().restore_shell(duplicate_panes)
    with pytest.raises(ValueError, match="duplicate view"):
        EditorPaneTree().restore_shell(duplicate_views)


def test_restore_shell_reapplies_structural_allocation_limits(qapp):
    too_many_views = PaneRecord(
        "leaf",
        "many-views",
        view_ids=tuple(f"view-{index}" for index in range(257)),
    )
    too_many_leaves = PaneRecord("leaf", "leaf-0")
    for index in range(1, 129):
        too_many_leaves = PaneRecord(
            "split",
            f"split-{index}",
            "horizontal",
            (0.5, 0.5),
            (too_many_leaves, PaneRecord("leaf", f"leaf-{index}")),
        )

    with pytest.raises(ValueError, match="256 views"):
        EditorPaneTree().restore_shell(too_many_views)
    with pytest.raises(ValueError, match="128 leaf panes"):
        EditorPaneTree().restore_shell(too_many_leaves)


def test_live_mutations_honor_the_persisted_layout_limits(qapp):
    class StubView(QWidget):
        def __init__(self, view_id: str):
            super().__init__()
            self.view_id = view_id

    maximum_views = PaneRecord(
        "leaf",
        "view-leaf",
        view_ids=tuple(f"view-{index}" for index in range(256)),
    )
    view_tree = EditorPaneTree()
    view_tree.restore_shell(maximum_views)
    with pytest.raises(ValueError, match="256 views"):
        view_tree.add_view(StubView("one-too-many"))

    maximum_leaves = PaneRecord(
        "leaf",
        "leaf-0",
        view_ids=("anchor",),
        selected_view_id="anchor",
    )
    for index in range(1, 128):
        maximum_leaves = PaneRecord(
            "split",
            f"split-{index}",
            "horizontal",
            (0.5, 0.5),
            (maximum_leaves, PaneRecord("leaf", f"leaf-{index}")),
        )
    leaf_tree = EditorPaneTree()
    leaf_tree.restore_shell(maximum_leaves)
    leaf_tree.add_view(StubView("anchor"))
    with pytest.raises(ValueError, match="128 leaf panes"):
        leaf_tree.split_view("anchor", Qt.Orientation.Horizontal)
