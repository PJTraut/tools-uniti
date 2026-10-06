from __future__ import annotations

import pytest

from uniti.app.file_environment_manager import FileEnvironmentManager
from uniti.core.environments.catalog import (
    ENVIRONMENTS,
    ENVIRONMENTS_BY_KEY,
    ExtensionAssignmentError,
    descriptor_for_key,
    environment_key_for_extension,
    extension_assignments,
    normalize_extension,
    overrides_for_assignments,
)
from uniti.core.syntax_profiles import PROFILES


def test_every_syntax_profile_has_exactly_one_environment():
    assert [descriptor.key for descriptor in ENVIRONMENTS] == [profile.key for profile in PROFILES]
    for descriptor in ENVIRONMENTS:
        assert descriptor.profile.key == descriptor.key
        assert descriptor.factory().key == descriptor.key


def test_descriptor_for_unknown_key_is_plain_text():
    assert descriptor_for_key("nope").key == "plain_text"
    assert descriptor_for_key(None).key == "plain_text"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(".USFM", "usfm"), ("sfm", "sfm"), ("  .Md ", "md"), ("a.b", None), ("", None), (".", None)],
)
def test_normalize_extension(raw, expected):
    assert normalize_extension(raw) == expected


def test_resolution_is_case_insensitive_and_honors_overrides():
    assert environment_key_for_extension(".USFM") == "usfm"
    assert environment_key_for_extension(".sfm") == "sfm"
    assert environment_key_for_extension(".SFM", {"sfm": "usfm"}) == "usfm"
    assert environment_key_for_extension(".txt") == "plain_text"
    assert environment_key_for_extension(".json", {"json": "no-such-env"}) == "plain_text"


def test_assigning_usfm_and_sfm_to_usfm_is_one_override():
    assignments = dict(extension_assignments())
    assignments["usfm"] = (".USFM", ".sfm")
    assignments["sfm"] = ()

    overrides = overrides_for_assignments(assignments)

    assert overrides == {"sfm": "usfm"}
    assert extension_assignments(overrides)["usfm"] == ("sfm", "usfm")
    assert extension_assignments(overrides)["sfm"] == ()


def test_unchanged_assignments_produce_no_overrides():
    assert overrides_for_assignments(extension_assignments()) == {}


def test_removing_a_default_extension_forces_it_to_plain_text():
    assignments = dict(extension_assignments())
    assignments["yaml"] = ("yaml",)

    assert overrides_for_assignments(assignments) == {"yml": "plain_text"}
    assert environment_key_for_extension("yml", {"yml": "plain_text"}) == "plain_text"


def test_new_extension_can_be_added_to_an_environment():
    assignments = dict(extension_assignments())
    assignments["json"] = ("json", "usj")

    assert overrides_for_assignments(assignments) == {"usj": "json"}


def test_extension_claimed_twice_is_rejected():
    assignments = dict(extension_assignments())
    assignments["usfm"] = ("usfm", "sfm")

    with pytest.raises(ExtensionAssignmentError, match="both"):
        overrides_for_assignments(assignments)


def test_invalid_extension_and_unknown_environment_are_rejected():
    with pytest.raises(ExtensionAssignmentError, match="not a file extension"):
        overrides_for_assignments({**extension_assignments(), "json": ("json", "a/b")})
    with pytest.raises(ExtensionAssignmentError, match="unknown environment"):
        overrides_for_assignments({"nope": ("x",)})


def test_builtin_manager_registers_every_catalog_environment():
    manager = FileEnvironmentManager.with_builtin_environments()

    assert all(manager.is_registered(key) for key in ENVIRONMENTS_BY_KEY)
    assert manager.resolve_key(".sfm", {"sfm": "usfm"}) == "usfm"
