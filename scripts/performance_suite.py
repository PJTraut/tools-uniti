#!/usr/bin/env python3
"""Run UNITI's isolated user-experience performance suite."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

from benchmarks.models import ResultState
from benchmarks.report import render_human
from benchmarks.runner import run_suite


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tier",
        choices=("quick", "routine", "design-target"),
        required=True,
    )
    parser.add_argument(
        "--mode",
        choices=("baseline", "real-world"),
        default="real-world",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--scenario", action="append", dest="scenarios")
    parser.add_argument("--native-gui", action="store_true")
    parser.add_argument("--temp-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    suite = run_suite(
        args.tier,
        args.mode,
        args.output,
        args.compare,
        scenario_names=args.scenarios,
        native_gui=args.native_gui,
        temp_root=args.temp_root,
    )
    print(render_human(suite), end="")
    if suite.state in {ResultState.PASS, ResultState.WARN}:
        return 0
    if suite.state is ResultState.NOT_RUN:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
