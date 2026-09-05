"""Concrete fixed-pitch editor font selection shared by UI and diagnostics."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QRawFont

from uniti.app.platform_policy import (
    PlatformFamily,
    classify_platform,
)


_PREFERENCES = {
    PlatformFamily.MACOS: ("Menlo", "Monaco"),
    PlatformFamily.WINDOWS: ("Cascadia Mono", "Consolas"),
    PlatformFamily.LINUX: (
        "DejaVu Sans Mono",
        "Liberation Mono",
        "Noto Sans Mono",
    ),
}
_cached_application: QGuiApplication | None = None
_cached_resolution: FontResolution | None = None


@dataclass(frozen=True, slots=True)
class FontResolution:
    font: QFont
    requested_family: str
    resolved_family: str
    fixed_pitch: bool
    latin_coverage: bool
    cyrillic_coverage: bool
    fallback: bool

    def __post_init__(self) -> None:
        if not isinstance(self.font, QFont):
            raise TypeError("resolved font must be a QFont")
        if not isinstance(self.requested_family, str) or not self.requested_family:
            raise ValueError("requested font family must be nonempty")
        if not isinstance(self.resolved_family, str) or not self.resolved_family:
            raise ValueError("resolved font family must be nonempty")
        for value in (
            self.fixed_pitch,
            self.latin_coverage,
            self.cyrillic_coverage,
            self.fallback,
        ):
            if not isinstance(value, bool):
                raise TypeError("font resolution flags must be bool")

    def as_dict(self) -> dict[str, object]:
        return {
            "requested_family": self.requested_family,
            "resolved_family": self.resolved_family,
            "fixed_pitch": self.fixed_pitch,
            "latin_coverage": self.latin_coverage,
            "cyrillic_coverage": self.cyrillic_coverage,
            "fallback": self.fallback,
        }


def _font_facts(
    font: QFont,
    raw_font_factory: Callable[[QFont], object],
) -> tuple[str, bool, bool]:
    raw_font = raw_font_factory(font)
    valid = bool(raw_font.isValid())
    resolved_family = raw_font.familyName() if valid else font.family()
    if not isinstance(resolved_family, str) or not resolved_family:
        resolved_family = font.family()
    latin = valid and bool(raw_font.supportsCharacter(ord("A")))
    cyrillic = valid and bool(raw_font.supportsCharacter(ord("Ж")))
    return resolved_family, latin, cyrillic


def _concrete_font(font: QFont, resolved_family: str) -> QFont:
    concrete = QFont(font)
    concrete.setFamily(resolved_family)
    return concrete


def resolve_editor_font(
    *,
    family: PlatformFamily = classify_platform(sys.platform),
    database: object = QFontDatabase,
    raw_font_factory: Callable[[QFont], object] | None = None,
) -> FontResolution:
    """Resolve one concrete fixed-pitch font with Latin/Cyrillic coverage."""

    global _cached_application, _cached_resolution

    application = QGuiApplication.instance()
    if not isinstance(application, QGuiApplication):
        raise RuntimeError("editor font resolution requires QGuiApplication")
    if not isinstance(family, PlatformFamily):
        raise TypeError("font platform family must be a PlatformFamily")
    use_cache = database is QFontDatabase and raw_font_factory is None
    if (
        use_cache
        and _cached_application is application
        and _cached_resolution is not None
    ):
        return _cached_resolution
    factory = QRawFont.fromFont if raw_font_factory is None else raw_font_factory
    installed = tuple(str(item) for item in database.families())
    installed_set = set(installed)
    preferred = tuple(
        candidate
        for candidate in _PREFERENCES[family]
        if candidate in installed_set
    )
    ordered = preferred + tuple(sorted(installed_set.difference(preferred)))

    resolution: FontResolution | None = None
    for requested_family in ordered:
        if not bool(database.isFixedPitch(requested_family)):
            continue
        font = QFont(requested_family)
        try:
            resolved_family, latin, cyrillic = _font_facts(font, factory)
        except Exception:
            continue
        if not (latin and cyrillic):
            continue
        resolution = FontResolution(
            _concrete_font(font, resolved_family),
            requested_family,
            resolved_family,
            True,
            latin,
            cyrillic,
            False,
        )
        break

    if resolution is None:
        font = database.systemFont(database.SystemFont.FixedFont)
        requested_family = font.family()
        try:
            resolved_family, latin, cyrillic = _font_facts(font, factory)
        except Exception:
            resolved_family = requested_family
            latin = False
            cyrillic = False
        resolution = FontResolution(
            _concrete_font(font, resolved_family),
            requested_family,
            resolved_family,
            bool(database.isFixedPitch(requested_family)),
            latin,
            cyrillic,
            True,
        )

    if use_cache:
        _cached_application = application
        _cached_resolution = resolution
    return resolution


__all__ = ["FontResolution", "resolve_editor_font"]
