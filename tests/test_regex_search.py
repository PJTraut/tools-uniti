from pathlib import Path

import pytest
import regex

from uniti.core.document import Document
from uniti.regex.engine import compile_pattern
from uniti.regex.search import (
    RegexSearchCancelled,
    RegexSearchTimeout,
    SearchOptions,
    search_document,
)


def test_compile_pattern_uses_regex_engine_and_reports_invalid_pattern():
    compiled = compile_pattern(r"(?P<word>\p{L}+)")
    assert isinstance(compiled, regex.Pattern)
    with pytest.raises(regex.error):
        compile_pattern("(")


def test_search_crosses_small_windows_with_partial_extension(tmp_path: Path):
    path = tmp_path / "cross.txt"
    path.write_text("abc---xyz tail", encoding="utf-8")
    with Document.open(path) as doc:
        results = list(
            search_document(
                doc,
                compile_pattern(r"abc.*?xyz"),
                options=SearchOptions(window_chars=4),
            )
        )
    assert [result.span for result in results] == [(0, 9)]


def test_search_records_named_repeated_capture_spans(tmp_path: Path):
    path = tmp_path / "captures.txt"
    path.write_text("123 xx", encoding="utf-8")
    with Document.open(path) as doc:
        [result] = list(search_document(doc, compile_pattern(r"(?P<digit>\d)+")))
    capture = result.captures[0]
    assert capture.group == 1
    assert capture.name == "digit"
    assert capture.spans == ((0, 1), (1, 2), (2, 3))


def test_zero_width_search_progresses_across_windows(tmp_path: Path):
    path = tmp_path / "zero.txt"
    path.write_text("aaa", encoding="utf-8")
    with Document.open(path) as doc:
        results = list(
            search_document(
                doc,
                compile_pattern(r"(?=a)"),
                options=SearchOptions(window_chars=2),
            )
        )
    assert [result.span for result in results] == [(0, 0), (1, 1), (2, 2)]


def test_search_can_cancel_before_engine_work(tmp_path: Path):
    path = tmp_path / "cancel.txt"
    path.write_text("abc" * 1000, encoding="utf-8")
    with Document.open(path) as doc:
        with pytest.raises(RegexSearchCancelled):
            list(
                search_document(
                    doc,
                    compile_pattern("abc"),
                    cancelled=lambda: True,
                )
            )


def test_search_timeout_is_wrapped(tmp_path: Path):
    path = tmp_path / "timeout.txt"
    path.write_text("a" * 100_000 + "X", encoding="utf-8")
    with Document.open(path) as doc:
        with pytest.raises(RegexSearchTimeout):
            list(
                search_document(
                    doc,
                    compile_pattern(r"(a+)+$"),
                    options=SearchOptions(window_chars=100_001, timeout=0.000001),
                )
            )


def test_first_result_can_arrive_without_indexing_entire_document(tmp_path: Path):
    path = tmp_path / "progressive.txt"
    path.write_text("hit\n" + ("miss\n" * 100_000), encoding="utf-8")
    with Document.open(path) as doc:
        results = list(
            search_document(
                doc,
                compile_pattern("hit"),
                options=SearchOptions(window_chars=32, max_matches=1),
            )
        )
        assert [result.span for result in results] == [(0, 3)]
        assert not doc.offset_mapper.complete


def test_prefix_retaining_regex_is_bounded_by_context_limit(tmp_path: Path):
    from uniti.regex.search import RegexContextLimitError

    path = tmp_path / "anchored.txt"
    path.write_text("a" + ("x" * 200) + "Z", encoding="utf-8")
    with Document.open(path) as doc:
        with pytest.raises(RegexContextLimitError):
            list(
                search_document(
                    doc,
                    compile_pattern(r"^a.*Z"),
                    options=SearchOptions(
                        window_chars=8,
                        max_context_chars=32,
                    ),
                )
            )
