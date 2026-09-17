# Outstanding Work Pools

Date: 2026-09-17
Status: active — a living index, not a milestone. Updated whenever the [Beta Feedback Log](../BETA_FEEDBACK.md) review below is repeated; individual item disposition always lives in its own `BF-NNN` entry, not here.
Feedback: [Beta Feedback Log](../BETA_FEEDBACK.md), [Parked Capability Catalog](../04_parked/CATALOG.md), [Feature Wishlist](../FEATURE_WISHLIST.md)
Milestone: reviewed against the active [B3 milestone](v0.001b3-find-replace-and-editor-refinement-beta.md)

## Why this document exists

The feedback log accumulates one `BF-NNN` entry per item, in report order. That's the right structure for disposition history, but it doesn't answer "what's left, and how does it cluster for planning the next pass of work" — this document is that view, refreshed periodically rather than maintained line-by-line. It does not replace the feedback log or the [ROADMAP](ROADMAP.md)'s milestone-level sequencing; it sits between them, at the level of "which outstanding `BF-NNN` items make sense to batch together next."

## Pool 1 — Benchmark coverage gaps

Measurement gaps, not implementation gaps — the features exist; there's no benchmark evidence for these scenarios. BF-040 (per-document task-pool fairness) landed 2026-09-17 as the fairness foundation these two benchmarks need to give trustworthy results — see the [Pool 1 task-fairness and schema-flexibility plan](../03_implemented/milestones/2026-09-17-pool-1-task-fairness-and-schema-flexibility-plan.md).

- [BF-030](../BETA_FEEDBACK.md#bf-030--no-benchmark-coverage-for-many-concurrently-open-documents) — No benchmark coverage for many concurrently open documents
- [BF-031](../BETA_FEEDBACK.md#bf-031--no-benchmark-coverage-for-large-cutpaste-or-undoredo-at-scale) — No benchmark coverage for large cut/paste or undo/redo at scale

## Pool 2 — Native/hosted confirmation (standing, blocked without hardware/testers)

Every item below is code-complete; only affected-host, native-input, or hosted-CI confirmation remains. This pool cannot move without physical hardware or the B1 tester program — it's not a coding task.

- [BF-001](../BETA_FEEDBACK.md#bf-001--slow-windows-first-launch-with-limited-progress-feedback)–[BF-010](../BETA_FEEDBACK.md#bf-010--eol-markers-unchanged-when-the-status-line-updates) (partial — most items in this range still need affected-host or native-input confirmation; see each entry's own Status line for which)
- [BF-017](../BETA_FEEDBACK.md#bf-017--findreplace-zoom-keyboard-shortcut-does-not-work-in-the-find-field) — Find/Replace zoom shortcut (native affected-host confirmation)
- [BF-019](../BETA_FEEDBACK.md#bf-019--match-report-capture-group-row-indentation-and-truncated-label) — Match Report label alignment (native visual confirmation)
- [BF-025](../BETA_FEEDBACK.md#bf-025--last-line-of-a-file-displays-only-80-when-the-editor-is-focused) — Last line partial-height fix (native visual confirmation)
- RTL/bidi (BF-064) physical Arabic/Hebrew IME qualification — needs native hardware, not just an emulator

## Pool 3 — Long-term wishlist (deliberately unscoped)

Recorded in the [Feature Wishlist](../FEATURE_WISHLIST.md), not yet promoted to a `BF-NNN` entry.

- Compare/diff between two files or open documents
- Multi-cursor / Select All Occurrences — deliberately kept long-term only (2026-09-13 direction); a data-model change to `EditorState`, not a UI toggle

## Also still open — BF-063's parked color half

Not pooled above because it's a single item with its own un-parking precondition, not a batch: [BF-063](../BETA_FEEDBACK.md#bf-063--theme--text-type-profile-editor)'s syntax-category-color editor stays parked in the [file-type-profiles capability](../04_parked/CATALOG.md#file-type-profiles-and-syntax-highlighting) — its extension→profile mapping half landed (see below), the color half needs the same kind of un-parking decision [ADR-0009](../05_decisions/ADR-0009-bounded-open-folder-by-type.md) recorded for BF-029, and wasn't pursued this pass.

## Not pooled — standing release-qualification gates

Unrelated to any `BF-NNN` item above; tracked by the [ROADMAP](ROADMAP.md) and [Current Status](../01_current/STATUS.md), not this document: the A22 seven real-use days, A23 executable health/recovery delivery, A24 stabilization, and the B1 fourteen-day three-tester feedback program.

## Recently closed (context for why they're absent above)

For continuity when this document is next refreshed: BF-029 (Open Folder by Type), BF-061 (Format/Minify Document), BF-064's content-level bidi work including its 2026-09-16 multi-rect-selection and caret-affinity fixes, BF-066 (font selection policy and Arabic/Hebrew bundling), and BF-067 (global font weight) all landed and were archived or updated between 2026-09-15 and 2026-09-16. This document's former Pool 1 (Recent Files, Find/Replace panel sizing, current-line highlight, Unicode hex hotkey — BF-058/059/060/053) and Pool 2 (Markdown preview, the extension→profile mapping half of the theme/text-type editor, and Inspect Selection — BF-062/063/065) all landed the same day (2026-09-16); see each `BF-NNN` entry in the [Beta Feedback Log](../BETA_FEEDBACK.md) for its implementation and verification notes. [BF-068](../BETA_FEEDBACK.md#bf-068--detached-findreplace-panel-geometry-can-restore-off-screen-after-a-monitor-is-removed) (detached Find/Replace panel geometry restoring off-screen after a monitor is removed) was found and fixed on 2026-09-17, the same pass that reviewed this document. This document's former Pool 1 — Escalated architecture findings (BF-040, per-document task-pool fairness; BF-042, the session-schema `extra` blob) — both landed 2026-09-17; see the [Pool 1 task-fairness and schema-flexibility plan](../03_implemented/milestones/2026-09-17-pool-1-task-fairness-and-schema-flexibility-plan.md) for implementation and verification detail. This document's former Pool 2 — RTL's one remaining real gap (the non-wrapped/multi-checkpoint horizontal-scroll case) — also landed 2026-09-17; see the [RTL/bidi support plan](../03_implemented/milestones/2026-09-15-rtl-bidi-support-plan.md) for implementation and verification detail. Remaining pools were renumbered accordingly (old Pool 2 → 1, Pool 3 → 2, Pool 4 → 3, Pool 5 → 4, then old Pool 3 → 2, Pool 4 → 3). See [`03_implemented/README.md`](../03_implemented/README.md#v0001b3-workstream-records) for the archived plans.
