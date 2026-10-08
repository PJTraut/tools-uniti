"""Versification: mapping references between numberings (plan P4)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from uniti.core.environments import user_config
from uniti.core.environments.sfm.paratext_project import PARATEXT_BOOKS
from uniti.core.environments.sfm.versification import (
    available_versifications,
    load_versification,
    map_reference,
    versification_for,
    versification_path,
)


@pytest.fixture
def user_root(tmp_path: Path):
    user_config.set_user_config_root(tmp_path / "user")
    yield tmp_path / "user"
    user_config.set_user_config_root(None)


@pytest.mark.parametrize(
    ("book", "english", "original"),
    [
        ("PSA", ("51", "1"), ("51", "3")),  # psalm titles
        ("MAL", ("4", "1"), ("3", "19")),
        ("JOL", ("2", "28"), ("3", "1")),
        ("GEN", ("1", "1"), ("1", "1")),
    ],
)
def test_english_and_original_map_both_ways(book, english, original):
    eng, org = load_versification("eng"), load_versification("org")
    assert map_reference(book, *english, eng, org) == original
    assert map_reference(book, *original, org, eng) == english


def test_bridges_and_parts_map_by_their_first_verse_and_the_rest_is_left_alone():
    eng, org = load_versification("eng"), load_versification("org")
    assert map_reference("PSA", "51", "1-2", eng, org) == ("51", "3")
    assert map_reference("PSA", "51", "1a", eng, org) == ("51", "3")
    assert map_reference(None, "51", "1", eng, org) == ("51", "1")
    assert map_reference("PSA", "51", None, eng, org) == ("51", None)
    assert map_reference("PSA", "51", "1", eng, eng) == ("51", "1")


def test_a_missing_file_falls_back_to_english(user_root: Path):
    septuagint = load_versification("lxx")
    assert septuagint.stem == "eng" and septuagint.fell_back
    assert septuagint.label == "English (Septuagint file missing)"
    assert "lxx" not in available_versifications()


def test_your_versification_files_are_used(user_root: Path):
    folder = user_config.usfm_versification_folder()
    folder.mkdir(parents=True)
    shutil.copyfile(versification_path("org"), folder / "lxx.vrs")  # a stand-in file

    assert available_versifications() == ("eng", "org", "lxx")
    septuagint = load_versification("lxx")
    assert septuagint.stem == "lxx" and not septuagint.fell_back
    assert septuagint.label == "Septuagint"


def _project(folder: Path, versification: int) -> Path:
    folder.mkdir(parents=True)
    present = "".join("1" if code == "PSA" else "0" for code in PARATEXT_BOOKS)
    (folder / "Settings.xml").write_text(
        f"<ScriptureText><Name>P</Name><Versification>{versification}</Versification>"
        f'<Naming PrePart="" PostPart="P.SFM" BookNameForm="41MAT" /><BooksPresent>{present}</BooksPresent>'
        "</ScriptureText>",
        encoding="utf-8",
    )
    return folder / "19PSAP.SFM"


def test_a_texts_versification_comes_from_its_choice_its_project_or_english(user_root: Path, tmp_path: Path):
    assert versification_for(tmp_path / "loose.usfm").stem == "eng"
    book = _project(tmp_path / "orig", versification=1)
    assert versification_for(book).stem == "org"
    assert versification_for(book, "eng").stem == "eng"  # its own choice wins


def test_a_projects_custom_vrs_is_layered_on_top(user_root: Path, tmp_path: Path):
    book = _project(tmp_path / "custom", versification=4)
    (book.parent / "custom.vrs").write_text("PSA 51:1 = PSA 51:9\n", encoding="utf-8")

    text = versification_for(book)

    assert text.custom == book.parent / "custom.vrs"
    assert text.label == "English + custom.vrs"
    assert map_reference("PSA", "51", "1", text, load_versification("org")) == ("51", "9")
