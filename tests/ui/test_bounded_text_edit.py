import importlib.util
import os

import pytest


def test_find_input_keeps_only_the_latest_fifty_user_edits():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from uniti.ui.regex_input import RegexInput

    app = QApplication.instance() or QApplication([])
    field = RegexInput()
    field.show()
    field.setFocus()
    QTest.keyClicks(field, "a" * 51)
    app.processEvents()

    for _ in range(50):
        assert field.undo_input() is True

    assert field.text() == "a"
    assert field.can_undo_input is False
    assert field.undo_input() is False
    field.close()


@pytest.mark.parametrize(
    "standard_key",
    ["ZoomIn", "ZoomOut"],
)
def test_zoom_shortcut_override_is_declined_not_claimed(standard_key: str):
    """BF-017: a bare QTextEdit claims the standard zoom key sequences for
    its own private font zoom via ShortcutOverride, which stops a
    higher-level QAction shortcut with the same sequence from ever firing
    while the field has focus. The field must decline (ignore) that
    override instead of accepting it."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent, QKeySequence
    from PySide6.QtWidgets import QApplication

    from uniti.ui.bounded_text_edit import BoundedSingleLineTextEdit

    app = QApplication.instance() or QApplication([])
    key_combination = QKeySequence(getattr(QKeySequence.StandardKey, standard_key))[0]
    field = BoundedSingleLineTextEdit()
    try:
        event = QKeyEvent(
            QEvent.Type.ShortcutOverride,
            key_combination.key(),
            key_combination.keyboardModifiers(),
        )

        result = field.event(event)

        assert result is True
        assert event.isAccepted() is False
    finally:
        field.close()


def test_find_and_replace_input_histories_are_independent():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from uniti.ui.regex_input import RegexInput, ReplacementInput

    app = QApplication.instance() or QApplication([])
    find = RegexInput()
    replace = ReplacementInput()
    find.show()
    replace.show()
    find.setFocus()
    QTest.keyClicks(find, "find")
    replace.setFocus()
    QTest.keyClicks(replace, "replace")
    app.processEvents()

    assert replace.undo_input() is True
    assert replace.text() == "replac"
    assert find.text() == "find"
    assert replace.redo_input() is True
    assert replace.text() == "replace"
    assert find.undo_input() is True
    assert find.text() == "fin"
    find.close()
    replace.close()


def test_input_history_round_trip_preserves_undo_redo_and_selection():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from uniti.ui.bounded_text_edit import BoundedSingleLineTextEdit

    app = QApplication.instance() or QApplication([])
    field = BoundedSingleLineTextEdit()
    field.show()
    field.setFocus()
    QTest.keyClicks(field, "alpha")
    QTest.keyClicks(field, " beta")
    assert field.undo_input()
    cursor = field.textCursor()
    cursor.setPosition(2)
    cursor.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
    field.setTextCursor(cursor)

    exported = field.export_history()
    restored = BoundedSingleLineTextEdit()
    restored.restore_history(exported)

    assert restored.export_history() == exported
    assert restored.textCursor().position() == 5
    assert restored.textCursor().anchor() == 2
    assert restored.can_undo_input is True
    assert restored.can_redo_input is True
    assert restored.redo_input() is True
    assert restored.text() == "alpha beta"
    field.close()
    restored.close()
    app.processEvents()
