"""Bounded, progressive regex search over UNITI virtual documents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

import regex

from uniti.core.document import Document
from uniti.core.offsets import ReadIntent
from .results import CaptureRecord, MatchRecord


class RegexSearchCancelled(RuntimeError):
    pass


class RegexSearchTimeout(TimeoutError):
    pass


class RegexContextLimitError(RuntimeError):
    """Pattern requires more retained context than virtual search permits."""


@dataclass(frozen=True, slots=True)
class SearchOptions:
    window_chars: int = 65_536
    timeout: float | None = 0.25
    max_matches: int | None = None
    max_context_chars: int = 1_048_576
    progress_chars: int = 1_048_576
    include_captures: bool = True

    def __post_init__(self) -> None:
        if self.window_chars <= 0:
            raise ValueError("window_chars must be positive")
        if self.timeout is not None and self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.max_matches is not None and self.max_matches < 0:
            raise ValueError("max_matches must be non-negative")
        if self.max_context_chars <= 0:
            raise ValueError("max_context_chars must be positive")
        if self.progress_chars <= 0:
            raise ValueError("progress_chars must be positive")


def _needs_full_prefix(compiled: regex.Pattern) -> bool:
    source = compiled.pattern
    if not isinstance(source, str):
        return True
    if "(?<=" in source or "(?<!" in source or "\\A" in source or "\\G" in source:
        return True
    if "^" in source and not (compiled.flags & regex.MULTILINE):
        return True
    return False


def _record_match(
    match: regex.Match,
    buffer_start: int,
    *,
    include_captures: bool = True,
) -> MatchRecord:
    captures: list[CaptureRecord] = []
    if include_captures:
        names_by_group = {number: name for name, number in match.re.groupindex.items()}
        for group in range(1, match.re.groups + 1):
            spans = tuple(
                (buffer_start + start, buffer_start + end)
                for start, end in match.spans(group)
                if start >= 0
            )
            captures.append(CaptureRecord(group, names_by_group.get(group), spans))
    start, end = match.span()
    return MatchRecord(buffer_start + start, buffer_start + end, tuple(captures))


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise RegexSearchCancelled("regex search cancelled")


def _finditer(
    compiled: regex.Pattern,
    text: str,
    *,
    pos: int,
    partial: bool,
    timeout: float | None,
):
    kwargs: dict[str, object] = {"pos": pos, "partial": partial}
    if timeout is not None:
        kwargs["timeout"] = timeout
    try:
        return compiled.finditer(text, **kwargs)
    except TimeoutError as exc:
        raise RegexSearchTimeout("regex search timed out") from exc


def _iter_engine_matches(
    document: Document,
    compiled: regex.Pattern,
    *,
    options: SearchOptions,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int | None], None] | None = None,
) -> Iterator[tuple[MatchRecord, regex.Match]]:
    """Yield compact records plus transient engine matches for immediate consumers."""

    if options.max_matches == 0:
        return
    retain_prefix = _needs_full_prefix(compiled)
    source_iter = iter(
        document.iter_text(
            chunk_chars=options.window_chars,
            intent=ReadIntent.STREAMING,
        )
    )
    buffer = ""
    buffer_start = 0
    search_pos = 0
    emitted = 0
    eof = False
    scanned = 0
    last_progress = 0
    emitted_overlap: list[tuple[int, int]] = []

    def should_emit(
        record: MatchRecord,
        replayed: list[tuple[int, int]],
        emitted_this_pass: list[tuple[int, int]],
    ) -> bool:
        if record.span in replayed:
            replayed.remove(record.span)
            emitted_this_pass.append(record.span)
            return False
        emitted_this_pass.append(record.span)
        return True

    while True:
        _check_cancelled(cancelled)
        if not eof:
            try:
                chunk_start, text = next(source_iter)
            except StopIteration:
                eof = True
            else:
                expected = buffer_start + len(buffer)
                if not buffer:
                    if chunk_start != expected:
                        buffer_start = chunk_start
                        expected = chunk_start
                if chunk_start != expected:
                    raise RuntimeError("document iterator returned a discontinuous range")
                buffer += text
                scanned = chunk_start + len(text)
                if (
                    progress is not None
                    and scanned - last_progress >= options.progress_chars
                ):
                    progress(scanned, None)
                    last_progress = scanned

        _check_cancelled(cancelled)
        if eof:
            replayed = list(emitted_overlap)
            emitted_this_pass: list[tuple[int, int]] = []
            try:
                matches = list(
                    _finditer(
                        compiled,
                        buffer,
                        pos=search_pos,
                        partial=False,
                        timeout=options.timeout,
                    )
                )
                _check_cancelled(cancelled)
                for match in matches:
                    _check_cancelled(cancelled)
                    record = _record_match(
                        match, buffer_start, include_captures=options.include_captures
                    )
                    if not should_emit(record, replayed, emitted_this_pass):
                        continue
                    yield record, match
                    emitted += 1
                    if options.max_matches is not None and emitted >= options.max_matches:
                        return
            except TimeoutError as exc:
                if isinstance(exc, RegexSearchTimeout):
                    raise
                raise RegexSearchTimeout("regex search timed out") from exc
            if progress is not None:
                progress(scanned, scanned)
            return

        unsafe_start = len(buffer)
        replayed = list(emitted_overlap)
        emitted_this_pass = []
        try:
            matches = list(
                _finditer(
                    compiled,
                    buffer,
                    pos=search_pos,
                    partial=True,
                    timeout=options.timeout,
                )
            )
            _check_cancelled(cancelled)
            for match in matches:
                _check_cancelled(cancelled)
                if match.partial:
                    unsafe_start = min(unsafe_start, match.start())
                    break
                provisional_terminal_newline = (
                    buffer.endswith("\n")
                    and match.end() == len(buffer) - 1
                )
                if match.end() == len(buffer) or provisional_terminal_newline:
                    unsafe_start = min(unsafe_start, match.start())
                    break
                record = _record_match(
                    match, buffer_start, include_captures=options.include_captures
                )
                if not should_emit(record, replayed, emitted_this_pass):
                    continue
                yield record, match
                emitted += 1
                if options.max_matches is not None and emitted >= options.max_matches:
                    return
        except TimeoutError as exc:
            if isinstance(exc, RegexSearchTimeout):
                raise
            raise RegexSearchTimeout("regex search timed out") from exc

        context_start = 0 if retain_prefix else max(0, unsafe_start - 1)
        retained = len(buffer) - context_start
        if retained > options.max_context_chars:
            raise RegexContextLimitError(
                "regex requires more retained context than allowed "
                f"({options.max_context_chars:,} characters)"
            )
        retained_start = buffer_start + context_start
        emitted_overlap = [
            span for span in emitted_this_pass if span[1] >= retained_start
        ]
        buffer_start += context_start
        buffer = buffer[context_start:]
        search_pos = unsafe_start - context_start



def resolve_captures(
    document: Document,
    compiled: regex.Pattern,
    record: MatchRecord,
    *,
    context_chars: int = 65_536,
    timeout: float | None = 0.25,
) -> MatchRecord:
    """Compatibility adapter over the bounded capture-report resolver."""

    if record.captures or compiled.groups == 0:
        return record
    if context_chars <= 0:
        raise ValueError("context_chars must be positive")
    if timeout is not None and timeout <= 0:
        raise ValueError("timeout must be positive")

    from .captures import MAX_CAPTURE_CONTEXT_CHARS, _resolve_exact_match

    with document.snapshot() as snapshot:
        resolution = _resolve_exact_match(
            snapshot,
            compiled,
            record,
            context_chars=min(context_chars, MAX_CAPTURE_CONTEXT_CHARS),
            timeout=timeout,
            cancelled=None,
        )
    if resolution.match is None:
        return record
    return _record_match(
        resolution.match,
        resolution.context_start,
        include_captures=True,
    )

def search_document(
    document: Document,
    compiled: regex.Pattern,
    *,
    options: SearchOptions | None = None,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int | None], None] | None = None,
) -> Iterator[MatchRecord]:
    opts = SearchOptions() if options is None else options
    for record, _ in _iter_engine_matches(
        document,
        compiled,
        options=opts,
        cancelled=cancelled,
        progress=progress,
    ):
        yield record
