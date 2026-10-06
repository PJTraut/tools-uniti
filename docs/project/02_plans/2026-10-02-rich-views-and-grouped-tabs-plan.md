# Rich Views, Style Inspector, and Grouped Tabs — Implementation Record

Date: 2026-10-02
Status: **Implemented.**
Decision: [ADR-0015](../05_decisions/ADR-0015-stylesheet-layers-and-rich-views.md) (stylesheet layers, inspector, E7–E10); BF-082 per its own [feedback entry](../BETA_FEEDBACK.md#bf-082--file-tabs-stack-files-per-group-longer-filenames-paging-nav).
Origin: "implement everything" (2026-10-02). Covers the E6 follow-ups, spec Phases E7–E10, and BF-082.

## What shipped

Core (Qt-free):

- `core/environments/sfm/style_layers.py`: `LayeredStyleRegistry`, `StyleLayer` / `StyleOrigin`, discovery and loading.
- `sfm/inspection.py`: `marker_at`, `inspect_marker`.
- `sfm/stylesheet_support.py`: the shared SFM/USFM mixin (layers, inspector and import commands, view providers).
- `sfm/semantic.py`: apply / remove character style, change paragraph marker, insert verse, Enter text.
- `sfm/views.py`: `SfmStandardView`, `SfmFormattedView`.
- `core/rich_views/`: `SourceMap`, `ProjectionBuilder` / `Projection`, `plan_view_edit`, `EditorViewProvider` / `ViewCommand`.
- `core/environments/markdown_views.py`: `MarkdownRenderedView`.
- `EnvironmentContext.document_path` / `caret` / `anchor`, and the `ShowStyleInspector` command result.

UI:

- `ui/style_inspector.py`; `ui/rich_view.py` (`RichViewPane`, Qt rendering of projections); `ui/rich_view_controller.py` (pane lifecycle and caret sync).
- **View As** block in the environment menu; `environment.inspect` slot (Ctrl+Alt+S); **Load Stylesheet…** host feature.
- BF-082: `ui/grouped_tabs.py` plus the opt-in **View > Grouped Tabs** toggle (`Settings.grouped_tabs`).

## BF-082 implementation notes

It is built on the existing `QTabWidget`, not a replacement:
- The tab bar becomes the Recent strip (the last 5 activated files in the split, plus the current one). Every other tab still exists, hidden with `setTabVisible(False)`, so session capture, Find/Replace, splits and drag-to-detach keep working exactly as before.
- Group slots sit in the leaf's top-left corner widget, one per group plus Ungrouped. Each opens a dropdown of its files.
- Filenames are not elided in grouped mode; the strip scrolls instead.
- Dragging a whole group slot off the bar to detach the group was added on 2026-10-03; see the follow-up below.

## Verification

- New tests:
  - `tests/test_sfm_style_layers.py` (10)
  - `tests/test_rich_views.py` (23)
  - `tests/ui/test_rich_view_ui.py` (9)
  - 2 Style Inspector / Load Stylesheet tests in `tests/ui/test_environment_ui.py`
  - 1 grouped-tabs test in `tests/app/test_service.py`
- `tests/test_rich_views.py` includes a 200-step random-edit test that checks the source-map invariants after every edit and that markers survive.
- Updated: menu expectations in `tests/ui/test_environment_ui.py`, the shortcut-policy fallback set, and the settings key list in `tests/app/test_settings.py` (`grouped_tabs`).
- Full suite: 2,377 passed, 6 platform skips.
- Offscreen screenshots checked: SFM Formatted and Standard views beside Source, and the grouped tab bar with slots and the Recent strip. Not run in the live app or with native input.

## Follow-up, 2026-10-03 (ADR-0016)

Decision: [ADR-0016](../05_decisions/ADR-0016-rich-view-persistence-notes-export-placement.md).

What shipped:

- **Per-tab rich view** (`UNITITextView.rich_view_key`, saved in `ViewRecord.extra["rich_view"]`), reopened on session restore.
- **Formatted View** footnotes, cross-references and tables.
- **`.sty` export** (`sfm/sty_export.py`, the `SaveTextFile` command result, `EnvironmentController.save_text_file`).
- **Check Marker Placement** (`sfm/placement.py`).
- **Group-slot detach** (`GroupSlotButton`, `UNITIService.undock_views`).
- The rich pane's mode combo is now sized after it's filled.

Tests:

- Rich views: per-tab choice and its view-record save in `tests/ui/test_rich_view_ui.py`; session reopen in `tests/app/test_session_orchestration.py`; notes and tables in `tests/test_rich_views.py`.
- `.sty` export: resolved round trip, overrides, and save requests in `tests/test_sfm_style_layers.py`; atomic file write in `tests/ui/test_environment_ui.py`.
- Placement: well-formed vs. misplaced USFM, and project rules for generic SFM, in `tests/test_sfm_style_layers.py`.
- Group detach by mouse drag in `tests/app/test_service.py`.

Full suite: 2,388 passed, 6 platform skips. A screenshot of notes and tables in Formatted View was checked offscreen.
