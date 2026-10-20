# Implemented UNITI Work

This directory contains completed, verified historical work. In UNITI project grammar, `implemented` inherently includes archival retention; no separate archive status or folder is used.

## Contents

- [`milestones/`](milestones/) retains completed milestone and workstream implementation plans.
- [`designs/`](designs/) retains the design and specification records that governed those milestones.

## Interpretation

Directory placement means the work is implemented. Completion is established by repository code and tests, Git history, milestone completion commits, tags where applicable, and recorded verification evidence.

Historical plans may contain unchecked task boxes because they are retained as originally authored execution records. Those stale checklist marks do not move implemented work back into the outstanding plan queue.

An implemented workstream is complete in its own right but does not imply that its parent product milestone is complete. a16's startup/bootstrap foundation and a21's Editor Layout and Visibility workstream were retained here before their parent gates closed; the complete a16 through a21 product milestones are now implemented.

## Environment track records (2026-09-29 → 2026-10-15)

The file-type environment and USFM track, run alongside B4 ([ADR-0013](../05_decisions/ADR-0013-environment-framework-ownership-boundary.md)–[ADR-0019](../05_decisions/ADR-0019-named-environment-windows-groups-and-project-tabs.md)). Moved here 2026-10-13; every phase is implemented. Live-app checks still open are tracked in [Current Status](../01_current/STATUS.md#environment-track-2026-09-29--2026-10-09), not here.

- [Environment framework E1–E4](milestones/2026-09-29-environment-framework-e1-e4-plan.md), [E5 SFM foundation](milestones/2026-09-29-environment-framework-e5-sfm-foundation-plan.md), [E6 USFM layer](milestones/2026-09-30-environment-framework-e6-usfm-layer-plan.md)
- [Environment workbench](milestones/2026-10-02-environment-workbench-plan.md) and [rich views and grouped tabs](milestones/2026-10-02-rich-views-and-grouped-tabs-plan.md) (E7–E10)
- [USFM field test](milestones/2026-10-07-usfm-field-test-plan.md), [round 2](milestones/2026-10-08-usfm-field-test-round-2-plan.md) (R1–R8) and [round 3](milestones/2026-10-08-usfm-field-test-round-3-plan.md) (T1–T7, plus the 2026-10-13 spec-check fixes)
- [USFM projects and versification](milestones/2026-10-07-usfm-projects-and-versification-plan.md) (P1–P5)
- [Show One Chapter](milestones/2026-10-09-usfm-per-chapter-view-plan.md) (C1–C4)
- [USFM book lock](milestones/2026-10-14-usfm-book-lock-plan.md) (L1–L5), [Check Spelling](milestones/2026-10-13-usfm-spellcheck-plan.md) (S1–S5) and the [footnote category filter](milestones/2026-10-14-footnote-category-filter-plan.md)
- [Hyphenation, justification and spelling follow-ups](milestones/2026-10-15-usfm-hyphenation-and-spelling-followups-plan.md) (H1–H3, J1, F1–F5)
- [USFM text direction](milestones/2026-10-15-usfm-text-direction-plan.md) (W1–W8)

## v0.001b4 workstream records

- [Compare/diff plan](milestones/2026-09-17-compare-diff-plan.md) (BF-070): Phases 1–2 implemented; Phase 3 (doc-vs-disk) is [parked](../04_parked/CATALOG.md#compare-doc-vs-disk-mode).

## v0.001b3 workstream records

Retained here individually while their parent [B3 milestone](../02_plans/v0.001b3-find-replace-and-editor-refinement-beta.md) is still active, per the same pattern as a16/a21 below.

- [B2 Find/Replace rework implementation plan](milestones/2026-09-13-b2-find-replace-rework-implementation.md) (BF-039 plus 12 consolidated Find/Replace-panel items) — archived 2026-09-16 after this review found its status line stale; all phases were already complete.
- [Format Document / Minify Document plan](milestones/2026-09-15-format-document-plan.md) (BF-061)
- [Arabic + Hebrew font bundling plan](milestones/2026-09-16-arabic-hebrew-font-bundling-plan.md) (BF-066)
- [Pool 1 task-fairness and schema-flexibility plan](milestones/2026-09-17-pool-1-task-fairness-and-schema-flexibility-plan.md) (BF-040, BF-042) — the last two escalated architecture findings from the P1 Find/Replace rework review; closed the outstanding-work-pools index's former Pool 1
- [RTL/bidi support plan](milestones/2026-09-15-rtl-bidi-support-plan.md) (BF-064) — archived 2026-09-17 once its last non-hardware-dependent gap (the non-wrapped/horizontal-scroll multi-checkpoint case) landed; only native/physical IME qualification, an external hardware gate, remains, tracked in [Current Status](../01_current/STATUS.md)

## v0.001a21 records

- [Cross-Platform Alpha milestone](milestones/2026-09-05-uniti-v0.001a21-cross-platform-alpha.md)
- [Cross-Platform Alpha implementation plan](milestones/2026-09-05-uniti-v0.001a21-cross-platform-implementation.md)
- [Cross-Platform Alpha design](designs/2026-09-05-uniti-v0.001a21-cross-platform-design.md)
- [Editor Layout and Visibility design](designs/2026-09-05-uniti-v0.001a21-editor-layout-visibility-design.md)
- [Editor Pane Docking implementation plan](milestones/2026-09-05-uniti-v0.001a21-editor-pane-docking-implementation.md)
- [Find/Replace Docking implementation plan](milestones/2026-09-05-uniti-v0.001a21-find-replace-docking-implementation.md)
- [Whitespace and Theme implementation plan](milestones/2026-09-05-uniti-v0.001a21-whitespace-theme-implementation.md)

## v0.001a20 records

- [Recovery & Session Alpha milestone](milestones/2026-09-04-uniti-v0.001a20-recovery-session-alpha.md)
- [Recovery & Session Alpha implementation plan](milestones/2026-09-04-uniti-v0.001a20-recovery-session-implementation.md)
- [Recovery & Session Alpha design](designs/2026-09-04-uniti-v0.001a20-recovery-session-design.md)

## v0.001a19 records

- [Regex Intelligence Alpha milestone](milestones/2026-09-02-uniti-v0.001a19-regex-intelligence-alpha.md)
- [Regex Intelligence Alpha implementation plan](milestones/2026-09-02-uniti-v0.001a19-regex-intelligence-implementation.md)
- [Regex Intelligence Alpha design](designs/2026-09-02-uniti-v0.001a19-regex-intelligence-design.md)

## v0.001a18 records

- [Large-File Alpha milestone](milestones/2026-09-02-uniti-v0.001a18-large-file-alpha.md)
- [Large-File Alpha implementation plan](milestones/2026-09-02-uniti-v0.001a18-large-file-implementation.md)
- [Large-File Alpha design](designs/2026-09-02-uniti-v0.001a18-large-file-design.md)

## v0.001a17 records

- [Text Integrity Alpha milestone](milestones/2026-09-01-uniti-v0.001a17-text-integrity-alpha.md)
- [Text Integrity Alpha implementation plan](milestones/2026-09-01-uniti-v0.001a17-text-integrity-implementation.md)
- [Text Integrity Alpha design](designs/2026-09-01-uniti-v0.001a17-text-integrity-design.md)

## v0.001a16 records

- [Usable Test Alpha milestone](milestones/2026-09-01-uniti-v0.001a16-usable-test-alpha.md)
- [Usable Test Alpha implementation plan](milestones/2026-09-01-uniti-v0.001a16-usable-test-alpha-implementation.md)
- [Startup/bootstrap foundation](milestones/2026-09-01-uniti-v0.001a16-startup-bootstrap.md)
- [Startup/bootstrap implementation plan](milestones/2026-09-01-uniti-v0.001a16-startup-bootstrap-implementation.md)
- [Startup/bootstrap design](designs/2026-09-01-uniti-v0.001a16-startup-bootstrap-design.md)

Implemented records never return to `02_plans`. A correction, extension, or replacement receives a new plan and, when it changes a consequential choice, a new or superseding architecture decision record.

Mechanical path corrections and explicit status notes are permitted when the documentation system changes, but historical requirements and intent remain intact.
