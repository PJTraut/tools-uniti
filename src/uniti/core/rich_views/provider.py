"""Editor view providers (spec §33, Phase E7).

An environment may offer alternative editable views of its documents
(`view_providers()`), e.g. SFM Standard/Formatted, Markdown Rendered.
Source View is always the ordinary editor and is not a provider.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .editing import EditPlan
from .projection import Projection


@dataclass(frozen=True, slots=True)
class ViewCommand:
    """A semantic command a view offers (Bold, Remove Style, Paragraph…).

    `run(source, selection_start, selection_end, argument)` works in
    *source* offsets and returns an `EditPlan` (or raises `EditRejected`).
    `choices`, when set, makes the host ask the user to pick an argument;
    `prompt`, when set, asks for free text instead.
    """

    command_id: str
    label: str
    run: Callable[[str, int, int, str | None], EditPlan]
    shortcut: str = ""
    choices: Callable[[], tuple[str, ...]] | None = None
    prompt: str | None = None


class EditorViewProvider(Protocol):
    key: str
    label: str

    def project(self, source: str) -> Projection: ...

    def enter_text(self, source: str, source_offset: int) -> str:
        """Source text to insert for Enter at `source_offset`."""
        ...

    def view_commands(self) -> tuple[ViewCommand, ...]: ...


def environment_view_providers(environment: object) -> tuple[EditorViewProvider, ...]:
    providers = getattr(environment, "view_providers", None)
    if providers is None:
        return ()
    try:
        return tuple(providers())
    except Exception:
        return ()
