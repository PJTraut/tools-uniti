# UNITI Current Development Workflow

Date: 2026-09-05
Version: `v0.001a20` / `0.1a20`

## Requirements and policy

- Python 3.12 or newer must already be installed.
- `regex==2026.5.9` is the authoritative regex engine.
- PySide6 6.8 or newer is required for the desktop UI.
- pytest 9 or newer is selected by the development extra.
- Bootstrap may mutate only a verified UNITI-owned virtual environment.
- Ordinary UNITI startup never invokes pip, repairs dependencies, or installs into the host Python.

## Source bootstrap

From the repository root:

```bash
python3.12 scripts/bootstrap.py --dev
```

This creates or safely adopts exactly `.venv`, installs `.[ui,dev]` through `.venv/bin/python -m pip`, validates imports and `pip check`, writes ownership/setup state, and launches UNITI. Explicit alternatives:

```bash
python3.12 scripts/bootstrap.py --no-launch --dev
python3.12 scripts/bootstrap.py --repair --dev
python3.12 scripts/bootstrap.py --self-check --deep --json
```

Root launchers provide the normal double-click path on macOS and Windows while retaining the same bootstrap ownership and validation rules:

```bash
./uniti.command
./uniti.command file.txt
```

Windows Command Prompt (`cmd.exe`):

```bat
uniti.bat
uniti.bat file.txt
```

PowerShell:

```powershell
.\uniti.bat
.\uniti.bat file.txt
```

The launchers preserve the caller's working directory, forward all arguments, and return the bootstrap/application exit code. Their default install is `.[ui]`; pass `--dev` to include the development dependency group.

Application-local mode is explicit:

```bash
python3.12 scripts/bootstrap.py --local
```

An existing unmarked application-local target is refused. UNITI never deletes or clears a managed environment automatically.

## Launch and CLI

```bash
.venv/bin/uniti
.venv/bin/uniti file.txt other.csv
.venv/bin/python -m uniti
.venv/bin/uniti --version
.venv/bin/python -m uniti --smoke
```

`--deep` and `--json` require `--self-check` on the application CLI. Bootstrap `--deep` implies self-check. `--smoke` runs the core workflow plus a real self-closing main window on the selected Qt platform. Use `--` before a filename beginning with `-`.

## Self-check

```bash
.venv/bin/uniti --self-check
.venv/bin/uniti --self-check --json
QT_QPA_PLATFORM=offscreen .venv/bin/uniti --self-check --deep --json
```

Exit codes:

| Code | Meaning |
|---:|---|
| `0` | success |
| `1` | unexpected internal failure |
| `2` | CLI usage error |
| `10` | unsupported runtime Python |
| `11` | unsafe or mismatched runtime ownership |
| `12` | dependency failure |
| `13` | path, persisted state, or schema failure |
| `14` | functional self-check failure |
| `15` | GUI/Qt/platform failure |

## Verification

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src scripts benchmarks tests
.venv/bin/python -m uniti --self-check --deep
QT_QPA_PLATFORM=offscreen .venv/bin/python -m uniti --smoke
.venv/bin/python -m uniti --smoke
git diff --check
```

The host-aware A20 user-experience suite uses the packaged policy table in `src/uniti/resources/performance_policy.toml`. Quick and routine tiers include `session_restore`; the design-target tier intentionally remains focused on sparse large-file behavior:

```bash
# 10 MiB, three isolated repetitions per daily-use scenario
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/performance_suite.py --tier quick

# inherited controlled 100 MiB a19 baseline
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/performance_suite.py \
  --tier routine --mode baseline \
  --output benchmarks/baselines/v0.001a19-mac15-8-routine.json

# sparse 1 GiB lazy-open/design probe
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/performance_suite.py \
  --tier design-target --mode baseline \
  --output benchmarks/baselines/v0.001a18-mac15-8-design-target.json

# real macOS window-system A20 UX run (no baseline is selected by default)
.venv/bin/python scripts/performance_suite.py --tier quick --native-gui
```

Use `--scenario NAME` to isolate a workflow, `--compare BASELINE.json` only for a compatible host fingerprint, and `--temp-root PATH` only for an owned location with adequate capacity. `PASS`, `WARN`, `FAIL`, `INVALID`, and `NOT RUN` are distinct; never describe an ineligible or contended controlled run as passing.

Qt-focused coverage:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  tests/test_a20_recovery_session_acceptance.py \
  tests/test_a21_cross_platform_acceptance.py \
  tests/test_a17_text_integrity_acceptance.py \
  tests/test_a16_startup_bootstrap_acceptance.py \
  tests/test_a16_usable_alpha_acceptance.py tests/app tests/ui
```

The current local gate reports 1,161 passed and six host-inapplicable skips, plus a passing 20-check deep self-check and combined offscreen smoke. The A20 freeze gate adds `recovery-session` to deep self-check and a thirteenth quick/routine `session_restore` scenario while retaining the a17 byte-integrity, a18 large-file, and a19 regex-intelligence gates. A20 freeze runs are evidence in the current status/handover but were not selected as committed JSON baselines; the existing a18/a19 baselines remain inherited evidence. Before remote integration, confirm the working tree is clean and ensure any separately authorized push is normal and fast-forward safe.

## Editor layout and display change discipline

