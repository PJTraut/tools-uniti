"""Which Find/Replace scopes each environment offers (scopes plan D1, S1).

A scope is named by its `ReplaceScope` value (a string), so this module needs
nothing from the UI. An environment that has its own scopes registers them
here (USFM's Book, Project and Group arrive with S2); every other
environment gets `DEFAULT_SCOPES`. "All Open Documents" is always limited to
the current document's environment, never a pool across environments.
"""

from __future__ import annotations

from uniti.core.environments.catalog import PROJECT_ENVIRONMENTS

DEFAULT_SCOPES: tuple[str, ...] = (
    "whole_document",
    "cursor_to_end",
    "current_group",
    "all_open_documents",
)

# USFM (scopes plan D2): the book, to the end of it, the project's books,
# the books of the group's open projects.
PROJECT_SCOPES: tuple[str, ...] = ("book", "cursor_to_end", "project", "project_group")

_ENVIRONMENT_SCOPES: dict[str, tuple[str, ...]] = {}


def register_scopes(environment_key: str, scopes: tuple[str, ...]) -> None:
    """Give `environment_key` its own scope list, in the order shown."""

    if not scopes:
        raise ValueError("an environment needs at least one scope")
    _ENVIRONMENT_SCOPES[environment_key] = tuple(scopes)


def scopes_for_environment(environment_key: str | None) -> tuple[str, ...]:
    """The scope values `environment_key` offers, in the order shown."""

    return _ENVIRONMENT_SCOPES.get(environment_key or "", DEFAULT_SCOPES)


for _key in PROJECT_ENVIRONMENTS:
    register_scopes(_key, PROJECT_SCOPES)
