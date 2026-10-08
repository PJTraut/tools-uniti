"""Per-environment user configuration and the configuration-file list
(field test round 2, R8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from uniti.core.environments import user_config
from uniti.core.environments.configuration import (
    BUILT_IN,
    PROJECT,
    YOURS,
    configuration_files,
    reference_copy_path,
    uniti_rules_template,
)
from uniti.core.environments.sfm.paratext_project import PARATEXT_BOOKS
from uniti.core.environments.sfm.sty import parse_raw_stylesheet
from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry, StyleOrigin, build_layers
from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline
from uniti.core.environments.sfm.views import presentation_attrs


@pytest.fixture
def user_root(tmp_path: Path):
    root = tmp_path / "user-data"
    user_config.set_user_config_root(root)
    yield root
    user_config.set_user_config_root(None)


def test_the_user_folder_is_per_environment(user_root: Path):
    assert user_config.environment_folder("USFM") == user_root / "Environments" / "USFM"
    assert not (user_root / "Environments").exists()
    assert user_config.environment_folder("Markdown", create=True).is_dir()
    assert user_config.usfm_user_rules_path() == user_root / "Environments" / "USFM" / "uniti.sty"
    assert user_config.usfm_versification_folder() == user_root / "Environments" / "USFM" / "Versification"


def test_no_root_no_user_files():
    user_config.set_user_config_root(None)
    assert user_config.usfm_user_rules_path() is None
    rows = configuration_files("usfm", "USFM", None)
    assert rows[0].path is None and not rows[0].exists


def test_your_rules_sit_between_the_built_in_rules_and_the_project(user_root: Path, tmp_path: Path):
    rules = user_config.usfm_user_rules_path()
    rules.parent.mkdir(parents=True)
    rules.write_text("\\Marker nd\n\\Underline\n\\SmallCaps -\n", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    (project / "custom.sty").write_text("\\Marker nd\n\\Italic\n", encoding="utf-8")

    styles = LayeredStyleRegistry(build_layers(load_usfm_baseline(), project / "GEN.usfm"))

    assert [layer.origin for layer in styles.layers] == [
        StyleOrigin.USFM_BASE,
        StyleOrigin.UNITI_BUILTIN,
        StyleOrigin.UNITI_USER,
        StyleOrigin.PROJECT,
    ]
    assert styles.layers[2].name == "uniti.sty (yours)"
    # Yours wins over the built-in small caps; the project's custom.sty adds italic.
    assert presentation_attrs(styles, "nd", block=False) == {"underline": "yes", "italic": "yes"}


def test_the_list_for_a_single_file(user_root: Path, tmp_path: Path):
    rows = configuration_files("usfm", "USFM", tmp_path / "loose" / "GEN.usfm")
    roles = [row.role for row in rows]
    assert roles == [
        "Your USFM configuration folder",
        "Official USFM stylesheet",
        "UNITI built-in rules",
        "Your rules (every USFM file)",
        "Project stylesheet (usfm.sty)",
        "Project custom stylesheet",
        "PTXprint changes",
        "Project rules (UNITI only)",
        "Your versification files",
    ]
    by_role = {row.role: row for row in rows}
    assert by_role["Official USFM stylesheet"].kind == BUILT_IN and by_role["Official USFM stylesheet"].exists
    assert not by_role["Official USFM stylesheet"].editable
    assert by_role["Your rules (every USFM file)"].kind == YOURS and by_role["Your rules (every USFM file)"].template
    assert by_role["Project custom stylesheet"].kind == PROJECT and by_role["Project custom stylesheet"].template
    assert by_role["PTXprint changes"].template is None  # PTXprint's own file
    # Other environments: just the user's folder.
    assert [row.role for row in configuration_files("json", "JSON", tmp_path / "a.json")] == [
        "Your JSON configuration folder"
    ]


def test_the_list_for_a_project_book(user_root: Path, tmp_path: Path):
    project = tmp_path / "NIV"
    project.mkdir()
    present = "".join("1" if code == "GEN" else "0" for code in PARATEXT_BOOKS)
    (project / "Settings.xml").write_text(
        "<ScriptureText><Name>NIV</Name><StyleSheet>usfm_sb.sty</StyleSheet>"
        f'<Naming PrePart="" PostPart="NIV.SFM" BookNameForm="41MAT" /><BooksPresent>{present}</BooksPresent>'
        "</ScriptureText>",
        encoding="utf-8",
    )
    (project / "usfm_sb.sty").write_text("\\Marker p\n", encoding="utf-8")
    rows = {row.role: row for row in configuration_files("usfm", "USFM", project / "01GENNIV.SFM")}

    assert rows["Project stylesheet (usfm_sb.sty)"].exists
    assert rows["Project settings (Settings.xml)"].exists
    assert not rows["Project book names (BookNames.xml)"].exists
    assert "Project versification changes (custom.vrs)" in rows


def test_the_rules_template_explains_and_holds_the_built_in_rules_commented_out(user_root: Path):
    template = uniti_rules_template("test")
    assert template.startswith("# uniti.sty - test.")
    assert "# \\Marker p+q1, p+q2, p+q3, q1+p, q2+p, q3+p" in template
    assert "# \\Marker nd" in template
    assert parse_raw_stylesheet(template).records == ()  # nothing active until uncommented


def test_built_in_files_are_copied_for_reading(user_root: Path):
    built_in = next(row for row in configuration_files("usfm", "USFM", None) if row.kind == BUILT_IN)
    assert reference_copy_path("USFM", built_in.path) == user_root / "Environments" / "USFM" / "Reference" / "usfm.sty"
