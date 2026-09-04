# UNITI Current Handover

Captured: 2026-09-04

This is a continuation snapshot, not a controlling specification. Resolve conflicts using the authority order in the [Documentation System](../00_governance/DOCUMENTATION_SYSTEM.md).

## Canonical repository state

- Repository: `https://github.com/PJTraut/tools-uniti.git`
- Canonical branch: `main`
- Remote baseline: `origin/main` at `84407e3`
- A20 design/plan commits: `c9cd792`, `06dd906`
- A20 implementation/acceptance sequence: `fabd036` through `f829d01`, followed by the A20 freeze closure
- Latest implemented milestone: `v0.001a20` — Recovery & Session Alpha
- Active milestone: `v0.001a21` — Cross-Platform Alpha
- Current display/package metadata: `v0.001a20` / `0.1a20`
- Latest immutable tag: `v0.001a15` at `10f419e`
- a16 through a20 tags: none

A20 is implemented and verified on local `main`. `origin/main` is intentionally unchanged until a separate push is authorized; no tag has been created.

## Canonical records

- [Current A20 status and exact evidence](../01_current/STATUS.md)
- [Current scope](../01_current/SCOPE.md)
- [Current architecture](../01_current/ARCHITECTURE.md)
- [Development and performance workflow](../01_current/DEVELOPMENT.md)
- [Ordered roadmap](../02_plans/ROADMAP.md)
- [Implemented A20 milestone](../03_implemented/milestones/2026-09-04-uniti-v0.001a20-recovery-session-alpha.md)
- [Implemented A20 design](../03_implemented/designs/2026-09-04-uniti-v0.001a20-recovery-session-design.md)
- [Implemented A20 execution plan](../03_implemented/milestones/2026-09-04-uniti-v0.001a20-recovery-session-implementation.md)
- [Implemented record index](../03_implemented/README.md)
- [Parked capabilities](../04_parked/CATALOG.md)
- [Architecture decisions](../05_decisions/README.md)

## A20 closure

A20 establishes one process-lifetime `UNITIService` as the sole authority for documents, settings, recovery, durable sessions, windows, and the one global Find/Replace panel. Secondary launches forward requests to the primary. The service remains alive after its final window closes; later activation can create or raise a window, and only explicit Quit resolves Save/Discard/Cancel across unique modified documents before shutting down.

Every source has one authoritative `Document` shared by independent views across tabs, splits, detached groups, and windows. Durable generation publication restores bounded pane/view state, the active approved document first, per-document saved Undo/Redo, and complete Find/Replace field/panel state. Find Previous/Next now search before/after the live cursor independently of Find All.

Saved history is authorized by SHA-256 of exact bytes, retained for seven days subject to the 256 MiB aggregate cap, and bounded per document at 50 transactions or 32 MiB decoded. Find and Replace retain at most 50 states each within 4 MiB decoded. Recovery v3 preserves semantic transactions, Undo/Redo, save points, and replacement evidence; journals compact at 64 MiB and low-space policy reserves 512 MiB while tests use injected failures only.

Implementation commits:

```text
fabd036 feat: add bounded semantic history snapshots
8dc5cc1 feat: define bounded session persistence schemas
c4de276 feat: publish durable session generations safely
152a997 fix: make find navigation cursor-relative
dc15e0b feat: add semantic recovery journal v3
368fe9a feat: harden recovery durability and compaction
e97de85 feat: persist global find replace state
45d1454 feat: add process lifetime document service
952c5e7 feat: restore independent shared document views
acaa66b feat: add split panes and detachable tabs
1ba35e2 feat: support one service with multiple windows
c6eb0ed feat: add explicit recovery center choices
5fbdfaa feat: enforce one service instance
b2bb917 feat: restore complete sessions and histories
f829d01 test: prove a20 recovery session safety
```

## Fresh evidence

```text
A20 acceptance: 8 passed
integrated A20 + inherited A17-A19 app/UI: 508 passed
full pytest: 1015 passed, 4 skipped
compileall and git diff --check: pass
deep self-check: pass, 20 checks including recovery-session
offscreen and native Cocoa combined smoke: pass
offscreen quick: 13/13 PASS
native Cocoa quick: 13/13 PASS
```

`session_restore` passed all worker-thread, responsiveness, cancellation, cleanup, and RSS gates. Its offscreen/native open-to-usable medians were 6.703/6.709 ms and retained RSS growth was 12.844/13.469 MiB. No A20 JSON baseline was selected; the a18/a19 committed baselines remain inherited evidence. No real LOWDISK state was created.

## Known boundary and next safe action

No known A20 correctness, durability, concurrent-writer, external-overwrite, responsiveness, unbounded-allocation, or inherited text-integrity/regex blocker remains. The service is not a permanently installed daemon; it persists with zero windows only while the launched process remains alive.

Continue with the active A21 Cross-Platform Alpha record on local `main`, preserving all A17-A20 acceptance and performance gates. Verify platform-specific behavior before changing canonical architecture. Do not tag or push until separately authorized.
