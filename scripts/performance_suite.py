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
from benchmarks.sustained_runner import render_sustained_human, run_sustained_suite


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=("point", "sustained"),
        default="point",
    )
    parser.add_argument(
        "--tier",
        choices=("quick", "routine", "design-target"),
    )
    parser.add_argument(
        "--mode",
        choices=("baseline", "real-world"),
    )
    parser.add_argument("--profile", choices=("hosted", "controlled"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenarios",
        help=(
            "run only the named scenario; repeat for multiple scenarios "
            "(for example, session_restore)"
        ),
    )
    parser.add_argument("--native-gui", action="store_true")
    parser.add_argument("--temp-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.suite == "point":
        if args.tier is None:
            parser.error("point suite requires --tier")
        if args.profile is not None or args.candidate is not None:
            parser.error("--profile/--candidate cannot be combined with point suite")
        suite = run_suite(
            args.tier,
            args.mode or "real-world",
            args.output,
            args.compare,
            scenario_names=args.scenarios,
            native_gui=args.native_gui,
            temp_root=args.temp_root,
        )
        rendered = render_human(suite)
    else:
        if args.profile is None:
            parser.error("sustained suite requires --profile")
        if (
            args.tier is not None
            or args.mode is not None
            or args.scenarios is not None
            or args.native_gui
        ):
            parser.error(
                "--tier/--mode/--scenario/--native-gui cannot be combined "
                "with sustained suite"
            )
        if args.candidate is not None and args.profile != "controlled":
            parser.error("--candidate requires the controlled profile")
        if args.candidate is not None and (
            args.output is None
            or args.output.expanduser().resolve()
            == args.candidate.expanduser().resolve()
        ):
            parser.error("--candidate requires a distinct --output path")
        suite = run_sustained_suite(
            args.profile,
            args.output,
            args.compare,
            args.candidate,
            temp_root=args.temp_root,
        )
        rendered = render_sustained_human(suite)
    print(rendered, end="")
    if suite.state in {ResultState.PASS, ResultState.WARN}:
        return 0
    if suite.state is ResultState.NOT_RUN:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
