from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from uniti.core.document import Document
from uniti.regex.captures import (
    MAX_CAPTURE_CONTEXT_CHARS,
    MAX_CAPTURE_PREVIEWS,
    MAX_CAPTURE_PREVIEW_CHARS,
    MAX_CAPTURE_REPORT_BYTES,
    CaptureReportRequest,
    resolve_capture_report,
)
from uniti.regex.engine import compile_pattern
from uniti.regex.results import CaptureRecord, MatchRecord
from uniti.regex.search import (
    RegexSearchCancelled,
    SearchOptions,
    search_document,
)


def _request(
    document: Document,
    matches: tuple[tuple[int, MatchRecord], ...],
    *,
    pattern_text: str,
    requested_index: int | None = None,
    match_count: int | None = None,
) -> CaptureReportRequest:
    if requested_index is None:
        requested_index = matches[0][0]
    if match_count is None:
        match_count = max(index for index, _ in matches) + 1
    return CaptureReportRequest(
        pattern_generation=4,
        pattern_text=pattern_text,
        document_key=str(id(document)),
        revision=document.revision,
        store_id="store-1",
        requested_index=requested_index,
        match_count=match_count,
        matches=matches,
    )


def test_capture_report_distinguishes_unmatched_empty_and_repeated(
    tmp_path: Path,
):
    path = tmp_path / "captures.txt"
    path.write_text("aaa", encoding="utf-8")
    pattern = r"(?P<repeat>a)+(?P<empty>)(?P<missing>z)?"
    with Document.open(path) as document:
        compiled = compile_pattern(pattern)
        [record] = list(
            search_document(
                document,
                compiled,
                options=SearchOptions(include_captures=False),
            )
        )
        request = _request(document, ((0, record),), pattern_text=pattern)
        with document.snapshot() as snapshot:
            report = resolve_capture_report(snapshot, compiled, request)

    assert report.request is request
    assert len(report.matches) == 1
    rows = report.matches[0].groups
    assert rows[0].occurrence_count == 3
    assert rows[0].state == "value"
    assert [preview.text for preview in rows[0].previews] == ["a", "a", "a"]
    assert rows[1].state == "empty"
    assert rows[1].previews[0].start == 3
    assert rows[1].previews[0].empty is True
    assert rows[2].state == "not_matched"
    assert rows[2].occurrence_count == 0
    assert rows[2].previews == ()
    assert all(row.number != 0 for row in rows)
    with pytest.raises(FrozenInstanceError):
        rows[0].state = "changed"


def test_capture_report_is_all_or_unavailable_above_context_bound(
    tmp_path: Path,
):
    path = tmp_path / "huge.txt"
    path.write_text("a" * (MAX_CAPTURE_CONTEXT_CHARS + 1), encoding="utf-8")
    pattern = r"(a+)"
    with Document.open(path) as document:
        compiled = compile_pattern(pattern)
        record = MatchRecord(0, MAX_CAPTURE_CONTEXT_CHARS + 1)
        request = _request(document, ((0, record),), pattern_text=pattern)
        with document.snapshot() as snapshot:
            report = resolve_capture_report(snapshot, compiled, request)

    match = report.matches[0]
    assert match.groups == ()
    assert "65,536" in (match.unavailable_reason or "")
    assert report.payload_bytes <= MAX_CAPTURE_REPORT_BYTES


@pytest.mark.parametrize(
    ("text", "pattern", "record"),
    (
        (
            "a" * MAX_CAPTURE_CONTEXT_CHARS + "x",
            rf"(?:(?P<actual>a{{{MAX_CAPTURE_CONTEXT_CHARS}}})(?=x)|"
            rf"(?P<wrong>a{{{MAX_CAPTURE_CONTEXT_CHARS}}})$)",
            MatchRecord(0, MAX_CAPTURE_CONTEXT_CHARS),
        ),
        (
            "x" + "a" * MAX_CAPTURE_CONTEXT_CHARS,
            rf"(?:(?<=x)(?P<actual>a{{{MAX_CAPTURE_CONTEXT_CHARS}}})|"
            rf"^(?P<wrong>a{{{MAX_CAPTURE_CONTEXT_CHARS}}}))",
            MatchRecord(1, MAX_CAPTURE_CONTEXT_CHARS + 1),
        ),
    ),
    ids=("right-edge", "left-edge"),
)
def test_capture_report_never_trusts_an_artificial_window_edge(
    tmp_path: Path,
    text: str,
    pattern: str,
    record: MatchRecord,
):
    path = tmp_path / "edge-sensitive.txt"
    path.write_text(text, encoding="utf-8")
    with Document.open(path) as document:
        compiled = compile_pattern(pattern)
        direct = compiled.search(text)
        assert direct is not None
        assert direct.span("actual") == record.span
        request = _request(document, ((0, record),), pattern_text=pattern)
        with document.snapshot() as snapshot:
            report = resolve_capture_report(snapshot, compiled, request)

    match = report.matches[0]
    assert match.groups == ()
    assert "65,536" in (match.unavailable_reason or "")


