"""Rich-view framework (ADR-0015, spec Phase E7).

Qt-free: projections of canonical source into an editable view text, the
bidirectional source map between them, and the planner that turns a
view-level edit or semantic command into ordinary `Document.replace_many`
edits. The canonical document stays the only source of truth (ADR-0002,
ADR-0013 decision 6) — a rich view never serializes its own text back.
"""

from .projection import BlockFormat, Projection, ProjectionBuilder, SpanFormat
from .source_map import Segment, SegmentRole, SourceMap
from .editing import EditPlan, EditRejected, plan_view_edit
from .provider import EditorViewProvider, ViewCommand, environment_view_providers

__all__ = [
    "BlockFormat",
    "EditPlan",
    "EditRejected",
    "EditorViewProvider",
    "Projection",
    "ProjectionBuilder",
    "Segment",
    "SegmentRole",
    "SourceMap",
    "SpanFormat",
    "ViewCommand",
    "environment_view_providers",
    "plan_view_edit",
]
