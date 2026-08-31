#!/usr/bin/env python3
"""Headless smoke probe for the UNITI core."""

from __future__ import annotations

import argparse
from pathlib import Path

from uniti.core import ByteSource, analyze_eol, decode_span, detect_encoding


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
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.window < 0:
        raise SystemExit("--window must be non-negative")

    with ByteSource.open(args.path) as source:
        encoding = detect_encoding(source)
        eol = analyze_eol(source)
        window = _aligned_window(min(source.size, args.window), encoding.detected)
        span = decode_span(source, 0, window, encoding.detected)

        print(f"size: {source.size}")
        print(f"encoding: {encoding.detected}")
        print(f"confidence: {encoding.confidence:.2f}")
        print(f"eol: {eol.kind}")
        print(f"decode-errors: {len(span.errors)}")
        print(f"text: {span.text!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