def test_capture_report_rejects_centered_match_with_out_of_window_lookaround(
    tmp_path: Path,
):
    target = 32_768
    text = "q" * target + "a" + "q" * 32_768 + "x"
    pattern = (
        r"(?:(?P<actual>a)(?=.{32768}x)|"
        r"(?P<wrong>a)(?=.{32768}$))"
    )
    record = MatchRecord(target, target + 1)
    path = tmp_path / "centered-edge-sensitive.txt"
    path.write_text(text, encoding="utf-8")
    with Document.open(path) as document:
        compiled = compile_pattern(pattern)
        direct = compiled.search(text)
        assert direct is not None
        assert direct.span("actual") == record.span
        request = _request(document, ((0, record),), pattern_text=pattern)
        with document.snapshot() as snapshot:
            report = resolve_capture_report(snapshot, compiled, request)

    match = report.matches[0]
    assert match.groups == ()
    assert "65,536" in (match.unavailable_reason or "")


def test_capture_report_bounds_context_preview_count_width_and_payload(
    tmp_path: Path,
):
    path = tmp_path / "bounded.txt"
    path.write_text("x" * 100_000 + "a" + "x" * 100_000, encoding="utf-8")
    pattern = r"(?P<item>a)"
    with Document.open(path) as document:
        compiled = compile_pattern(pattern)
        record = MatchRecord(100_000, 100_001)
        request = _request(document, ((0, record),), pattern_text=pattern)
        with document.snapshot() as snapshot:
            reads: list[tuple[int, int]] = []

            class RecordingSnapshot:
                def total_chars(self) -> int:
                    raise AssertionError(
                        "bounded capture resolution measured the whole document"
                    )

                def read(self, start: int, end: int) -> str:
                    reads.append((start, end))
                    return snapshot.read(start, end)

            report = resolve_capture_report(
                RecordingSnapshot(),
                compiled,
                request,
            )

    assert reads
    assert all(end - start <= MAX_CAPTURE_CONTEXT_CHARS for start, end in reads)
    assert report.matches[0].groups[0].previews[0].text == "a"
    assert report.payload_bytes <= MAX_CAPTURE_REPORT_BYTES


def test_capture_report_escapes_and_truncates_repeated_previews(tmp_path: Path):
    path = tmp_path / "previews.txt"
    value = "a\n\t\0\x01" + "x" * 95
    path.write_text(value * 6, encoding="utf-8")
    pattern = r"(?P<item>[\s\S]{100})+"
    with Document.open(path) as document:
        compiled = compile_pattern(pattern)
        [record] = list(
            search_document(
                document,
                compiled,
                options=SearchOptions(include_captures=False),
            )
        )
        request = _request(document, ((0, record),), pattern_text=pattern)
        with document.snapshot() as snapshot:
            report = resolve_capture_report(snapshot, compiled, request)

    [row] = report.matches[0].groups
    assert row.occurrence_count == 6
    assert len(row.previews) == MAX_CAPTURE_PREVIEWS
    assert all(
        len(preview.text) <= MAX_CAPTURE_PREVIEW_CHARS
        for preview in row.previews
    )
    assert all(preview.text.endswith("…") for preview in row.previews)
    assert row.previews[0].text.startswith(r"a\n\t\0\x01")
    assert report.payload_bytes <= MAX_CAPTURE_REPORT_BYTES


