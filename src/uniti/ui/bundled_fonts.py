"""Application-scoped Noto resources; capability is separate from primary pitch."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QLocale
from PySide6.QtGui import QFontDatabase, QGuiApplication

FONT_ROOT = Path(__file__).parent / 'assets' / 'fonts'


@dataclass(frozen=True, slots=True)
class BundledFontCapability:
    families: tuple[str, ...]
    failures: tuple[str, ...]
    font_ids: tuple[int, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.failures and len(self.families) == 13


def register_bundled_fonts(*, root: Path = FONT_ROOT) -> BundledFontCapability:
    application = QGuiApplication.instance()
    if application is None:
        raise RuntimeError('font registration requires QGuiApplication')
    if root == FONT_ROOT:
        cached = getattr(application, '_uniti_bundled_fonts', None)
        if cached is not None:
            return cached
    try:
        manifest_path = root / 'manifest.json'
        if manifest_path.stat().st_size > 32768:
            raise ValueError('oversized manifest')
        entries = json.loads(manifest_path.read_text(encoding='utf-8'))['fonts']
        if len(entries) != 13:
            raise ValueError('expected thirteen faces')
    except (OSError, ValueError, KeyError, TypeError):
        return BundledFontCapability((), ('manifest.json: unavailable',))
    families, failures, ids = [], [], []
    for entry in entries:
        name = entry.get('path', '')
        try:
            if Path(name).name != name:
                raise ValueError('invalid asset path')
            path = root / name
            if path.stat().st_size != entry['bytes'] or path.stat().st_size > 20_000_000:
                raise ValueError('asset size mismatch')
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
                raise ValueError('asset hash mismatch')
            identifier = QFontDatabase.addApplicationFont(str(path))
            if identifier < 0 or entry['family'] not in QFontDatabase.applicationFontFamilies(identifier):
                raise ValueError('font registration failed')
            ids.append(identifier)
            families.append(entry['family'])
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            failures.append(f'{str(name)[:80]}: unavailable')
    capability = BundledFontCapability(tuple(families), tuple(failures), tuple(ids))
    if root == FONT_ROOT:
        application._uniti_bundled_fonts = capability
    return capability


def ordered_families(primary: str, capability: BundledFontCapability) -> list[str]:
    """Han regional forms follow locale; plain text has no per-range language."""
    locale = QLocale().name().lower()
    regional = ['Noto Sans SC', 'Noto Sans TC', 'Noto Sans KR']
    if locale.startswith(('zh_tw', 'zh_hk', 'zh_mo')):
        regional = ['Noto Sans TC', 'Noto Sans SC', 'Noto Sans KR']
    elif locale.startswith('ko'):
        regional = ['Noto Sans KR', 'Noto Sans SC', 'Noto Sans TC']
    available = set(capability.families)
    return list(dict.fromkeys([primary, *[f for f in capability.families if f not in regional], *[f for f in regional if f in available]]))
