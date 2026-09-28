import importlib.util
import os

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None, reason="PySide6 is not installed"
)


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_lists_only_fixed_pitch_fonts(app):
    """The editor's rendering pipeline (cell width, tab stops, whitespace-
    marker centering) assumes uniform character width -- a proportional
    font would silently violate that invariant, so it must never appear
    as a selectable choice."""

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontDatabase
    from uniti.ui.font_family_picker import FontFamilyPicker

    picker = FontFamilyPicker(None, default_family="Menlo")
    try:
        listed = {
            picker._list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(picker._list.count())
        }
        listed.discard(None)  # the "Default (...)" entry
        for family in listed:
            assert QFontDatabase.isFixedPitch(family)
        # Sanity: at least the well-known fixed-pitch macOS fonts made it in.
        assert "Courier New" in listed or "Menlo" in listed
        # And a widely-installed proportional font must be excluded.
        assert "Arial" not in listed
    finally:
        picker.close()


def test_default_entry_is_first_and_labeled_with_the_resolved_family(app):
    from PySide6.QtCore import Qt
    from uniti.ui.font_family_picker import FontFamilyPicker

    picker = FontFamilyPicker(None, default_family="Menlo")
    try:
        first = picker._list.item(0)
        assert first.data(Qt.ItemDataRole.UserRole) is None
        assert first.text() == "Default (Menlo)"
    finally:
        picker.close()


def test_current_family_is_preselected(app):
    from PySide6.QtCore import Qt
    from uniti.ui.font_family_picker import FontFamilyPicker

    picker = FontFamilyPicker("Courier New", default_family="Menlo")
    try:
        assert picker._list.currentItem().data(Qt.ItemDataRole.UserRole) == "Courier New"
    finally:
        picker.close()


def test_no_current_family_preselects_the_default_entry(app):
    from PySide6.QtCore import Qt
    from uniti.ui.font_family_picker import FontFamilyPicker

    picker = FontFamilyPicker(None, default_family="Menlo")
    try:
        current = picker._list.currentItem()
        assert current is not None
        assert current.data(Qt.ItemDataRole.UserRole) is None
    finally:
        picker.close()


def test_filter_hides_non_matching_families(app):
    from uniti.ui.font_family_picker import FontFamilyPicker

    picker = FontFamilyPicker(None, default_family="Menlo")
    try:
        picker._filter.setText("courier")
        visible = [
            picker._list.item(row).text()
            for row in range(picker._list.count())
            if not picker._list.item(row).isHidden()
        ]
        assert any("Courier" in text for text in visible)
        assert all(
            "courier" in text.lower() for text in visible
        )
    finally:
        picker.close()


def test_selected_family_reflects_the_highlighted_row(app):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    from uniti.ui.font_family_picker import FontFamilyPicker

    picker = FontFamilyPicker(None, default_family="Menlo")
    try:
        for row in range(picker._list.count()):
            item = picker._list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == "Courier New":
                picker._list.setCurrentItem(item)
                break
        assert isinstance(picker._list.currentItem(), QListWidgetItem)
        assert picker.selected_family() == "Courier New"
    finally:
        picker.close()
