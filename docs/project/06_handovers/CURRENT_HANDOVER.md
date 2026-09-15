# UNITI Current Handover

Captured: 2026-09-15

This is a continuation snapshot. [Current Status](../01_current/STATUS.md) owns the baseline and verification evidence; the [Documentation System](../00_governance/DOCUMENTATION_SYSTEM.md) defines authority.

## Current version and Git state

- Display/package identity: `v0.001b3` / `0.1b3`, consistent in `VERSION`, `src/uniti/__init__.py`, and `pyproject.toml`.
- Active milestone: B3 Find/Replace Rework & Editor Refinement Beta. B2 Feedback Refinement Beta is superseded as active (its own BF-001–BF-010 native-host/hosted evidence remains open, not implemented history). A21 Cross-Platform Alpha is the latest fully completed milestone.
- Complete reviewed feedback source: BF-012–BF-057, committed and integrated on `main` at `ca05d0b` (previously `596c88f`, "1b2 feedback implementation").
- Local `main` is ahead of `origin/main` by one commit (`ca05d0b`) as of this capture; it has not yet been pushed.
- Latest immutable release tag: `v0.001a15` at `10f419e`. This source promotion creates a B3 development identity; it does not create a tag, release, or native distribution.

B3 is now the installed source version under [ADR-0008](../05_decisions/ADR-0008-b3-version-and-qualification.md), continuing [ADR-0007](../05_decisions/ADR-0007-beta-source-version-and-qualification.md)'s B1→B2 pattern. Historical A22/A23/A24/B1 plan names, and B2's own outstanding native/hosted evidence, retain outstanding release requirements; they do not require reverting the source version. Earlier checkpoints such as `5724f6c`, `aab3f3c`, `33c71d3`, and `3e20214` remain historical evidence; their changes must not be reapplied.

## Integrated feedback behavior

- First-use bootstrap reports flushed progress; healthy startup stays quiet. Last-window close retains a usable empty editor; explicit Quit shuts down the service and releases the terminal. `Ctrl/Cmd+N` now also creates a real blank document in the current window (BF-047).
- Find/Replace was substantially reworked (the P1 job/result-model refactor, BF-039, and its dependents): Find-in-Selection and a single direction control, saved recipes, per-match preview, a "current group" replace scope, clickable Match Report rows, and per-match interactive replace. The panel now attaches into the editor pane tree instead of `QMainWindow` docking (BF-048) and can be minimized/toggled hidden (BF-054).
- The Find hotkey now toggles the panel open/closed instead of only opening it; Find and Navigation moved from their own top-level/submenu into blocks inside Edit; several submenu wrappers (Encoding, Line Endings, Editor View, F/R View) were flattened into blocks in their parent menus (BF-057).
- The Match Report shows 3 full matches by default (BF-050) and — after a follow-up correction — its minimum height no longer depends on match content, only on zoom/font size, so a large report can no longer force the panel to grow (BF-056).
- EOL conversion takes effect live instead of only on save (BF-023); converting to CRLF/CR no longer has a quadratic slowdown relative to converting to LF (BF-051, a lookaround-free rewrite of the conversion patterns).
- File-type syntax-highlighting profiles and their extension point are integrated (BF-027, BF-041); configurable tab width and tabs-to-spaces conversion are integrated (BF-028).
- Whitespace markers are centered, Unicode inspection has configurable held modifiers, line numbers use 80% font size, and EOL status distinguishes current bytes from conversion-on-save across all shared views (carried from B2).
- System/Light/Dark are joined by Paper/Slate and editable custom profiles (carried from B2); Bundled Noto fallback, bounded shaped LTR layout, grapheme-aware editing, UTF-16 IME offsets, exact-width wrapping, and visible preedit carets are integrated (carried from B2). RTL/mixed-direction editing remains outside scope.

Per-item implementation and remaining host checks are in the [Beta Feedback Log](../BETA_FEEDBACK.md). Runtime ownership and document/recovery boundaries are in [Architecture](../01_current/ARCHITECTURE.md); supported behavior is in [Scope](../01_current/SCOPE.md).

