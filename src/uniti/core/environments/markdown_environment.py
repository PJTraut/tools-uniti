"""Markdown environment (ADR-0014).

Decoration is the existing `MARKDOWN` `SyntaxProfile`. Markdown has no
strict grammar to validate against, so this environment's value is its
tools: whole-document formatting (`core/reformatters.py`'s Markdown
formatter, BF-061, following MD's Environment Settings, N31) and the
editable Preview mode (`markdown_views`), styled from layered CSS
(`markdown_css`, N27). BF-062's read-only preview side pane was retired on
2026-11-05 (Q7).
"""

from __future__ import annotations

from pathlib import Path

from uniti.core.decoration import DecorationProvider, SyntaxProfileDecorationAdapter
from uniti.core.environment import EnvironmentContext
from uniti.core.environment_commands import EnvironmentCommand, reformat_commands
from uniti.core.environment_findings import EnvironmentFinding
from uniti.core.syntax_profiles import MARKDOWN

from .settings import CHOICE, FLAG, NUMBER, OPENS_IN, TEXT_MODE, EnvironmentSetting

EXTENDED = "extended"
GITHUB = "github"
COMMONMARK = "commonmark"
AS_WRITTEN = "as-written"

MARKDOWN_SETTINGS: tuple[EnvironmentSetting, ...] = (
    EnvironmentSetting(
        "flavour",
        "Flavour",
        CHOICE,
        EXTENDED,
        "Which Markdown the Preview commands write and Preview recognises.",
        choices=(
            (EXTENDED, "Extended (Markdown Guide cheat sheet)"),
            (GITHUB, "GitHub"),
            (COMMONMARK, "CommonMark"),
        ),
        section="Syntax",
    ),
    EnvironmentSetting(
        OPENS_IN,
        "Opens in",
        CHOICE,
        TEXT_MODE,
        "The mode a Markdown file opens in.",
        choices=((TEXT_MODE, "Text"), ("markdown.rendered", "Preview")),
        section="Syntax",
    ),
    EnvironmentSetting(
        "bullet",
        "Bullet",
        CHOICE,
        "-",
        "The bullet character every list item gets.",
        choices=(("-", "- (hyphen)"), ("*", "* (asterisk)"), ("+", "+ (plus)")),
        section="Format Document",
    ),
    EnvironmentSetting(
        "emphasis",
        "Emphasis",
        CHOICE,
        AS_WRITTEN,
        "The delimiter of italic text.",
        choices=((AS_WRITTEN, "As written"), ("*", "*italic*"), ("_", "_italic_")),
        section="Format Document",
    ),
    EnvironmentSetting(
        "strong",
        "Bold",
        CHOICE,
        AS_WRITTEN,
        "The delimiter of bold text.",
        choices=((AS_WRITTEN, "As written"), ("**", "**bold**"), ("__", "__bold__")),
        section="Format Document",
    ),
    EnvironmentSetting(
        "numbering",
        "Numbered lists",
        CHOICE,
        AS_WRITTEN,
        "How numbered list items are numbered.",
        choices=((AS_WRITTEN, "As written"), ("renumber", "Renumber 1, 2, 3 …"), ("ones", "All 1.")),
        section="Format Document",
    ),
    EnvironmentSetting(
        "blank_lines",
        "Most blank lines in a row",
        NUMBER,
        1,
        "Longer runs of blank lines outside code blocks are shortened to this.",
        minimum=1,
        maximum=9,
        section="Format Document",
    ),
    EnvironmentSetting(
        "align_tables",
        "Align table columns",
        FLAG,
        True,
        "Pad pipe-table cells so the columns line up.",
        section="Format Document",
    ),
)


class MarkdownEnvironment:
    """Markdown decoration plus Format Document and the preview pane."""

    key = "markdown"

    stylesheet_file_filter = "CSS stylesheets (*.css);;All Files (*)"

    def __init__(self) -> None:
        self._decoration_provider = SyntaxProfileDecorationAdapter(MARKDOWN)
        self._document_path: Path | None = None
        self._imported: list[Path] = []  # Load Stylesheet…, this session
        self._view_providers: tuple | None = None

    @staticmethod
    def settings_declarations() -> tuple[EnvironmentSetting, ...]:
        """MD's Environment Settings (N31)."""

        return MARKDOWN_SETTINGS

    def activate(self, context: EnvironmentContext) -> None:
        self._document_path = context.document_path

    def deactivate(self) -> None:
        pass

    @property
    def decoration_provider(self) -> DecorationProvider | None:
        return self._decoration_provider

    def validate(self, context: EnvironmentContext) -> tuple[EnvironmentFinding, ...]:
        del context
        return ()

    def view_providers(self) -> tuple:
        """The editable Preview (ADR-0015, Phase E10), styled from this
        document's stylesheet layers (N27)."""

        from .markdown_css import markdown_styles
        from .markdown_views import MarkdownRenderedView

        if self._view_providers is None:
            self._view_providers = (
                MarkdownRenderedView(
                    styles=lambda source: markdown_styles(self._document_path, source, self._imported)
                ),
            )
        return self._view_providers

    @property
    def document_path(self) -> Path | None:
        return self._document_path

    @property
    def imported_stylesheets(self) -> tuple:
        """Stylesheets loaded by hand (Load Stylesheet…), lowest first, as
        rows for Configuration Files… (`.name`, `.path`)."""

        from types import SimpleNamespace

        return tuple(SimpleNamespace(name=path.name, path=path) for path in self._imported)

    def import_stylesheet(self, path: Path) -> bool:
        """Layer a chosen `.css` on top, for this session (N27)."""

        from .markdown_css import load_css

        path = Path(path)
        if load_css(path) is None:
            return False
        self._imported = [item for item in self._imported if item != path] + [path]
        return True

    def reload_stylesheets(self) -> None:
        """Stylesheets are re-read when they change on disk; nothing to do."""

    def commands(self) -> tuple[EnvironmentCommand, ...]:
        from .sfm.stylesheet_support import IMPORT_STYLESHEET_FEATURE

        return (
            *reformat_commands("markdown"),
            EnvironmentCommand(
                "import_stylesheet",
                "Load Stylesheet…",
                group="styles",
                host_feature=IMPORT_STYLESHEET_FEATURE,
            ),
        )
