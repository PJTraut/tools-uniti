# USFM Field Test: Environment Windows, In-Place Views, Reference Sync — Implementation Record

Date: 2026-10-07
Status: **Implemented** (not committed).
Decision: [ADR-0017](../05_decisions/ADR-0017-environment-windows-in-place-views-reference-sync.md).
Origin: `@externalresources/field_test_feedback` (2026-10-07), with the user's answers the same day. The per-chapter view was paused and moved to the [wishlist](../FEATURE_WISHLIST.md#usfm-per-chapter-view).

## Feedback → change

| Feedback | Change |
|---|---|
| Undock from main into an "environment panel" | **Move to Environment Window** (environment menu). There's one window per environment and document group, with an environment toolbar. Dock returns the file to where it came from. |
| Plain text / standard / preview in the same window, not a side panel | Rich views are panes laid over the tab's own Source editor, one per tab. Plain Text is a mode. |
| Preview: footnote and cross-reference frame, stacked per class | Preview hides note bodies, keeps generated callers, and stacks one section per note class below the text. Clicking a note moves the caret to it, and the caret on a caller highlights its note. |
| Conditional styling, e.g. `\p` then `\q` → blank line | `\Marker p+q1` adjacent-sibling rules. The built-in rule gives a 12 pt blank line between prose and poetry. |
| "How are we extending the STY to PREVIEW?" | Selector records in ordinary `.sty` layers: a built-in `uniti.sty` plus a project `uniti.sty`. See [USFM stylesheet rules](../../usfm-stylesheet-rules.md). |
| Book / chapter / verse selector in the USFM frame | Book lists every file of the environment in the project folder, by `\id`, in canonical order. Chapter and Verse follow the caret. |
| View per chapter or per book | Paused (wishlist). |
| Side-by-side sync within a group, highlight matched lines | `ReferenceSync` scrolls the other splits of the same group and book to the caret's chapter:verse, and highlights the verse on every side. |
| Regex search always matches the underlying plain text (follow-up) | Already how Find/Replace worked: it searches the tab's source in every mode, and the rich view mirrors the current match. Now recorded as ADR-0017 decision 8 and covered by a test. |
| All styling by paragraph and character styles | Removed every hard-coded look. Chapter, verse, notes, note-internal markers and cells all take their stylesheet style. |

## What shipped

Core (Qt-free):

- `core/rich_views/projection.py`: `NoteSection` and `Projection.notes`.
- `sfm/style_layers.py`: rule parsing (`PresentationRule`, `is_selector`, `rule_marker_key`), `formatting(marker, previous)`, `caller_formatting`, the `UNITI_BUILTIN` / `UNITI_PROJECT` origins, and project `uniti.sty` discovery.
- `sfm/assets/uniti.sty`, the built-in rules, which are in the asset manifest and package data.
- `sfm/views.py`: stylesheet-only styling, rules, generated callers and notes sections.
- `sfm/sty_export.py`: the built-in layer is excluded from overrides.
- `sfm/references.py`: `ReferenceMap` (chapters, verses, `reference_at`, `find`, `verse_range`), `book_code`, `scan_books` and `BOOK_ORDER`.

UI:

- `ui/rich_view.py`:
  - The pane works in place: a focus signal, refresh only while shown, no × button, and an optional mode selector.
  - The notes frame (`_NoteSectionView`).
  - Reference highlight and `scroll_to_source`.
  - Own-key shortcut override.
- `ui/rich_view_controller.py`: one pane per tab, kept fitted to its editor, with a focus proxy, `sync`/`forget`, and `key_for`/`pane_for`/`set_mode`.
- `ui/environment_window.py`: `EnvironmentBar`, `ReferenceSync` and `ReferenceMaps` (cached per document revision).
- `ui/main_window.py`:
  - `set_environment_window` and `move_to_environment_window`;
  - an environment-aware window title;
  - Edit commands routed to the pane;
  - pane lifecycle on transfer, close and restore.
- `ui/environment_controller.py`: the View As block acts per tab, plus **Move to Environment Window** and **Sync Side-by-Side by Reference**.
- `app/service.py`: `environment_window_for`, `move_to_environment_window`.
- `app/session_runtime.py` / `session_controller.py`: environment-window identity in `ViewRecord.extra["environment_window"]`, rebuilt by `restore_shell`.

## Verification

New tests:

- `tests/test_sfm_presentation.py` (19): stylesheet-only styling, rules, callers, notes sections.
- `tests/test_sfm_references.py` (5).
- `tests/app/test_environment_window.py` (9):
  - grouping into windows, and dock back;
  - capture identity;
  - the Book selector over the project folder, opening into the group and mode;
  - chapter/verse navigation and caret following;
  - the mode switch in place;
  - sync on, sync with a tab switch, no sync across groups, sync off.
- `tests/ui/test_rich_view_ui.py` (+7): in-place pane, per-split modes, the Edit menu can't change Preview, the notes frame, Standard keeps notes inline, and regex search on the source in Standard and Preview.
- `tests/app/test_session_orchestration.py` (+1): restore rebuilds the environment window.

Updated: `tests/test_rich_views.py` and `tests/test_sfm_style_layers.py` (styling expectations), and the environment menu expectation in `tests/ui/test_environment_ui.py`.

Full suite: 2,448 passed, 6 platform skips. Checked offscreen with a screenshot of an environment window: Preview, the notes frame, the selector and the reference highlight.
- `tests/performance/test_ux_scenarios.py::test_resource_recovery_scenario_restores_parallel_capacity` fails on this machine. It fails the same way on the committed `HEAD` in a clean worktree, so it predates this change and has nothing to do with it.
- Not run in the live app or with native input.
