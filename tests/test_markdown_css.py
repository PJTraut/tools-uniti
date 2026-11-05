"""Markdown Preview stylesheets (N27, 2026-11-05)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from uniti.core.environment import EnvironmentContext
from uniti.core.environments import user_config
from uniti.core.environments.configuration import (
    BUILT_IN,
    LOADED,
    PROJECT,
    YOURS,
    configuration_files,
)
from uniti.core.environments.markdown_css import (
    cascade,
    clear_css_cache,
    declarations_to_attrs,
    document_stylesheet_paths,
    front_matter_stylesheets,
    markdown_styles,
    parse_css,
    user_stylesheet_path,
)
from uniti.core.environments.markdown_environment import EXTENDED, MarkdownEnvironment
from uniti.core.environments.markdown_views import MarkdownRenderedView


@pytest.fixture(autouse=True)
def user_root(tmp_path: Path):
    root = tmp_path / "user-data"
    user_config.set_user_config_root(root)
    clear_css_cache()
    yield root
    user_config.set_user_config_root(None)
    clear_css_cache()


def _block(projection, marker: str) -> dict[str, str]:
    return dict(next(block for block in projection.blocks if block.marker == marker).attrs)


def test_the_parser_reads_element_rules_and_notes_the_rest():
    sheet = parse_css(
        """/* a comment { } */
        h1, h2 { color: #800; font-size: 2em !important; }
        .note { color: red; }
        p > em { font-style: normal; }
        @media print { h1 { color: black; } }
        blockquote { float: left; margin-left: 24px }
        """
    )
    assert sheet.rules == (
        ("h1", "color", "#800"),
        ("h2", "color", "#800"),
        ("h1", "font-size", "2em"),
        ("h2", "font-size", "2em"),
        ("blockquote", "margin-left", "24px"),
    )
    assert sheet.ignored == ("selector .note", "selector p > em", "@media", "property float")


def test_values_map_onto_view_attributes():
    attrs, bad = declarations_to_attrs(
        {
            "font-weight": "700",
            "font-style": "italic",
            "text-decoration": "underline line-through",
            "color": "GrayText",
            "background-color": "rgb(255, 0, 0)",
            "font-family": '"Gentium Plus", serif',
            "font-size": "150%",
            "margin-left": "0.5in",
            "margin-top": "12pt",
            "text-align": "center",
        }
    )
    assert attrs == {
        "bold": "yes",
        "italic": "yes",
        "underline": "yes",
        "strikeout": "yes",
        "muted": "yes",
        "background": "rgb(255, 0, 0)",
        "font_family": "Gentium Plus,serif",
        "font_scale": "1.500",
        "left_margin": "0.500",
        "space_before": "16",
        "align": "center",
    }
    assert bad == []
    assert declarations_to_attrs({"font-family": "monospace"})[0] == {"monospace": "yes"}
    assert declarations_to_attrs({"font-size": "huge"})[1] == ["font-size: huge"]


def test_later_layers_win_property_by_property():
    first = parse_css("h1 { color: red; font-weight: bold; }", "first")
    second = parse_css("h1 { color: blue; }", "second")
    styles = cascade([first, second])
    assert styles.for_element("h1") == {"color": "blue", "bold": "yes"}
    third = parse_css("h1 { font-weight: normal; }", "third")
    assert cascade([first, second, third]).for_element("h1") == {"color": "blue"}


def test_the_built_in_stylesheet_keeps_todays_look():
    projection = MarkdownRenderedView(EXTENDED).project("# T\n> q\n```\nx\n```\n[a](u)")
    assert _block(projection, "h1") == {"bold": "yes", "font_scale": "1.800", "space_before": "6", "heading_level": "1"}
    assert _block(projection, "quote") == {"italic": "yes", "muted": "yes", "left_margin": "0.300"}
    assert _block(projection, "pre") == {"monospace": "yes", "left_margin": "0.250"}
    link = next(span for span in projection.spans if span.marker == "link")
    assert dict(link.attrs) == {"underline": "yes", "color": "#1a56db"}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("---\nstylesheet: [a.css, 'b.css']\n---\n# x", ("a.css", "b.css")),
        ("---\ntitle: t\nstylesheet: one.css\n---\n", ("one.css",)),
        ("---\nstylesheet:\n  - a.css\n  - b.css\nother: 1\n---\n", ("a.css", "b.css")),
        ("---\ntitle: t\n---\n", None),
        ("# no front matter\nstylesheet: a.css", None),
        ("---\nstylesheet: a.css\n", None),  # never closed
    ],
)
def test_front_matter_names_the_documents_stylesheets(source, expected):
    assert front_matter_stylesheets(source) == expected


def test_a_folder_uniti_css_is_the_fallback(tmp_path: Path):
    document = tmp_path / "notes" / "a.md"
    assert document_stylesheet_paths(document, "# x") == (tmp_path / "notes" / "uniti.css",)
    assert document_stylesheet_paths(document, "---\nstylesheet: [s.css]\n---\n") == (tmp_path / "notes" / "s.css",)


def test_layers_cascade_in_order(tmp_path: Path):
    user = user_stylesheet_path()
    user.parent.mkdir(parents=True)
    user.write_text("h1 { color: red; } h2 { color: red; }", encoding="utf-8")
    (tmp_path / "doc.css").write_text("h1 { color: green; }", encoding="utf-8")
    loaded = tmp_path / "loaded.css"
    loaded.write_text("h2 { color: navy; }", encoding="utf-8")
    source = "---\nstylesheet: [doc.css, missing.css]\n---\n"
    styles = markdown_styles(tmp_path / "a.md", source, [loaded])
    assert styles.for_element("h1")["color"] == "green"
    assert styles.for_element("h2")["color"] == "navy"
    assert styles.for_element("h1")["bold"] == "yes"  # from the built-in sheet
    assert "missing.css: not found ignored" in styles.notes


def test_a_changed_stylesheet_changes_the_views_cache_token(tmp_path: Path):
    environment = MarkdownEnvironment()
    document = tmp_path / "a.md"
    document.write_text("# T", encoding="utf-8")
    environment.activate(EnvironmentContext(edits=None, resource_profile=None, document_path=document))  # type: ignore[arg-type]
    view = environment.view_providers()[0]
    view.project("# T")
    token = view.cache_token()
    assert view.cache_token() is token
    css = tmp_path / "uniti.css"
    css.write_text("h1 { color: purple; }", encoding="utf-8")
    assert view.cache_token() is not token
    assert _block(view.project("# T"), "h1")["color"] == "purple"
    css.write_text("h1 { color: teal; }", encoding="utf-8")
    os.utime(css, ns=(1, 1))  # a different stamp even within the clock's resolution
    assert _block(view.project("# T"), "h1")["color"] == "teal"


def test_load_stylesheet_adds_a_session_layer(tmp_path: Path):
    environment = MarkdownEnvironment()
    environment.activate(EnvironmentContext(edits=None, resource_profile=None, document_path=tmp_path / "a.md"))  # type: ignore[arg-type]
    assert environment.import_stylesheet(tmp_path / "absent.css") is False
    sheet = tmp_path / "print.css"
    sheet.write_text("em { color: maroon; }", encoding="utf-8")
    assert environment.import_stylesheet(sheet) is True
    projection = environment.view_providers()[0].project("*it*")
    assert dict(next(span for span in projection.spans if span.marker == "em").attrs)["color"] == "maroon"
    assert [command.label for command in environment.commands()] == ["Format Document", "Load Stylesheet…"]


def test_configuration_files_lists_the_markdown_layers(tmp_path: Path):
    environment = MarkdownEnvironment()
    document = tmp_path / "a.md"
    document.write_text("---\nstylesheet: [x.css]\n---\n", encoding="utf-8")
    environment.activate(EnvironmentContext(edits=None, resource_profile=None, document_path=document))  # type: ignore[arg-type]
    loaded = tmp_path / "l.css"
    loaded.write_text("", encoding="utf-8")
    environment.import_stylesheet(loaded)
    rows = configuration_files("markdown", "Markdown", document, environment)
    kinds = [(row.role, row.kind) for row in rows]
    assert ("Built-in Preview stylesheet (markdown.css)", BUILT_IN) in kinds
    assert ("Your stylesheet (every Markdown file)", YOURS) in kinds
    assert ("Document stylesheet (x.css)", PROJECT) in kinds
    assert ("Loaded stylesheet (l.css)", LOADED) in kinds
    built_in = next(row for row in rows if row.kind == BUILT_IN)
    assert built_in.exists and not built_in.editable
