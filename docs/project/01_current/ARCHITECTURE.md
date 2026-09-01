# UNITI Current Architecture

Date: 2026-09-01
Baseline: automatically verified a16 implementation through `8151325` on `main`

## Lifecycle boundary

UNITI now has two deliberately separate execution paths:

```text
explicit bootstrap
host Python 3.12+
    -> scripts/bootstrap.py compatibility shim
    -> uniti.bootstrap discovery / ownership / dependencies
    -> source .venv or application-local venv
    -> managed Python -m uniti

ordinary application startup
application CLI parsed before Qt
    -> StartupCoordinator phases 01-12
    -> validated owned runtime and installed dependencies
    -> paths / schemas / settings / resources / cleanup / recovery
    -> lazy Qt capabilities and UNITIMainWindow
```

Only explicit bootstrap may create or repair a runtime and invoke `<managed-python> -m pip`. Ordinary `uniti` startup does not invoke pip, install packages, access the network, or mutate dependencies.

## Managed runtime ownership

`uniti.bootstrap.environment.EnvironmentManager` is the sole owner of virtual-environment mutation. Source mode uses exactly `<source-root>/.venv`; local mode uses `AppPaths.local_runtime_dir`. A schema-1 `.uniti-runtime.json` marker records owner, deterministic environment ID, mode, resolved path, source provenance, host/runtime identities, timestamps, dependency fingerprint, and health.

A missing target receives an unhealthy marker before `venv.EnvBuilder(clear=False)` runs. Partial environments therefore remain explicit and repairable. Existing source `.venv` directories may be adopted only after interpreter/venv validation. Existing unmarked local targets and every owner/mode/ID/path mismatch are refused. Exclusive lock files reject live concurrent bootstrap and preserve stale lock evidence.

`uniti.bootstrap.dependencies` reads canonical declarations from `pyproject.toml`, installs source mode editable and local mode non-editable, validates UNITI/`regex`/PySide6 metadata and imports, runs managed `pip check`, and records a deterministic fingerprint. A healthy matching runtime uses a validation-only fast path unless `--repair` is supplied.

## Startup state machine

`uniti.app.startup.StartupCoordinator` owns this strict order:

```text
BOOT
  -> 01 RUNTIME_IDENTITY
  -> 02 ENVIRONMENT_VALIDATION
  -> 03 DEPENDENCY_VALIDATION
  -> 04 APPLICATION_PATHS
  -> 05 SCHEMA_MIGRATIONS
  -> 06 SETTINGS_LOAD
  -> 07 RESOURCE_CALIBRATION
  -> 08 STALE_STATE_CLEANUP
  -> 09 RECOVERY_DISCOVERY
  -> 10 GUI_CAPABILITIES
  -> 11 SESSION_RESTORE
  -> 12 READY
```

The coordinator owns ordering, phase timing, atomic state updates, safe failure translation, bounded JSONL logging, and reverse-order cleanup. Application callbacks construct services and import PySide6 only in GUI phases. Exit codes separate usage, runtime, ownership, dependencies, state/schema, functional, and Qt/platform failures.

`setup-state.json` and schema-1 settings use shared durable JSON replacement with file and parent syncing where supported. Malformed files are copied to timestamped `.invalid` siblings before replacement; future schemas fail without modification. Startup logs rotate at 5 MiB and retain ten rotations.

## Paths, capabilities, and cleanup

`AppPaths` distinguishes config, data, state, and cache roots and derives the local runtime, setup state, logs, temp artifacts, sessions, recovery journals, and settings paths. Bounded probes report runtime, memory, CPU, disk, file handles, ownership, write/fsync/atomic replace, mmap, xattrs, Qt, fonts, clipboard, input method, screens, and DPI.

Cleanup has authority only inside UNITI temp, session, and rotated-log roots. It recognizes known prefixes or schema records, preserves live/active sessions, applies seven-day temp/session and thirty-day log thresholds, inspects at most 200 entries, and removes at most 100. Recovery journals and search spill files are outside this authority.

## Document ownership model

The lifecycle wraps rather than replaces the established editor engine:

```text
QApplication / UNITIMainWindow
    -> UNITITextView (custom QAbstractScrollArea)
    -> EditorState
    -> Document
    -> PieceTable + DocumentLineIndex + History
    -> EditStore + immutable SourcePiece ranges
    -> OffsetMapper + decoder
    -> ByteSource (mmap preferred, bounded fallback)
```

`src/uniti/core` and `src/uniti/regex` remain Qt-free. Qt owns presentation and input only; it never becomes the document store.

