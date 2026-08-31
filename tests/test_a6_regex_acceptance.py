from pathlib import Path

from uniti.core.document import Document
from uniti.regex.engine import compile_pattern
from uniti.regex.replace import stream_replace_to_file
from uniti.regex.search import search_document


def test_regex_search_and_stream_rewrite_across_normal_large_workload(tmp_path: Path):
    source = tmp_path / "regex-large.txt"
    target = tmp_path / "regex-large-out.txt"
    filler = b"a" * (11 * 1024 * 1024)
    source.write_bytes(b"MARK1\n" + filler + b"\nMARK2")

    pattern = compile_pattern(r"MARK(\d)")
    with Document.open(source, encoding="utf-8") as document:
        matches = list(search_document(document, pattern))
        assert [m.start for m in matches] == [0, source.stat().st_size - 5]
        result = stream_replace_to_file(document, pattern, r"TAG[\1]", target)
        assert result.count == 2
        assert not document.modified

    with target.open("rb") as handle:
        assert handle.read(7) == b"TAG[1]\n"
        handle.seek(-6, 2)
        assert handle.read() == b"TAG[2]"
