"""Regex replacement services for UNITI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import regex

from uniti.core.document import Document
from .search import SearchOptions, _iter_engine_matches


@dataclass(frozen=True, slots=True)
class Replacement:
    start: int
    end: int
    text: str


def collect_replacements(
    document: Document,
    compiled: regex.Pattern,
    replacement: str,
    *,
    options: SearchOptions | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> list[Replacement]:
    opts = SearchOptions() if options is None else options
    replacements: list[Replacement] = []
    for record, match in _iter_engine_matches(
        document,
        compiled,
        options=opts,
        cancelled=cancelled,
    ):
        replacements.append(Replacement(record.start, record.end, match.expand(replacement)))
    return replacements


def replace_all(
    document: Document,
    compiled: regex.Pattern,
    replacement: str,
    *,
    options: SearchOptions | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> int:
    replacements = collect_replacements(
        document,
        compiled,
        replacement,
        options=options,
        cancelled=cancelled,
    )
    document.replace_many([(r.start, r.end, r.text) for r in replacements])
    return len(replacements)


@dataclass(frozen=True, slots=True)
class StreamReplaceResult:
    path: Path
    count: int


def stream_replace_to_file(
    document: Document,
    compiled: regex.Pattern,
    replacement: str,
    destination: str | Path,
    *,
    options: SearchOptions | None = None,
    cancelled: Callable[[], bool] | None = None,
    encoding: str | None = None,
    eol: str | None = None,
) -> StreamReplaceResult:
    """Stream a whole-document regex rewrite without mutating the document."""

    from uniti.core.save import EOLName, atomic_write_text_chunks

    opts = SearchOptions() if options is None else options
    output_encoding = (
        encoding
        or document.encoding_info.output_encoding
        or document.encoding_info.detected
    )
    output_eol: EOLName | None = document.output_eol if eol is None else eol  # type: ignore[assignment]
    count_box = [0]

    def chunks():
        source_iter = iter(document.iter_text(chunk_chars=opts.window_chars))
        current_start = 0
        current_text = ""
        current_index = 0
        absolute_pos = 0
        source_eof = False

        def load_next() -> bool:
            nonlocal current_start, current_text, current_index, source_eof
            if current_index < len(current_text):
                return True
            if source_eof:
                return False
            try:
                current_start, current_text = next(source_iter)
            except StopIteration:
                source_eof = True
                return False
            current_index = 0
            return True

        def advance_to(target: int, *, emit: bool):
            nonlocal current_index, absolute_pos
            if target < absolute_pos:
                raise RuntimeError("replacement spans are not monotonic")
            while absolute_pos < target:
                if not load_next():
                    raise RuntimeError("replacement span extends beyond document")
                chunk_pos = current_start + current_index
                if chunk_pos != absolute_pos:
                    raise RuntimeError("document output iterator became discontinuous")
                take = min(target - absolute_pos, len(current_text) - current_index)
                if emit and take:
                    yield current_text[current_index : current_index + take]
                current_index += take
                absolute_pos += take

        for record, match in _iter_engine_matches(
            document,
            compiled,
            options=opts,
            cancelled=cancelled,
        ):
            replacement_text = match.expand(replacement)
            yield from advance_to(record.start, emit=True)
            yield replacement_text
            yield from advance_to(record.end, emit=False)
            count_box[0] += 1

        while load_next():
            if current_index < len(current_text):
                text = current_text[current_index :]
                absolute_pos += len(text)
                current_index = len(current_text)
                yield text

    source_norm = document.encoding_info.detected.lower().replace("_", "-")
    output_norm = output_encoding.lower().replace("_", "-")
    bom = document.encoding_info.bom if source_norm == output_norm else None
    path = atomic_write_text_chunks(
        chunks(),
        destination,
        encoding=output_encoding,
        eol=output_eol,
        bom=bom,
    )
    return StreamReplaceResult(path, count_box[0])
