# UNITI Current Status

Date: 2026-09-04

## Canonical baseline

| Item | Current value |
|---|---|
| Repository branch | local `main` |
| Remote baseline | `origin/main` at `84407e3` |
| Verified A20 implementation sequence | `fabd036` through `f829d01`, preceded by design/plan commits `c9cd792` and `06dd906`, followed by the A20 freeze closure |
| Latest implemented milestone | `v0.001a20` — Recovery & Session Alpha |
| Active product milestone | `v0.001a21` — Cross-Platform Alpha |
| Display/package metadata | `v0.001a20` / `0.1a20` |
| Latest immutable release tag | `v0.001a15` at `10f419e` |
| Queued milestones | `v0.001a22` through `v0.001a23` |

The A20 implementation and freeze are local. `origin/main` remains unchanged until a separate push is authorized; no A20 tag was created.

## Implemented A20 behavior

- one user-scoped service is the only document/settings/session/recovery writer; secondary launches forward bounded activation/file requests and exit;
- closing the final window leaves the service running, while explicit Quit offers Save/Discard/Cancel once per unique modified document;
- multiple top-level windows, detachable tab groups, horizontal/vertical splits, and independent views share one authoritative document and Undo/Redo history per source;
- one service-owned Find/Replace panel follows the most recently focused live view and persists complete bounded field state/history, options, geometry, visibility, zoom, and report state;
- Find Previous and Find Next search relative to the cursor and wrap without requiring Find All; Find All remains a separate revision-bound result-store operation;
- durable startup sessions restore bounded window/pane/tab/view state, the active approved document first, other histories lazily, and saved-document Undo/Redo only when exact saved bytes remain compatible;
- SHA-256 is the saved-history authority; externally changed or missing files require explicit Open Disk/Locate Matching File, Skip, or Discard choices and are never overwritten automatically;
- recovery v3 records semantic transactions, Undo/Redo, save points, metadata, checkpoints, and terminal state; v1/v2 remain readable, truncated prefixes remain visible, and recovered evidence retires only after replacement durability exists; and
- all hashing, serialization, compression, fsync, discovery, replay, compaction, and saved-session publication work is scheduled off the GUI thread.

## Storage and safety policy

| State | Implemented bound/policy |
|---|---|
| Document Undo/Redo persistence | newest 50 transactions or 32 MiB decoded per document, first limit reached |
| Find history | at most 50 states |
| Replace history | at most 50 states |
| Combined Find/Replace persistence | 4 MiB decoded; current field state survives history pruning |
| Saved session/history union | 256 MiB physical cap across current and previous generation |
| Closed saved-document retention | seven days, subject to the aggregate cap |
| Session structure | 1 MiB manifest; 32 windows; 128 leaves; 256 views; 128 documents |
| Recovery compaction | 64 MiB per journal, publish before retirement |
| Low-space reserve | 512 MiB; suppress convenience history before recovery durability |

Aggregate pruning removes oldest closed-document history first, then inactive-open history, then oldest active-document transactions; current state is never evicted. Low-space tests use injected capacity and controlled write/fsync failures only—no test fills, reserves, or truncates the real filesystem to manufacture LOWDISK.

## A20 closure verification

Fresh verification on the implementation/freeze tree reported:

```text
A20 acceptance contract: 8 passed
integrated A20 plus inherited A17-A19 app/UI suites: 508 passed
full pytest: 1015 passed, 4 skipped
compileall and git diff --check: pass
deep self-check: pass, 20 checks including recovery-session
offscreen combined smoke: pass; service lifetime/restart/history restore exercised
native Cocoa combined smoke: pass; qt_platform=cocoa
offscreen quick performance suite: 13/13 PASS
native Cocoa quick performance suite: 13/13 PASS
```

The four skips are one unavailable xattr capability case and three Windows `cmd.exe` launcher cases unavailable on macOS. The acceptance suite contains an AST guard against real low-disk creation and covers failure-injected session publication, corruption, hash mismatch, recovery choice/second-crash safety, service lifetime, and global-panel state.

The new offscreen `session_restore` scenario measured median 6.703 ms open-to-usable, 3.353 ms GUI heartbeat p95, 1.640 ms cancellation, 22.578 MiB peak RSS growth, and 12.844 MiB retained growth. Native Cocoa measured 6.709 ms open-to-usable, 1.767 ms heartbeat p95, 5.974 ms maximum heartbeat, 1.468 ms cancellation, 23.219 MiB peak growth, and 13.469 MiB retained growth. Both runs proved storage/load callbacks ran on worker threads and all thirteen scenarios passed. These A20 runs were not selected as committed JSON baselines; the recorded [a19 routine](../../../benchmarks/baselines/v0.001a19-mac15-8-routine.json), [a19 native quick](../../../benchmarks/baselines/v0.001a19-mac15-8-native-quick.json), and [a18 sparse 1 GiB target](../../../benchmarks/baselines/v0.001a18-mac15-8-design-target.json) remain inherited evidence.

## Known boundary

No known session-writer race, silent admitted-history loss, external-file overwrite, recovery-evidence loss, unsafe instance takeover, cursor-navigation dependency on Find All, GUI freeze, unbounded allocation, or inherited text-integrity/regex blocker remains.

A20 does not install a permanent OS daemon: the zero-window service exists only while the launched desktop process remains alive and exits on explicit Quit, logout, shutdown, or process termination. Project/workspace semantics, cloud sync, collaboration, plugins, LSP, syntax highlighting, permanent background services, polished installers, editor whitespace visualization, and expanded keyboard-driven Unicode inspection remain outside A20.

The A20 milestone, design, and implementation plan are retained in [Implemented](../03_implemented/README.md). See [Scope](SCOPE.md), [Architecture](ARCHITECTURE.md), [Development](DEVELOPMENT.md), [Roadmap](../02_plans/ROADMAP.md), and the [Current Handover](../06_handovers/CURRENT_HANDOVER.md).
