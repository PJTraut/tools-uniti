from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from uniti.app.file_environment_manager import FileEnvironmentManager
from uniti.core.document import Document
from uniti.core.environment import EnvironmentContext, PlainEnvironment
from uniti.core.environment_commands import (
    EnvironmentCommand,
    NavigateTo,
    ReplaceDocumentText,
    ShowFindings,
    ShowMessage,
    environment_commands,
    validate_command,
)
from uniti.core.environments import (
    CsvEnvironment,
    JsonEnvironment,
    MarkdownEnvironment,
    TsvEnvironment,
    UsfmEnvironment,
    XmlEnvironment,
)
from uniti.core.environments.catalog import ENVIRONMENTS
from uniti.core.environments.delimited_environment import column_count_findings
from uniti.core.environments.markdown_environment import MARKDOWN_PREVIEW_FEATURE
from uniti.core.resource_profile import ENVIRONMENT_LARGE_FILE_BYTES, ResourceProfile

_USFM = (
    "\\id GEN\n\\c 1\n\\p\n\\v 1 In the beginning\n\\v 2 And\n"
    "\\c 3\n\\v 15 Enmity\n\\v 16-17 Pain\n"
)


@contextmanager
def _context(tmp_path: Path, text: str, name: str = "doc.txt"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8", newline="")
    with Document.open(path) as document:
        yield EnvironmentContext.for_document(document)


def _command(environment, command_id: str) -> EnvironmentCommand:
    return next(c for c in environment_commands(environment) if c.command_id == command_id)


def test_every_environment_offers_well_formed_commands():
    for descriptor in ENVIRONMENTS:
        commands = environment_commands(descriptor.factory())
        ids = [command.command_id for command in commands]
        assert len(ids) == len(set(ids)), descriptor.key
    assert environment_commands(PlainEnvironment()) == ()


def test_command_needs_exactly_one_implementation():
    with pytest.raises(ValueError):
        EnvironmentCommand("x", "X")
    with pytest.raises(ValueError):
        EnvironmentCommand("x", "X", run=lambda c, a: None, host_feature="f")


def test_environment_commands_tolerates_a_broken_environment():
    class Broken:
        def commands(self):
            raise RuntimeError("boom")

    assert environment_commands(Broken()) == ()
    assert environment_commands(object()) == ()


def test_json_format_and_minify(tmp_path: Path):
    environment = JsonEnvironment()
    with _context(tmp_path, '{"a": [1, 2]}') as context:
        formatted = _command(environment, "format").run(context, None)
        minified = _command(environment, "minify").run(context, None)
    assert isinstance(formatted, ReplaceDocumentText) and '\n  "a"' in formatted.text
    assert minified == ReplaceDocumentText('{"a":[1,2]}')


def test_format_failure_is_an_error_message_not_an_exception(tmp_path: Path):
    with _context(tmp_path, "{invalid") as context:
        result = _command(JsonEnvironment(), "format").run(context, None)
    assert isinstance(result, ShowMessage) and result.level == "error"
    assert "line 1" in result.text


def test_xml_offers_format_minify_and_validate():
    ids = [command.command_id for command in environment_commands(XmlEnvironment())]
    assert ids == ["format", "minify", "validate"]


def test_validate_reports_findings_and_large_file_skips(tmp_path: Path):
    command = _command(JsonEnvironment(), "validate")
    with _context(tmp_path, '{"a": [1}') as context:
        result = command.run(context, None)
        large = EnvironmentContext(
            edits=context.edits,
            resource_profile=ResourceProfile(size_bytes=ENVIRONMENT_LARGE_FILE_BYTES + 1),
        )
        skipped = command.run(large, None)
    assert isinstance(result, ShowFindings) and result.findings
    assert isinstance(skipped, ShowMessage) and "too large" in skipped.text


def test_validate_command_wraps_any_validate_method(tmp_path: Path):
    with _context(tmp_path, "fine") as context:
        result = validate_command(PlainEnvironment()).run(context, None)
    assert result == ShowFindings("Validate Document", ())


def test_markdown_declares_preview_as_a_host_feature_plus_format():
    commands = environment_commands(MarkdownEnvironment())
    assert commands[0].host_feature == MARKDOWN_PREVIEW_FEATURE and commands[0].run is None
    assert [c.command_id for c in commands] == ["preview", "format"]


@pytest.mark.parametrize(
    ("argument", "verse_text"),
    [("1:2", "\\v 2"), ("3:16", "\\v 16-17"), ("3:17", "\\v 16-17"), ("3", "\\v 15"), (" 1 . 1 ", "\\v 1")],
)
def test_usfm_go_to_verse(tmp_path: Path, argument: str, verse_text: str):
    with _context(tmp_path, _USFM, "book.usfm") as context:
        result = _command(UsfmEnvironment(), "go_to").run(context, argument)
    assert isinstance(result, NavigateTo)
    assert _USFM[result.offset :].startswith(verse_text)


@pytest.mark.parametrize("argument", ["2:1", "9", "abc", ""])
def test_usfm_go_to_verse_reports_missing_or_invalid(tmp_path: Path, argument: str):
    with _context(tmp_path, _USFM, "book.usfm") as context:
        result = _command(UsfmEnvironment(), "go_to").run(context, argument)
    assert isinstance(result, ShowMessage)


def test_usfm_go_to_verse_prompts():
    command = _command(UsfmEnvironment(), "go_to")
    assert command.prompt and command.group == "navigate"


def test_csv_column_counts_respect_quoted_fields():
    text = 'a,b,c\n1,"x,y",3\n4,5\n6,"multi\nline",7\n8,9,10,11\n'
    findings = column_count_findings(text, ",", "csv")
    assert [f.message for f in findings] == [
        "row 3 has 2 fields; expected 3",
        "row 6 has 4 fields; expected 3",
    ]
    assert text[findings[0].start : findings[0].end] == "4,5"


def test_tsv_environment_validates_through_its_command(tmp_path: Path):
    with _context(tmp_path, "a\tb\n1\t2\t3\n") as context:
        result = _command(TsvEnvironment(), "validate").run(context, None)
    assert isinstance(result, ShowFindings) and len(result.findings) == 1
    assert CsvEnvironment().key == "csv"


def test_active_for_caches_per_document_and_switches_on_reassignment(tmp_path: Path):
    manager = FileEnvironmentManager.with_builtin_environments()
    path = tmp_path / "book.sfm"
    path.write_text(_USFM, encoding="utf-8")
    with Document.open(path) as document:
        first = manager.active_for(document, "sfm")
        assert manager.active_for(document, "sfm") is first
        switched = manager.active_for(document, "usfm")
        assert switched.key == "usfm" and isinstance(switched.environment, UsfmEnvironment)
        assert not switched.failed
        manager.release(document)
        assert manager.active_for(document, "usfm") is not switched


def test_failed_activation_is_plain_text_within_the_environment(tmp_path: Path):
    class Exploding:
        key = "json"

        def activate(self, context):
            raise RuntimeError("boom")

    manager = FileEnvironmentManager()
    manager.register("json", Exploding)
    path = tmp_path / "a.json"
    path.write_text("{}", encoding="utf-8")
    with Document.open(path) as document:
        active = manager.active_for(document, "json")
    assert active.key == "json"
    assert active.failed is True
    assert isinstance(active.environment, PlainEnvironment)


def test_unregistered_key_is_not_reported_as_a_failure(tmp_path: Path):
    path = tmp_path / "a.txt"
    path.write_text("x", encoding="utf-8")
    with Document.open(path) as document:
        assert FileEnvironmentManager().active_for(document, "markdown").failed is False
