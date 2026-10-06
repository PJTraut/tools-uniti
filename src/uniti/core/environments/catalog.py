"""The built-in environment catalog and extension assignment (ADR-0014).

One `EnvironmentDescriptor` per file-type environment: its key, its label,
the `SyntaxProfile` it renders with by default, and a factory. Every
`syntax_profiles.PROFILES` entry has exactly one environment here (keys are
shared — ADR-0013 decision 3), so "which environment is this file" and "which
profile does it render with by default" can never disagree.

Extension assignment: `DEFAULT_EXTENSION_PROFILES` is each environment's
default extension set; `Settings.syntax_extension_overrides` (the existing,
already-persisted extension -> key map, now edited per environment through
View > File Type Environments…) reassigns individual extensions. Extensions
are case-insensitive and stored without the leading dot, so ``.USFM`` and
``.sfm`` both assign the same way.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from uniti.core.environment import Environment, PlainEnvironment
from uniti.core.syntax_profiles import DEFAULT_EXTENSION_PROFILES, PROFILES_BY_KEY, SyntaxProfile

from .delimited_environment import CsvEnvironment, TsvEnvironment
from .json_environment import JsonEnvironment
from .markdown_environment import MarkdownEnvironment
from .sfm_environment import SfmEnvironment
from .usfm_environment import UsfmEnvironment
from .xml_environment import XmlEnvironment
from .yaml_environment import YamlEnvironment

PLAIN_ENVIRONMENT_KEY = PlainEnvironment.key
MAX_EXTENSION_OVERRIDES = 64
_EXTENSION_RE = re.compile(r"[a-z0-9_-]{1,32}")


@dataclass(frozen=True, slots=True)
class EnvironmentDescriptor:
    key: str
    label: str
    factory: Callable[[], Environment]

    @property
    def profile(self) -> SyntaxProfile:
        return PROFILES_BY_KEY[self.key]


def _descriptor(factory: Callable[[], Environment]) -> EnvironmentDescriptor:
    key = factory.key  # type: ignore[attr-defined]
    return EnvironmentDescriptor(key, PROFILES_BY_KEY[key].label, factory)


ENVIRONMENTS: tuple[EnvironmentDescriptor, ...] = tuple(
    _descriptor(factory)
    for factory in (
        PlainEnvironment,
        MarkdownEnvironment,
        XmlEnvironment,
        JsonEnvironment,
        YamlEnvironment,
        SfmEnvironment,
        UsfmEnvironment,
        CsvEnvironment,
        TsvEnvironment,
    )
)
ENVIRONMENTS_BY_KEY: dict[str, EnvironmentDescriptor] = {
    descriptor.key: descriptor for descriptor in ENVIRONMENTS
}


def descriptor_for_key(key: str | None) -> EnvironmentDescriptor:
    """The descriptor for `key`; Plain Text for an unknown or missing key."""

    return ENVIRONMENTS_BY_KEY.get(key or "", ENVIRONMENTS_BY_KEY[PLAIN_ENVIRONMENT_KEY])


def normalize_extension(text: str) -> str | None:
    """``".USFM"`` -> ``"usfm"``; `None` for anything not a plain extension."""

    normalized = text.strip().lower().lstrip(".")
    return normalized if _EXTENSION_RE.fullmatch(normalized) else None


def environment_key_for_extension(
    extension: str, overrides: Mapping[str, str] | None = None
) -> str:
    """Resolve an extension (``"usfm"``, ``".SFM"``) to an environment key.

    An override or default naming an unknown environment falls back to
    Plain Text — a document must always open in *some* environment.
    """

    normalized = extension.strip().lower().lstrip(".")
    key = (overrides or {}).get(normalized) or DEFAULT_EXTENSION_PROFILES.get(normalized)
    return key if key in ENVIRONMENTS_BY_KEY else PLAIN_ENVIRONMENT_KEY


def extension_assignments(
    overrides: Mapping[str, str] | None = None,
) -> dict[str, tuple[str, ...]]:
    """Effective extensions per environment key (defaults with overrides applied).

    Plain Text lists only extensions explicitly reassigned to it — every
    unlisted extension also resolves there, implicitly.
    """

    effective: dict[str, str] = dict(DEFAULT_EXTENSION_PROFILES)
    for extension, key in (overrides or {}).items():
        effective[extension] = key
    assignments: dict[str, list[str]] = {descriptor.key: [] for descriptor in ENVIRONMENTS}
    for extension, key in effective.items():
        assignments.setdefault(key if key in ENVIRONMENTS_BY_KEY else PLAIN_ENVIRONMENT_KEY, []).append(
            extension
        )
    return {key: tuple(sorted(extensions)) for key, extensions in assignments.items()}


class ExtensionAssignmentError(ValueError):
    pass


def overrides_for_assignments(
    assignments: Mapping[str, Iterable[str]],
) -> dict[str, str]:
    """The minimal override map that produces `assignments`.

    `assignments` maps an environment key to the extensions the user wants
    it to own (with or without dots, any case). A default extension the user
    removed from its environment, and did not give to another one, is
    reassigned to Plain Text explicitly — otherwise it would silently snap
    back to its default. Raises `ExtensionAssignmentError` for an invalid
    extension, one claimed by two environments, an unknown environment, or
    more than `MAX_EXTENSION_OVERRIDES` overrides.
    """

    owner: dict[str, str] = {}
    for key, extensions in assignments.items():
        if key not in ENVIRONMENTS_BY_KEY:
            raise ExtensionAssignmentError(f"unknown environment: {key!r}")
        for raw in extensions:
            extension = normalize_extension(raw)
            if extension is None:
                raise ExtensionAssignmentError(
                    f"{raw!r} is not a file extension (1-32 letters, digits, underscores or hyphens)"
                )
            previous = owner.get(extension)
            if previous is not None and previous != key:
                raise ExtensionAssignmentError(
                    f".{extension} is assigned to both "
                    f"{ENVIRONMENTS_BY_KEY[previous].label} and {ENVIRONMENTS_BY_KEY[key].label}"
                )
            owner[extension] = key
    overrides = {
        extension: key
        for extension, key in owner.items()
        if DEFAULT_EXTENSION_PROFILES.get(extension, PLAIN_ENVIRONMENT_KEY) != key
    }
    for extension in DEFAULT_EXTENSION_PROFILES:
        if extension not in owner:
            overrides[extension] = PLAIN_ENVIRONMENT_KEY
    if len(overrides) > MAX_EXTENSION_OVERRIDES:
        raise ExtensionAssignmentError(
            f"At most {MAX_EXTENSION_OVERRIDES} extension reassignments are supported."
        )
    return dict(sorted(overrides.items()))


__all__ = [
    "ENVIRONMENTS",
    "ENVIRONMENTS_BY_KEY",
    "EnvironmentDescriptor",
    "ExtensionAssignmentError",
    "MAX_EXTENSION_OVERRIDES",
    "PLAIN_ENVIRONMENT_KEY",
    "descriptor_for_key",
    "environment_key_for_extension",
    "extension_assignments",
    "normalize_extension",
    "overrides_for_assignments",
]
