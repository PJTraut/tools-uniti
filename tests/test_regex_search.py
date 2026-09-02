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


@pytest.mark.parametrize(
    ("pattern", "text", "expected"),
    (
        (r"(?=a)", "aaa", [(0, 0), (1, 1), (2, 2)]),
        (r"^|$", "ab", [(0, 0), (2, 2)]),
        (r"^|$", "a\na", [(0, 0), (3, 3)]),
        (r"a$", "a\na", [(2, 3)]),
        (r"a*?", "a\n", [(0, 0), (0, 1), (1, 1), (2, 2)]),
        (r"(?m)^|$", "a\nb", [(0, 0), (1, 1), (2, 2), (3, 3)]),
        (r"\b", "ab cd", [(0, 0), (2, 2), (3, 3), (5, 5)]),
    ),
)
def test_zero_width_results_are_exact_across_tiny_windows(
    tmp_path: Path,
    pattern: str,
    text: str,
    expected: list[tuple[int, int]],
):
    path = tmp_path / "zero-boundary.txt"
    path.write_text(text, encoding="utf-8")
    with Document.open(path) as document:
        results = list(
            search_document(
                document,
                compile_pattern(pattern),
                options=SearchOptions(window_chars=1),
            )
        )

    assert [record.span for record in results] == expected


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


def test_partial_pattern_cannot_grow_search_buffer_without_bound(tmp_path: Path):
    from uniti.regex.search import RegexContextLimitError

    path = tmp_path / "partial-context.txt"
    path.write_text("a" + ("x" * 200), encoding="utf-8")
    with Document.open(path) as doc:
        with pytest.raises(RegexContextLimitError, match="32"):
            list(
                search_document(
                    doc,
                    compile_pattern(r"a.*z"),
                    options=SearchOptions(
                        window_chars=8,
                        max_context_chars=32,
                    ),
                )
            )


def test_search_reports_bounded_character_progress(tmp_path: Path):
    path = tmp_path / "progress.txt"
    path.write_text("line\n" * 100, encoding="utf-8")
    updates: list[tuple[int, int | None]] = []

    with Document.open(path) as doc:
        list(
            search_document(
                doc,
                compile_pattern("absent"),
                options=SearchOptions(window_chars=16, progress_chars=32),
                progress=lambda completed, total: updates.append((completed, total)),
            )
        )

    assert updates
    assert updates[-1][0] == 500
    assert all(left[0] <= right[0] for left, right in zip(updates, updates[1:]))


def test_search_can_defer_capture_spans_for_large_result_storage(tmp_path: Path):
    path = tmp_path / "lazy-captures.txt"
    path.write_text("123 456", encoding="utf-8")
    compiled = compile_pattern(r"(?P<digit>\d)+")
    with Document.open(path) as doc:
        results = list(
            search_document(
                doc,
                compiled,
                options=SearchOptions(include_captures=False),
            )
        )
    assert [result.span for result in results] == [(0, 3), (4, 7)]
    assert all(result.captures == () for result in results)


def test_deferred_capture_spans_can_be_resolved_for_current_match(tmp_path: Path):
    from uniti.regex.search import resolve_captures

    path = tmp_path / "resolve-captures.txt"
    path.write_text("123 456", encoding="utf-8")
    compiled = compile_pattern(r"(?P<digit>\d)+")
    with Document.open(path) as doc:
        [first, _] = list(
            search_document(
                doc,
                compiled,
                options=SearchOptions(include_captures=False),
            )
        )
        resolved = resolve_captures(doc, compiled, first)
    assert resolved.captures[0].name == "digit"
    assert resolved.captures[0].spans == ((0, 1), (1, 2), (2, 3))
