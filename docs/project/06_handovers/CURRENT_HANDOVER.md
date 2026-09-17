# UNITI Current Handover

Captured: 2026-09-17

This is a continuation snapshot. [Current Status](../01_current/STATUS.md) owns the baseline and verification evidence; the [Documentation System](../00_governance/DOCUMENTATION_SYSTEM.md) defines authority.

## Current version and Git state

- Display/package identity: `v0.001b3` / `0.1b3`, consistent in `VERSION`, `src/uniti/__init__.py`, and `pyproject.toml`.
- Active milestone: B3 Find/Replace Rework & Editor Refinement Beta. B2 Feedback Refinement Beta is superseded as active (its own BF-001–BF-010 native-host/hosted evidence remains open, not implemented history). A21 Cross-Platform Alpha is the latest fully completed milestone.
- Complete reviewed feedback source: BF-012–BF-068, plus BF-040/042 (the last two escalated architecture findings from the P1 review) and BF-064's multi-checkpoint RTL horizontal-scroll fix, committed and integrated on `main` at `81c59e9` (previously `ca05d0b`, then `6d0e90f`/`d511723`/`0d75094`/`05483ec`; see the [B3 milestone plan](../02_plans/v0.001b3-find-replace-and-editor-refinement-beta.md) for the full item table).
- Local `main` is ahead of `origin/main` by four commits (`d511723`, `0d75094`, `05483ec`, `81c59e9`) as of this capture; it has not yet been pushed.
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
- System/Light/Dark are joined by Paper/Slate and editable custom profiles (carried from B2); Bundled Noto fallback, bounded shaped LTR layout, grapheme-aware editing, UTF-16 IME offsets, exact-width wrapping, and visible preedit carets are integrated (carried from B2).
- **Open Folder by Type** (BF-029, [ADR-0009](../05_decisions/ADR-0009-bounded-open-folder-by-type.md)): a bounded, one-shot batch-open by extension with optional group assignment; Format Document / Minify Document for JSON/XML/Markdown (BF-061).
- **RTL/bidi content support** (BF-064, un-parking BF-043): content-level bidi correctness — direction detection, shaping/layout, caret movement and selection, a caret-freeze fix, and (as of 2026-09-17) the non-wrapped/multi-checkpoint horizontal-scroll case — is implemented for Arabic/Hebrew; application chrome stays left-to-right by design. Arabic/Hebrew fonts are bundled (BF-066, [ADR-0010](../05_decisions/ADR-0010-bundled-font-selection-policy.md)). Global editor font weight with hotkeys is integrated (BF-067). **Still outstanding:** native IME/physical qualification only, an external hardware gate — see the [RTL/bidi plan](../03_implemented/milestones/2026-09-15-rtl-bidi-support-plan.md).
- Recent Files (BF-058), remembered Find/Replace attach height instead of a 50% default (BF-059), current-line highlight (BF-060), a Unicode hex ↔ character toggle hotkey (BF-053), a read-only Markdown preview pane (BF-062), a text-type profile editor for extension→syntax-profile mapping plus (2026-09-17) full per-category syntax color editing ([ADR-0011](../05_decisions/ADR-0011-syntax-category-color-editing.md), BF-063), "Inspect Selection" per-character Unicode properties (BF-065), and a fix for detached Find/Replace panel geometry restoring off-screen after a monitor is removed (BF-068) are all integrated.
- Per-document task-pool fairness (BF-040: same-priority tasks now round-robin across documents instead of pure FIFO) and an open-ended, forward-compatible session-schema `extra` blob on `ViewRecord`/`DocumentRecord`/`FindReplaceManifestRecord` (BF-042, `SESSION_SCHEMA` now 6) are integrated — the last two escalated architecture findings from the P1 review. BF-030/031 (multi-document and large-scale benchmark coverage) are unblocked by BF-040 but not yet run; tracked as Pool 1 of the [outstanding work pools](../02_plans/2026-09-16-outstanding-work-pools.md).

Per-item implementation and remaining host checks are in the [Beta Feedback Log](../BETA_FEEDBACK.md). Runtime ownership and document/recovery boundaries are in [Architecture](../01_current/ARCHITECTURE.md); supported behavior is in [Scope](../01_current/SCOPE.md).

## Verification and its limits

