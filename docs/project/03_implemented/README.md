# Implemented UNITI Work

This directory contains completed, verified historical work. In UNITI project grammar, `implemented` inherently includes archival retention; no separate archive status or folder is used.

## Contents

- [`milestones/`](milestones/) retains completed milestone and workstream implementation plans.
- [`designs/`](designs/) retains the design and specification records that governed those milestones.

## Interpretation

Directory placement means the work is implemented. Completion is established by repository code and tests, Git history, milestone completion commits, tags where applicable, and recorded verification evidence.

Historical plans may contain unchecked task boxes because they are retained as originally authored execution records. Those stale checklist marks do not move implemented work back into the outstanding plan queue.

An implemented workstream is complete in its own right but does not imply that its parent product milestone is complete. a16's startup/bootstrap foundation and a21's Editor Layout and Visibility workstream were retained here before their parent gates closed; the complete a16 through a21 product milestones are now implemented.

## v0.001b3 workstream records

Retained here individually while their parent [B3 milestone](../02_plans/v0.001b3-find-replace-and-editor-refinement-beta.md) is still active, per the same pattern as a16/a21 below.

- [B2 Find/Replace rework implementation plan](milestones/2026-09-13-b2-find-replace-rework-implementation.md) (BF-039 plus 12 consolidated Find/Replace-panel items) — archived 2026-09-16 after this review found its status line stale; all phases were already complete.
- [Format Document / Minify Document plan](milestones/2026-09-15-format-document-plan.md) (BF-061)
- [Arabic + Hebrew font bundling plan](milestones/2026-09-16-arabic-hebrew-font-bundling-plan.md) (BF-066)

The [RTL/bidi support plan](../02_plans/2026-09-15-rtl-bidi-support-plan.md) (BF-064) stays in `02_plans/` — most of its scope is implemented, but it still names real, non-hardware-dependent unfinished work of its own (the non-wrapped/horizontal-scroll multi-checkpoint case), not just an external gate.

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
