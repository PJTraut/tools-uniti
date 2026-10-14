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
        # Sanity: a well-known fixed-pitch font of this platform made it in
        # (macOS, Windows, or a Linux runner's DejaVu/Liberation).
        assert listed & {"Menlo", "Courier New", "Consolas", "DejaVu Sans Mono", "Liberation Mono"}
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

    from PySide6.QtGui import QFontDatabase

    # A fixed-pitch family this platform has (Linux runners lack Courier New).
    family = next(
        name
        for name in ("Courier New", "Menlo", "Consolas", "DejaVu Sans Mono", "Liberation Mono")
        if name in QFontDatabase.families() and QFontDatabase.isFixedPitch(name)
    )
    picker = FontFamilyPicker(family, default_family="Menlo")
    try:
        assert picker._list.currentItem().data(Qt.ItemDataRole.UserRole) == family
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
        # Filter on a family this platform lists (row 0 is "Default (...)").
        word = picker._list.item(1).text().split()[0]
        picker._filter.setText(word.lower())
        visible = [
            picker._list.item(row).text()
            for row in range(picker._list.count())
            if not picker._list.item(row).isHidden()
        ]
        assert any(word in text for text in visible)
        assert all(word.lower() in text.lower() for text in visible)
    finally:
        picker.close()


def test_selected_family_reflects_the_highlighted_row(app):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    from uniti.ui.font_family_picker import FontFamilyPicker

    picker = FontFamilyPicker(None, default_family="Menlo")
    try:
        # The first real family listed (row 0 is "Default (...)"), whatever
        # this platform has.
        item = picker._list.item(1)
        family = item.data(Qt.ItemDataRole.UserRole)
        picker._list.setCurrentItem(item)
        assert isinstance(picker._list.currentItem(), QListWidgetItem)
        assert family and picker.selected_family() == family
    finally:
        picker.close()
