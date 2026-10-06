from __future__ import annotations

from pathlib import Path

from uniti.core.document import Document
from uniti.core.environment import EnvironmentContext
from uniti.core.environment_commands import ShowMessage, ShowStyleInspector, environment_commands
from uniti.core.environments import SfmEnvironment, UsfmEnvironment
from uniti.core.environments.sfm.inspection import inspect_marker, marker_at
from uniti.core.environments.sfm.style_layers import (
    MAX_STYLESHEET_BYTES,
    LayeredStyleRegistry,
    StyleOrigin,
    build_layers,
    clean_value,
    discover_project_stylesheets,
    load_stylesheet_file,
)
from uniti.core.environments.sfm.sty import parse_raw_stylesheet
from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline

_CUSTOM = "\\Marker q1\n\\LeftMargin 1.0\n\\FontSize 11\n\\Marker zcustom\n\\Name zcustom - Project marker\n\\StyleType Character\n\\Endmarker zcustom*\n"
_MODS = "\\Marker q1\n\\FontSize 10   # smaller for print\n"
_BOOK = "\\id GEN\n\\c 1\n\\q1 Poetry \\bd bold\\bd* line\n\\v 1 text\n"


def _project(tmp_path: Path) -> Path:
    (tmp_path / "custom.sty").write_text(_CUSTOM, encoding="utf-8")
    (tmp_path / "shared" / "ptxprint").mkdir(parents=True)
    (tmp_path / "shared" / "ptxprint" / "ptxprint-mods.sty").write_text(_MODS, encoding="utf-8")
    book = tmp_path / "01GEN.usfm"
    book.write_text(_BOOK, encoding="utf-8")
    return book


def test_discovery_finds_project_layers_in_precedence_order(tmp_path: Path):
    book = _project(tmp_path)
    layers = discover_project_stylesheets(book)
    assert [(layer.name, layer.origin) for layer in layers] == [
        ("custom.sty", StyleOrigin.PROJECT),
        ("ptxprint-mods.sty", StyleOrigin.PTXPRINT),
    ]
    assert discover_project_stylesheets(None) == ()


def test_oversized_or_missing_stylesheets_are_skipped(tmp_path: Path):
    big = tmp_path / "custom.sty"
    big.write_bytes(b"#" * (MAX_STYLESHEET_BYTES + 1))
    assert load_stylesheet_file(big, StyleOrigin.PROJECT) is None
    assert load_stylesheet_file(tmp_path / "nope.sty", StyleOrigin.PROJECT) is None


def test_provenance_reports_effective_source_and_base(tmp_path: Path):
    registry = LayeredStyleRegistry(build_layers(load_usfm_baseline(), _project(tmp_path)))
    presentation = dict(registry.presentation("q1"))
    assert presentation["FontSize"].value == "10"
    assert presentation["FontSize"].origin_layer == "ptxprint-mods.sty"
    assert presentation["FontSize"].base_value == "12"
    assert presentation["LeftMargin"].origin_layer == "custom.sty"
    name = registry.property("q1", "name")
    assert name is not None and name.origin_layer == "usfm.sty (official)"
    assert registry.defining_layers("zcustom") == ("custom.sty",)
    assert registry.registry.end_marker("zcustom") == "zcustom*"


def test_clean_value_strips_trailing_comments():
    assert clean_value(".125   # 1/8 inch") == ".125"
    assert clean_value("  ") is None
    assert clean_value(None) is None


def test_marker_at_prefers_marker_token_then_character_span_then_preceding():
    text = _BOOK
    assert marker_at(text, text.index("\\c") + 1) == "c"
    assert marker_at(text, text.index("bold") + 1) == "bd"
    assert marker_at(text, text.index("line")) == "q1"
    assert marker_at(text, text.index("\\bd*") + 2) == "bd"
    assert marker_at("no markers", 3) is None


