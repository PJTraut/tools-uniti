from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics
from PySide6.QtWidgets import QApplication

from uniti.app.platform_policy import PlatformFamily


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@dataclass(frozen=True)
class _RawSpec:
    resolved: str
    valid: bool = True
    latin: bool = True
    cyrillic: bool = True


class _RawFont:
    def __init__(self, spec: _RawSpec):
        self.spec = spec

    def isValid(self) -> bool:
        return self.spec.valid

    def familyName(self) -> str:
        return self.spec.resolved

    def supportsCharacter(self, codepoint: int) -> bool:
        if codepoint == ord("A"):
            return self.spec.latin
        if codepoint == ord("Ж"):
            return self.spec.cyrillic
        return False


class _SystemFont:
    FixedFont = object()


class _Database:
    SystemFont = _SystemFont

    def __init__(
        self,
        families: tuple[str, ...],
        *,
        fixed: frozenset[str],
        system_family: str = "System Fixed",
    ) -> None:
        self._families = families
        self._fixed = fixed
        self._system_family = system_family

    def families(self) -> tuple[str, ...]:
        return self._families

    def isFixedPitch(self, family: str) -> bool:
        return family in self._fixed

    def systemFont(self, _kind: object) -> QFont:
        return QFont(self._system_family)


def _factory(specs: dict[str, _RawSpec], calls: list[str]):
    def create(font: QFont):
        family = font.family()
        calls.append(family)
        return _RawFont(specs[family])

    return create


def test_default_font_probe_avoids_unsafe_raw_font_conversion():
    source = Path("src/uniti/ui/font_policy.py").read_text(encoding="utf-8")

    assert "QRawFont" not in source
    assert "QFontInfo" in source
    assert "QFontMetrics" in source


