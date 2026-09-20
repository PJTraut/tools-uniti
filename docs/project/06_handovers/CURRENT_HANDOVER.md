# UNITI Current Handover

Captured: 2026-09-20

This is a continuation snapshot. [Current Status](../01_current/STATUS.md) owns the baseline and verification evidence; the [Documentation System](../00_governance/DOCUMENTATION_SYSTEM.md) defines authority.

## Current version and Git state

- Display/package identity: `v0.001b4` / `0.1b4`, consistent in `VERSION`, `src/uniti/__init__.py`, and `pyproject.toml`.
- Active milestone: B4 Compare, Character Inspector & Per-View Settings Beta. B3 Find/Replace Rework & Editor Refinement Beta and B2 Feedback Refinement Beta are both superseded as active (their own native-host/hosted evidence remains open, not implemented history). A21 Cross-Platform Alpha is the latest fully completed milestone.
- Complete reviewed feedback source: BF-019 (real fix), BF-070 (Compare full editor parity and all its same-day follow-ups), BF-072, BF-073 (Character Inspector list+detail rebuild and all its same-day follow-ups), and BF-075 (per-view settings), plus a shared toggle-window state-persistence mechanism, committed and integrated on `main` at `366ea42` (see the [B4 milestone plan](../02_plans/v0.001b4-compare-character-inspector-and-per-view-settings-beta.md) for the full item table).
- Latest immutable release tag: `v0.001a15` at `10f419e`. This source promotion creates a B4 development identity; it does not create a tag, release, or native distribution.

B4 is now the installed source version under [ADR-0012](../05_decisions/ADR-0012-b4-version-and-qualification.md), continuing [ADR-0008](../05_decisions/ADR-0008-b3-version-and-qualification.md)'s B2→B3 pattern. Historical A22/A23/A24/B1 plan names, and B2's/B3's own outstanding native/hosted evidence, retain outstanding release requirements; they do not require reverting the source version.

## Integrated feedback behavior

- **BF-019** (Match Report label/content sizing): both the label and content columns of `CaptureReportDelegate` now render through one `QTextLayout` rendering path (`_paint_single_color_text`), removing the code-level divergence BF-072's own fix had introduced between them. User-confirmed on native hardware.
- **BF-070** (Compare/diff "full editor parity" and its follow-ups): both panes are now real `UNITITextView` instances constructed directly on the compared documents (not a bespoke `QPlainTextEdit` snapshot), giving Compare whitespace markers, syntax highlighting, theming, and IME for free; a standalone frameless always-on-top window with its own drag-to-move title bar (`_CompareTitleBar`); per-pane zoom kept in sync across both sides; a cross-pane current-line marker mapped through the existing diff line-alignment machinery; character-level intra-line diff highlighting within `REPLACE` hunks (`_char_diff_spans`); a right-click per-pane context menu for whitespace/tab width/syntax profile/editor theme; default whitespace/tab-width/syntax seeding from `Settings` at open time (`apply_view_defaults`); a hotkey (`Ctrl+Alt+C`) that toggles the window open/closed like Find; and a file-picker prompt when no documents are open yet. Phase 3 (doc-vs-disk mode) remains parked.
- **BF-072** (Match Report replacement-preview tab rendering): `_paint_content_group_spans` rewritten onto a single `QTextLayout` with per-span `QTextCharFormat`s, replacing independently measured/drawn segments that disagreed on tab-stop width. User-confirmed fixed on native hardware.
- **BF-073** (Character Inspector rebuild): the old `QTableWidget` grid is replaced by a list+detail layout (`CharacterListModel`/`CharacterListDelegate` plus a `QSplitter` detail panel); a default hotkey (`Ctrl+Alt+I`) registered as a real `CommandDefinition` under a new `CommandCategory.TOOLS`; mouse (Ctrl/Cmd+scroll) and keyboard (`QKeySequence.StandardKey.ZoomIn`/`ZoomOut`, `Ctrl+0`, `Ctrl+=`) zoom from 50–500%; a large glyph-preview area (4× text size) anchored to the top of the window in a fixed-height (3 em), centered box; expanded Unicode properties (general category, combining class, bidirectional category, decomposition, uppercase/titlecase mapping, Unicode version) with codepoints shown alongside every mapped glyph; the selection cap lowered from 4,096 to 128 characters; frameless window chrome (`Qt.WindowType.Tool | WindowStaysOnTopHint | FramelessWindowHint` plus a custom title bar) matching Find/Replace's detached window; persisted geometry and zoom on reopen; and a fix so arrow-key list navigation (not just mouse clicks) updates the detail panel.
- **BF-075** (per-view settings): whitespace mode, editor theme, tab width, and syntax-profile choice now act on `current_view` only, instead of broadcasting to every open document — each is stored per-`ViewRecord`/exported in `UNITITextView.export_state` with skip-if-default logic matching the existing `text_direction_override` pattern, so no session-schema bump was needed.
- **Toggle-window state-persistence manager**: `Settings` gained two generic fields, `toggle_window_geometry`/`toggle_window_zoom_percent` (keyed by a short window identifier), and `UNITIMainWindow` gained `_toggle_window(key, factory)`/`_on_toggle_window_closed(key, window)` — a single shared open/close/geometry/zoom-persistence lifecycle both Compare and Character Inspector now use, replacing each window's own ad hoc tracking code. Deliberately a persistence/lifecycle mechanism only, not a shared visual-widget module: each toggle window keeps its own local title-bar implementation, per the user's explicit scope narrowing.

