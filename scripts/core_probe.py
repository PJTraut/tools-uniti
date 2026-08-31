#!/usr/bin/env python3
"""Headless smoke probe for the UNITI core."""

from __future__ import annotations

import argparse
from pathlib import Path

from uniti.core import Document, analyze_eol, decode_span


def _aligned_window(length: int, encoding: str) -> int:
    normalized = encoding.lower().replace("_", "-")
    if normalized.startswith("utf-32"):
        return length - (length % 4)
    if normalized.startswith("utf-16"):
        return length - (length % 2)
    return length


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect a file using the UNITI core")
    parser.add_argument("path", type=Path)
    parser.add_argument("--window", type=int, default=256, help="bytes to decode from byte 0")
    parser.add_argument(
        "--full-eol",
        action="store_true",
        help="scan the complete source to classify line endings",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.window < 0:
        raise SystemExit("--window must be non-negative")

    with Document.open(args.path) as document:
        source = document.source
        encoding = document.encoding_info
        mapper_complete_before_read = document.offset_mapper.complete
        line_index_complete_before_read = document.source_line_index.complete

        window = _aligned_window(min(source.size, args.window), encoding.detected)
        span = decode_span(source, 0, window, encoding.detected)
        document_text = document.read(0, len(span.text))

        eol_kind = (
            analyze_eol(source, encoding=encoding.detected).kind
            if args.full_eol
            else "not-scanned"
        )

        print(f"size: {source.size}")
        print(f"encoding: {encoding.detected}")
        print(f"confidence: {encoding.confidence:.2f}")
        print(f"eol: {eol_kind}")
        print(f"offset-index-complete: {str(mapper_complete_before_read).lower()}")
        print(
            "source-line-index-complete: "
            f"{str(line_index_complete_before_read).lower()}"
        )
        print(f"decode-errors: {len(span.errors)}")
        print(f"text: {span.text!r}")
        print(f"document-text: {document_text!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
