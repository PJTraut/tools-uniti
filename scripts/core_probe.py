#!/usr/bin/env python3
"""Headless smoke probe for the UNITI core."""

from __future__ import annotations

import argparse
from pathlib import Path

from uniti.core import Document, analyze_eol, decode_span, iter_decoded_spans



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

        visible_start = document.offset_mapper.char_to_byte(0)
        if args.window == 0 or visible_start >= source.size:
            span = decode_span(source, visible_start, 0, encoding.detected)
        else:
            span = next(
                iter_decoded_spans(
                    source,
                    encoding.detected,
                    start=visible_start,
                    end=source.size,
                    chunk_size=args.window,
                )
            )
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