def test_inspection_sections_follow_the_spec_shape(tmp_path: Path):
    registry = LayeredStyleRegistry(build_layers(load_usfm_baseline(), _project(tmp_path)))
    inspection = inspect_marker(registry, "\\q1")
    sections = dict(inspection.sections)
    assert list(sections) == ["Identity", "Structure", "Semantics", "Presentation", "Definition"]
    definition = {row.label: row.value for row in sections["Definition"]}
    assert definition["Effective source"] == "ptxprint-mods.sty"
    assert definition["Base source"] == "usfm.sty (official)"
    structure = {row.label: row.value for row in sections["Structure"]}
    assert structure["Repeatable"] == "yes"
    unknown = inspect_marker(registry, "nothing")
    assert unknown.known is False


def _context(path: Path, caret: int | None):
    document = Document.open(path)
    return document, EnvironmentContext.for_document(document, caret=caret)


def test_usfm_environment_layers_project_stylesheets_on_activation(tmp_path: Path):
    book = _project(tmp_path)
    environment = UsfmEnvironment()
    document, context = _context(book, _BOOK.index("Poetry"))
    try:
        environment.activate(context)
        assert [layer.name for layer in environment.layered_styles.layers] == [
            "usfm.sty (official)",
            "custom.sty",
            "ptxprint-mods.sty",
        ]
        inspect = next(c for c in environment_commands(environment) if c.command_id == "inspect")
        result = inspect.run(context, None)
        assert isinstance(result, ShowStyleInspector) and result.selected == "q1"
    finally:
        document.close()


def test_generic_sfm_uses_project_layers_without_a_baseline(tmp_path: Path):
    book = _project(tmp_path)
    sfm_path = book.with_suffix(".sfm")
    book.rename(sfm_path)
    environment = SfmEnvironment()
    document, context = _context(sfm_path, 0)
    try:
        environment.activate(context)
        assert [layer.origin for layer in environment.layered_styles.layers] == [
            StyleOrigin.PROJECT,
            StyleOrigin.PTXPRINT,
        ]
        assert environment.layered_styles.style_for("bd") is None
    finally:
        document.close()


def test_import_stylesheet_layers_on_top_and_can_be_reloaded(tmp_path: Path):
    extra = tmp_path / "elsewhere" / "house.sty"
    extra.parent.mkdir()
    extra.write_text("\\Marker q1\n\\FontSize 9\n", encoding="utf-8")
    book = _project(tmp_path)
    environment = UsfmEnvironment()
    document, context = _context(book, None)
    try:
        environment.activate(context)
        assert environment.import_stylesheet(extra) is True
        assert environment.import_stylesheet(extra) is True  # re-import replaces, not duplicates
        assert environment.layered_styles.layers[-1].origin is StyleOrigin.UNITI_IMPORT
        assert len(environment.layered_styles.layers) == 4
        assert environment.layered_styles.formatting("q1")["fontsize"] == "9"
        assert environment.import_stylesheet(tmp_path / "missing.sty") is False
        reload = next(c for c in environment_commands(environment) if c.command_id == "reload_stylesheets")
        assert isinstance(reload.run(context, None), ShowMessage)
        inspect = next(c for c in environment_commands(environment) if c.command_id == "inspect")
        assert isinstance(inspect.run(context, None), ShowStyleInspector)
    finally:
        document.close()


def test_raw_parse_of_custom_sheet_still_lossless_records():
    sheet = parse_raw_stylesheet(_CUSTOM)
    assert [record.marker for record in sheet.records] == ["q1", "zcustom"]


def test_resolved_export_round_trips_every_effective_style(tmp_path: Path):
    from uniti.core.environments.sfm.sty_export import export_resolved
    from uniti.core.environments.sfm.style_layers import StyleLayer

    registry = LayeredStyleRegistry(build_layers(load_usfm_baseline(), _project(tmp_path)))
    exported = export_resolved(registry)
    reimported = LayeredStyleRegistry(
        [StyleLayer("resolved.sty", StyleOrigin.UNITI_IMPORT, parse_raw_stylesheet(exported))]
    )
    assert reimported.markers() == registry.markers()
    for marker in registry.markers():
        assert reimported.style_for(marker).style_type == registry.style_for(marker).style_type
        assert reimported.formatting(marker) == registry.formatting(marker)
    assert "# " not in exported.split("\n", 3)[3]  # value comments stripped


