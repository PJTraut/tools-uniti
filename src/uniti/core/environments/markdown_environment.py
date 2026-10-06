"""Markdown environment (ADR-0014).

Decoration is the existing `MARKDOWN` `SyntaxProfile`. Markdown has no
strict grammar to validate against, so this environment's value is its
tools: whole-document formatting (`core/reformatters.py`'s Markdown
formatter, BF-061) and the live preview pane (BF-062), which is a UI-owned
host feature the environment only declares.
"""

from __future__ import annotations

from uniti.core.decoration import DecorationProvider, SyntaxProfileDecorationAdapter
from uniti.core.environment import EnvironmentContext
from uniti.core.environment_commands import EnvironmentCommand, reformat_commands
from uniti.core.environment_findings import EnvironmentFinding
from uniti.core.syntax_profiles import MARKDOWN

MARKDOWN_PREVIEW_FEATURE = "markdown.preview"


class MarkdownEnvironment:
    """Markdown decoration plus Format Document and the preview pane."""

    key = "markdown"

    def __init__(self) -> None:
        self._decoration_provider = SyntaxProfileDecorationAdapter(MARKDOWN)

    def activate(self, context: EnvironmentContext) -> None:
        del context

    def deactivate(self) -> None:
        pass

    @property
    def decoration_provider(self) -> DecorationProvider | None:
        return self._decoration_provider

    def validate(self, context: EnvironmentContext) -> tuple[EnvironmentFinding, ...]:
        del context
        return ()

    def view_providers(self) -> tuple:
        """The editable Rendered View (ADR-0015, Phase E10)."""

        from .markdown_views import MarkdownRenderedView

        return (MarkdownRenderedView(),)

    def commands(self) -> tuple[EnvironmentCommand, ...]:
        return (
            EnvironmentCommand(
                "preview",
                "Markdown Preview",
                group="view",
                host_feature=MARKDOWN_PREVIEW_FEATURE,
            ),
            *reformat_commands("markdown"),
        )
