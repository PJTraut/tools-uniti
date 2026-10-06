from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from uniti.core.document import Document
from uniti.core.environment import EnvironmentContext
from uniti.core.environment_findings import FindingSeverity
from uniti.core.environments.sfm_environment import SfmEnvironment
from uniti.core.resource_profile import ENVIRONMENT_LARGE_FILE_BYTES, ResourceProfile


@contextmanager
def _context(tmp_path: Path, text: str):
    path = tmp_path / "doc.sfm"
    path.write_text(text, encoding="utf-8")
    with Document.open(path) as document:
        yield EnvironmentContext.for_document(document)


def test_decoration_provider_wraps_the_existing_sfm_syntax_profile():
    environment = SfmEnvironment()

    provider = environment.decoration_provider

    assert provider is not None
    assert provider.key == "sfm"
    tokens, _state = provider.tokenize(r"\v 1 In the beginning", provider.initial_state)
    assert len(tokens) > 0


def test_activate_and_deactivate_never_raise(tmp_path: Path):
    with _context(tmp_path, r"\id GEN") as context:
        environment = SfmEnvironment()

        environment.activate(context)
        environment.deactivate()


def test_validate_reports_no_findings_for_ordinary_unclosed_paragraph_markers(tmp_path: Path):
    with _context(tmp_path, "\\id GEN\n\\c 1\n\\v 1 In the beginning.\n") as context:
        environment = SfmEnvironment()

        assert environment.validate(context) == ()


def test_validate_reports_no_findings_for_a_matched_character_style(tmp_path: Path):
    with _context(tmp_path, r"\v 1 In the \bd beginning\bd* God created.") as context:
        environment = SfmEnvironment()

        assert environment.validate(context) == ()


def test_validate_reports_an_unmatched_end_marker(tmp_path: Path):
    with _context(tmp_path, r"\v 1 stray \bd* end marker") as context:
        environment = SfmEnvironment()

        findings = environment.validate(context)

        assert len(findings) == 1
        assert findings[0].severity == FindingSeverity.ERROR
        assert findings[0].code == "sfm.end-marker-unmatched"


def test_validate_treats_an_empty_document_as_having_no_findings(tmp_path: Path):
    with _context(tmp_path, "") as context:
        environment = SfmEnvironment()

        assert environment.validate(context) == ()


def test_validate_skips_full_parse_on_a_large_file(tmp_path: Path):
    with _context(tmp_path, r"\bd* stray end marker") as context:
        degraded_context = EnvironmentContext(
            edits=context.edits,
            resource_profile=ResourceProfile(size_bytes=ENVIRONMENT_LARGE_FILE_BYTES + 1),
        )
        environment = SfmEnvironment()

        assert environment.validate(degraded_context) == ()