def test_overrides_export_contains_only_changes(tmp_path: Path):
    from uniti.core.environments.sfm.sty_export import export_overrides

    registry = LayeredStyleRegistry(build_layers(load_usfm_baseline(), _project(tmp_path)))
    exported = export_overrides(registry)
    sheet = parse_raw_stylesheet(exported)
    by_marker = {record.marker: {e.key: e.value for e in record.entries} for record in sheet.records}
    assert set(by_marker) == {"q1", "zcustom"}
    assert by_marker["q1"] == {"LeftMargin": "1.0", "FontSize": "10"}
    assert "Name" in by_marker["zcustom"]


def test_export_commands_return_save_requests(tmp_path: Path):
    from uniti.core.environment_commands import SaveTextFile

    book = _project(tmp_path)
    environment = UsfmEnvironment()
    document, context = _context(book, None)
    try:
        environment.activate(context)
        commands = {c.command_id: c for c in environment_commands(environment)}
        result = commands["export_stylesheet_overrides"].run(context, None)
        assert isinstance(result, SaveTextFile) and result.suggested_name == "overrides.sty"
        assert "\\Marker q1" in result.text
        assert commands["export_resolved_stylesheet"].run(context, None).suggested_name == "resolved.sty"
    finally:
        document.close()


def test_placement_check_accepts_well_formed_usfm_and_flags_misplacement():
    from uniti.core.environments.sfm.placement import placement_findings

    registry = LayeredStyleRegistry(build_layers(load_usfm_baseline(), None)).registry
    good = (
        "\\id GEN\n\\h Genesis\n\\toc1 Genesis\n\\mt1 Genesis\n\\c 1\n\\s1 Title\n\\p\n"
        "\\v 1 In the \\bd beginning\\bd* God\\f + \\fr 1.1: \\ft note \\bd x\\bd*\\f* made.\n"
        "\\q1 poem \\v 2 more\n\\rem note\n"
    )
    assert placement_findings(good, registry) == ()
    bad = "\\id GEN\n\\p too early\n\\c 1\n\\v 1 orphan verse\n\\p ok \\fr stray\n\\mt1 late\n"
    findings = placement_findings(bad, registry)
    flagged = [bad[f.start : f.end] for f in findings]
    assert flagged == ["\\p", "\\v", "\\fr", "\\mt1"]
    assert all(f.code == "sfm.occurs-under" for f in findings)
    assert "\\f \\fe" in findings[2].message


def test_placement_uses_project_rules_for_generic_sfm(tmp_path: Path):
    from uniti.core.environment_commands import ShowFindings, ShowMessage

    (tmp_path / "custom.sty").write_text(
        "\\Marker sec\n\\StyleType Paragraph\n\\OccursUnder id\n"
        "\\Marker note\n\\StyleType Paragraph\n\\OccursUnder sec\n",
        encoding="utf-8",
    )
    source = tmp_path / "doc.sfm"
    source.write_text("\\id X\n\\note orphan\n\\sec Part\n\\note fine\n", encoding="utf-8")
    environment = SfmEnvironment()
    document, context = _context(source, None)
    try:
        environment.activate(context)
        command = next(c for c in environment_commands(environment) if c.command_id == "check_placement")
        result = command.run(context, None)
        assert isinstance(result, ShowFindings)
        assert len(result.findings) == 1 and "\\note" in result.findings[0].message
    finally:
        document.close()
    bare = tmp_path / "bare" / "doc.sfm"
    bare.parent.mkdir()
    bare.write_text("\\p x", encoding="utf-8")
    environment = SfmEnvironment()
    document, context = _context(bare, None)
    try:
        environment.activate(context)
        command = next(c for c in environment_commands(environment) if c.command_id == "check_placement")
        assert isinstance(command.run(context, None), ShowMessage)
    finally:
        document.close()
