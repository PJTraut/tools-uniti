# UNITI Current Development Workflow

Date: 2026-09-01
Version: `v0.001a16` / `0.1a16`

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
```

`--deep` and `--json` require `--self-check` on the application CLI. Bootstrap `--deep` implies self-check. Use `--` before a filename beginning with `-`.

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
.venv/bin/python -m compileall -q src scripts tests
.venv/bin/python scripts/alpha_smoke.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m uniti --self-check --deep --json
git diff --check
```

Qt-focused coverage:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  tests/test_a16_startup_bootstrap_acceptance.py \
  tests/test_a16_usable_alpha_acceptance.py tests/app tests/ui
```

The final a16 checkpoint at `61d1250` recorded `420 passed, 4 skipped`, clean compilation, a passing alpha smoke, a passing deep offscreen self-check, a clean Qt-free core/regex/resource boundary, and `v0.001a16` through `./uniti.command --version`. A self-closing native Cocoa run also passed equal-height expanding F/R inputs and bottom-anchored controls; the full suite retains window/capture resizing, capture collapse, action grouping, Literal/Regex semantics, and report-hotkey rotation coverage. Before remote integration, confirm the working tree is clean and ensure the push is normal and fast-forward safe.

## Lifecycle files

- Runtime ownership: `<managed-environment>/.uniti-runtime.json`
- Setup/startup state: `AppPaths.setup_state_file`
- Settings: `AppPaths.settings_file`
- Startup log: `AppPaths.startup_log_file`, rotated at 5 MiB with ten rotations
- Sessions: `AppPaths.session_dir/<session-id>/session.json`
- Recovery: `AppPaths.recovery_dir`; never removed by stale cleanup

Malformed supported state/settings are preserved as timestamped `.invalid` siblings. Future schemas are left untouched and produce exit code 13.

## Versioning and documentation

Display versions use `v0.001aN` in `VERSION` and `uniti.__display_version__`; package versions use `0.1aN` in `pyproject.toml` and `uniti.__version__`. Tags are immutable historical records. `v0.001a16` is implemented without a new tag; `v0.001a17` is active planning state, while runtime/package metadata remains at a16 until a17 implementation deliberately advances it.

Approved outstanding work belongs in the ordered [Roadmap](../02_plans/ROADMAP.md). Verified plans move to [Implemented](../03_implemented/README.md); current documents and the [Current Handover](../06_handovers/CURRENT_HANDOVER.md) are updated in the same closure.
