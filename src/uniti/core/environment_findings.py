"""Validation findings surfaced by an environment (ADR-0013, Phase E3).

Named `EnvironmentFinding`, not `Diagnostic`: this codebase's "Diagnostics"
(`app/diagnostics.py`, `ui/diagnostics_dialog.py`) already means app-health/
startup telemetry, an unrelated concept. Reusing that name here would be a
same-name-different-meaning collision, the same class of problem this
initiative already avoided twice (`FileEnvironmentManager`, and the
`EditTransaction` reconciliation — see ADR-0013).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class EnvironmentFinding:
    start: int
    end: int
    severity: FindingSeverity
    message: str
    code: str | None = None
