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


def test_collect_replacements_leaves_group_zero_repetition_and_escapes_to_expand(
    tmp_path: Path,
):
    path = tmp_path / "expand.txt"
    path.write_text("abc", encoding="utf-8")
    pattern = compile_pattern(r"(?P<item>[a-z])+")

    with Document.open(path) as doc:
        replacements = collect_replacements(
            doc,
            pattern,
            r"\g<0>:\g<item>:\\",
        )

    assert [replacement.text for replacement in replacements] == ["abc:c:\\"]


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


def test_stream_replace_to_file_handles_many_matches_without_mutating_document(tmp_path: Path):
    from uniti.regex.replace import stream_replace_to_file

    path = tmp_path / "stream-source.txt"
    target = tmp_path / "stream-target.txt"
    path.write_text(("x1\n" * 20_000) + "end", encoding="utf-8")
    with Document.open(path) as doc:
        result = stream_replace_to_file(
            doc,
            compile_pattern(r"x(\d+)"),
            r"[\1]",
            target,
            options=SearchOptions(window_chars=127),
        )
        assert result.count == 20_000
        assert not doc.modified
        assert not doc.can_undo
        assert doc.read(0, 3) == "x1\n"
    with target.open("r", encoding="utf-8") as handle:
        assert handle.read(8) == "[1]\n[1]\n"
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(size - 3)
        assert handle.read() == "end"


def test_stream_replace_to_file_applies_output_encoding_and_eol(tmp_path: Path):
    from uniti.regex.replace import stream_replace_to_file

    path = tmp_path / "stream-encoding.txt"
    target = tmp_path / "stream-encoding-target.txt"
    path.write_text("café\nfoo\n", encoding="utf-8")
    with Document.open(path) as doc:
        stream_replace_to_file(
            doc,
            compile_pattern("foo"),
            "bar",
            target,
            encoding="windows-1252",
            eol="CRLF",
        )
    assert target.read_bytes() == b"caf\xe9\r\nbar\r\n"


def test_probe_replacements_stops_at_threshold_and_marks_streaming_route(tmp_path: Path):
    from uniti.regex.replace import probe_replacements

    path = tmp_path / "probe-replace.txt"
    path.write_text("x " * 20, encoding="utf-8")
    with Document.open(path) as doc:
        probe = probe_replacements(doc, compile_pattern("x"), "y", threshold=5)
    assert probe.truncated is True
    assert len(probe.replacements) == 5


def test_probe_replacements_returns_complete_small_transaction(tmp_path: Path):
    from uniti.regex.replace import probe_replacements

    path = tmp_path / "probe-small.txt"
    path.write_text("x x x", encoding="utf-8")
    with Document.open(path) as doc:
        probe = probe_replacements(doc, compile_pattern("x"), "y", threshold=5)
    assert probe.truncated is False
    assert [item.text for item in probe.replacements] == ["y", "y", "y"]
