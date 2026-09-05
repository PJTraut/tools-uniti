# UNITI Current Handover

Captured: 2026-09-05

This is a continuation snapshot, not a controlling specification. Resolve conflicts using the authority order in the [Documentation System](../00_governance/DOCUMENTATION_SYSTEM.md).

## Canonical repository state

- Repository: `https://github.com/PJTraut/tools-uniti.git`
- Canonical branch: `main`
- Remote baseline: `origin/main` at hosted-proven candidate `8b24f4b`
- A20 design/plan commits: `c9cd792`, `06dd906`
- A20 implementation/acceptance sequence: `fabd036` through `f829d01`, followed by the A20 freeze closure
- A21 Editor Layout and Visibility design/plan commits: `9477197`, `61c1f19`
- A21 Editor Layout and Visibility implementation sequence: `23d6c2d` through `dcf04c6`, plus schema-reporting repair `fcfd5ea`
- A21 Cross-Platform design/plan commit: `a3a4d81`
- A21 Cross-Platform candidate/remediation sequence: `09ad62b` through `8b24f4b`
- Latest implemented milestone: `v0.001a21` — Cross-Platform Alpha at hosted-proven commit `8b24f4b`
- Active milestone: `v0.001a22` — Dogfood / Performance Alpha
- Queued milestones: `v0.001a23` — Executable Health & Recovery Alpha; `v0.001a24` — Beta Candidate
- Current display/package metadata: `v0.001a21` / `0.1a21`
- Latest immutable tag: `v0.001a15` at `10f419e`
- a16 through a20 tags: none

A20, the A21 Editor Layout and Visibility workstream, and the A21 Cross-Platform source candidate are implemented on `main`. The required macOS, Windows, Linux/Python 3.12, and Linux/latest-Python jobs passed on identical commit `8b24f4b`. No new tag, release, installer, bundle, or other distributable package was created.

## Canonical records

- [Current status and exact evidence](../01_current/STATUS.md)
- [Current scope](../01_current/SCOPE.md)
- [Current architecture](../01_current/ARCHITECTURE.md)
- [Development and performance workflow](../01_current/DEVELOPMENT.md)
- [Ordered roadmap](../02_plans/ROADMAP.md)
- [Approved A22 design](../02_plans/v0.001a22-dogfood-performance-design.md)
- [A22 implementation plan](../02_plans/v0.001a22-dogfood-performance-implementation.md)
- [Queued A23 executable health/recovery design](../02_plans/v0.001a23-executable-health-recovery-design.md)
- [Executable-only product boundary decision](../05_decisions/ADR-0006-executable-health-recovery-boundary.md)
- [Implemented A20 milestone](../03_implemented/milestones/2026-09-04-uniti-v0.001a20-recovery-session-alpha.md)
- [Implemented A20 design](../03_implemented/designs/2026-09-04-uniti-v0.001a20-recovery-session-design.md)
- [Implemented A20 execution plan](../03_implemented/milestones/2026-09-04-uniti-v0.001a20-recovery-session-implementation.md)
- [Implemented A21 Editor Layout and Visibility design](../03_implemented/designs/2026-09-05-uniti-v0.001a21-editor-layout-visibility-design.md)
- [Implemented A21 Editor Pane Docking plan](../03_implemented/milestones/2026-09-05-uniti-v0.001a21-editor-pane-docking-implementation.md)
- [Implemented A21 Find/Replace Docking plan](../03_implemented/milestones/2026-09-05-uniti-v0.001a21-find-replace-docking-implementation.md)
- [Implemented A21 Whitespace and Theme plan](../03_implemented/milestones/2026-09-05-uniti-v0.001a21-whitespace-theme-implementation.md)
- [Implemented A21 Cross-Platform milestone](../03_implemented/milestones/2026-09-05-uniti-v0.001a21-cross-platform-alpha.md)
- [Implemented A21 Cross-Platform design](../03_implemented/designs/2026-09-05-uniti-v0.001a21-cross-platform-design.md)
- [Implemented A21 Cross-Platform execution plan](../03_implemented/milestones/2026-09-05-uniti-v0.001a21-cross-platform-implementation.md)
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

## A21 Cross-Platform closure

Shared code now classifies only macOS, Windows, and Linux; selects absolute native application roots; normalizes native identity without hard-coded shared drive/separator rules; and routes durable settings/setup/Save/session/recovery publication through explicit `full`, `file_synced`, or `unsafe` results. Unsafe publication preserves prior complete state. Session discovery scans at most 200 complete generations and repairs a missing/stale pointer only after usable restoration under one-writer authority.