Carried unchanged from B3 (see the [B3 milestone plan](../02_plans/v0.001b3-find-replace-and-editor-refinement-beta.md) and its own handover history for the full item list): the P1 Find/Replace job/result-model refactor, file-type syntax-highlighting profiles including multiline-aware tokenizing (BF-071), per-document task-pool fairness and the `extra` schema-flexibility mechanism, RTL/bidi content support for Arabic/Hebrew, bundled font policy, global editor font weight, Recent Files, current-line highlight, and the text-type profile editor with full syntax color editing (ADR-0011).

Per-item implementation and remaining host checks are in the [Beta Feedback Log](../BETA_FEEDBACK.md). Runtime ownership and document/recovery boundaries are in [Architecture](../01_current/ARCHITECTURE.md); supported behavior is in [Scope](../01_current/SCOPE.md).

## Verification and its limits

Local full suite at `366ea42` (after refreshing the owned development installation via `scripts/bootstrap.py --dev --no-launch` to `v0.001b4`, required to clear 8 initial metadata-mismatch failures): **2,058 passed, 6 expected platform skips, no failures**. See [Current Status](../01_current/STATUS.md) for the full B4 source promotion record.

No fresh hosted CI run or native-host confirmation exists for this B4 candidate beyond the user's own local reports confirming BF-019, BF-070, and BF-072 fixed on native hardware. The historical B3 verification remains as it was captured; it is evidence for `3861e63`/`ca05d0b`, not for the current `366ea42` tip.

The latest complete four-lane hosted feedback pass remains [run `34253008439`](https://github.com/PJTraut/tools-uniti/actions/runs/34253008439) on earlier checkpoint `aab3f3c`. The last recorded hosted attempt, [run `34259043043`](https://github.com/PJTraut/tools-uniti/actions/runs/34259043043) on `33c71d3`, reported failure with zero executed steps in all four jobs; GitHub annotations cited failed account payments or a spending-limit block. No hosted attempt has been made on any B3 or B4 commit.

## Remaining work

1. Push `366ea42` (and this promotion's follow-up commit) to `origin/main` when ready.
2. Obtain affected Windows and Mac confirmation of first use, last-window close, explicit Quit, terminal prompt return, and relaunch. BF-002 remains a critical testing blocker until those reports exist.
3. Continue obtaining native confirmation for any item still recorded as pending native/affected-host evidence, notably BF-017 and BF-025 (carried from B3) and any BF-070/BF-073 follow-up not yet exercised on native hardware beyond the user's own visual/interaction reports already recorded in the feedback log.
4. Qualify physical Chinese/Korean IME composition, commit, and cancellation on Windows, macOS, and Linux. Synthetic events do not close physical input qualification.
5. Complete all four hosted lanes on the integrated B4 candidate once GitHub allows jobs to execute; none has run yet on this or the B3 candidate.
6. Complete the retained release sequence: seven distinct qualifying A22 real-use days; A23 executable health/recovery delivery; A24 same-candidate qualification; then B1 private executable feedback over fourteen calendar days with three independent testers covering macOS, Windows, and Linux. These gates remain open; source integration and automated runs do not replace them.
7. Keep the source version at B4 while completing the outstanding qualification. Do not mark a release ready or create a tag, public release, or tester distribution solely from this version promotion.

BF-074 (font family selection) is reported but not yet implemented; see the [Beta Feedback Log](../BETA_FEEDBACK.md) for its scoping notes and open questions.

Use the [Roadmap](../02_plans/ROADMAP.md) for ordering, the [B4 milestone](../02_plans/v0.001b4-compare-character-inspector-and-per-view-settings-beta.md) for the current scope table, and [Development](../01_current/DEVELOPMENT.md) for bootstrap and validation commands. Historical implementation details remain in [Implemented](../03_implemented/README.md), dated handovers, and Git history.
