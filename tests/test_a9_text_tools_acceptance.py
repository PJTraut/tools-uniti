from pathlib import Path

from uniti.core.document import Document
from uniti.regex.engine import compile_pattern
from uniti.regex.lexer import tokenize_pattern, tokenize_replacement
from uniti.regex.replace import replace_all
from uniti.regex.search import search_document


def test_a9_text_tools_end_to_end(tmp_path: Path):
    source = tmp_path / "input.txt"
    output = tmp_path / "output.txt"
    source.write_bytes("2026-08-31 Pieter\r\n2026-09-01 John\r\n".encode("utf-8"))

    pattern = r"(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<name>\w+)"
    replacement = r"\g<name> [\g<date>]"
    assert any(token.kind == "group_open" for token in tokenize_pattern(pattern))
    assert any(token.kind == "backreference" for token in tokenize_replacement(replacement))

    with Document.open(source) as document:
        compiled = compile_pattern(pattern)
        matches = list(search_document(document, compiled))
        assert len(matches) == 2
        name_capture = next(c for c in matches[0].captures if c.name == "name")
        start, end = name_capture.spans[0]
        assert document.read(start, end) == "Pieter"

        count = replace_all(document, compiled, replacement)
        assert count == 2
        assert document.read(0, document.total_chars()).startswith("Pieter [2026-08-31]")

        document.set_output_encoding("utf-16-le")
        document.set_output_eol("LF")
        document.export_copy(output, output_format=document.output_format)
        assert document.modified

    saved = output.read_bytes().decode("utf-16-le")
    assert saved == "Pieter [2026-08-31]\nJohn [2026-09-01]\n"
