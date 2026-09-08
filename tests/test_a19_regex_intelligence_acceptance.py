from dataclasses import FrozenInstanceError
import importlib.metadata
from pathlib import Path
import tomllib

from packaging.version import Version

import pytest
import uniti

from uniti.core.document import Document
from uniti.regex.analysis import AnalysisState, analyze_pattern
from uniti.regex.captures import CaptureReportRequest, resolve_capture_report
from uniti.regex.engine import compile_pattern
from uniti.regex.replace import replace_all
from uniti.regex.search import SearchOptions, search_document


def test_release_metadata_remains_canonical_after_a19():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    display = Path("VERSION").read_text(encoding="utf-8").strip()

    assert display == uniti.__display_version__
    assert project["project"]["version"] == uniti.__version__
    assert display.startswith("v0.001")
    assert uniti.__version__.startswith("0.1")
    assert display.removeprefix("v0.001") == uniti.__version__.removeprefix("0.1")
    assert Version(uniti.__version__) >= Version("0.1a19")


def test_a19_uses_only_the_pinned_engine_and_advanced_metadata():
    assert importlib.metadata.version("regex") == "2026.5.9"
    analysis = analyze_pattern(
        r"(?V1)(?P<item>a)(?P<item>b)(?|(c)|(d))(?P=item)",
        generation=1,
    )

    assert analysis.state is AnalysisState.VALID
    assert analysis.compiled.__class__.__module__ == "_regex"
    assert analysis.identities_reconciled


def test_a19_expression_and_report_bounds_are_exact(tmp_path: Path):
    assert analyze_pattern("x" * 65_536, 1).state is AnalysisState.VALID
    assert analyze_pattern("x" * 65_537, 2).state is AnalysisState.OVER_LIMIT
    path = tmp_path / "captures.txt"
    path.write_text("aaaaaa", encoding="utf-8")
    with Document.open(path) as document:
        compiled = compile_pattern(r"(?P<item>a)+")
        records = tuple(
            search_document(
                document,
                compiled,
                options=SearchOptions(include_captures=False),
            )
        )
        request = CaptureReportRequest(
            pattern_generation=4,
            pattern_text=compiled.pattern,
            document_key=str(id(document)),
            revision=document.revision,
            store_id="acceptance-store",
            requested_index=0,
            match_count=len(records),
            matches=((0, records[0]),),
        )
        with document.snapshot() as snapshot:
            report = resolve_capture_report(snapshot, compiled, request)

    assert report.payload_bytes <= 1 << 20
    assert all(
        len(row.previews) <= 5
        for match in report.matches
        for row in match.groups
    )
    assert report.matches[0].groups[0].occurrence_count == 6
    with pytest.raises(FrozenInstanceError):
        request.revision = 9


def test_a19_zero_width_search_and_bulk_replace_are_exact_and_atomic(
    tmp_path: Path,
):
    path = tmp_path / "atomic.txt"
    path.write_text("aa", encoding="utf-8")
    with Document.open(path) as document:
        positions = [
            record.start
            for record in search_document(
                document,
                compile_pattern(r"(?=a)|(?<=a)"),
                options=SearchOptions(include_captures=False),
            )
        ]
        assert positions == [0, 1, 2]
        assert replace_all(document, compile_pattern(r"(?=a)"), "X") == 2
        assert document.read(0, document.total_chars()) == "XaXa"
        document.undo()
        assert document.read(0, document.total_chars()) == "aa"


def test_a19_core_boundaries_stay_qt_free_and_reports_stay_model_backed():
    core_sources = tuple(Path("src/uniti/regex").glob("*.py")) + tuple(
        Path("src/uniti/resources").glob("*.py")
    )
    for source_path in core_sources:
        source = source_path.read_text(encoding="utf-8")
        assert "PySide6" not in source
        assert "PyQt" not in source

    report_source = Path("src/uniti/ui/capture_report.py").read_text(
        encoding="utf-8"
    )
    panel_source = Path("src/uniti/ui/find_replace.py").read_text(
        encoding="utf-8"
    )
    assert "QAbstractListModel" in report_source
    assert "QListWidget" not in report_source
    assert "resolve_captures" not in panel_source
    for seal in (
        "pattern_generation",
        "pattern_text",
        "document_key",
        "revision",
        "store_id",
        "requested_index",
    ):
        assert seal in panel_source
