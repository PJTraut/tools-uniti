# UNITI Current Handover

Captured: 2026-09-05

This is a continuation snapshot, not a controlling specification. Resolve conflicts using the authority order in the [Documentation System](../00_governance/DOCUMENTATION_SYSTEM.md).

## Canonical repository state

- Repository: `https://github.com/PJTraut/tools-uniti.git`
- Canonical branch: `main`
- Remote baseline: `origin/main` at `84407e3`
- A20 design/plan commits: `c9cd792`, `06dd906`
- A20 implementation/acceptance sequence: `fabd036` through `f829d01`, followed by the A20 freeze closure
- A21 Editor Layout and Visibility design/plan commits: `9477197`, `61c1f19`
- A21 Editor Layout and Visibility implementation sequence: `23d6c2d` through `dcf04c6`, plus schema-reporting repair `fcfd5ea`
- A21 Cross-Platform design/plan commit: `a3a4d81`
- A21 Cross-Platform local candidate sequence: `09ad62b`, `56b344f`, `fffe2ac`, then `f78c936` through `03b7545`
- Latest implemented milestone: `v0.001a20` — Recovery & Session Alpha
- Latest local candidate: `v0.001a21` — Cross-Platform Alpha; hosted evidence pending
- Active milestone: `v0.001a21` — Cross-Platform Alpha
- Current display/package metadata: `v0.001a21` / `0.1a21`
- Latest immutable tag: `v0.001a15` at `10f419e`
- a16 through a20 tags: none

A20, the A21 Editor Layout and Visibility workstream, and the A21 Cross-Platform source candidate are implemented and verified on local `main`. `origin/main` is intentionally unchanged until a separate push is authorized. The hosted lanes have not run on this candidate, and no new tag has been created.

## Canonical records

- [Current status and exact evidence](../01_current/STATUS.md)
- [Current scope](../01_current/SCOPE.md)
- [Current architecture](../01_current/ARCHITECTURE.md)
- [Development and performance workflow](../01_current/DEVELOPMENT.md)
- [Ordered roadmap](../02_plans/ROADMAP.md)
- [Implemented A20 milestone](../03_implemented/milestones/2026-09-04-uniti-v0.001a20-recovery-session-alpha.md)
- [Implemented A20 design](../03_implemented/designs/2026-09-04-uniti-v0.001a20-recovery-session-design.md)
- [Implemented A20 execution plan](../03_implemented/milestones/2026-09-04-uniti-v0.001a20-recovery-session-implementation.md)
- [Implemented A21 Editor Layout and Visibility design](../03_implemented/designs/2026-09-05-uniti-v0.001a21-editor-layout-visibility-design.md)
- [Implemented A21 Editor Pane Docking plan](../03_implemented/milestones/2026-09-05-uniti-v0.001a21-editor-pane-docking-implementation.md)
- [Implemented A21 Find/Replace Docking plan](../03_implemented/milestones/2026-09-05-uniti-v0.001a21-find-replace-docking-implementation.md)
- [Implemented A21 Whitespace and Theme plan](../03_implemented/milestones/2026-09-05-uniti-v0.001a21-whitespace-theme-implementation.md)
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

## A21 Editor Layout and Visibility workstream

Every pane now exposes Assign Document, Split Right, Split Down, and Dock/Undock. A split creates an independent view; an undock transactionally transfers one view and persists its source return anchor without changing the one authoritative document or shared history.

The one service-owned Find/Replace surface can attach full-width below the active editor window or detach as the same topmost tool. Placement, detached geometry, complete field state, bounded Undo/Redo, results, report state, and zoom survive window moves and session restore without creating a second panel.

Whitespace modes are Off, EOL, Spaces & Tabs, Invisible Unicode, and All. They paint only committed visible content, preserve exact document bytes/coordinates, classify LF/CRLF/CR through bounded terminator reads, and cap one frame at 4,096 marker operations with visible aggregation. System/Light/Dark and Standard/High Contrast are independent settings backed by complete theme tokens.

Implementation commits:

