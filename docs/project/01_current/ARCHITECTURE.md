# UNITI Current Architecture

Date: 2026-09-01
Baseline: `v0.001a16` implementation series on `main`

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

## Search, save, recovery, and resources

Third-party `regex==2026.5.9` remains authoritative. Search is cancellable, timeout-aware, revision-bound, compactly stored, and delivered to Qt through queued signals. Save remains streaming, atomic, explicit about encoding/EOL conversion, metadata-aware where supported, and protected against external file replacement.

`RecoveryManager` serializes journal durability independently from disposable background work. The application-wide `ResourceManager` remains the single cache/pressure/worker policy owner and now exposes its constructed cache budget and worker count for state and diagnostics.

## Self-check and diagnostics

`uniti.app.self_check` provides stable human and schema-1 JSON reports. Fast mode validates runtime ownership, dependencies, paths, state/settings, regex, resources, filesystem primitives, and PySide/Qt versions. Deep mode adds temporary encoding/endianness, EOL, mmap/fallback, raw-byte, regex replacement, streaming save/reopen, recovery replay, and offscreen Qt/view checks.

The completed startup snapshot is passed into `UNITIMainWindow` and the diagnostics dialog. Diagnostics consume that snapshot and do not repeat ambient probes.
