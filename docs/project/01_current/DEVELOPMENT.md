# UNITI Current Development Workflow

Date: 2026-09-01

## Requirements

- Python 3.12 or newer
- `regex==2026.5.9`
- PySide6 6.8 or newer for the desktop UI
- pytest 9 or newer for development tests

The repository currently relies on a manually created source-development `.venv`. The automated host-Python discovery, UNITI-owned environment repair, startup-state persistence, and self-check lifecycle described by `v0.001a16` are planned, not yet implemented.

## Source environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[ui,dev]'
```

Dependencies belong in this repository-owned virtual environment, never in the host/system Python package environment.

## Launch

```bash
uniti
uniti ~/Documents/example.txt ~/Documents/data.csv
python -m uniti
```

## Verification

Full suite and Python compilation:

```bash
PYTHONPATH=src pytest
python -m compileall -q src scripts tests
```

Qt offscreen desktop coverage:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src pytest -q tests/test_a15_desktop_alpha_acceptance.py tests/ui
```

Headless functional smoke workflow:

```bash
PYTHONPATH=src python scripts/alpha_smoke.py
```

Retain its generated fixtures when investigating a failure:

```bash
PYTHONPATH=src python scripts/alpha_smoke.py --workdir /tmp/uniti-smoke
```

Before a completion claim, run tests proportionate to the change, `git diff --check`, and import-boundary checks confirming that `src/uniti/core` and `src/uniti/regex` do not import PySide6.

## Versioning

- Display versions use `v0.001aN` in `VERSION` and `uniti.__display_version__`.
- PEP 440 package versions use `0.1aN` in `pyproject.toml` and `uniti.__version__`.
- Tags are immutable milestone records.
- Version metadata advances only with the milestone implementation and verification gate.

Current metadata remains `v0.001a15` / `0.1a15`; the next planned value is `v0.001a16` / `0.1a16`.

## Documentation lifecycle

Use the ordered [Roadmap](../02_plans/ROADMAP.md) and active milestone plan for future work. Once a milestone is verified, move its plan to [Implemented](../03_implemented/README.md), update affected current-state documents, and refresh the [Current Handover](../06_handovers/CURRENT_HANDOVER.md).
