"""SFM files belong to the USFM environment (field test round 2, R5).

The generic SFM environment and profile were retired on 2026-10-08: `.sfm`
and `.usfm`, in any case, open as USFM, and anything saved under the old
`sfm` key is read as `usfm`.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from uniti.core.document import Document
from uniti.core.environment import EnvironmentContext
from uniti.core.environment_findings import FindingSeverity
from uniti.core.environments import UsfmEnvironment
from uniti.core.environments.catalog import (
    ENVIRONMENTS_BY_KEY,
    descriptor_for_key,
    environment_key_for_extension,
    extension_assignments,
)
from uniti.core.environments.sfm.validation import unmatched_end_marker_findings
from uniti.core.syntax_profiles import PROFILES, PROFILES_BY_KEY, USFM, canonical_key, profile_for_extension


@contextmanager
def _context(tmp_path: Path, text: str, name: str = "doc.sfm"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    with Document.open(path) as document:
        yield EnvironmentContext.for_document(document)


def test_sfm_and_usfm_extensions_open_as_usfm():
    for extension in (".sfm", ".SFM", "usfm", ".USFM"):
        assert environment_key_for_extension(extension) == "usfm"
    assert "sfm" not in ENVIRONMENTS_BY_KEY
    assert [profile.key for profile in PROFILES].count("usfm") == 1
    assert "sfm" not in [profile.key for profile in PROFILES]
    assert set(extension_assignments()["usfm"]) >= {"sfm", "usfm"}
    assert profile_for_extension(".SFM") is USFM


def test_anything_saved_under_the_old_sfm_key_reads_as_usfm():
    assert canonical_key("sfm") == "usfm" and canonical_key("json") == "json" and canonical_key(None) is None
    # An extension override, a per-view syntax choice, a descriptor lookup.
    assert environment_key_for_extension(".txt", {"txt": "sfm"}) == "usfm"
    assert extension_assignments({"lex": "sfm"})["usfm"].count("lex") == 1
    assert PROFILES_BY_KEY["sfm"] is USFM
    assert descriptor_for_key("sfm").key == "usfm"


def test_a_saved_sfm_pin_is_restored_as_usfm():
    from types import SimpleNamespace

    from uniti.app.session_controller import SessionController

    entry = SimpleNamespace(environment_override=None, environment_key="plain_text")
    SessionController._restore_entry_environment(entry, SimpleNamespace(extra={"environment_override": "sfm"}))
    assert (entry.environment_override, entry.environment_key) == ("usfm", "usfm")


def test_usfm_highlighting_marks_every_marker_form():
    provider = UsfmEnvironment().decoration_provider
    assert provider is not None and provider.key == "usfm"
    line = '\\v 1 \\nd Lord \\+it God\\+it*\\nd* \\qt-s |who="P"\\*Hi\\qt-e\\*'
    tokens, _state = provider.tokenize(line, provider.initial_state)
    marked = {line[token.start : token.end] for token in tokens}
    assert {"\\v", "\\nd", "\\+it", "\\+it*", "\\nd*", "\\qt-s", "\\*", "\\qt-e"} <= marked


def test_an_sfm_file_gets_the_usfm_stylesheets_and_checks(tmp_path: Path):
    with _context(tmp_path, "\\id GEN\n\\c 1\n\\p\n\\v 1 In the \\bd beginning\\bd*.\n") as context:
        environment = UsfmEnvironment()
        environment.activate(context)
        assert environment.layered_styles.style_for("bd") is not None
        environment.deactivate()
    findings = unmatched_end_marker_findings(r"\v 1 stray \bd* end marker")
    assert len(findings) == 1
    assert findings[0].severity == FindingSeverity.ERROR
    assert findings[0].code == "sfm.end-marker-unmatched"
