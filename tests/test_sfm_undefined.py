"""Undefined markup: markers no loaded stylesheet defines (round 2, R7)."""

from __future__ import annotations

from pathlib import Path

from uniti.core.environment import EnvironmentContext
from uniti.core.environment_commands import ShowUndefinedMarkup, environment_commands
from uniti.core.environments import UsfmEnvironment
from uniti.core.environments.sfm.sty import parse_raw_stylesheet
from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry, StyleLayer, StyleOrigin, build_layers
from uniti.core.environments.sfm.undefined import definition_stubs, report_text, undefined_markers
from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline

_SOURCE = (
    "\\id GEN Test\n\\c 1\n\\p\n\\v 1 A \\zfoo x\\zfoo* \\qt-s |who=\"P\"\\*q\\qt-e\\*\n"
    "\\esb \\cat People\\cat*\n\\p B \\nd y \\+zfoo z\\+zfoo*\\nd* \\zbar*\n\\esbe\n\\tr \\th1-2 H\n"
)


def _styles(document_path: Path | None = None) -> LayeredStyleRegistry:
    return LayeredStyleRegistry(build_layers(load_usfm_baseline(), document_path))


def test_undefined_markers_in_order_of_first_use():
    markers = undefined_markers(_SOURCE, _styles())
    assert [(m.marker, m.count, m.closed, m.custom) for m in markers] == [
        ("zfoo", 2, True, True),  # opener uses only; nested \+zfoo counts as \zfoo
        ("esb", 1, False, False),
        ("zbar", 1, True, True),  # a stray end marker still counts once
        ("esbe", 1, False, False),
    ]
    # Milestones (\qt-s, \*), \cat (built-in), \nd and the \th1-2 range cell are defined or skipped.
    assert markers[0].display == "\\zfoo"
    assert "custom.sty" in markers[0].advice


def test_project_definitions_count(tmp_path: Path):
    (tmp_path / "custom.sty").write_text("\\Marker zfoo\n\\Endmarker zfoo*\n\\StyleType Character\n", encoding="utf-8")
    markers = undefined_markers(_SOURCE, _styles(tmp_path / "GEN.usfm"))
    assert "zfoo" not in [m.marker for m in markers]


def test_the_report_lists_markers_and_locations():
    styles = _styles()
    markers = undefined_markers(_SOURCE, styles)
    report = report_text("GEN.usfm", tuple(layer.name for layer in styles.layers), markers, _SOURCE)
    assert report.startswith("Undefined markers in GEN.usfm\nChecked against: usfm.sty (official) → uniti.sty (built-in)\n")
    assert "\\zfoo — 2 uses — custom marker: define it in the project's custom.sty\n    GEN 1:1, line 4\n    GEN 1:1, line 6\n" in report
    assert "\\esb — 1 use — not defined in any loaded stylesheet" in report
    assert report_text("X.usfm", (), (), "").endswith("Every marker is defined.\n")


def test_starter_definitions_define_the_markers():
    styles = _styles()
    markers = undefined_markers(_SOURCE, styles)
    stubs = definition_stubs(markers, "GEN.usfm")
    assert "\\Marker zfoo\n\\Endmarker zfoo*\n\\Name zfoo - (describe this marker)\n\\StyleType Character" in stubs
    assert "\\Marker esb\n\\Name esb - (describe this marker)\n\\StyleType Paragraph" in stubs

    layer = StyleLayer("custom.sty", StyleOrigin.PROJECT, parse_raw_stylesheet(stubs))
    defined = LayeredStyleRegistry((*styles.layers, layer))
    assert undefined_markers(_SOURCE, defined) == ()


def test_the_usfm_environment_offers_the_check(tmp_path: Path):
    from uniti.core.document import Document

    path = tmp_path / "GEN.usfm"
    path.write_text(_SOURCE, encoding="utf-8")
    environment = UsfmEnvironment()
    with Document.open(path) as document:
        context = EnvironmentContext.for_document(document)
        environment.activate(context)
        command = next(c for c in environment_commands(environment) if c.command_id == "check_undefined")
        result = command.run(context, None)
    assert command.label == "Check Undefined Markers" and command.group == "validate"
    assert isinstance(result, ShowUndefinedMarkup)
    assert [m.marker for m in result.markers] == ["zfoo", "esb", "zbar", "esbe"]
    assert result.layer_names[:2] == ("usfm.sty (official)", "uniti.sty (built-in)")