Local full suite at `81c59e9`: **1,970 passed, 6 expected platform skips, no failures** (the 8 local bootstrap/metadata-mismatch failures previously recorded at `0d75094` did not reproduce in this run; they were already characterized there as environment-dependent and unrelated to any integrated change, so their absence here is not itself evidence they're fixed — see the [Pool 1 plan](../03_implemented/milestones/2026-09-17-pool-1-task-fairness-and-schema-flexibility-plan.md) for that earlier characterization). This supersedes the `ca05d0b` count below, which is retained for history: **1,830 passed, 6 expected platform skips**, including the regressions added for that batch (BF-017's single- and two-window shortcut-delivery tests, BF-056's match-report-sizing test) and the rewritten menu-structure test for BF-057. One order-dependent flaky failure (`test_palette_change_rebuilds_group_formats_with_accessible_contrast`, in `tests/ui/test_find_replace_contract.py`) was confirmed present on the pre-session code too, when the full file runs in a particular order; it is unrelated to that batch's changes and passes in isolation.

No fresh hosted CI run or native-host confirmation exists for this B3 candidate. The historical B2 verification below remains as it was captured; it is evidence for `3e20214`/`596c88f`, not for the current `81c59e9` tip.

Recorded local evidence on the earlier B2 promotion (`33c71d3`/`3e20214`), retained for history:

- Full suite: 1,646 passed, six expected platform skips in 95.63 seconds (later B2 feedback batches, through `596c88f`, added further passing tests recorded in [Current Status](../01_current/STATUS.md)).
- Compilation, diff checks, all 21 deep self-checks, 108 native Cocoa targeted tests, and native/offscreen combined smoke passed.
- Unchanged scroll, typing, giant-line, and mixed-script performance gates passed, as did all four local hosted-profile sustained families.
- The isolated wheel contained all 40 expected resources; mixed text and Find/Replace rendered from the installed wheel.

The latest complete four-lane hosted feedback pass remains [run `34253008439`](https://github.com/PJTraut/tools-uniti/actions/runs/34253008439) on earlier checkpoint `aab3f3c`. The last recorded hosted attempt, [run `34259043043`](https://github.com/PJTraut/tools-uniti/actions/runs/34259043043) on `33c71d3`, reported failure with zero executed steps in all four jobs; GitHub annotations cited failed account payments or a spending-limit block. No hosted attempt has been made on any B3 commit.

## Remaining work

1. Push `81c59e9` to `origin/main` when ready (local is four commits ahead as of this capture).
2. Obtain affected Windows and Mac confirmation of first use, last-window close, explicit Quit, terminal prompt return, and relaunch. BF-002 remains a critical testing blocker until those reports exist.
3. Obtain native confirmation for the B3-specific items still marked pending in the feedback log: BF-017 (Find/Replace zoom shortcut; the underlying wiring is now regression-tested in headless simulation, but real macOS confirmation is still open), BF-019 and BF-025 (visual confirmations), and any other item recorded as pending native/affected-host evidence.
4. Qualify physical Chinese/Korean IME composition, commit, and cancellation on Windows, macOS, and Linux. Synthetic events do not close physical input qualification.
5. Complete all four hosted lanes on the integrated B3 candidate once GitHub allows jobs to execute; none has run yet on this candidate.
6. Complete the retained release sequence: seven distinct qualifying A22 real-use days; A23 executable health/recovery delivery; A24 same-candidate qualification; then B1 private executable feedback over fourteen calendar days with three independent testers covering macOS, Windows, and Linux. These gates remain open; source integration and automated runs do not replace them.
7. Keep the source version at B3 while completing the outstanding qualification. Do not mark a release ready or create a tag, public release, or tester distribution solely from this version promotion.

BF-029/BF-044, BF-040/042, and BF-063 (both halves) are resolved — see the [Beta Feedback Log](../BETA_FEEDBACK.md) for each. No decision-dependent items currently await a scope call.

Use the [Roadmap](../02_plans/ROADMAP.md) for ordering, the [B3 milestone](../02_plans/v0.001b3-find-replace-and-editor-refinement-beta.md) for the current scope table, and [Development](../01_current/DEVELOPMENT.md) for bootstrap and validation commands. Historical implementation details remain in [Implemented](../03_implemented/README.md), dated handovers, and Git history.