def test_font_policy_requires_an_existing_gui_application():
    script = """
from uniti.ui.font_policy import resolve_editor_font
try:
    resolve_editor_font()
except RuntimeError as error:
    print(error)
    raise SystemExit(0)
raise SystemExit(1)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[2],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "QGuiApplication" in completed.stdout


@pytest.mark.parametrize(
    "family, preferred",
    [
        (PlatformFamily.MACOS, "Menlo"),
        (PlatformFamily.WINDOWS, "Cascadia Mono"),
        (PlatformFamily.LINUX, "DejaVu Sans Mono"),
    ],
)
def test_platform_preferences_precede_sorted_remaining_families(
    qapp,
    family,
    preferred,
):
    from uniti.ui.font_policy import resolve_editor_font

    calls: list[str] = []
    database = _Database(
        ("Zeta Mono", preferred, "Alpha Mono"),
        fixed=frozenset({"Zeta Mono", preferred, "Alpha Mono", "System Fixed"}),
    )
    specs = {
        preferred: _RawSpec(f"Concrete {preferred}"),
        "Alpha Mono": _RawSpec("Concrete Alpha"),
        "Zeta Mono": _RawSpec("Concrete Zeta"),
        "System Fixed": _RawSpec("Concrete System"),
    }

    resolved = resolve_editor_font(
        family=family,
        database=database,
        raw_font_factory=_factory(specs, calls),
    )

    assert calls == [preferred]
    assert resolved.requested_family == preferred
    assert resolved.resolved_family == f"Concrete {preferred}"
    assert resolved.font.family() == resolved.resolved_family
    assert resolved.fixed_pitch is True
    assert resolved.latin_coverage is True
    assert resolved.cyrillic_coverage is True
    assert resolved.fallback is False


@pytest.mark.parametrize(
    "fixed, first_spec",
    [
        (frozenset({"Monaco", "System Fixed"}), _RawSpec("Menlo")),
        (
            frozenset({"Menlo", "Monaco", "System Fixed"}),
            _RawSpec("Menlo", latin=False),
        ),
        (
            frozenset({"Menlo", "Monaco", "System Fixed"}),
            _RawSpec("Menlo", cyrillic=False),
        ),
    ],
)
def test_resolver_rejects_proportional_or_missing_required_glyphs(
    qapp,
    fixed,
    first_spec,
):
    from uniti.ui.font_policy import resolve_editor_font

    calls: list[str] = []
    database = _Database(
        ("Menlo", "Monaco"),
        fixed=fixed,
    )
    specs = {
        "Menlo": first_spec,
        "Monaco": _RawSpec("Concrete Monaco"),
        "System Fixed": _RawSpec("Concrete System"),
    }

    resolved = resolve_editor_font(
        family=PlatformFamily.MACOS,
        database=database,
        raw_font_factory=_factory(specs, calls),
    )

    assert resolved.requested_family == "Monaco"
    assert resolved.resolved_family == "Concrete Monaco"
    assert resolved.fallback is False


def test_system_fixed_fallback_reports_degraded_coverage_without_font_payload(qapp):
    from uniti.ui.font_policy import resolve_editor_font

    calls: list[str] = []
    database = _Database(
        ("Proportional",),
        fixed=frozenset({"System Fixed"}),
    )
    specs = {
        "System Fixed": _RawSpec(
            "Concrete System",
            latin=True,
            cyrillic=False,
        ),
    }

    resolved = resolve_editor_font(
        family=PlatformFamily.LINUX,
        database=database,
        raw_font_factory=_factory(specs, calls),
    )

    assert resolved.fallback is True
    assert resolved.fixed_pitch is True
    assert resolved.latin_coverage is True
    assert resolved.cyrillic_coverage is False
    assert resolved.font.family() == "Concrete System"
    assert resolved.as_dict() == {
        "requested_family": "System Fixed",
        "resolved_family": "Concrete System",
        "fixed_pitch": True,
        "latin_coverage": True,
        "cyrillic_coverage": False,
        "fallback": True,
    }


def test_windows_offscreen_registers_bounded_installed_system_font(
    qapp,
    monkeypatch,
):
    from uniti.ui import font_policy

    calls: list[str] = []

    class _OffscreenWindowsDatabase(_Database):
        def addApplicationFont(self, path: str) -> int:
            calls.append(path)
            self._families = ("Consolas",)
            self._fixed = frozenset({"Consolas", "System Fixed"})
            return 0

    database = _OffscreenWindowsDatabase((), fixed=frozenset())
    monkeypatch.setattr(
        font_policy,
        "_windows_fixed_font_paths",
        lambda: (Path("C:/Windows/Fonts/consola.ttf"),),
    )

    resolved = font_policy.resolve_editor_font(
        family=PlatformFamily.WINDOWS,
        database=database,
        raw_font_factory=_factory(
            {
                "Consolas": _RawSpec("Consolas"),
                "System Fixed": _RawSpec("System Fixed"),
            },
            [],
        ),
    )

    assert calls == [os.fspath(Path("C:/Windows/Fonts/consola.ttf"))]
    assert resolved.requested_family == "Consolas"
    assert resolved.fixed_pitch is True
    assert resolved.latin_coverage is True
    assert resolved.cyrillic_coverage is True
    assert resolved.fallback is False


def test_real_editor_font_is_concrete_fixed_pitch_with_required_coverage(qapp):
    from uniti.ui.font_policy import resolve_editor_font

    resolution = resolve_editor_font()
    metrics = QFontMetrics(resolution.font)

    assert resolution.font.family().casefold() != "monospace"
    assert QFontDatabase.isFixedPitch(resolution.resolved_family)
    assert metrics.inFontUcs4(ord("A"))
    assert metrics.inFontUcs4(ord("Ж"))
    assert resolution.fixed_pitch is True
    assert resolution.latin_coverage is True
    assert resolution.cyrillic_coverage is True


def test_bundled_faces_cover_each_declared_sample_without_system_fallback(qapp):
    import hashlib
    import json
    from PySide6.QtGui import QRawFont
    root = Path('src/uniti/ui/assets/fonts')
    assert (root / 'manifest.json').is_file()
    manifest = json.loads((root / 'manifest.json').read_text())
    assert len(manifest['fonts']) == 13
    for entry in manifest['fonts']:
        path = root / entry['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256']
        assert path.stat().st_size == entry['bytes']
        assert hashlib.sha256((root / entry['noticePath']).read_bytes()).hexdigest() == entry['noticeSha256']
        raw = QRawFont(str(path), 18)
        assert raw.isValid()
        assert raw.familyName() == entry['family']
        assert all(raw.supportsCharacter(ord(ch)) for ch in entry['sample']), entry['family']


def test_missing_bundle_is_explicit_bounded_capability_failure(qapp, tmp_path):
    from uniti.ui import font_policy
    assert hasattr(font_policy, 'register_bundled_fonts')
    capability = font_policy.register_bundled_fonts(root=tmp_path)
    assert not capability.complete
    assert capability.failures == ('manifest.json: unavailable',)


def test_real_font_requests_registered_fallbacks(qapp):
    from uniti.ui.font_policy import resolve_editor_font
    families = resolve_editor_font().font.families()
    assert 'Noto Sans Devanagari' in families
    assert {'Noto Sans SC', 'Noto Sans TC', 'Noto Sans KR'} <= set(families)
