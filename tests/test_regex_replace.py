from pathlib import Path

from uniti.core.document import Document
from uniti.regex.engine import compile_pattern
from uniti.regex.replace import collect_replacements, replace_all
from uniti.regex.search import SearchOptions


def test_collect_replacements_uses_engine_expand_for_named_groups(tmp_path: Path):
    path = tmp_path / "replace.txt"
    path.write_text("Smith, Pieter\nJones, Sam", encoding="utf-8")
    pattern = compile_pattern(r"(?P<last>\w+),\s+(?P<first>\w+)")
    with Document.open(path) as doc:
        replacements = collect_replacements(
            doc,
            pattern,
            r"\g<first> \g<last>",
            options=SearchOptions(window_chars=8),
        )
    assert [(r.start, r.end, r.text) for r in replacements] == [
        (0, 13, "Pieter Smith"),
        (14, 24, "Sam Jones"),
    ]


def test_replace_all_is_single_undo_step(tmp_path: Path):
    path = tmp_path / "replace-all.txt"
    path.write_text("x1 x22 x333", encoding="utf-8")
    with Document.open(path) as doc:
        count = replace_all(doc, compile_pattern(r"x(\d+)"), r"[\1]")
        assert count == 3
        assert doc.read(0, doc.total_chars()) == "[1] [22] [333]"
        doc.undo()
        assert doc.read(0, doc.total_chars()) == "x1 x22 x333"
        doc.redo()
        assert doc.read(0, doc.total_chars()) == "[1] [22] [333]"
