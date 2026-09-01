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
