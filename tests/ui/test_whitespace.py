from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("character", "label"),
    (
        ("\u00a0", "NBSP"),
        ("\u202f", "NNBSP"),
        ("\u200b", "ZWSP"),
        ("\u200c", "ZWNJ"),
        ("\u200d", "ZWJ"),
        ("\u2060", "WJ"),
        ("\ufeff", "BOM"),
        ("\u2066", "U+2066"),
    ),
)
def test_invisible_unicode_labels_are_deterministic(character: str, label: str):
    from uniti.ui.whitespace import (
        WhitespaceKind,
        WhitespaceMarker,
        WhitespaceMode,
        iter_character_markers,
    )

    markers = tuple(
        iter_character_markers(character, WhitespaceMode.INVISIBLE_UNICODE)
    )

    assert markers == (WhitespaceMarker(0, WhitespaceKind.INVISIBLE, label),)


def test_whitespace_modes_classify_only_their_exact_character_sets():
    from uniti.ui.whitespace import (
        WhitespaceKind,
        WhitespaceMarker,
        WhitespaceMode,
        iter_character_markers,
        shows_eol,
    )

    text = " \t\u00a0\u200b\n"
    expected_ascii = (
        WhitespaceMarker(0, WhitespaceKind.SPACE, "SPACE"),
        WhitespaceMarker(1, WhitespaceKind.TAB, "TAB"),
    )
    expected_unicode = (
        WhitespaceMarker(2, WhitespaceKind.INVISIBLE, "NBSP"),
        WhitespaceMarker(3, WhitespaceKind.INVISIBLE, "ZWSP"),
    )

    assert tuple(iter_character_markers(text, WhitespaceMode.OFF)) == ()
    assert tuple(iter_character_markers(text, WhitespaceMode.EOL)) == ()
    assert tuple(
        iter_character_markers(text, WhitespaceMode.SPACES_TABS)
    ) == expected_ascii
    assert tuple(
        iter_character_markers(text, WhitespaceMode.INVISIBLE_UNICODE)
    ) == expected_unicode
    assert tuple(iter_character_markers(text, WhitespaceMode.ALL)) == (
        expected_ascii + expected_unicode
    )
    assert shows_eol(WhitespaceMode.OFF) is False
    assert shows_eol(WhitespaceMode.SPACES_TABS) is False
    assert shows_eol(WhitespaceMode.INVISIBLE_UNICODE) is False
    assert shows_eol(WhitespaceMode.EOL) is True
    assert shows_eol(WhitespaceMode.ALL) is True


def test_whitespace_mode_parser_is_strict_and_module_is_qt_free():
    from uniti.ui.whitespace import WhitespaceMode, parse_whitespace_mode

    assert parse_whitespace_mode(WhitespaceMode.ALL) is WhitespaceMode.ALL
    assert parse_whitespace_mode("spaces_tabs") is WhitespaceMode.SPACES_TABS
    with pytest.raises(ValueError, match="whitespace mode"):
        parse_whitespace_mode("everything")
    with pytest.raises(TypeError, match="whitespace mode"):
        parse_whitespace_mode(None)

    source = Path("src/uniti/ui/whitespace.py").read_text(encoding="utf-8")
    assert "PySide6" not in source
    assert "PyQt" not in source
