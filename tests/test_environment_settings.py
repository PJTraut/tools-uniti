"""Environment settings (N31, 2026-11-05): declarations, settings.json, and
Markdown's Format Document options."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uniti.core.environments import user_config
from uniti.core.environments.configuration import configuration_files
from uniti.core.environments.markdown_environment import MARKDOWN_SETTINGS
from uniti.core.environments.settings import (
    clear_settings_cache,
    declarations_for,
    environment_settings,
    parse_settings,
    save_settings,
    settings_path,
    store_environment_settings,
)
from uniti.core.reformatters import MARKDOWN, align_table


@pytest.fixture
def user_root(tmp_path: Path):
    root = tmp_path / "user-data"
    user_config.set_user_config_root(root)
    clear_settings_cache()
    yield root
    user_config.set_user_config_root(None)
    clear_settings_cache()


def test_markdown_declares_its_settings_with_defaults():
    settings = parse_settings(MARKDOWN_SETTINGS, "")
    assert settings.get("flavour") == "extended"
    assert settings.get("opens_in") == "text"
    assert settings.get("bullet") == "-"
    assert settings.get("blank_lines") == 1
    assert settings.get("align_tables") is True
    assert settings.notes == ()
    assert declarations_for("markdown") == MARKDOWN_SETTINGS
    assert declarations_for("plain_text") == ()


def test_settings_live_next_to_the_environment_groups(user_root: Path):
    assert settings_path("markdown") == user_root / "Environments" / "Markdown" / "settings.json"


def test_only_changed_values_are_written_and_unknown_keys_are_kept(user_root: Path):
    path = settings_path("markdown")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"from_a_newer_uniti": 3}), encoding="utf-8")
    settings = environment_settings("markdown").with_values({"bullet": "*", "flavour": "extended", "blank_lines": 2})
    save_settings(settings, path)
    assert json.loads(path.read_text(encoding="utf-8")) == {"from_a_newer_uniti": 3, "bullet": "*", "blank_lines": 2}
    assert environment_settings("markdown").get("bullet") == "*"


def test_a_bad_file_or_value_is_ignored_with_a_note(user_root: Path):
    settings = parse_settings(MARKDOWN_SETTINGS, '{"bullet": "x", "blank_lines": 0, "nonsense": 1, "align_tables": false}')
    assert settings.get("bullet") == "-"
    assert settings.get("blank_lines") == 1
    assert settings.get("align_tables") is False
    assert len(settings.notes) == 3
    broken = parse_settings(MARKDOWN_SETTINGS, "{not json")
    assert broken.values == {} and "isn't valid JSON" in broken.notes[0]
    assert parse_settings(MARKDOWN_SETTINGS, "[1, 2]").notes


def test_settings_are_reread_when_the_file_changes(user_root: Path):
    path = settings_path("markdown")
    path.parent.mkdir(parents=True)
    path.write_text('{"bullet": "+"}', encoding="utf-8")
    assert environment_settings("markdown").get("bullet") == "+"
    path.write_text('{"bullet": "*", "emphasis": "_"}', encoding="utf-8")
    assert environment_settings("markdown").get("bullet") == "*"


def test_without_a_user_folder_settings_last_the_session():
    user_config.set_user_config_root(None)
    clear_settings_cache()
    try:
        chosen = environment_settings("markdown").with_values({"bullet": "+"})
        assert store_environment_settings("markdown", chosen) is None
        assert environment_settings("markdown").get("bullet") == "+"
    finally:
        clear_settings_cache()


def test_configuration_files_lists_settings_json_for_environments_with_settings(user_root: Path, tmp_path: Path):
    rows = configuration_files("markdown", "Markdown", tmp_path / "notes.md")
    roles = [row.role for row in rows]
    assert "Your settings (settings.json)" in roles
    row = rows[roles.index("Your settings (settings.json)")]
    assert row.path == settings_path("markdown") and row.template == "{}\n"
    plain = configuration_files("plain_text", "Plain Text", tmp_path / "a.txt")
    assert all(row.role != "Your settings (settings.json)" for row in plain)


# --- Markdown's Format Document options -------------------------------------------


def test_format_uses_the_chosen_bullet_and_keeps_rules():
    text = "- a\n* b\n+ c\n\n* * *\n"
    assert MARKDOWN.format(text, {"bullet": "*"}) == "* a\n* b\n* c\n\n* * *\n"
    assert MARKDOWN.format(text) == "- a\n- b\n- c\n\n* * *\n"


def test_format_normalises_emphasis_outside_code():
    text = "an _it_ and __bold__ and `_code_` and snake_case_name\n"
    result = MARKDOWN.format(text, {"emphasis": "*", "strong": "**"})
    assert result == "an *it* and **bold** and `_code_` and snake_case_name\n"
    assert MARKDOWN.format(text) == text  # as written by default
    assert MARKDOWN.format("*a* **b**\n", {"emphasis": "_", "strong": "__"}) == "_a_ __b__\n"


def test_format_numbers_lists():
    text = "1. a\n1. b\n   more\n7. c\n   1. x\n   1. y\n\npara\n\n3. d\n3. e\n"
    renumbered = MARKDOWN.format(text, {"numbering": "renumber"})
    assert renumbered == "1. a\n2. b\n   more\n3. c\n   1. x\n   2. y\n\npara\n\n3. d\n4. e\n"
    assert MARKDOWN.format(text, {"numbering": "ones"}).count("1. ") == 7
    assert MARKDOWN.format(text) == text


def test_format_keeps_the_chosen_number_of_blank_lines():
    assert MARKDOWN.format("a\n\n\n\n\nb\n", {"blank_lines": 2}) == "a\n\n\nb\n"


def test_format_aligns_pipe_tables():
    text = "| a | long header |\n|:-|-:|\n| wide cell | 1 |\n|x|`a|b`|\n\nafter\n"
    assert MARKDOWN.format(text) == (
        "| a         | long header |\n"
        "| :-------- | ----------: |\n"
        "| wide cell |           1 |\n"
        "| x         |       `a|b` |\n"
        "\n"
        "after\n"
    )
    assert MARKDOWN.format(text, {"align_tables": False}) == text


def test_align_table_centres_and_counts_wide_characters():
    assert align_table(["|h|", "|:-:|", "|中|"]) == ["|  h  |", "| :-: |", "| 中  |"]


# --- JSON, XML, YAML, CSV and TSV (N31 step 6) -------------------------------------


def test_every_structured_environment_declares_its_settings():
    assert [s.key for s in declarations_for("json")] == ["indent", "sort_keys", "ascii"]
    assert [s.key for s in declarations_for("xml")] == ["indent", "attributes"]
    assert [s.key for s in declarations_for("yaml")] == ["indent"]
    assert [s.key for s in declarations_for("csv")] == ["delimiter", "quote", "header"]
    assert [s.key for s in declarations_for("tsv")] == ["header"]
    assert declarations_for("usfm") == ()


def test_json_format_follows_indent_sort_and_ascii():
    from uniti.core.reformatters import JSON

    text = '{"b": 1, "a": ["é"]}'
    assert JSON.format(text) == '{\n  "b": 1,\n  "a": [\n    "é"\n  ]\n}\n'
    assert JSON.format(text, {"indent": 4, "sort_keys": True, "ascii": True}) == (
        '{\n    "a": [\n        "\\u00e9"\n    ],\n    "b": 1\n}\n'
    )


def test_xml_format_follows_indent_and_attribute_wrapping():
    from uniti.core.reformatters import XML

    text = '<root><item id="1" kind="a&amp;b"><x/></item></root>'
    assert XML.format(text, {"indent": 4}) == '<root>\n    <item id="1" kind="a&amp;b">\n        <x/>\n    </item>\n</root>\n'
    assert XML.format(text, {"attributes": "wrapped"}) == (
        '<root>\n  <item id="1"\n        kind="a&amp;b">\n    <x/>\n  </item>\n</root>\n'
    )


def _context_for(text: str):
    from uniti.core.environment import EnvironmentContext
    from uniti.core.resource_profile import ResourceProfile

    class Edits:
        def iter_text(self):
            yield 0, text

        def total_chars(self):
            return len(text)

    return EnvironmentContext(Edits(), ResourceProfile(size_bytes=len(text)))  # type: ignore[arg-type]


def test_yaml_check_indentation_warns_about_off_width_indents(user_root: Path):
    from uniti.core.environments.yaml_environment import YamlEnvironment

    text = "a:\n  b: 1\n   c: 2\n  # comment\n d: |\n     free text\n       any indent\ne: 1\n"
    findings = YamlEnvironment().validate(_context_for(text))
    assert [(f.message, text[f.start : f.end + 1]) for f in findings] == [
        ("indented 3 spaces, not a multiple of 2", "   c"),
        ("indented 1 spaces, not a multiple of 2", " d"),
    ]
    store_environment_settings("yaml", environment_settings("yaml").with_values({"indent": 1}))
    assert YamlEnvironment().validate(_context_for(text)) == ()


def test_csv_check_uses_the_delimiter_quote_and_header_settings(user_root: Path):
    from uniti.core.environments.delimited_environment import CsvEnvironment

    text = "a;b\n'x;y';2\n1;2;3\n"
    store_environment_settings("csv", environment_settings("csv").with_values({"delimiter": ";", "quote": "'", "header": False}))
    findings = CsvEnvironment().validate(_context_for(text))
    assert [f.message for f in findings] == ["row 3 has 3 fields; the first row has 2"]
