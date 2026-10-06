from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from uniti.core.document import Document
from uniti.core.environment import EnvironmentContext
from uniti.core.environments.usfm_environment import UsfmEnvironment
from uniti.core.resource_profile import ENVIRONMENT_LARGE_FILE_BYTES, ResourceProfile

_WELL_FORMED = "\\id GEN\n\\usfm 3.1\n\\c 1\n\\v 1 In the beginning God created the heavens and the earth.\n"


@contextmanager
def _context(tmp_path: Path, text: str):
    path = tmp_path / "doc.usfm"
    path.write_text(text, encoding="utf-8")
    with Document.open(path) as document:
        yield EnvironmentContext.for_document(document)


def test_decoration_provider_wraps_the_usfm_syntax_profile():
    environment = UsfmEnvironment()

    provider = environment.decoration_provider

    assert provider is not None
    assert provider.key == "usfm"
    tokens, _state = provider.tokenize(r"\v 1 In the beginning", provider.initial_state)
    assert len(tokens) > 0


def test_activate_and_deactivate_never_raise(tmp_path: Path):
    with _context(tmp_path, _WELL_FORMED) as context:
        environment = UsfmEnvironment()

        environment.activate(context)
        environment.deactivate()


def test_style_registry_has_baseline_structural_knowledge():
    environment = UsfmEnvironment()

    assert environment.style_registry.occurs_under("usfm") == ("id",)
    assert environment.style_registry.style_for("missing-marker") is None


def test_validate_reports_no_findings_for_well_formed_usfm(tmp_path: Path):
    with _context(tmp_path, _WELL_FORMED) as context:
        environment = UsfmEnvironment()

        assert environment.validate(context) == ()


def test_validate_reports_an_unmatched_end_marker(tmp_path: Path):
    with _context(tmp_path, r"\v 1 stray \bd* end marker") as context:
        environment = UsfmEnvironment()

        findings = environment.validate(context)

        assert any(f.code == "sfm.end-marker-unmatched" for f in findings)


def test_validate_reports_usfmtc_reference_findings(tmp_path: Path):
    text = "\\id GEN\n\\usfm 3.1\n\\c 1\n\\v 1 Text \\zzzcustom stuff\\zzzcustom* here.\n"
    with _context(tmp_path, text) as context:
        environment = UsfmEnvironment()

        findings = environment.validate(context)

        assert any(f.code == "usfm.usfmtc-reference" for f in findings)


def test_validate_skips_full_parse_on_a_large_file(tmp_path: Path):
    with _context(tmp_path, r"\bd* stray end marker") as context:
        degraded_context = EnvironmentContext(
            edits=context.edits,
            resource_profile=ResourceProfile(size_bytes=ENVIRONMENT_LARGE_FILE_BYTES + 1),
        )
        environment = UsfmEnvironment()

        assert environment.validate(degraded_context) == ()


def test_chapter_verse_index_reports_locations(tmp_path: Path):
    with _context(tmp_path, _WELL_FORMED) as context:
        environment = UsfmEnvironment()

        index = environment.chapter_verse_index(context)

        assert [(loc.chapter, loc.verse) for loc in index] == [("1", "1")]


def test_chapter_verse_index_skips_full_parse_on_a_large_file(tmp_path: Path):
    with _context(tmp_path, _WELL_FORMED) as context:
        degraded_context = EnvironmentContext(
            edits=context.edits,
            resource_profile=ResourceProfile(size_bytes=ENVIRONMENT_LARGE_FILE_BYTES + 1),
        )
        environment = UsfmEnvironment()

        assert environment.chapter_verse_index(degraded_context) == ()
