# UNITI Current Status

Date: 2026-09-05

## Canonical baseline

| Item | Current value |
|---|---|
| Repository branch | local `main` |
| Remote baseline | `origin/main` at `84407e3` |
| Verified A20 implementation sequence | `fabd036` through `f829d01`, preceded by design/plan commits `c9cd792` and `06dd906`, followed by the A20 freeze closure |
| Verified A21 Editor Layout and Visibility sequence | `23d6c2d` through `dcf04c6`, plus schema-reporting repair `fcfd5ea`; preceded by design/plan commits `9477197` and `61c1f19` |
| Local A21 Cross-Platform candidate sequence | `09ad62b`, `56b344f`, `fffe2ac`, then `f78c936` through `03b7545`; preceded by plan commit `a3a4d81` |
| Latest implemented milestone | `v0.001a20` — Recovery & Session Alpha |
| Latest local candidate | `v0.001a21` — Cross-Platform Alpha; hosted evidence pending |
| Active product milestone | `v0.001a21` — Cross-Platform Alpha |
| Display/package metadata | `v0.001a21` / `0.1a21` |
| Latest immutable release tag | `v0.001a15` at `10f419e` |
| Queued milestones | `v0.001a22` through `v0.001a23` |

The A20 implementation/freeze, completed A21 workstream, and A21 cross-platform candidate are local. `origin/main` remains unchanged until a separate push is authorized; the four hosted lanes have not run on this candidate and no new tag was created.

## Locally implemented A21 Cross-Platform behavior

- one Qt-free policy classifies only macOS, Windows, and Linux, selects absolute native application roots, and keeps existing-file/native lexical identity consistent without hard-coded shared-code drive or separator assumptions;
- one durability adapter reports `full`, `file_synced`, or `unsafe`; settings, setup, Save, sessions, recovery, compaction, and pointer repair preserve the last complete state instead of direct-overwrite fallback;
- session discovery validates at most 200 complete generations and repairs a missing/stale pointer only after a usable scanned generation restores under one-writer authority;
- real POSIX `sh`, Windows `cmd.exe`, and PowerShell launcher contracts cover Unicode, spaces, metacharacters, working directory, interpreter discovery, and exit propagation;
- native Qt standard shortcuts, portable bounded overrides, and one concrete fixed-pitch Latin/Cyrillic editor font are resolved only after `QApplication`;
- deep self-check, diagnostics export, and combined smoke expose bounded categorized/capability facts without raw roots, document/IPC content, or session/recovery paths; smoke includes a Unicode/spaced source and real local-instance forwarding; and
- a standard-library owned-runtime CI driver enforces exact per-family skip sets, 2 MiB per-file/8 MiB aggregate sanitizer budgets, seven-day metadata, and a fixed parsed artifact allowlist. The pinned read-only workflow defines four fail-closed lanes and failure-only uploads, but hosted results remain pending.

## Implemented A21 Editor Layout and Visibility behavior

- every pane has direct Dock/Undock, Split Right, Split Down, and Assign Document controls; splitting creates an independent view and assignment never replaces an existing tab;
- undocking transfers one view transactionally into another service window, persists the source window/pane/tab return anchor, and docks back exactly when available with bounded deterministic fallbacks;
- the one service-owned Find/Replace surface is a bottom-only full-width dock that follows the active window while attached and remains one modeless topmost tool while detached;
- Find/Replace placement, detached geometry, options, results, zoom, report state, and bounded input Undo/Redo survive host moves and session restoration without a second panel;
- whitespace visualization is display-only with Off, EOL, Spaces & Tabs, Invisible Unicode, and All modes; logical LF/CRLF/CR labels use bounded terminator reads, and marker painting is capped at 4,096 operations per frame with visible overflow aggregation; and
- System/Light/Dark appearance and Standard/High Contrast are independent global settings. Complete editor tokens meet the verified High Contrast thresholds of 7:1 for primary text and 4.5:1 for whitespace markers.

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

## Current verification

Fresh local verification on the A21 candidate tree reported:

```text
focused A21 cross-platform slice: 165 passed, 6 skipped in 10.17s
full pytest: 1232 passed, 6 skipped in 51.82s
compileall and git diff --check: pass
deep self-check: pass, 21/21 checks including cross-platform
offscreen combined smoke: pass; full durability, font, shortcuts, instance forwarding, service/session/history, and explicit Quit facts
native Cocoa combined smoke: pass with the same invariants and qt_platform=cocoa
quick performance: pass, 13/13 unchanged scenarios; no new baseline selected
```

The six skips exactly match `ci/a21-skip-policy.json`: one Windows native-path test, three Windows `cmd.exe` launcher tests, one Windows PowerShell launcher test, and one filesystem-backed local-endpoint test. Optional xattr availability is now a capability fact rather than a skip. The acceptance suite retains its AST guard against real low-disk creation and all reversible docking, one-panel placement, display-only byte integrity, terminator, contrast, and marker-budget coverage.

The local quick run recorded representative medians of 12.501 ms open-to-usable, 469.549 ms sparse navigation completion, 42.553 ms capture report, 46.430 ms Save completion, and 35.809/47.743 ms session open/completion with 17.562 MiB retained RSS. These are evidence only; thresholds and committed baselines were unchanged, and no real LOWDISK state was created.

The new offscreen `session_restore` scenario measured median 6.703 ms open-to-usable, 3.353 ms GUI heartbeat p95, 1.640 ms cancellation, 22.578 MiB peak RSS growth, and 12.844 MiB retained growth. Native Cocoa measured 6.709 ms open-to-usable, 1.767 ms heartbeat p95, 5.974 ms maximum heartbeat, 1.468 ms cancellation, 23.219 MiB peak growth, and 13.469 MiB retained growth. Both runs proved storage/load callbacks ran on worker threads and all thirteen scenarios passed. These A20 runs were not selected as committed JSON baselines; the recorded [a19 routine](../../../benchmarks/baselines/v0.001a19-mac15-8-routine.json), [a19 native quick](../../../benchmarks/baselines/v0.001a19-mac15-8-native-quick.json), and [a18 sparse 1 GiB target](../../../benchmarks/baselines/v0.001a18-mac15-8-design-target.json) remain inherited evidence.

## Known boundary

No known shared-code session-writer race, silent admitted-history loss, external-file overwrite, recovery-evidence loss, unsafe instance takeover, cursor-navigation dependency on Find All, GUI freeze, unbounded allocation, or inherited text-integrity/regex blocker remains in local evidence. Authoritative Windows/Linux/macOS hosted results are still required before A21 closure.

A20 does not install a permanent OS daemon: the zero-window service exists only while the launched desktop process remains alive and exits on explicit Quit, logout, shutdown, or process termination. Project/workspace semantics, cloud sync, collaboration, plugins, LSP, syntax highlighting, permanent background services, polished installers, user-authored themes, and expanded keyboard-driven Unicode inspection remain outside the implemented boundary.

The A20 milestone and completed A21 Editor Layout and Visibility records are retained in [Implemented](../03_implemented/README.md). The A21 Cross-Platform milestone/design/plan remain active pending same-commit hosted evidence. See [Scope](SCOPE.md), [Architecture](ARCHITECTURE.md), [Development](DEVELOPMENT.md), [Roadmap](../02_plans/ROADMAP.md), and the [Current Handover](../06_handovers/CURRENT_HANDOVER.md).