```text
23d6c2d feat: persist editor docking state
6bf6e8b feat: expose editor pane controls
a40d880 feat: add reversible document docking
5479048 fix: stabilize restored session document order
e3063c9 test: prove reversible editor layout
aae36d4 refactor: make find replace dockable
86cd592 feat: attach find replace to active window
ad52133 test: prove global find replace docking
2c5e275 feat: define whitespace display grammar
1561f32 feat: add high contrast theme axis
dcf04c6 feat: visualize whitespace safely
fcfd5ea fix: report current persistence schemas
```

## A21 Cross-Platform candidate

Shared code now classifies only macOS, Windows, and Linux; selects absolute native application roots; normalizes native identity without hard-coded shared drive/separator rules; and routes durable settings/setup/Save/session/recovery publication through explicit `full`, `file_synced`, or `unsafe` results. Unsafe publication preserves prior complete state. Session discovery scans at most 200 complete generations and repairs a missing/stale pointer only after usable restoration under one-writer authority.

The POSIX and Windows launchers have real native-shell argument/working-directory/exit tests. Qt resolves native standard shortcuts plus bounded portable overrides and selects one concrete fixed-pitch font with Latin/Cyrillic coverage. Deep self-check, export-safe diagnostics, and smoke publish bounded facts rather than roots or document/IPC/session/recovery content; smoke proves Unicode/spaced paths, one primary with a forwarding contender, restored service/session/history state, and explicit Quit.

`scripts/a21_ci.py` validates only the ownership-marked runtime, produces complete JUnit, enforces the exact per-family skip policy, runs compile/self-check/offscreen/native smoke, and sanitizes a fixed parsed artifact set within 2 MiB per-file and 8 MiB aggregate input budgets. `.github/workflows/a21-cross-platform.yml` pins read-only action revisions and four fail-closed macOS/Windows/Linux lanes. This workflow definition is committed locally; no hosted result is claimed.

Implementation commits:

```text
09ad62b feat: define cross-platform path policy
56b344f refactor: share native path identity
fffe2ac feat: report filesystem durability levels
f78c936 feat: preserve state across durability downgrades
f029ebb feat: repair sessions from complete generations
a27ddba test: prove portable source launchers
bc8cf91 feat: resolve native shortcut policy
1b73b04 feat: validate the editor fixed font
f3fc381 test: add cross-platform runtime evidence
e1a51bf test: enforce exact platform evidence
03b7545 ci: add a21 cross-platform gate
```

## Fresh evidence

```text
focused A21 cross-platform slice: 165 passed, 6 skipped in 10.17s
full pytest: 1232 passed, 6 skipped in 51.82s
compileall and git diff --check: pass
deep self-check: pass, 21/21 checks including cross-platform
offscreen/native combined smoke: pass with full durability, font, shortcut, instance, service/session/history, and explicit-Quit facts; native qt_platform=cocoa
quick performance: pass, 13/13 unchanged scenarios; no new baseline selected
```

The six skips exactly match the macOS policy: one Windows native-path test, three Windows `cmd.exe` tests, one Windows PowerShell test, and one filesystem-backed local-endpoint test. Optional xattr availability is a capability result rather than a skip.

The local quick run recorded representative medians of 12.501 ms open-to-usable, 469.549 ms sparse navigation completion, 42.553 ms capture report, 46.430 ms Save completion, and 35.809/47.743 ms session open/completion with 17.562 MiB retained RSS. The a18/a19 committed baselines remain inherited evidence; no A21 baseline was selected and no real LOWDISK state was created.

## Known boundary and next safe action

No known A20, completed A21 workstream, or local A21 candidate correctness, durability, concurrent-writer, external-overwrite, responsiveness, unbounded-allocation, or inherited text-integrity/regex blocker remains. The service is not a permanently installed daemon; it persists with zero windows only while the launched process remains alive. Authoritative hosted evidence is still pending.

Continue with Task 13 of the active [A21 Cross-Platform implementation plan](../02_plans/v0.001a21-cross-platform-implementation.md): only after explicit authorization, push the exact clean candidate commit and obtain all four hosted job URLs. Remediate any platform defect in shared code test-first and rerun every lane on one commit. Do not tag, release, or freeze A21 before that evidence succeeds.