- Keep one process-lifetime `UNITIService`, one global Find/Replace surface, and one authoritative `Document` per native source identity across every window, pane, and placement.
- Move a view transactionally during Dock/Undock. Preserve its return anchor and independent cursor/presentation state; never transfer or duplicate document/history authority.
- Splits create independent views. Assign Document selects or adds a view without closing or replacing another pane tab.
- Keep Find/Replace attached only as a full-width bottom dock following the active window, or detached as the same single modeless topmost surface.
- Paint whitespace only from committed visible slices using existing row layout geometry. Keep the 4,096-operation frame budget and reserve visible overflow aggregation.
- Keep logical terminator classification exact and bounded to at most two direct document characters; do not infer CRLF from normalized display text.
- Preserve appearance and contrast as independent global settings and update complete application/editor theme tokens together.
- Never create, reserve, or fill real LOWDISK state. Inject capacity and write/fsync failures.

## Recovery/session change discipline

- Keep one `UNITIService` as the sole settings, session, recovery, document-registry, window-manager, and global Find/Replace authority. A window close is not service shutdown.
- Capture immutable GUI state quickly, then serialize, compress, hash, write, sync, discover, replay, and clean through worker tasks. Tests record thread identities for the session-restore path.
- Publish immutable packs before their manifest and the manifest before the current pointer. Retain the previous complete generation until its successor is durably current.
- Persist editor history to the first of 50 transactions or 32 MiB decoded, Find and Replace to at most 50 states each within 4 MiB decoded, and the physical saved-history union within 256 MiB.
- Preserve current state when pruning, keep compatible closed history for seven days subject to the aggregate cap, and never treat recovery journals as disposable history.
- Use SHA-256 over exact saved bytes as history authority. Metadata may avoid unnecessary hashing but may never override a detected content mismatch.
- Keep the 64 MiB recovery compaction threshold and 512 MiB free-space reserve centralized. Exercise low-space behavior only with injected capacity/write/fsync failures; never fill or reserve the real filesystem for a test.
- Quit must resolve Save/Discard/Cancel once per unique modified document. A second crash or failed publication must leave the last complete session/recovery evidence discoverable.

## Regex-intelligence change discipline

- Keep `regex==2026.5.9` as the sole semantic authority; lexer output may describe spans but must be reconciled before claiming group identity.
- Limit interactive pattern/replacement analysis to 65,536 code points and keep engine compilation off the GUI thread after the 150 ms quiet interval.
- Publish analysis and capture results only after every expression, document, revision, result-store, and match-index seal remains current.
- Resolve capture reports from immutable snapshots within the 65,536-character read, five-preview, 80-character-preview, and 1 MiB payload bounds.
- Store and navigate zero-width matches by result index; apply each result exactly once and retain atomic one-step Replace All undo.
- Close snapshots, match stores, replacement plans, documents, task records, and superseded pending requests in tests and measured scenarios.

## Large-file change discipline

- Long index, EOL, navigation, search, replacement-plan, and save work consumes a snapshot and publishes only for its captured revision/identity.
- Use `TaskCoordinator` for admission, priorities, progress, cancellation, and background-pause semantics; do not create competing worker ownership.
- Use `ReadIntent.STREAMING` for sequential scans that must not populate reusable decoded-span cache.
- Account disposable caches by bytes and explicit priority; never put authoritative text, Undo/Redo, recovery, or unsaved state in cache.
- Keep viewport and wrap details bounded. Do not restore one Python or Qt object per line, visual row, or match.
- Add a deterministic scenario and integrity fact when changing a measured daily-use path. Threshold values change only in the packaged policy table after real-use evidence.

## Text-integrity change discipline

- Add or select formats only through `core.text_format.EncodingProfile` and `OutputFormat`; do not recreate codec/BOM/EOL grammar in a menu or dialog.
- Keep encoding assessment serious and independent from line-ending reporting.
- Test all save-path changes against exact bytes, logical reopen text, document state, destination identity, and temporary cleanup.
- Use `Document.save()` only for the current resolved path and `Document.export_copy()` for another path.
- Preserve malformed bytes only under same-profile `PRESERVE`; never introduce replacement-byte conversion silently.
- Keep Qt and tab coordination in `src/uniti/ui`; core/regex/resource modules remain Qt-free.

## Lifecycle files

- Runtime ownership: `<managed-environment>/.uniti-runtime.json`
- Setup/startup state: `AppPaths.setup_state_file`
- Settings: `AppPaths.settings_file`
- Startup log: `AppPaths.startup_log_file`, rotated at 5 MiB with ten rotations
- Cache process-session records: `AppPaths.session_dir/<session-id>/session.json`
- Durable generation sessions/history packs: `AppPaths.durable_session_dir`
- Recovery journals: `AppPaths.recovery_dir`; never removed by cache-session stale cleanup
- Single-instance lease: `AppPaths.instance_lock_file`; local endpoint name derives from the resolved application-data identity

Malformed supported state/settings are preserved as timestamped `.invalid` siblings. Future schemas are left untouched and produce exit code 13.

## Versioning and documentation

Display versions use `v0.001aN` in `VERSION` and `uniti.__display_version__`; package versions use `0.1aN` in `pyproject.toml` and `uniti.__version__`. Tags are immutable historical records. `v0.001a20` is implemented without a new tag; `v0.001a21` is active, with Editor Layout and Visibility implemented and Cross-Platform implementation resuming at Task 4.

Approved outstanding work belongs in the ordered [Roadmap](../02_plans/ROADMAP.md). Verified plans move to [Implemented](../03_implemented/README.md); current documents and the [Current Handover](../06_handovers/CURRENT_HANDOVER.md) are updated in the same closure.
