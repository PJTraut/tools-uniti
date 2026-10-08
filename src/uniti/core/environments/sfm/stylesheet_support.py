"""Shared stylesheet layering and inspector commands for SFM/USFM (ADR-0015).

The USFM environment is the one user (`.sfm` and `.usfm` both belong to it
since field test round 2, R5). Without an official baseline (`baseline=None`)
the Standard/Preview views still render over the USFM baseline, so every
marker isn't shown as unknown; validation, placement and the Style
Inspector never see that fallback.
"""

from __future__ import annotations

from pathlib import Path

from uniti.core.environment import EnvironmentContext
from uniti.core.environment_commands import (
    CommandResult,
    EnvironmentCommand,
    SaveTextFile,
    ShowFindings,
    TOO_LARGE_TO_VALIDATE,
    ShowMessage,
    ShowStyleInspector,
    ShowUndefinedMarkup,
    UNDEFINED_MARKUP_COMMAND,
    document_text,
)

from .inspection import marker_at
from .sty import RawStyleSheet, StyleRegistry
from .style_layers import LayeredStyleRegistry, StyleLayer, StyleOrigin, build_layers, load_stylesheet_file

IMPORT_STYLESHEET_FEATURE = "sfm.import_stylesheet"


class StylesheetSupport:
    """Mixin: layered `.sty` registry, Style Inspector, stylesheet import,
    and the Standard/Preview rich views (ADR-0015)."""

    _baseline: RawStyleSheet | None = None

    def _init_styles(self, baseline: RawStyleSheet | None) -> None:
        self._baseline = baseline
        self._document_path: Path | None = None
        self._imported: list[StyleLayer] = []
        self._layered = LayeredStyleRegistry(build_layers(baseline, None))
        self._view_styles = self._presentation_styles()

    def _rebuild_styles(self) -> None:
        self._layered = LayeredStyleRegistry(build_layers(self._baseline, self._document_path, self._imported))
        self._view_styles = self._presentation_styles()

    def _presentation_styles(self) -> LayeredStyleRegistry:
        """What the rich views render with (see the module docstring)."""

        if self._baseline is not None:
            return self._layered
        from .usfm_baseline import load_usfm_baseline

        return LayeredStyleRegistry(
            build_layers(load_usfm_baseline(), self._document_path, self._imported)
        )

    def activate(self, context: EnvironmentContext) -> None:
        self._document_path = context.document_path
        self._rebuild_styles()

    @property
    def layered_styles(self) -> LayeredStyleRegistry:
        return self._layered

    @property
    def imported_stylesheets(self) -> tuple[StyleLayer, ...]:
        """Stylesheets loaded by hand (Load Stylesheet…), lowest first."""

        return tuple(self._imported)

    @property
    def style_registry(self) -> StyleRegistry:
        """The effective (all layers merged) structural registry."""

        return self._layered.registry

    def view_providers(self) -> tuple:
        """Standard (editable) and Preview (read-only) views over the live
        layered styles."""

        from .views import SfmPreviewView, SfmStandardView

        providers = getattr(self, "_view_providers", None)
        if providers is None:
            providers = (
                SfmStandardView(lambda: self._view_styles),
                SfmPreviewView(lambda: self._view_styles),
            )
            self._view_providers = providers
        return providers

    def import_stylesheet(self, path: Path) -> bool:
        """Layer an explicitly chosen `.sty` on top (highest precedence)."""

        layer = load_stylesheet_file(Path(path), StyleOrigin.UNITI_IMPORT)
        if layer is None:
            return False
        self._imported = [item for item in self._imported if item.path != layer.path] + [layer]
        self._rebuild_styles()
        return True

    def reload_stylesheets(self) -> None:
        self._rebuild_styles()

    def stylesheet_commands(self) -> tuple[EnvironmentCommand, ...]:
        return (
            EnvironmentCommand(
                "check_placement",
                "Check Marker Placement",
                group="validate",
                run=self._check_placement,
            ),
            EnvironmentCommand(
                UNDEFINED_MARKUP_COMMAND,
                "Check Undefined Markers",
                group="validate",
                run=self._check_undefined,
            ),
            EnvironmentCommand("inspect", "Inspect Marker at Cursor", group="styles", run=self._inspect_at_cursor),
            EnvironmentCommand("styles", "Style Inspector…", group="styles", run=self._open_inspector),
            EnvironmentCommand(
                "import_stylesheet",
                "Load Stylesheet…",
                group="styles",
                host_feature=IMPORT_STYLESHEET_FEATURE,
            ),
            EnvironmentCommand(
                "reload_stylesheets",
                "Reload Project Stylesheets",
                group="styles",
                run=self._reload,
            ),
            EnvironmentCommand(
                "export_resolved_stylesheet",
                "Export Resolved Stylesheet…",
                group="styles",
                run=self._export(resolved=True),
            ),
            EnvironmentCommand(
                "export_stylesheet_overrides",
                "Export Stylesheet Overrides…",
                group="styles",
                run=self._export(resolved=False),
            ),
        )

    def _export(self, *, resolved: bool):
        from .sty_export import export_overrides, export_resolved

        def run(context: EnvironmentContext, argument: str | None) -> CommandResult:
            del context, argument
            text = export_resolved(self._layered) if resolved else export_overrides(self._layered)
            return SaveTextFile(
                "Export Resolved Stylesheet" if resolved else "Export Stylesheet Overrides",
                "resolved.sty" if resolved else "overrides.sty",
                text,
                "Stylesheets (*.sty);;All Files (*)",
            )

        return run

    def _check_placement(self, context: EnvironmentContext, argument: str | None) -> CommandResult:
        """`OccursUnder` placement against the loaded stylesheets (ADR-0016)."""

        from .placement import placement_findings

        del argument
        title = "Check Marker Placement"
        if not context.resource_profile.allow_full_parse:
            return ShowMessage(title, TOO_LARGE_TO_VALIDATE)
        if not self._layered.layers:
            return ShowMessage(title, "No stylesheet is loaded, so there are no placement rules to check against.")
        return ShowFindings(title, placement_findings(document_text(context), self._layered.registry))

    def _check_undefined(self, context: EnvironmentContext, argument: str | None) -> CommandResult:
        """Markers no stylesheet the views render with defines (round 2 R7)."""

        from .undefined import undefined_markers

        del argument
        title = "Undefined Markers"
        if not context.resource_profile.allow_full_parse:
            return ShowMessage(title, TOO_LARGE_TO_VALIDATE)
        styles = self._view_styles
        return ShowUndefinedMarkup(
            title,
            tuple(layer.name for layer in styles.layers),
            undefined_markers(document_text(context), styles),
        )

    def _layer_summary(self) -> str:
        names = [layer.name for layer in self._layered.layers]
        return " → ".join(names) if names else "no stylesheet loaded"

    def _open_inspector(self, context: EnvironmentContext, argument: str | None) -> CommandResult:
        del context
        return ShowStyleInspector(f"Style Inspector — {self._layer_summary()}", self._layered, argument)

    def _inspect_at_cursor(self, context: EnvironmentContext, argument: str | None) -> CommandResult:
        del argument
        if context.caret is None:
            return self._open_inspector(context, None)
        if not context.resource_profile.allow_full_parse:
            return ShowMessage(
                "Inspect Marker",
                "This document is too large to locate markers; use the Style Inspector instead.",
            )
        marker = marker_at(document_text(context), context.caret)
        if marker is None:
            return ShowMessage("Inspect Marker", "There is no marker at or before the cursor.")
        return ShowStyleInspector(f"Style Inspector — {self._layer_summary()}", self._layered, marker)

    def _reload(self, context: EnvironmentContext, argument: str | None) -> CommandResult:
        del argument
        self._document_path = context.document_path or self._document_path
        self._rebuild_styles()
        return ShowMessage("Stylesheets", f"Loaded: {self._layer_summary()}")


__all__ = ["IMPORT_STYLESHEET_FEATURE", "StylesheetSupport"]
