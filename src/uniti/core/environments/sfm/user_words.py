"""The user's own spelling list (plan 2026-10-15-usfm-hyphenation-and-spelling-followups, F1).

Words approved or rejected from the right-click menu, kept beside UNITI's
other USFM configuration: `<user data>/Environments/USFM/Spelling/<project
short name>.json`. It sits above Paratext's lists: an approved word is
correct and a rejected one wrong, whatever `SpellingStatus.xml` says. UNITI
never writes Paratext's files (ADR-0018). Without a user data folder
(tests, headless tools) the list lives in memory only. Qt-free.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path

from uniti.core.environments.user_config import environment_folder

from .spelling import normalize

logger = logging.getLogger("uniti.environment.sfm.spelling")

SPELLING_FOLDER = "Spelling"


def user_words_path(project_name: str) -> Path | None:
    """The file of a project's user list (it may not exist yet)."""

    folder = environment_folder("USFM")
    if folder is None:
        return None
    safe = re.sub(r"[^\w.\-]+", "_", project_name).strip("._") or "project"
    return folder / SPELLING_FOLDER / f"{safe}.json"


class UserWords:
    """One project's approved and rejected words, as typed; compared
    normalized (NFC, case-folded). `version` counts changes."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.version = 0
        self._approved: dict[str, str] = {}
        self._rejected: dict[str, str] = {}
        self._stamp: tuple[int, int] | None = None
        self.load()

    # --- reading -----------------------------------------------------------------

    @property
    def approved(self) -> tuple[str, ...]:
        return tuple(sorted(self._approved.values(), key=normalize))

    @property
    def rejected(self) -> tuple[str, ...]:
        return tuple(sorted(self._rejected.values(), key=normalize))

    def is_approved(self, word: str) -> bool:
        return normalize(word) in self._approved

    def is_rejected(self, word: str) -> bool:
        return normalize(word) in self._rejected

    def __contains__(self, word: str) -> bool:
        return self.is_approved(word) or self.is_rejected(word)

    # --- changing ----------------------------------------------------------------

    def approve(self, word: str) -> None:
        key = normalize(word)
        self._rejected.pop(key, None)
        self._approved[key] = word
        self._changed()

    def reject(self, word: str) -> None:
        key = normalize(word)
        self._approved.pop(key, None)
        self._rejected[key] = word
        self._changed()

    def forget(self, word: str) -> None:
        key = normalize(word)
        if self._approved.pop(key, None) is not None or self._rejected.pop(key, None) is not None:
            self._changed()

    def _changed(self) -> None:
        self.version += 1
        self.save()

    # --- the file ----------------------------------------------------------------

    @staticmethod
    def _stamp_of(path: Path) -> tuple[int, int] | None:
        try:
            info = path.stat()
        except OSError:
            return None
        return (info.st_mtime_ns, info.st_size)

    def load(self) -> bool:
        """Read the file; False when there is none or it's damaged (the
        words in memory are kept)."""

        if self.path is None:
            return False
        stamp = self._stamp_of(self.path)
        if stamp is None:
            return False
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            approved = [item for item in data.get("approved", []) if isinstance(item, str) and item]
            rejected = [item for item in data.get("rejected", []) if isinstance(item, str) and item]
        except (OSError, ValueError, AttributeError):
            logger.warning("could not read the spelling list %s", self.path, exc_info=True)
            return False
        self._approved = {normalize(word): word for word in approved}
        self._rejected = {normalize(word): word for word in rejected if normalize(word) not in self._approved}
        self._stamp = stamp
        self.version += 1
        return True

    def reload_if_changed(self) -> bool:
        """Read the file again when it changed on disk (another UNITI)."""

        if self.path is None or self._stamp_of(self.path) == self._stamp:
            return False
        return self.load()

    def save(self) -> bool:
        if self.path is None:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"approved": list(self.approved), "rejected": list(self.rejected)}
            temporary = self.path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.path)
            self._stamp = self._stamp_of(self.path)
        except OSError:
            logger.warning("could not write the spelling list %s", self.path, exc_info=True)
            return False
        return True


_LISTS: dict[tuple[str, str], UserWords] = {}
_LOCK = threading.Lock()


def user_words_for(project_name: str) -> UserWords:
    """The one `UserWords` of a project in this process, per user data
    folder."""

    path = user_words_path(project_name)
    key = (str(path), project_name)
    with _LOCK:
        words = _LISTS.get(key)
        if words is None:
            words = _LISTS[key] = UserWords(path)
    return words


__all__ = ["SPELLING_FOLDER", "UserWords", "user_words_for", "user_words_path"]
