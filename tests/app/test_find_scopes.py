from __future__ import annotations

import pytest

from uniti.app import find_scopes


def test_an_environment_with_no_scopes_of_its_own_gets_the_defaults():
    assert find_scopes.scopes_for_environment("json") == find_scopes.DEFAULT_SCOPES
    assert find_scopes.scopes_for_environment(None) == find_scopes.DEFAULT_SCOPES


def test_a_registered_environment_gets_its_own_scopes(monkeypatch):
    monkeypatch.setattr(find_scopes, "_ENVIRONMENT_SCOPES", {})

    find_scopes.register_scopes("demo", ("whole_document", "current_group"))

    assert find_scopes.scopes_for_environment("demo") == ("whole_document", "current_group")
    assert find_scopes.scopes_for_environment("json") == find_scopes.DEFAULT_SCOPES


def test_an_environment_needs_at_least_one_scope(monkeypatch):
    monkeypatch.setattr(find_scopes, "_ENVIRONMENT_SCOPES", {})

    with pytest.raises(ValueError):
        find_scopes.register_scopes("demo", ())
