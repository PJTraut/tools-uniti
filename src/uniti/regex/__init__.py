"""UNITI regex services backed exclusively by the third-party regex package."""

from .analysis import (
    AnalysisState,
    DiagnosticSeverity,
    ExpressionRole,
    GroupIdentity,
    InlineSwitch,
    MAX_EXPRESSION_CHARS,
    RegexAnalysis,
    RegexDiagnostic,
    RegexToken,
    TokenPair,
)
from .replacement_plan import (
    Replacement,
    ReplacementPlan,
    ReplacementPlanEstimate,
    ReplacementPlanLimitError,
)

__all__ = [
    "AnalysisState",
    "DiagnosticSeverity",
    "ExpressionRole",
    "GroupIdentity",
    "InlineSwitch",
    "MAX_EXPRESSION_CHARS",
    "RegexAnalysis",
    "RegexDiagnostic",
    "RegexToken",
    "Replacement",
    "ReplacementPlan",
    "ReplacementPlanEstimate",
    "ReplacementPlanLimitError",
    "TokenPair",
]
