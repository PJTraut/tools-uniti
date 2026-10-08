"""Vendored official USFM baseline stylesheet (ADR-0013, Phase E6).

`assets/usfm.sty` is vendored verbatim from a pinned upstream commit — see
`assets/manifest.json` for provenance (source repository, pinned revision,
sha256) and the licensing note recorded there: the upstream `ubsicap/usfm`
repository declares no LICENSE file, so this is vendored as de facto
standard USFM marker-metadata reference data (a marker schema, not
application code) per an explicit project decision, not because its
licensing is settled.

Loading is deliberately lazy and cached (`functools.lru_cache`): nothing at
package-import time reads or parses this file — only `UsfmEnvironment.
__init__`, which itself is only constructed when a `.usfm` document is
opened (`FileEnvironmentManager.activate_for`), triggers the first call.
Every subsequent `.usfm` open in the same process reuses the cached,
already-parsed sheet instead of re-parsing ~3,500 lines each time.

`assets/uniti.sty` is UNITI's own built-in presentation-rule layer (see
`style_layers.py`), listed in the same manifest and loaded the same way.
"""

from __future__ import annotations

import hashlib
import json
import logging
from functools import lru_cache
from pathlib import Path

from .sty import RawStyleSheet, parse_raw_stylesheet

logger = logging.getLogger("uniti.environment.usfm")

_ASSETS_ROOT = Path(__file__).parent / "assets"
_STYLESHEET_ID = "usfm-baseline"
_UNITI_BUILTIN_ID = "uniti-builtin"


@lru_cache(maxsize=1)
def load_usfm_baseline() -> RawStyleSheet:
    """Load and verify the vendored official `usfm.sty`.

    Never raises: a missing/corrupt/tampered asset logs and returns an empty
    `RawStyleSheet` rather than failing `UsfmEnvironment` activation — the
    same "degrade, never refuse" rule every environment in this framework
    follows (ADR-0013 decision 6).
    """

    return _load_asset(_STYLESHEET_ID, "failed to load vendored usfm.sty baseline; USFM structural knowledge disabled")


@lru_cache(maxsize=1)
def load_uniti_builtin() -> RawStyleSheet:
    """Load and verify UNITI's built-in `uniti.sty` presentation rules.

    Never raises: a broken asset leaves the views without the default rules.
    """

    return _load_asset(_UNITI_BUILTIN_ID, "failed to load built-in uniti.sty; default presentation rules disabled")


def asset_path(stylesheet_id: str) -> Path | None:
    """Where a built-in stylesheet asset lives (read-only)."""

    try:
        manifest = json.loads((_ASSETS_ROOT / "manifest.json").read_text(encoding="utf-8"))
        entry = next(e for e in manifest["stylesheets"] if e["id"] == stylesheet_id)
    except (OSError, ValueError, KeyError, StopIteration):
        return None
    return _ASSETS_ROOT / entry["path"] if Path(entry["path"]).name == entry["path"] else None


def usfm_baseline_path() -> Path | None:
    return asset_path(_STYLESHEET_ID)


def uniti_builtin_path() -> Path | None:
    return asset_path(_UNITI_BUILTIN_ID)


def _load_asset(stylesheet_id: str, failure: str) -> RawStyleSheet:
    try:
        manifest = json.loads((_ASSETS_ROOT / "manifest.json").read_text(encoding="utf-8"))
        entry = next(e for e in manifest["stylesheets"] if e["id"] == stylesheet_id)
        path = _ASSETS_ROOT / entry["path"]
        if Path(entry["path"]).name != entry["path"]:
            raise ValueError("invalid asset path")
        data = path.read_bytes()
        if len(data) != entry["bytes"]:
            raise ValueError("asset size mismatch")
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("asset hash mismatch")
        return parse_raw_stylesheet(data.decode("utf-8"))
    except (OSError, ValueError, KeyError, TypeError, StopIteration, json.JSONDecodeError):
        logger.exception(failure)
        return RawStyleSheet(())


__all__ = ["load_uniti_builtin", "load_usfm_baseline"]
