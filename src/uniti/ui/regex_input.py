"""Syntax-aware miniature editors for regex and replacement expressions."""

from __future__ import annotations

from PySide6.QtGui import (
    QColor,
    QSyntaxHighlighter,
    QTextCharFormat,
)

from uniti.regex.lexer import tokenize_pattern, tokenize_replacement
from uniti.ui.bounded_text_edit import BoundedSingleLineTextEdit


def _format(color: str, *, bold: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(700)
    return fmt


_FORMATS = {
    "literal": _format("#d0d0d0"),
    "escape": _format("#57c7ff"),
    "unicode_property": _format("#c792ea"),
    "char_class": _format("#8bd49c"),
    "anchor": _format("#ff6b6b", bold=True),
    "quantifier": _format("#ffb86c", bold=True),
    "alternation": _format("#ff79c6", bold=True),
    "group_open": _format("#82aaff", bold=True),
    "group_close": _format("#82aaff", bold=True),
    "flag": _format("#b0bec5"),
    "backreference": _format("#c792ea", bold=True),
}
_INVALID_FORMAT = _format("#ff5555", bold=True)
_INVALID_FORMAT.setUnderlineColor(QColor("#ff5555"))
_INVALID_FORMAT.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)


class PatternHighlighter(QSyntaxHighlighter):
    def highlightBlock(self, text: str) -> None:
        for token in tokenize_pattern(text):
            fmt = _FORMATS.get(token.kind, _FORMATS["literal"])
            if not token.valid or token.kind == "invalid":
                fmt = _INVALID_FORMAT
            self.setFormat(token.start, token.end - token.start, fmt)


class ReplacementHighlighter(QSyntaxHighlighter):
    def __init__(self, document) -> None:
        super().__init__(document)
        self.group_count = 0
        self.group_names: dict[str, int] = {}

    def set_groups(self, group_count: int, group_names: dict[str, int]) -> None:
        self.group_count = group_count
        self.group_names = dict(group_names)
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        for token in tokenize_replacement(
            text,
            group_count=self.group_count,
            group_names=self.group_names,
        ):
            fmt = _FORMATS.get(token.kind, _FORMATS["literal"])
            if not token.valid or token.kind == "invalid":
                fmt = _INVALID_FORMAT
            self.setFormat(token.start, token.end - token.start, fmt)


class RegexInput(BoundedSingleLineTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.highlighter = PatternHighlighter(self.document())


class ReplacementInput(BoundedSingleLineTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.highlighter = ReplacementHighlighter(self.document())

    def set_groups(self, group_count: int, group_names: dict[str, int]) -> None:
        self.highlighter.set_groups(group_count, group_names)
