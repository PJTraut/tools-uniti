"""Per-document resource gating for environment capabilities (ADR-0013).

Deliberately narrow, and deliberately not unified with the ad hoc large-file
thresholds already scattered across `ui/main_window.py` (`MAX_REFORMAT_CHARS`,
the navigation/index `1 << 20` gate, `MAX_COMPARE_CHARS`) or with
`resources.manager`'s machine-level `HostResourceProfile` (cache/worker-pool
sizing). Retrofitting those is a separate, larger effort outside this
initiative's scope. This gate exists only for *new* environment capabilities
layered on top of the existing editor — e.g. a future SFM semantic parse
that must self-downgrade to plain behavior on a huge file rather than
refusing it outright.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ResourceTier = Literal["small", "large"]

# Same order of magnitude as the existing ad hoc 1 << 20 gate in
# ui/main_window.py, chosen for consistency with what "large" already means
# to a user of this editor — not a shared constant with it.
ENVIRONMENT_LARGE_FILE_BYTES = 1 << 20


@dataclass(frozen=True, slots=True)
class ResourceProfile:
    size_bytes: int

    def __post_init__(self) -> None:
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")

    def tier(self) -> ResourceTier:
        return "large" if self.size_bytes > ENVIRONMENT_LARGE_FILE_BYTES else "small"

    @property
    def allow_full_parse(self) -> bool:
        """Whether an environment may build a full semantic model/tree.

        Mirrors the spec's "may I build a full semantic model? / yes/no"
        pattern (an environment asks Core, never decides from a hardcoded
        threshold of its own) while staying to exactly one boolean for this
        phase — no environment exists yet that needs finer-grained budgets.
        """

        return self.tier() == "small"