The POSIX and Windows launchers have real native-shell argument/working-directory/exit tests. Qt resolves native standard shortcuts plus bounded portable overrides and selects one concrete fixed-pitch font with Latin/Cyrillic coverage. Deep self-check, export-safe diagnostics, and smoke publish bounded facts rather than roots or document/IPC/session/recovery content; smoke proves Unicode/spaced paths, one primary with a forwarding contender, restored service/session/history state, and explicit Quit.

`scripts/a21_ci.py` validates only the ownership-marked runtime, produces complete JUnit, enforces the exact per-family skip policy, runs compile/self-check/offscreen/native smoke, and sanitizes a fixed parsed artifact set within 2 MiB per-file and 8 MiB aggregate input budgets. `.github/workflows/a21-cross-platform.yml` pins read-only action revisions and four fail-closed macOS/Windows/Linux lanes. All four passed in authoritative hosted run [33945017353](https://github.com/PJTraut/tools-uniti/actions/runs/33945017353).

Hosted remediation preserved the shared architecture while adding native Windows process liveness and memory probes, shared-delete file access, safe replacement/publication, bounded installed-font exposure for offscreen Qt, portable sparse fixtures, deterministic exact-byte/newline fixtures, and a batch-to-bootstrap argument handoff that prevents `cmd.exe` from re-parsing user metacharacters. The sequence begins at `1c1952d` and ends at hosted candidate `8b24f4b`.

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
full pytest: 1257 passed, 6 skipped in 51.55s
compileall and git diff --check: pass
deep self-check: pass, 21/21 checks including cross-platform
offscreen/native combined smoke: pass with full durability, font, shortcut, instance, service/session/history, and explicit-Quit facts; native qt_platform=cocoa
```

The six skips exactly match the macOS policy: one Windows native-path test, three Windows `cmd.exe` tests, one Windows PowerShell test, and one filesystem-backed local-endpoint test. Optional xattr availability is a capability result rather than a skip.

The local quick run recorded representative medians of 12.501 ms open-to-usable, 469.549 ms sparse navigation completion, 42.553 ms capture report, 46.430 ms Save completion, and 35.809/47.743 ms session open/completion with 17.562 MiB retained RSS. The a18/a19 committed baselines remain inherited evidence; no A21 baseline was selected and no real LOWDISK state was created.

The same-commit hosted matrix is:

| Job | Runner / Python | Qt / native plugin | Font / durability | Complete pytest |
|---|---|---|---|---|
| [macos-py312](https://github.com/PJTraut/tools-uniti/actions/runs/33945017353/job/101249420423) | `macos-15` / `3.12.10` | `6.11.2` / `cocoa` | Menlo / `full` | 1257 passed, 6 skipped |
| [windows-py312](https://github.com/PJTraut/tools-uniti/actions/runs/33945017353/job/101249420366) | `windows-2025` / `3.12.10` | `6.11.2` / `windows` | Cascadia Mono / `file_synced` | 1256 passed, 7 skipped |
| [linux-py312](https://github.com/PJTraut/tools-uniti/actions/runs/33945017353/job/101249420400) | `ubuntu-24.04` / `3.12.14` | `6.11.2` / `xcb` | DejaVu Sans Mono / `full` | 1256 passed, 7 skipped |
| [linux-latest](https://github.com/PJTraut/tools-uniti/actions/runs/33945017353/job/101249420399) | `ubuntu-24.04` / `3.14.7` | `6.11.2` / `xcb` | DejaVu Sans Mono / `full` | 1256 passed, 7 skipped |

Each job also passed compilation, 21/21 deep self-check, offscreen/native smoke, and exact skip verification. Successful jobs uploaded no artifacts, and no distributable package was produced.

## Known boundary and next safe action

No known A20, completed A21 workstream, or A21 candidate correctness, durability, concurrent-writer, external-overwrite, responsiveness, unbounded-allocation, launcher, native-path, or inherited text-integrity/regex blocker remains in local or hosted evidence. The service is not a permanently installed daemon; it persists with zero windows only while the launched process remains alive.

Begin A22 from the active [Dogfood / Performance Alpha milestone](../02_plans/v0.001a22-dogfood-performance-alpha.md). Preserve A21's source-only hosted matrix and the A17–A21 correctness/storage boundaries; do not create a tag, release, installer, package, or new performance baseline without its own approved gate. A23 Executable Health & Recovery Alpha is approved and queued behind A22; it is not implicit A22 scope. The A21 closure commit remains local unless separately authorized for push.
