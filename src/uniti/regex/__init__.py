"""UNITI regex services backed exclusively by the third-party regex package."""

from .analysis import (
    AnalysisState,
    DiagnosticSeverity,
    ExpressionRole,
    GroupIdentity,
    InlineSwitch,
    MAX_EXPRESSION_CHARS,
    PatternStructure,
    RegexAnalysis,
    RegexDiagnostic,
    RegexToken,
    TokenPair,
    analyze_pattern,
    analyze_replacement,
    pending_pattern_analysis,
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
    "PatternStructure",
    "RegexAnalysis",
    "RegexDiagnostic",
    "RegexToken",
    "Replacement",
    "ReplacementPlan",
    "ReplacementPlanEstimate",
    "ReplacementPlanLimitError",
    "TokenPair",
    "analyze_pattern",
    "analyze_replacement",
    "pending_pattern_analysis",
]
