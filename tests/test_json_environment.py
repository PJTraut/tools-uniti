from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from uniti.core.document import Document
from uniti.core.environment import EnvironmentContext
from uniti.core.environment_findings import FindingSeverity
from uniti.core.environments.json_environment import JsonEnvironment


@contextmanager
def _context(tmp_path: Path, text: str):
    path = tmp_path / "doc.json"
    path.write_text(text, encoding="utf-8")
    with Document.open(path) as document:
        yield EnvironmentContext.for_document(document)


def test_decoration_provider_wraps_the_existing_json_syntax_profile():
    environment = JsonEnvironment()

    provider = environment.decoration_provider

    assert provider is not None
    assert provider.key == "json"
    tokens, _state = provider.tokenize('{"a": 1}', provider.initial_state)
    assert len(tokens) > 0


def test_activate_and_deactivate_never_raise(tmp_path: Path):
    with _context(tmp_path, "{}") as context:
        environment = JsonEnvironment()

        environment.activate(context)
        environment.deactivate()


def test_validate_reports_no_findings_for_well_formed_json(tmp_path: Path):
    with _context(tmp_path, '{"a": [1, 2, {"b": 3}]}') as context:
        environment = JsonEnvironment()

        assert environment.validate(context) == ()


def test_validate_reports_unmatched_closer(tmp_path: Path):
    with _context(tmp_path, '{"a": 1}}') as context:
        environment = JsonEnvironment()

        findings = environment.validate(context)

        assert len(findings) == 1
        assert findings[0].severity == FindingSeverity.ERROR
        assert findings[0].code == "json.bracket-mismatch"
        assert findings[0].start == 8


def test_validate_reports_unclosed_opener(tmp_path: Path):
    with _context(tmp_path, '{"a": [1, 2') as context:
        environment = JsonEnvironment()

        findings = environment.validate(context)

        assert {f.code for f in findings} == {"json.bracket-unclosed"}
        assert len(findings) == 2  # both the outer { and the inner [


def test_validate_ignores_brackets_inside_string_literals(tmp_path: Path):
    with _context(tmp_path, '{"a": "} unbalanced { on purpose"}') as context:
        environment = JsonEnvironment()

        assert environment.validate(context) == ()


def test_validate_handles_escaped_quotes_inside_strings(tmp_path: Path):
    with _context(tmp_path, r'{"a": "she said \"hi\""}') as context:
        environment = JsonEnvironment()

        assert environment.validate(context) == ()
