# Outstanding Work Pools

Date: 2026-09-16
Status: active — a living index, not a milestone. Updated whenever the [Beta Feedback Log](../BETA_FEEDBACK.md) review below is repeated; individual item disposition always lives in its own `BF-NNN` entry, not here.
Feedback: [Beta Feedback Log](../BETA_FEEDBACK.md), [Parked Capability Catalog](../04_parked/CATALOG.md), [Feature Wishlist](../FEATURE_WISHLIST.md)
Milestone: reviewed against the active [B3 milestone](v0.001b3-find-replace-and-editor-refinement-beta.md)

## Why this document exists

The feedback log accumulates one `BF-NNN` entry per item, in report order. That's the right structure for disposition history, but it doesn't answer "what's left, and how does it cluster for planning the next pass of work" — this document is that view, refreshed periodically rather than maintained line-by-line. It does not replace the feedback log or the [ROADMAP](ROADMAP.md)'s milestone-level sequencing; it sits between them, at the level of "which outstanding `BF-NNN` items make sense to batch together next."

## Pool 1 — Escalated architecture findings (unscheduled)

Both are P2/P4 findings from the P1 Find/Replace rework review, explicitly escalated rather than folded into that work.

- [BF-040 \[P2\]](../BETA_FEEDBACK.md#bf-040-p2--per-document-task-pool-fairness-and-multi-document-benchmark-foundation) — Per-document task-pool fairness and multi-document benchmark foundation
- [BF-042 \[P4\]](../BETA_FEEDBACK.md#bf-042-p4--session-schema-is-being-bumped-one-field-at-a-time) — Session schema is being bumped one field at a time (worth revisiting now that BF-067's font-weight work bumped it again, to 5)

## Pool 2 — Benchmark coverage gaps

Measurement gaps, not implementation gaps — the features exist; there's no benchmark evidence for these scenarios.

- [BF-030](../BETA_FEEDBACK.md#bf-030--no-benchmark-coverage-for-many-concurrently-open-documents) — No benchmark coverage for many concurrently open documents
- [BF-031](../BETA_FEEDBACK.md#bf-031--no-benchmark-coverage-for-large-cutpaste-or-undoredo-at-scale) — No benchmark coverage for large cut/paste or undo/redo at scale

## Pool 3 — RTL's one remaining real gap

- Non-wrapped/horizontal-scroll multi-checkpoint case for an RTL line longer than one 8192-character checkpoint window. Investigated 2026-09-16 and deliberately not attempted: `HorizontalLayouts`'s progressive checkpoint model assumes reading further into a line always means visually further right (true for LTR, false for RTL), and a correct fix needs a mirrored coordinate space — a real architecture change touching several call sites currently tuned only for LTR, not a bounded patch. See the [RTL/bidi support plan](2026-09-15-rtl-bidi-support-plan.md)'s "Progress" section and [BF-064](../BETA_FEEDBACK.md#bf-064--rtlbidi-content-support-arabic--hebrew) for the full investigation.

## Pool 4 — Native/hosted confirmation (standing, blocked without hardware/testers)

Every item below is code-complete; only affected-host, native-input, or hosted-CI confirmation remains. This pool cannot move without physical hardware or the B1 tester program — it's not a coding task.

- [BF-001](../BETA_FEEDBACK.md#bf-001--slow-windows-first-launch-with-limited-progress-feedback)–[BF-010](../BETA_FEEDBACK.md#bf-010--eol-markers-unchanged-when-the-status-line-updates) (partial — most items in this range still need affected-host or native-input confirmation; see each entry's own Status line for which)
- [BF-017](../BETA_FEEDBACK.md#bf-017--findreplace-zoom-keyboard-shortcut-does-not-work-in-the-find-field) — Find/Replace zoom shortcut (native affected-host confirmation)
- [BF-019](../BETA_FEEDBACK.md#bf-019--match-report-capture-group-row-indentation-and-truncated-label) — Match Report label alignment (native visual confirmation)
- [BF-025](../BETA_FEEDBACK.md#bf-025--last-line-of-a-file-displays-only-80-when-the-editor-is-focused) — Last line partial-height fix (native visual confirmation)
- RTL/bidi (BF-064) physical Arabic/Hebrew IME qualification — needs native hardware, not just an emulator

## Pool 5 — Long-term wishlist (deliberately unscoped)

Recorded in the [Feature Wishlist](../FEATURE_WISHLIST.md), not yet promoted to a `BF-NNN` entry.

- Compare/diff between two files or open documents
- Multi-cursor / Select All Occurrences — deliberately kept long-term only (2026-09-13 direction); a data-model change to `EditorState`, not a UI toggle

## Also still open — BF-063's parked color half

Not pooled above because it's a single item with its own un-parking precondition, not a batch: [BF-063](../BETA_FEEDBACK.md#bf-063--theme--text-type-profile-editor)'s syntax-category-color editor stays parked in the [file-type-profiles capability](../04_parked/CATALOG.md#file-type-profiles-and-syntax-highlighting) — its extension→profile mapping half landed (see below), the color half needs the same kind of un-parking decision [ADR-0009](../05_decisions/ADR-0009-bounded-open-folder-by-type.md) recorded for BF-029, and wasn't pursued this pass.

## Not pooled — standing release-qualification gates

Unrelated to any `BF-NNN` item above; tracked by the [ROADMAP](ROADMAP.md) and [Current Status](../01_current/STATUS.md), not this document: the A22 seven real-use days, A23 executable health/recovery delivery, A24 stabilization, and the B1 fourteen-day three-tester feedback program.

## Recently closed (context for why they're absent above)

For continuity when this document is next refreshed: BF-029 (Open Folder by Type), BF-061 (Format/Minify Document), BF-064's content-level bidi work including its 2026-09-16 multi-rect-selection and caret-affinity fixes, BF-066 (font selection policy and Arabic/Hebrew bundling), and BF-067 (global font weight) all landed and were archived or updated between 2026-09-15 and 2026-09-16. This document's former Pool 1 (Recent Files, Find/Replace panel sizing, current-line highlight, Unicode hex hotkey — BF-058/059/060/053) and Pool 2 (Markdown preview, the extension→profile mapping half of the theme/text-type editor, and Inspect Selection — BF-062/063/065) all landed the same day (2026-09-16); see each `BF-NNN` entry in the [Beta Feedback Log](../BETA_FEEDBACK.md) for its implementation and verification notes. See [`03_implemented/README.md`](../03_implemented/milestones/README.md#v0001b3-workstream-records) for the archived plans.
