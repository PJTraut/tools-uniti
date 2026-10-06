"""Environment-contributed commands (ADR-0014).

An environment declares the functions/tools it offers for a document as
`EnvironmentCommand`s. Commands are Qt-free: `run` receives the same
restricted `EnvironmentContext` every other environment capability sees
(ADR-0013 decision 6) and returns a declarative `CommandResult` describing
what the host should do — never touching a widget itself. The UI layer
(`ui/environment_menu.py`) turns each command into a menu action and
applies its result.

Two command kinds:

- **Core commands** (`run` set): fully implemented here, headless-testable.
- **Host features** (`host_feature` set): a capability whose implementation
  is inherently UI (e.g. the Markdown preview pane). The environment only
  declares that it offers the feature; the host owns the implementation
  and its checked/enabled state.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from .environment import EnvironmentContext
from .environment_findings import EnvironmentFinding


@dataclass(frozen=True, slots=True)
class ReplaceDocumentText:
    """Replace the whole document with `text` as one undoable edit."""

    text: str


@dataclass(frozen=True, slots=True)
class ShowFindings:
    """Present `findings` (possibly empty) to the user under `title`."""

    title: str
    findings: tuple[EnvironmentFinding, ...]


@dataclass(frozen=True, slots=True)
class NavigateTo:
    """Move the caret to character `offset`."""

    offset: int


@dataclass(frozen=True, slots=True)
class ShowMessage:
    """Tell the user something, at `level` severity."""

    title: str
    text: str
    level: Literal["info", "warning", "error"] = "info"


@dataclass(frozen=True, slots=True)
class ShowStyleInspector:
    """Open the marker/style inspector over `registry` (a
    `LayeredStyleRegistry`), with `selected` (a bare marker) preselected."""

    title: str
    registry: object
    selected: str | None = None


@dataclass(frozen=True, slots=True)
class SaveTextFile:
    """Ask where to save `text` (suggesting `suggested_name` next to the
    document) and write it there. The environment never writes files itself
    (ADR-0013 decision 6); the host does, after the user chose the path."""

    title: str
    suggested_name: str
    text: str
    file_filter: str = "All Files (*)"


CommandResult = (
    ReplaceDocumentText
    | ShowFindings
    | NavigateTo
    | ShowMessage
    | ShowStyleInspector
    | SaveTextFile
    | None
)

CommandRunner = Callable[[EnvironmentContext, str | None], CommandResult]


@dataclass(frozen=True, slots=True)
class EnvironmentCommand:
    """One function/tool an environment offers.

    `command_id` is environment-local and stable (e.g. ``"format"``,
    ``"validate"``), so the host can address the same capability across
    environments (Format Document runs whichever environment's ``"format"``).
    `group` clusters commands into separated menu blocks, in declaration
    order. `prompt`, when set, asks the user for one line of text first and
    passes it to `run` as its argument.
    """

    command_id: str
    label: str
    group: str = "tools"
    run: CommandRunner | None = None
    host_feature: str | None = None
    prompt: str | None = None
    prompt_title: str | None = None

    def __post_init__(self) -> None:
        if not self.command_id:
            raise ValueError("command_id must not be empty")
        if (self.run is None) == (self.host_feature is None):
            raise ValueError("a command needs exactly one of run or host_feature")


def environment_commands(environment: object) -> tuple[EnvironmentCommand, ...]:
    """The commands `environment` offers; `()` for one that declares none."""

    commands = getattr(environment, "commands", None)
    if commands is None:
        return ()
    try:
        offered = commands() if callable(commands) else commands
        return tuple(command for command in offered if isinstance(command, EnvironmentCommand))
    except Exception:
        return ()


def document_text(context: EnvironmentContext) -> str:
    return "".join(chunk for _start, chunk in context.edits.iter_text())


TOO_LARGE_TO_VALIDATE = (
    "This document is too large for a full validation pass; "
    "validation is skipped above 1 MiB to keep editing responsive."
)


def validate_command(
    environment: object,
    *,
    label: str = "Validate Document",
    title: str | None = None,
) -> EnvironmentCommand:
    """A ``"validate"`` command over `environment.validate(context)`.

    Distinguishes "skipped because the file is large" from "no problems",
    which `validate()` alone cannot (both return `()`).
    """

    def run(context: EnvironmentContext, _argument: str | None) -> CommandResult:
        if not context.resource_profile.allow_full_parse:
            return ShowMessage(label, TOO_LARGE_TO_VALIDATE)
        findings = environment.validate(context)  # type: ignore[attr-defined]
        return ShowFindings(title or label, tuple(findings))

    return EnvironmentCommand("validate", label, group="validate", run=run)


def reformat_commands(reformatter_key: str) -> Sequence[EnvironmentCommand]:
    """``"format"``/``"minify"`` commands over a `core.reformatters` entry."""

    from . import reformatters
    from .reformatters import ReformatFailure, reformatter_for_key

    reformatter = reformatter_for_key(reformatter_key)
    if reformatter is None:
        return ()

    def make(minify: bool) -> CommandRunner:
        title = "Minify Failed" if minify else "Format Failed"

        def run(context: EnvironmentContext, _argument: str | None) -> CommandResult:
            # Read at run time (not import time) so the cap stays one
            # patchable module constant.
            limit = reformatters.MAX_REFORMAT_CHARS
            text = document_text(context)
            if len(text) > limit:
                return ShowMessage(
                    "Document Too Large",
                    "This document is larger than "
                    f"{limit:,} characters. Formatting requires "
                    "reading the whole document into memory, so it is not "
                    "offered above that size.",
                    level="warning",
                )
            action = reformatter.minify if minify else reformatter.format
            assert action is not None
            try:
                return ReplaceDocumentText(action(text))
            except ReformatFailure as exc:
                error = exc.error
                location = (
                    f" (line {error.line}, column {error.column})"
                    if error.line is not None
                    else ""
                )
                return ShowMessage(title, f"{error.message}{location}", level="error")

        return run

    commands = [EnvironmentCommand("format", "Format Document", group="format", run=make(False))]
    if reformatter.can_minify:
        commands.append(
            EnvironmentCommand("minify", "Minify Document", group="format", run=make(True))
        )
    return tuple(commands)


__all__ = [
    "CommandResult",
    "CommandRunner",
    "EnvironmentCommand",
    "NavigateTo",
    "ReplaceDocumentText",
    "ShowFindings",
    "ShowMessage",
    "ShowStyleInspector",
    "SaveTextFile",
    "document_text",
    "environment_commands",
    "reformat_commands",
    "validate_command",
]
