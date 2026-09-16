# B2 Find/Replace Rework Implementation Plan

Date: 2026-09-13
Status: implemented, integrated on `main`. All 13 consolidated P1 items complete (see "Verification" below); archived here 2026-09-16 after this review found the status line stale (all phases had long been checked off).
Feedback: [Beta Feedback Log](../BETA_FEEDBACK.md), consolidated P1 scope

## Goal

Resolve [BF-039](../BETA_FEEDBACK.md#bf-039-p1--findreplace-jobresult-model-refactor) (the escalated Find/Replace job/result-model architecture finding) together with every outstanding Find/Replace-panel feedback item consolidated into P1 on 2026-09-13: BF-017, BF-018, BF-019, BF-020, BF-021, BF-022, BF-032, BF-033, BF-035, BF-036, BF-037, BF-038. (BF-014 and BF-015 were already implemented earlier and are not part of this plan.)

Three investigation passes (2026-09-13) confirmed root causes for every bug and found reusable primitives for every feature; those findings are recorded in the individual `BF-NNN` entries in the feedback log, not duplicated here. This plan tracks phase sequencing and completion only.

## Phases

### Phase 1 — Foundation: addressable Match Report, BF-021, BF-019

- [x] `CaptureReportModel` carries a real match index per row (`MatchIndexRole`), not just display position.
- [x] `capture_view` click wired to jump to that match (`_navigate_to`) — this also completed BF-037.
- [x] BF-021: removed the duplicate status-line "match N/M"; added `matchPositionChanged` signal, surfaced in each window's own status bar (new permanent right-aligned label), scoped so a shared panel never updates another window's status bar.
- [x] BF-019: decoupled the label rectangle from the content column's clamp so it is never shrunk below its measured width; raised the minimum visible report rows to 3.
- Explicit descope, recorded in BF-039: no incremental/partial-invalidation result model was built. The existing all-or-nothing staleness model stays; Phase 4's step-through mode (BF-038) is designed to re-run Find All after each confirmed replacement instead.

### Phase 2 — Independent panel fixes: BF-017, BF-018, BF-022

- [x] BF-017: `BoundedSingleLineTextEdit.event()` declines `ShortcutOverride` for the standard zoom sequences. **Root cause not confirmed** — direct testing disproved the specific claim from the initial investigation (a bare `QTextEdit` does not swallow the shortcut in this environment); the fix is a defensible hardening, not a proven resolution. A more plausible lead (ambiguous shortcuts across multiple windows sharing one panel) is recorded in BF-019... see [BF-017](../BETA_FEEDBACK.md#bf-017--findreplace-zoom-keyboard-shortcut-does-not-work-in-the-find-field) for the full note. Native affected-host confirmation remains the real test.
- [x] BF-018: custom title-bar widget with an attach/detach toggle button, reusing `attach_to`/`detach` directly.
- [x] BF-022: Cancel button kept as-is (confirmed distinct from closing); `closeEvent`/`reject()` now cancel an in-flight job instead of leaving it running after the panel closes.

### Phase 3 — Match Report coloring: BF-020

- [x] Reuse the Find input's per-group color mechanism (`regex_input.py`'s `_group_color`/palette) in `capture_report_delegate.py`, keyed by group number.
- [x] Add one new alternate color for capturing-group parentheses `()` (not per-group).
- [x] Verify against every theme including High Contrast (covered by construction — both colors reuse the same WCAG contrast-enforcement loop).

### Phase 4 — New capabilities built on Phase 1: BF-032, BF-036, BF-035, BF-038, BF-033

- [x] BF-036: add `CURRENT_GROUP` to `ReplaceScope`, with a group-filtered document enumerator.
- [x] BF-032: "Find in Selection" checkbox; add an `end` bound alongside `SearchOptions.start`; force Replace Scope back to Whole Document while checked. Previous/Next stay as two buttons (decided, no direction-switch collapse).
- [x] BF-035: extend `CaptureReportModel` to also show the expanded replacement value per row (read-only preview).
- [x] BF-038: step-through replace (confirm/skip), re-running Find All after each confirmed replacement per the Phase 1 descope. Note: one segfault seen in 1 of 5 full-suite runs, not reproduced since adding a `_poll_job` shutdown guard, cause not conclusively identified — see BF-038.
- [x] BF-033: `FindReplaceRecipe`/`FindReplaceRecipeStore` mirroring `theme_profiles.py`/`document_groups.py`; small save/load UI.

## Verification

Each phase: targeted test files first (`tests/ui/test_find_replace_contract.py`, `tests/ui/test_capture_report.py`, `tests/ui/test_main_window_contract.py`, `tests/ui/test_bounded_text_edit.py`, `tests/test_regex_search.py`), then the full suite (`.venv/bin/python -m pytest -q`) and `python -m compileall -q src scripts benchmarks tests`. New regression tests accompany every change; several were verified to actually fail without their corresponding fix before being accepted (not just pass with it).

Phase 1 and Phase 2 verification: full suite passed (1709 passed, 6 platform-only skips) after both phases landed, no regressions.

**All five Phase 4 items complete.** All 13 consolidated P1 items (BF-039 plus BF-017/018/019/020/021/022/032/033/035/036/037/038) are implemented and integrated on `main`. Full suite: 1747 passed, 6 platform-only skips, across 7 full-suite runs (one pre-fix segfault, six clean since).