## Verification and its limits

Local full suite at `ca05d0b`: **1,830 passed, 6 expected platform skips**. This includes the new regressions added for this batch (BF-017's single- and two-window shortcut-delivery tests, BF-056's match-report-sizing test) and the rewritten menu-structure test for BF-057. One order-dependent flaky failure (`test_palette_change_rebuilds_group_formats_with_accessible_contrast`, in `tests/ui/test_find_replace_contract.py`) was confirmed present on the pre-session code too, when the full file runs in a particular order; it is unrelated to this batch's changes and passes in isolation.

No fresh hosted CI run or native-host confirmation exists for this B3 candidate. The historical B2 verification below remains as it was captured; it is evidence for `3e20214`/`596c88f`, not for the current `ca05d0b` tip.

Recorded local evidence on the earlier B2 promotion (`33c71d3`/`3e20214`), retained for history:

- Full suite: 1,646 passed, six expected platform skips in 95.63 seconds (later B2 feedback batches, through `596c88f`, added further passing tests recorded in [Current Status](../01_current/STATUS.md)).
- Compilation, diff checks, all 21 deep self-checks, 108 native Cocoa targeted tests, and native/offscreen combined smoke passed.
- Unchanged scroll, typing, giant-line, and mixed-script performance gates passed, as did all four local hosted-profile sustained families.
- The isolated wheel contained all 40 expected resources; mixed text and Find/Replace rendered from the installed wheel.

The latest complete four-lane hosted feedback pass remains [run `34253008439`](https://github.com/PJTraut/tools-uniti/actions/runs/34253008439) on earlier checkpoint `aab3f3c`. The last recorded hosted attempt, [run `34259043043`](https://github.com/PJTraut/tools-uniti/actions/runs/34259043043) on `33c71d3`, reported failure with zero executed steps in all four jobs; GitHub annotations cited failed account payments or a spending-limit block. No hosted attempt has been made on any B3 commit.

## Remaining work

1. Push `ca05d0b` to `origin/main` when ready (local is one commit ahead as of this capture).
2. Obtain affected Windows and Mac confirmation of first use, last-window close, explicit Quit, terminal prompt return, and relaunch. BF-002 remains a critical testing blocker until those reports exist.
3. Obtain native confirmation for the B3-specific items still marked pending in the feedback log: BF-017 (Find/Replace zoom shortcut; the underlying wiring is now regression-tested in headless simulation, but real macOS confirmation is still open), BF-019 and BF-025 (visual confirmations), and any other item recorded as pending native/affected-host evidence.
4. Qualify physical Chinese/Korean IME composition, commit, and cancellation on Windows, macOS, and Linux. Synthetic events do not close physical input qualification.
5. Complete all four hosted lanes on the integrated B3 candidate once GitHub allows jobs to execute; none has run yet on this candidate.
6. Complete the retained release sequence: seven distinct qualifying A22 real-use days; A23 executable health/recovery delivery; A24 same-candidate qualification; then B1 private executable feedback over fourteen calendar days with three independent testers covering macOS, Windows, and Linux. These gates remain open; source integration and automated runs do not replace them.
7. Keep the source version at B3 while completing the outstanding qualification. Do not mark a release ready or create a tag, public release, or tester distribution solely from this version promotion.

Decision-dependent items awaiting a scope call before implementation: BF-029/BF-044 (folder-level open-as-group vs. the parked project/workspace boundary), BF-040 (per-document task-pool fairness), BF-042 (session schema versioning approach), BF-053 (Unicode hex-to-character conversion, not yet scoped).

Use the [Roadmap](../02_plans/ROADMAP.md) for ordering, the [B3 milestone](../02_plans/v0.001b3-find-replace-and-editor-refinement-beta.md) for the current scope table, and [Development](../01_current/DEVELOPMENT.md) for bootstrap and validation commands. Historical implementation details remain in [Implemented](../03_implemented/README.md), dated handovers, and Git history.
