"""Command-line surface for explicit UNITI bootstrap."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or repair a UNITI-owned runtime")
    parser.add_argument("--local", action="store_true", help="use the application-local runtime")
    parser.add_argument("--dev", action="store_true", help="install development dependencies")
    parser.add_argument("--repair", action="store_true", help="reinstall and revalidate dependencies")
    parser.add_argument("--no-launch", action="store_true", help="prepare without launching UNITI")
    parser.add_argument("--self-check", action="store_true", help="launch UNITI self-check")
    parser.add_argument("--deep", action="store_true", help="include deep functional checks")
    parser.add_argument("--json", dest="json_output", action="store_true", help="emit self-check JSON")
    parser.add_argument("forwarded", nargs="*")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    return 0
