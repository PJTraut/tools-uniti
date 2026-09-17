"""Immutable, bounded capture-only reports for stored regex matches."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

import regex

from .lexer import tokenize_replacement
from .results import MatchRecord
from .search import RegexSearchCancelled, RegexSearchTimeout

if TYPE_CHECKING:
    from uniti.core.snapshot import DocumentReadSnapshot


MAX_CAPTURE_CONTEXT_CHARS = 65_536
MAX_CAPTURE_PREVIEWS = 5
MAX_CAPTURE_PREVIEW_CHARS = 80
MAX_CAPTURE_REPORT_BYTES = 1 << 20
MAX_CAPTURE_REPORT_MATCHES = 3

_RECORD_PAYLOAD_BYTES = 64
_CAPTURE_TIMEOUT_SECONDS = 0.25
_PAYLOAD_LIMIT_REASON = "capture details exceed 1 MiB report limit"
# Three distinct causes previously shared one undifferentiated message —
# each now names what a user could actually act on.
_LOOKAROUND_CONTEXT_REASON = (
    "capture details unavailable — this pattern uses lookaround, which needs "
    "to see past the 65,536-character capture context to confirm the match"
)
_WINDOW_BOUNDARY_REASON = (
    "capture details unavailable — the match could not be confirmed within "
    "a 65,536-character window around it (it may need more surrounding "
    "context, or the document changed since this match was found)"
)
_MATCH_LIMIT_REASON = "match exceeds 65,536-character report limit"
_OUTSIDE_SNAPSHOT_REASON = "stored match is outside document snapshot"


@dataclass(frozen=True, slots=True)
class CaptureReportRequest:
    pattern_generation: int
    pattern_text: str
    document_key: str
    revision: int
    store_id: str
    requested_index: int
    match_count: int
    matches: tuple[tuple[int, MatchRecord], ...]

    def __post_init__(self) -> None:
        if self.pattern_generation < 0:
            raise ValueError("pattern generation must be non-negative")
        if self.revision < 0:
            raise ValueError("document revision must be non-negative")
        if self.match_count < 0:
            raise ValueError("match count must be non-negative")
        if self.requested_index < 0:
            raise ValueError("requested index must be non-negative")
        if self.matches and self.matches[0][0] != self.requested_index:
            raise ValueError("the requested match must be first")
        if len(self.matches) > MAX_CAPTURE_REPORT_MATCHES:
            raise ValueError(
                f"capture reports contain at most {MAX_CAPTURE_REPORT_MATCHES} matches"
            )
        for index, record in self.matches:
            if index < 0 or index >= self.match_count:
                raise ValueError("capture-report match index is out of range")
            if record.start < 0 or record.end < record.start:
                raise ValueError("invalid capture-report match span")
            if record.captures:
                raise ValueError("capture-report requests require capture-free matches")


@dataclass(frozen=True, slots=True)
class CapturePreview:
    start: int
    end: int
    text: str
    empty: bool


@dataclass(frozen=True, slots=True)
class CaptureGroupRow:
    number: int
    name: str | None
    state: str
    occurrence_count: int
    previews: tuple[CapturePreview, ...]


@dataclass(frozen=True, slots=True)
class CaptureMatchReport:
    index: int
    total: int
    groups: tuple[CaptureGroupRow, ...]
    unavailable_reason: str | None = None
    replacement_preview: str | None = None
    # (start, end, group_number) for each span of `replacement_preview` that
    # came from a capturing-group backreference — BF-052 item 5, lets the
    # Match Report color those spans like the referenced group elsewhere.
    replacement_preview_group_spans: tuple[tuple[int, int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class CaptureReport:
    request: CaptureReportRequest
    matches: tuple[CaptureMatchReport, ...]
    payload_bytes: int


@dataclass(frozen=True, slots=True)
class _ExactMatchResolution:
    match: object | None
    context_start: int
    window: str
    unavailable_reason: str | None = None


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise RegexSearchCancelled("regex capture report cancelled")


def _utf8_size(text: str | None) -> int:
    return 0 if text is None else len(text.encode("utf-8"))


def _request_payload_size(request: CaptureReportRequest) -> int:
    return (
        _RECORD_PAYLOAD_BYTES * (2 + len(request.matches))
        + _utf8_size(request.pattern_text)
    )


def _preview_payload_size(preview: CapturePreview) -> int:
    return _RECORD_PAYLOAD_BYTES + _utf8_size(preview.text)


def _group_payload_size(row: CaptureGroupRow) -> int:
    return (
        _RECORD_PAYLOAD_BYTES
        + _utf8_size(row.name)
        + sum(_preview_payload_size(preview) for preview in row.previews)
    )


def _match_payload_size(match: CaptureMatchReport) -> int:
    return (
        _RECORD_PAYLOAD_BYTES
        + _utf8_size(match.unavailable_reason)
        + _utf8_size(match.replacement_preview)
        + _RECORD_PAYLOAD_BYTES * len(match.replacement_preview_group_spans)
        + sum(_group_payload_size(row) for row in match.groups)
    )


def _unavailable(index: int, total: int, reason: str) -> CaptureMatchReport:
    return CaptureMatchReport(
        index=index,
        total=total,
        groups=(),
        unavailable_reason=reason,
    )


def _escape_preview(text: str) -> str:
    escaped: list[str] = []
    replacements = {
        "\r": r"\r",
        "\n": r"\n",
        "\t": r"\t",
        "\0": r"\0",
    }
    for character in text:
        replacement = replacements.get(character)
        if replacement is not None:
            escaped.append(replacement)
            continue
        if unicodedata.category(character) == "Cc":
            codepoint = ord(character)
            if codepoint <= 0xFF:
                escaped.append(f"\\x{codepoint:02x}")
            elif codepoint <= 0xFFFF:
                escaped.append(f"\\u{codepoint:04x}")
            else:
                escaped.append(f"\\U{codepoint:08x}")
            continue
        escaped.append(character)
    value = "".join(escaped)
    if len(value) > MAX_CAPTURE_PREVIEW_CHARS:
        return value[: MAX_CAPTURE_PREVIEW_CHARS - 1] + "…"
    return value


def _find_exact_match(
    compiled: regex.Pattern,
    window: str,
    *,
    local_start: int,
    local_end: int,
    timeout: float | None,
    cancelled: Callable[[], bool] | None,
):
    try:
        matches = compiled.finditer(
            window,
            pos=local_start,
            partial=False,
            timeout=timeout,
        )
        for match in matches:
            _check_cancelled(cancelled)
            start, end = match.span()
            if start > local_start:
                break
            if start == local_start and end == local_end:
                return match
    except TimeoutError as exc:
        raise RegexSearchTimeout("regex capture resolution timed out") from exc
    return None


def _pattern_has_lookaround(compiled: regex.Pattern) -> bool:
    source = compiled.pattern
    if not isinstance(source, str):
        return True
    from .lexer import scan_pattern

    structure = scan_pattern(source)
    prefixes = ("(?=", "(?!", "(?<=", "(?<!")
    return any(
        token.kind == "group_open"
        and any(prefix in token.text for prefix in prefixes)
        for token in structure.tokens
    )


def _resolve_exact_match(
    snapshot: DocumentReadSnapshot,
    compiled: regex.Pattern,
    record: MatchRecord,
    *,
    context_chars: int,
    timeout: float | None,
    cancelled: Callable[[], bool] | None,
) -> _ExactMatchResolution:
    """Return one engine match without trusting an artificial slice edge."""

    _check_cancelled(cancelled)
    if context_chars <= 0 or context_chars > MAX_CAPTURE_CONTEXT_CHARS:
        raise ValueError("capture context must be between 1 and 65,536 characters")
    if timeout is not None and timeout <= 0:
        raise ValueError("timeout must be positive")

    match_chars = record.end - record.start
    if match_chars > context_chars:
        reason = (
            _MATCH_LIMIT_REASON
            if context_chars == MAX_CAPTURE_CONTEXT_CHARS
            else f"match exceeds {context_chars:,}-character capture context"
        )
        return _ExactMatchResolution(None, 0, "", reason)

    remaining = context_chars - match_chars
    before = min(record.start, remaining // 2)
    context_start = record.start - before
    requested_end = record.end + (remaining - before)
    try:
        window = snapshot.read(context_start, requested_end)
    except ValueError:
        document_chars = snapshot.total_chars()
        if record.end > document_chars:
            return _ExactMatchResolution(None, 0, "", _OUTSIDE_SNAPSHOT_REASON)
        context_end = min(document_chars, requested_end)
        window = snapshot.read(context_start, context_end)
        excludes_right = False
    else:
        context_end = requested_end
        try:
            snapshot.read(context_end, context_end + 1)
        except ValueError:
            excludes_right = False
        else:
            excludes_right = True
    if len(window) > context_chars:
        raise AssertionError("capture resolver exceeded its context bound")
    _check_cancelled(cancelled)

    local_start = record.start - context_start
    local_end = record.end - context_start
    excludes_document_content = context_start > 0 or excludes_right
    if excludes_document_content and _pattern_has_lookaround(compiled):
        return _ExactMatchResolution(
            None, context_start, window, _LOOKAROUND_CONTEXT_REASON
        )
    match = _find_exact_match(
        compiled,
        window,
        local_start=local_start,
        local_end=local_end,
        timeout=timeout,
        cancelled=cancelled,
    )
    if match is None:
        return _ExactMatchResolution(
            None, context_start, window, _WINDOW_BOUNDARY_REASON
        )

    touches_artificial_left = context_start > 0 and local_start == 0
    touches_artificial_right = excludes_right and local_end == len(window)
    if touches_artificial_left or touches_artificial_right:
        return _ExactMatchResolution(
            None, context_start, window, _WINDOW_BOUNDARY_REASON
        )
    return _ExactMatchResolution(match, context_start, window)


def _replacement_preview(
    match: object,
    replacement: str | None,
    compiled: regex.Pattern,
) -> tuple[str | None, tuple[tuple[int, int, int], ...]]:
    if replacement is None:
        return None, ()
    try:
        tokens = tokenize_replacement(
            replacement,
            group_count=compiled.groups,
            group_names=compiled.groupindex,
        )
        pieces: list[str] = []
        spans: list[tuple[int, int, int]] = []
        offset = 0
        for token in tokens:
            # Delegate all actual escape/backreference decoding to the
            # engine itself (one call per token) rather than reimplementing
            # escape semantics here — this only tracks where each piece
            # lands in the concatenated output (BF-052 item 5).
            piece = match.expand(token.text)
            if (
                token.kind == "backreference"
                and token.valid
                and token.group_number is not None
                and token.group_number != 0
            ):
                spans.append((offset, offset + len(piece), token.group_number))
            pieces.append(piece)
            offset += len(piece)
        return "".join(pieces), tuple(spans)
    except (regex.error, IndexError):
        return None, ()


def _resolve_match(
    snapshot: DocumentReadSnapshot,
    compiled: regex.Pattern,
    index: int,
    total: int,
    record: MatchRecord,
    *,
    max_payload_bytes: int,
    cancelled: Callable[[], bool] | None,
    replacement: str | None = None,
) -> CaptureMatchReport:
    resolution = _resolve_exact_match(
        snapshot,
        compiled,
        record,
        context_chars=MAX_CAPTURE_CONTEXT_CHARS,
        timeout=_CAPTURE_TIMEOUT_SECONDS,
        cancelled=cancelled,
    )
    if resolution.match is None:
        assert resolution.unavailable_reason is not None
        return _unavailable(index, total, resolution.unavailable_reason)
    match = resolution.match
    context_start = resolution.context_start
    window = resolution.window

    names_by_group = {
        number: name for name, number in compiled.groupindex.items()
    }
    rows: list[CaptureGroupRow] = []
    match_payload = _RECORD_PAYLOAD_BYTES
    for group in range(1, compiled.groups + 1):
        _check_cancelled(cancelled)
        if match.span(group) == (-1, -1):
            row = CaptureGroupRow(
                number=group,
                name=names_by_group.get(group),
                state="not_matched",
                occurrence_count=0,
                previews=(),
            )
        else:
            transient_spans = match.spans(group)
            try:
                occurrence_count = len(transient_spans)
                previews = tuple(
                    CapturePreview(
                        start=context_start + start,
                        end=context_start + end,
                        text=_escape_preview(window[start:end]),
                        empty=start == end,
                    )
                    for start, end in transient_spans[:MAX_CAPTURE_PREVIEWS]
                )
                state = (
                    "empty"
                    if transient_spans
                    and all(start == end for start, end in transient_spans)
                    else "value"
                )
            finally:
                del transient_spans
            row = CaptureGroupRow(
                number=group,
                name=names_by_group.get(group),
                state=state,
                occurrence_count=occurrence_count,
                previews=previews,
            )
        _check_cancelled(cancelled)
        row_payload = _group_payload_size(row)
        if match_payload + row_payload > max_payload_bytes:
            rows.clear()
            return _unavailable(index, total, _PAYLOAD_LIMIT_REASON)
        rows.append(row)
        match_payload += row_payload

    preview, preview_group_spans = _replacement_preview(match, replacement, compiled)
    if match_payload + _utf8_size(preview) > max_payload_bytes:
        preview = None
        preview_group_spans = ()

    return CaptureMatchReport(
        index=index,
        total=total,
        groups=tuple(rows),
        replacement_preview=preview,
        replacement_preview_group_spans=preview_group_spans,
    )


def resolve_capture_report(
    snapshot: DocumentReadSnapshot,
    compiled: regex.Pattern,
    request: CaptureReportRequest,
    *,
    cancelled: Callable[[], bool] | None = None,
    replacement: str | None = None,
) -> CaptureReport:
    """Resolve at most `MAX_CAPTURE_REPORT_MATCHES` exact stored matches into a
    bounded capture report."""

    payload_bytes = _request_payload_size(request)
    if payload_bytes > MAX_CAPTURE_REPORT_BYTES:
        raise ValueError("capture-report request exceeds the 1 MiB payload limit")

    reports: list[CaptureMatchReport] = []
    future_reserve = _RECORD_PAYLOAD_BYTES + max(
        _utf8_size(reason)
        for reason in (
            _PAYLOAD_LIMIT_REASON,
            _LOOKAROUND_CONTEXT_REASON,
            _WINDOW_BOUNDARY_REASON,
            _MATCH_LIMIT_REASON,
            _OUTSIDE_SNAPSHOT_REASON,
        )
    )
    for ordinal, (index, record) in enumerate(request.matches):
        future_count = len(request.matches) - ordinal - 1
        available = (
            MAX_CAPTURE_REPORT_BYTES
            - payload_bytes
            - future_count * future_reserve
        )
        report = _resolve_match(
            snapshot,
            compiled,
            index,
            request.match_count,
            record,
            max_payload_bytes=max(0, available),
            cancelled=cancelled,
            replacement=replacement,
        )
        reports.append(report)
        payload_bytes += _match_payload_size(report)

    if payload_bytes > MAX_CAPTURE_REPORT_BYTES:
        raise AssertionError("capture report exceeded its payload bound")
    return CaptureReport(
        request=request,
        matches=tuple(reports),
        payload_bytes=payload_bytes,
    )
