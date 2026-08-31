"""Streaming line-ending analysis for UNITI."""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from typing import Literal

from .byte_source import ByteSource


EOLKind = Literal["LF", "CRLF", "CR", "MIXED", "NONE"]


@dataclass(frozen=True, slots=True)
class EOLReport:
    lf: int
    crlf: int
    cr: int
    kind: EOLKind


def _classify(lf: int, crlf: int, cr: int) -> EOLKind:
    present = sum(count > 0 for count in (lf, crlf, cr))
    if present == 0:
        return "NONE"
    if present > 1:
        return "MIXED"
    if crlf:
        return "CRLF"
    if lf:
        return "LF"
    return "CR"


def analyze_eol(
    source: ByteSource,
    chunk_size: int = 1 << 20,
    *,
    encoding: str = "utf-8",
    end: int | None = None,
) -> EOLReport:
    """Count logical CRLF, LF and CR endings through an incremental decoder."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
    lf = 0
    crlf = 0
    cr = 0
    pending_cr = False

    def consume(text: str) -> None:
        nonlocal lf, crlf, cr, pending_cr
        if not text:
            return

        if pending_cr:
            if text.startswith("\n"):
                crlf += 1
                text = text[1:]
            else:
                cr += 1
            pending_cr = False
            if not text:
                return

        if text.endswith("\r"):
            pending_cr = True
            text = text[:-1]

        pairs = text.count("\r\n")
        crlf += pairs
        lf += text.count("\n") - pairs
        cr += text.count("\r") - pairs

    stop = source.size if end is None else min(source.size, max(0, end))
    for chunk in source.iter_chunks(end=stop, chunk_size=chunk_size):
        consume(decoder.decode(chunk, final=False))
    consume(decoder.decode(b"", final=True))

    if pending_cr:
        cr += 1

    return EOLReport(lf=lf, crlf=crlf, cr=cr, kind=_classify(lf, crlf, cr))
