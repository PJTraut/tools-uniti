from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from uniti.core.document import Document
from uniti.core.environment import EnvironmentContext
from uniti.core.environment_findings import FindingSeverity
from uniti.core.environments.yaml_environment import YamlEnvironment


@contextmanager
def _context(tmp_path: Path, text: str):
    path = tmp_path / "doc.yaml"
    path.write_text(text, encoding="utf-8")
    with Document.open(path) as document:
        yield EnvironmentContext.for_document(document)


def test_decoration_provider_wraps_the_existing_yaml_syntax_profile():
    environment = YamlEnvironment()

    provider = environment.decoration_provider

    assert provider is not None
    assert provider.key == "yaml"


def test_validate_reports_no_findings_for_space_indented_yaml(tmp_path: Path):
    with _context(tmp_path, "a:\n  b: 1\n  c: 2\n") as context:
        environment = YamlEnvironment()

        assert environment.validate(context) == ()


def test_validate_reports_a_tab_used_for_indentation(tmp_path: Path):
    with _context(tmp_path, "a:\n\tb: 1\n") as context:
        environment = YamlEnvironment()

        findings = environment.validate(context)

        assert len(findings) == 1
        assert findings[0].severity == FindingSeverity.ERROR
        assert findings[0].code == "yaml.tab-indentation"


def test_validate_reports_one_finding_per_offending_line_not_per_tab(tmp_path: Path):
    with _context(tmp_path, "a:\n\t\tb: 1\n") as context:
        environment = YamlEnvironment()

        findings = environment.validate(context)

        assert len(findings) == 1


def test_validate_ignores_a_tab_that_is_not_leading_indentation(tmp_path: Path):
    with _context(tmp_path, "a: \tvalue-with-a-tab-inside\n") as context:
        environment = YamlEnvironment()

        assert environment.validate(context) == ()