`EditHistory` retains at most 50 immutable document transactions. When the oldest transaction is evicted, its state is folded into the retained baseline so modified/save-point semantics remain correct. Typing, backspace, and delete may coalesce while contiguous; cursor movement, selection changes, save, Undo/Redo, and explicit operations break coalescing. `Document.replace_many` applies all non-overlapping original-coordinate replacements as one transaction.

## Editor presentation and command flow

`UNITITextView` continues to paint only visible document content through the custom virtual viewport. It selects a concrete fixed-pitch font with Western/Latin and Cyrillic coverage, applies clamped 50–300% font scaling, and handles primary-modifier wheel zoom without transferring text ownership to Qt.

Soft wrap is display-only and defaults off. `ui.wrap_index.VisualRowIndex` incrementally maps logical lines to visual rows at the current viewport width; scrolling advances that index rather than constructing a whole-document Qt layout. Wrap therefore does not insert EOLs or change document coordinates.

Input flows through `EditorState` for insertion/deletion, clipboard operations, selection, Unicode-category word movement, page movement, document start/end, and line navigation. Reload/Revert asks before discarding modifications, reopens through `Document.open`, and installs a fresh history. The status bar receives cursor, encoding/EOL, size, editor zoom, and `Wrap`/`No Wrap` state from the active view.

## Floating Find/Replace

`FindReplaceWindow` is a modeless Qt tool window over the active `UNITITextView`. The document remains editable while it is visible. Its Find and Replace inputs use explicit immutable snapshot histories capped independently at 50 steps; focus routing sends Undo/Redo and clipboard commands to the active field before falling back to the document.

Literal mode escapes the query and alone supplies Case Sensitive and Whole Word options. Regex mode sends raw syntax and inline switches to the authoritative third-party engine. Search remains cancellable and revision-bound. The report pane can be Hidden, Bottom, or Right and renders capture groups `1..N` only, with delimiters between adjacent matches.

Single Replace and Replace All return through the authoritative `Document`. Replace All collects the revision-bound replacement set off the GUI thread, rejects stale results, and submits the entire set to `replace_many` as one Undo operation. The UI does not use the core streaming-rewrite service for Replace All because a disk rewrite would bypass the a16 history contract.

Editor zoom/wrap and Find/Replace zoom/geometry/report placement persist independently through `SettingsStore`.

## Command registry

`app.commands.CommandRegistry` is the Qt-free authority for command definitions, defaults, current shortcuts, categories, and `WINDOW`/`EDITOR`/`FIND_REPLACE` collision scopes. `UNITIMainWindow` creates shared `QAction` handlers from that registry. Editor and modeless-window dispatch use focus-aware action/shortcut forwarding, including interception of native text-control shortcuts so Find/Replace fields keep ownership.

`HotkeysPopup` is a modeless editor over the same registry. It exposes the six approved horizontal categories and Default/Current bindings, and performs assignment, clearing, collision rejection, selected/category/all resets, and portable-text persistence. Menus and customized shortcuts therefore do not maintain competing handler paths.

## Search, save, recovery, and resources

Third-party `regex==2026.5.9` remains authoritative. Search is cancellable, timeout-aware, revision-bound, compactly stored, and delivered to Qt through queued signals. Core streaming replacement remains available for future bounded large-file work but is not a UI Replace All path in a16. Save remains streaming, atomic, explicit about encoding/EOL conversion, metadata-aware where supported, and protected against external file replacement.

`RecoveryManager` serializes journal durability independently from disposable background work. The application-wide `ResourceManager` remains the single cache/pressure/worker policy owner and now exposes its constructed cache budget and worker count for state and diagnostics.

## Self-check and diagnostics

`uniti.app.self_check` provides stable human and schema-1 JSON reports. Fast mode validates runtime ownership, dependencies, paths, state/settings, regex, resources, filesystem primitives, and PySide/Qt versions. Deep mode adds temporary encoding/endianness, EOL, mmap/fallback, raw-byte, regex replacement, streaming save/reopen, recovery replay, and offscreen Qt/view checks.

The completed startup snapshot is passed into `UNITIMainWindow` and the diagnostics dialog. Diagnostics consume that snapshot and do not repeat ambient probes.

## Active-plan boundary

The planned a16 functionality is implemented and automatically verified, so it is part of current architecture. The milestone remains active only because interactive macOS smoke, sustained real editing/search dogfood, and the final no-known-integrity-defect review require human evidence. Those gates are recorded in the [active a16 plan](../02_plans/v0.001a16-usable-test-alpha.md) and [ADR-0004](../05_decisions/ADR-0004-a16-usability-boundary.md). Queued a17+ behavior is not current architecture.
