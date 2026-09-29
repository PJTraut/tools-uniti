from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from uniti.core.document import Document
from uniti.core.environment import EnvironmentContext
from uniti.core.resource_profile import ENVIRONMENT_LARGE_FILE_BYTES, ResourceProfile
from uniti.core.environment_findings import FindingSeverity
from uniti.core.environments.xml_environment import XmlEnvironment


@contextmanager
def _context(tmp_path: Path, text: str):
    path = tmp_path / "doc.xml"
    path.write_text(text, encoding="utf-8")
    with Document.open(path) as document:
        yield EnvironmentContext.for_document(document)


def test_decoration_provider_wraps_the_existing_xml_syntax_profile():
    environment = XmlEnvironment()

    provider = environment.decoration_provider

    assert provider is not None
    assert provider.key == "xml"
    tokens, _state = provider.tokenize("<a>text</a>", provider.initial_state)
    assert len(tokens) > 0


def test_validate_reports_no_findings_for_well_formed_xml(tmp_path: Path):
    with _context(tmp_path, "<a><b>text</b></a>") as context:
        environment = XmlEnvironment()

        assert environment.validate(context) == ()


def test_validate_reports_mismatched_tag(tmp_path: Path):
    with _context(tmp_path, "<a><b></a>") as context:
        environment = XmlEnvironment()

        findings = environment.validate(context)

        assert len(findings) == 1
        assert findings[0].severity == FindingSeverity.ERROR
        assert findings[0].code == "xml.not-well-formed"


def test_validate_treats_an_empty_document_as_having_no_findings(tmp_path: Path):
    with _context(tmp_path, "") as context:
        environment = XmlEnvironment()

        assert environment.validate(context) == ()


def test_validate_skips_full_parse_on_a_large_file(tmp_path: Path):
    # Malformed XML that would normally be reported...
    with _context(tmp_path, "<a><b></a>") as context:
        # ...but with a resource profile that denies full parse, matching
        # how this environment must degrade rather than materialize an
        # arbitrarily huge document into an ElementTree.
        degraded_context = EnvironmentContext(
            edits=context.edits,
            resource_profile=ResourceProfile(
                size_bytes=ENVIRONMENT_LARGE_FILE_BYTES + 1
            ),
        )
        environment = XmlEnvironment()

        assert environment.validate(degraded_context) == ()
