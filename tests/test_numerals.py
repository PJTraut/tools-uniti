"""Preview Numerals: per-project display digits."""

from __future__ import annotations

from pathlib import Path

from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry, build_layers
from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline
from uniti.core.environments.sfm.views import layout_projection
from uniti.core.environments.user_config import set_user_config_root
from uniti.core.numerals import (
    convert_numerals,
    effective_numerals,
    project_numerals,
    set_language_numerals,
    set_project_numerals,
    with_numerals,
)

STYLES = LayeredStyleRegistry(build_layers(load_usfm_baseline(), None))
SOURCE = "\\id PRO\n\\c 1\n\\p\n\\v 5-6 Text 12 \\f + \\ft 3 notes\\f* ۷\n"


def test_digits_convert_between_systems():
    assert convert_numerals("v 5-6 and ۷ and ٣", "persian") == "v ۵-۶ and ۷ and ۳"
    assert convert_numerals("12 ۳", "latin") == "12 3"
    assert convert_numerals("12", "arabic-indic") == "١٢"
    assert convert_numerals("12", "as-written") == "12"
    assert convert_numerals("12", "unknown") == "12"


def test_the_projection_changes_text_only_and_keeps_the_source_map():
    plain = layout_projection(SOURCE, STYLES, "k", show_markers=False)
    shown = with_numerals(plain, "persian")
    assert shown.text == convert_numerals(plain.text, "persian")
    assert len(shown.text) == len(plain.text)
    assert shown.source_map.segments == plain.source_map.segments
    shown.source_map.check()
    assert all(
        section.projection.text == convert_numerals(other.projection.text, "persian")
        for section, other in zip(shown.notes, plain.notes)
    )
    assert with_numerals(plain, "as-written") is plain


def test_the_choice_is_per_project_then_per_language(tmp_path: Path):
    set_user_config_root(tmp_path)
    try:
        assert effective_numerals("faPCBv3", "fa") == "as-written"
        set_language_numerals("fa", "persian")
        assert effective_numerals("faPCBv3", "fa") == "persian"
        assert effective_numerals("faPCBv3", "FA ") == "persian"
        assert effective_numerals("enNIV", "en") == "as-written"
        set_project_numerals("faPCBv3", "latin")  # the project's own choice wins
        assert effective_numerals("faPCBv3", "fa") == "latin"
        assert project_numerals("faPCBv3") == "latin"
        set_project_numerals("faPCBv3", "as-written")  # explicitly as written, even in Persian
        assert effective_numerals("faPCBv3", "fa") == "as-written"
        set_project_numerals("faPCBv3", None)  # follow the language again
        assert effective_numerals("faPCBv3", "fa") == "persian"
        set_language_numerals("fa", None)
        assert effective_numerals("faPCBv3", "fa") == "as-written"
    finally:
        set_user_config_root(None)


def test_a_character_style_can_keep_its_own_numerals():
    """`\\TextProperties numerals-latin` in the project's stylesheet: that
    style's digits stay Latin while the rest of Preview shows Persian."""

    from uniti.core.environments.sfm.sty import parse_raw_stylesheet
    from uniti.core.environments.sfm.style_layers import StyleLayer, StyleOrigin
    custom = parse_raw_stylesheet(
        "\\Marker zn\n\\Endmarker zn*\n\\Name zn - Latin numbers\n\\StyleType Character\n"
        "\\TextProperties publishable vernacular numerals-latin\n\\FontSize 12\n"
    )
    layers = build_layers(load_usfm_baseline(), None)
    styles = LayeredStyleRegistry((*layers, StyleLayer("custom.sty", StyleOrigin.PROJECT, custom)))
    source = "\\id PRO\n\\c 1\n\\p\n\\v 5 Year 12 and \\zn 2026\\zn* in ۷\n"
    projection = layout_projection(source, styles, "k", show_markers=False)
    shown = with_numerals(projection, "persian")
    assert "2026" in shown.text  # kept Latin
    assert "۱۲" in shown.text  # 12: Persian
    assert "۲۰۲۶" not in shown.text
    shown.source_map.check()
    assert len(shown.text) == len(projection.text)
