# UNITI Current Development Workflow

Date: 2026-09-02
Version: `v0.001a18` / `0.1a18`

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

The host-aware a18 user-experience suite uses the packaged policy table in `src/uniti/resources/performance_policy.toml`:

```bash
# 10 MiB, three isolated repetitions per daily-use scenario
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/performance_suite.py --tier quick

# controlled 100 MiB freeze baseline
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/performance_suite.py \
  --tier routine --mode baseline --output benchmarks/baselines/a18-routine.json

# sparse 1 GiB lazy-open/design probe
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/performance_suite.py \
  --tier design-target --mode baseline --output benchmarks/baselines/a18-design-target.json

# real macOS window-system UX run
.venv/bin/python scripts/performance_suite.py --tier quick --native-gui
```

Use `--scenario NAME` to isolate a workflow, `--compare BASELINE.json` only for a compatible host fingerprint, and `--temp-root PATH` only for an owned location with adequate capacity. `PASS`, `WARN`, `FAIL`, `INVALID`, and `NOT RUN` are distinct; never describe an ineligible or contended controlled run as passing.

Qt-focused coverage:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  tests/test_a17_text_integrity_acceptance.py \
  tests/test_a16_startup_bootstrap_acceptance.py \
  tests/test_a16_usable_alpha_acceptance.py tests/app tests/ui
```

The a18 freeze gate adds `large-file` to deep self-check and retains all a17 byte-integrity coverage. Its selected evidence is stored under `benchmarks/baselines/`: controlled 100 MiB routine, sparse 1 GiB design target, and native Cocoa 10 MiB quick runs. All required scenarios passed on the recorded Apple M3 Max host. Before remote integration, confirm the working tree is clean and ensure the push is normal and fast-forward safe.

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
- Sessions: `AppPaths.session_dir/<session-id>/session.json`
- Recovery: `AppPaths.recovery_dir`; never removed by stale cleanup

Malformed supported state/settings are preserved as timestamped `.invalid` siblings. Future schemas are left untouched and produce exit code 13.

## Versioning and documentation

Display versions use `v0.001aN` in `VERSION` and `uniti.__display_version__`; package versions use `0.1aN` in `pyproject.toml` and `uniti.__version__`. Tags are immutable historical records. `v0.001a18` is implemented without a new tag; `v0.001a19` is the active planned milestone.

Approved outstanding work belongs in the ordered [Roadmap](../02_plans/ROADMAP.md). Verified plans move to [Implemented](../03_implemented/README.md); current documents and the [Current Handover](../06_handovers/CURRENT_HANDOVER.md) are updated in the same closure.
