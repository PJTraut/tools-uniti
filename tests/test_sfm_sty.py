from __future__ import annotations

from uniti.core.environments.sfm.sty import (
    RawStyleEntry,
    StyleRegistry,
    normalize_style,
    parse_raw_stylesheet,
)

_MINIMAL_STY = """\
\\Marker id
\\Name Identification
\\OccursUnder Text
\\Rank 1
\\StyleType Paragraph

\\Marker bd
\\Name Bold
\\StyleType Character
\\EndMarker bd*
\\TextProperties bold
"""


def test_parses_one_record_per_marker_block():
    sheet = parse_raw_stylesheet(_MINIMAL_STY)

    assert [record.marker for record in sheet.records] == ["id", "bd"]


def test_preserves_field_order_and_raw_line():
    sheet = parse_raw_stylesheet(_MINIMAL_STY)

    id_record = sheet.records[0]
    assert [entry.key for entry in id_record.entries] == ["Name", "OccursUnder", "Rank", "StyleType"]
    assert id_record.entries[0].raw_line == "\\Name Identification\n"


def test_ignores_comments_and_blank_lines():
    text = "# a comment\n\n\\Marker id\n# another comment\n\\Name Identification\n"

    sheet = parse_raw_stylesheet(text)

    assert len(sheet.records) == 1
    assert sheet.records[0].entries[0].key == "Name"


def test_unknown_fields_survive_as_extensions():
    text = "\\Marker z1\n\\FontScale 1.2\n\\Raise 3\n"

    sheet = parse_raw_stylesheet(text)
    style = normalize_style(sheet.records[0])

    assert style.extensions == (("FontScale", "1.2"), ("Raise", "3"))


def test_normalizes_structural_fields():
    sheet = parse_raw_stylesheet(_MINIMAL_STY)

    id_style = normalize_style(sheet.records[0])
    bd_style = normalize_style(sheet.records[1])

    assert id_style.occurs_under == ("Text",)
    assert id_style.rank == 1
    assert id_style.style_type == "Paragraph"
    assert bd_style.end_marker == "bd*"
    assert bd_style.text_properties == frozenset({"bold"})


def test_not_repeatable_field_sets_repeatable_false():
    sheet = parse_raw_stylesheet("\\Marker q1\n\\NotRepeatable\n")

    style = normalize_style(sheet.records[0])

    assert style.repeatable is False


def test_repeatable_defaults_to_none_when_unspecified():
    sheet = parse_raw_stylesheet("\\Marker q1\n\\Name Poetry\n")

    style = normalize_style(sheet.records[0])

    assert style.repeatable is None


def test_registry_answers_structural_queries():
    sheet = parse_raw_stylesheet(_MINIMAL_STY)

    registry = StyleRegistry.from_layers(sheet)

    assert registry.occurs_under("id") == ("Text",)
    assert registry.end_marker("bd") == "bd*"
    assert registry.rank("id") == 1
    assert registry.style_for("missing") is None
    assert registry.occurs_under("missing") == ()


def test_later_layer_overrides_earlier_layer_field_by_field():
    base = parse_raw_stylesheet("\\Marker q1\n\\Rank 4\n\\StyleType Paragraph\n")
    project = parse_raw_stylesheet("\\Marker q1\n\\Rank 5\n")

    registry = StyleRegistry.from_layers(base, project)

    effective = registry.style_for("q1")
    assert effective.rank == 5  # project layer wins
    assert effective.style_type == "Paragraph"  # unset in project layer, base survives


def test_extensions_accumulate_across_layers():
    base = parse_raw_stylesheet("\\Marker q1\n\\FontScale 1.0\n")
    project = parse_raw_stylesheet("\\Marker q1\n\\Raise 2\n")

    registry = StyleRegistry.from_layers(base, project)

    assert registry.style_for("q1").extensions == (("FontScale", "1.0"), ("Raise", "2"))


def test_raw_style_entry_is_a_plain_value_object():
    entry = RawStyleEntry(key="Name", value="Bold", raw_line="\\Name Bold\n")

    assert entry.key == "Name"
    assert entry.value == "Bold"