def test_capture_report_discards_all_group_rows_when_payload_would_overflow():
    group_count = 10_000

    class FakeMatch:
        def span(self, group: int = 0) -> tuple[int, int]:
            return (0, 1)

        def spans(self, group: int) -> list[tuple[int, int]]:
            return [(0, 1)]

    class FakeCompiled:
        groups = group_count
        groupindex = {
            f"group_{number}_{'n' * 96}": number
            for number in range(1, group_count + 1)
        }

        def finditer(self, text: str, **_kwargs):
            return iter((FakeMatch(),))

    class FakeSnapshot:
        def total_chars(self) -> int:
            return 1

        def read(self, start: int, end: int) -> str:
            if start < 0 or end > 1:
                raise ValueError("outside fake snapshot")
            return "x"[start:end]

    request = CaptureReportRequest(
        pattern_generation=1,
        pattern_text="(x)",
        document_key="doc",
        revision=0,
        store_id="store",
        requested_index=0,
        match_count=1,
        matches=((0, MatchRecord(0, 1)),),
    )

    report = resolve_capture_report(FakeSnapshot(), FakeCompiled(), request)

    assert report.matches[0].groups == ()
    assert "1 MiB" in (report.matches[0].unavailable_reason or "")
    assert report.payload_bytes <= MAX_CAPTURE_REPORT_BYTES


def test_capture_report_request_rejects_records_with_retained_captures():
    record = MatchRecord(
        0,
        1,
        (CaptureRecord(1, "item", tuple((0, 1) for _ in range(100_000))),),
    )

    with pytest.raises(ValueError, match="capture-free"):
        CaptureReportRequest(
            pattern_generation=1,
            pattern_text="(x)",
            document_key="doc",
            revision=0,
            store_id="store",
            requested_index=0,
            match_count=1,
            matches=((0, record),),
        )


def test_capture_report_checks_cancellation_between_groups():
    processed: list[int] = []

    class FakeMatch:
        def span(self, group: int = 0) -> tuple[int, int]:
            return (0, 1)

        def spans(self, group: int) -> list[tuple[int, int]]:
            processed.append(group)
            return [(0, 1)]

    class FakeCompiled:
        groups = 3
        groupindex = {}

        def finditer(self, text: str, **_kwargs):
            return iter((FakeMatch(),))

    class FakeSnapshot:
        def total_chars(self) -> int:
            return 1

        def read(self, start: int, end: int) -> str:
            if start < 0 or end > 1:
                raise ValueError("outside fake snapshot")
            return "x"[start:end]

    request = CaptureReportRequest(
        pattern_generation=1,
        pattern_text="(x)(x)(x)",
        document_key="doc",
        revision=0,
        store_id="store",
        requested_index=0,
        match_count=1,
        matches=((0, MatchRecord(0, 1)),),
    )

    with pytest.raises(RegexSearchCancelled):
        resolve_capture_report(
            FakeSnapshot(),
            FakeCompiled(),
            request,
            cancelled=lambda: bool(processed),
        )

    assert processed == [1]


def test_capture_report_preserves_requested_current_then_wrapped_next_order(
    tmp_path: Path,
):
    path = tmp_path / "ordered.txt"
    path.write_text("a aa aaa", encoding="utf-8")
    pattern = r"(a+)"
    with Document.open(path) as document:
        compiled = compile_pattern(pattern)
        records = tuple(
            search_document(
                document,
                compiled,
                options=SearchOptions(include_captures=False),
            )
        )
        request = _request(
            document,
            ((2, records[2]), (0, records[0])),
            pattern_text=pattern,
            requested_index=2,
            match_count=3,
        )
        with document.snapshot() as snapshot:
            report = resolve_capture_report(snapshot, compiled, request)

    assert report.request is request
    assert [(match.index, match.total) for match in report.matches] == [
        (2, 3),
        (0, 3),
    ]


def test_capture_report_does_not_duplicate_a_single_match(tmp_path: Path):
    path = tmp_path / "single.txt"
    path.write_text("a", encoding="utf-8")
    pattern = r"(a)"
    with Document.open(path) as document:
        compiled = compile_pattern(pattern)
        [record] = list(
            search_document(
                document,
                compiled,
                options=SearchOptions(include_captures=False),
            )
        )
        request = _request(document, ((0, record),), pattern_text=pattern)
        with document.snapshot() as snapshot:
            report = resolve_capture_report(snapshot, compiled, request)

    assert len(report.matches) == 1
    assert report.matches[0].index == 0
    assert report.matches[0].total == 1
