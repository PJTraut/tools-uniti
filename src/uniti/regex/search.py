"""Bounded, progressive regex search over UNITI virtual documents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

import regex

from uniti.core.document import Document
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

    def __post_init__(self) -> None:
        if self.window_chars <= 0:
            raise ValueError("window_chars must be positive")
        if self.timeout is not None and self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.max_matches is not None and self.max_matches < 0:
            raise ValueError("max_matches must be non-negative")
        if self.max_context_chars <= 0:
            raise ValueError("max_context_chars must be positive")


def _needs_full_prefix(compiled: regex.Pattern) -> bool:
    source = compiled.pattern
    if not isinstance(source, str):
        return True
    if "(?<=" in source or "(?<!" in source or "\\A" in source or "\\G" in source:
        return True
    if "^" in source and not (compiled.flags & regex.MULTILINE):
        return True
    return False


def _record_match(match: regex.Match, buffer_start: int) -> MatchRecord:
    names_by_group = {number: name for name, number in match.re.groupindex.items()}
    captures: list[CaptureRecord] = []
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
) -> Iterator[tuple[MatchRecord, regex.Match]]:
    """Yield compact records plus transient engine matches for immediate consumers."""

    if options.max_matches == 0:
        return
    retain_prefix = _needs_full_prefix(compiled)
    source_iter = iter(document.iter_text(chunk_chars=options.window_chars))
    buffer = ""
    buffer_start = 0
    search_pos = 0
    emitted = 0
    eof = False

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

        _check_cancelled(cancelled)
        if eof:
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
                for match in matches:
                    _check_cancelled(cancelled)
                    record = _record_match(match, buffer_start)
                    yield record, match
                    emitted += 1
                    if options.max_matches is not None and emitted >= options.max_matches:
                        return
            except TimeoutError as exc:
                if isinstance(exc, RegexSearchTimeout):
                    raise
                raise RegexSearchTimeout("regex search timed out") from exc
            return

        unsafe_start = len(buffer)
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
            for match in matches:
                _check_cancelled(cancelled)
                if match.partial:
                    unsafe_start = min(unsafe_start, match.start())
                    break
                if match.end() == len(buffer):
                    unsafe_start = min(unsafe_start, match.start())
                    break
                record = _record_match(match, buffer_start)
                yield record, match
                emitted += 1
                if options.max_matches is not None and emitted >= options.max_matches:
                    return
        except TimeoutError as exc:
            if isinstance(exc, RegexSearchTimeout):
                raise
            raise RegexSearchTimeout("regex search timed out") from exc

        if retain_prefix:
            if len(buffer) > options.max_context_chars:
                raise RegexContextLimitError(
                    "regex requires more retained prefix context than allowed "
                    f"({options.max_context_chars:,} characters)"
                )
            search_pos = unsafe_start
            continue

        context_start = max(0, unsafe_start - 1)
        buffer_start += context_start
        buffer = buffer[context_start:]
        search_pos = unsafe_start - context_start


def search_document(
    document: Document,
    compiled: regex.Pattern,
    *,
    options: SearchOptions | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Iterator[MatchRecord]:
    opts = SearchOptions() if options is None else options
    for record, _ in _iter_engine_matches(
        document,
        compiled,
        options=opts,
        cancelled=cancelled,
    ):
        yield record
