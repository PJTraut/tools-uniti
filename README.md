# UNITI

**Unicode Intelligent Text Interchange** — a focused cross-platform power text editor built around text correctness, explicit encoding/EOL state, large-file editing, and Python `regex`.

UNITI is a private alpha. The canonical project/display version is stored in `VERSION`; Python packaging uses the PEP 440-normalized equivalent.

## Project documentation

- [Project record](docs/project/README.md) — documentation grammar, progression, and ownership.
- [Current status](docs/project/01_current/STATUS.md) — canonical baseline and verification state.
- [Ordered roadmap](docs/project/02_plans/ROADMAP.md) — approved outstanding milestones in implementation sequence.
- [Current handover](docs/project/06_handovers/CURRENT_HANDOVER.md) — concise continuation context and next safe action.

## Alpha capabilities

The current development alpha includes:

- mmap-preferred immutable byte source with bounded fallback reads;
- lazy UTF-8 / UTF-16 LE/BE / UTF-32 LE/BE handling;
- Windows-1252 fallback and explicit reinterpretation;
- invalid-byte preservation for untouched source regions;
- LF, CRLF, CR, and mixed-EOL analysis;
- explicit encoding conversion and EOL conversion on save;
- sparse byte↔character mapping and progressive line indexes;
- hybrid source/edit piece table with bounded huge-line reads;
- insert/delete/replace, selections, undo/redo, and transaction history;
- streaming atomic Save / Save As;
- external-file change protection before overwrite;
- incremental crash-recovery journals and startup recovery discovery;
- third-party `regex` search with engine-reconciled group identities, inline-switch and replacement-reference highlighting, structured diagnostics, and deterministic zero-width results;
- integrated application ResourceManager with cache pressure, active/inactive document priorities, and shared background scheduling;
- custom PySide6 `QAbstractScrollArea` editor viewport — Qt never owns the document;
- tabs, native File/Edit/Search menus, Cut/Copy/Paste, IME composition support, and operational status bar;
- asynchronous regex-aware Find/Replace fields, compact match index, visible-only normal/zero-width overlays, and bounded model-backed current/next capture reports;
- separate **Reinterpret As** and **Convert on Save** controls;
- source-aware inserted-EOL policy, EOL controls, invalid-byte viewport annotations, character inspector, settings paths, and diagnostics.
- explicit Python 3.12+ bootstrap into a UNITI-owned source or application-local virtual environment;
- ownership markers, exclusive bootstrap locks, dependency fingerprints, explicit repair, and validation-only normal startup;
- atomic schema-1 setup/settings state, ordered BOOT→READY startup phases, bounded lifecycle logs, and narrow stale-artifact cleanup; and
- fast/deep self-checks for runtime, dependencies, paths, schemas, resources, filesystem primitives, regex intelligence, text fidelity, recovery, large-file behavior, and offscreen Qt.

Explicitly deferred beyond this alpha: editor whitespace visualization and expanded keyboard-driven Unicode inspection, project/workspace concepts, plugins, LSP, Git UI, terminal, AI/cloud features, hex editing, full syntax highlighting, and polished platform installers.

## Requirements

- Python 3.12+
- `regex==2026.5.9`
- PySide6 6.8+ for the desktop UI

The core can be installed/tested without Qt. PySide6 is an optional dependency so the text engine remains headless-testable.

## Bootstrap and launch

From a source checkout, use an existing Python 3.12 or newer to create or adopt the repository `.venv`, install canonical dependencies there, validate it, and launch UNITI:

```bash
python3.12 scripts/bootstrap.py --dev
```

For a normal desktop launch, double-click `uniti.command` on macOS or `uniti.bat` on Windows. The launchers locate this checkout, run the same safe bootstrap flow, and then start UNITI. From a macOS terminal:

```bash
./uniti.command ~/Documents/example.txt
```

From Windows Command Prompt (`cmd.exe`):

```bat
uniti.bat "%USERPROFILE%\Documents\example.txt"
```

From PowerShell:

```powershell
.\uniti.bat "$HOME\Documents\example.txt"
```

The first launch creates `.venv` and installs the UI dependencies. Pass `--dev` when the managed environment should also include development dependencies.

Bootstrap never installs into the host Python. Source mode owns exactly `<checkout>/.venv`; explicit application-local mode uses the OS application-data runtime:

```bash
python3.12 scripts/bootstrap.py --local
```

Repair is explicit. Ordinary `uniti` startup validates but never runs pip or performs dependency/network mutation:

```bash
python3.12 scripts/bootstrap.py --repair --dev
```

Inspect the managed launch command without starting the application:

```bash
python3.12 scripts/bootstrap.py --no-launch
```

Once bootstrapped:

```bash
.venv/bin/uniti
.venv/bin/uniti ~/Documents/example.txt ~/Documents/data.csv
.venv/bin/python -m uniti
```

Bootstrap options include `--local`, `--dev`, `--repair`, `--no-launch`, and `--self-check [--deep] [--json]`. Use `--` before filenames beginning with `-`.

## Runtime self-check

Fast validation:

```bash
.venv/bin/uniti --self-check
.venv/bin/uniti --self-check --json
```

The deep check adds encoding/endianness, EOL, mmap/fallback, invalid-byte, regex intelligence/replacement, streaming save/reopen, recovery replay, large-file, and offscreen Qt/view fixtures:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/uniti --self-check --deep --json
```

Lifecycle exit codes are `0` success, `1` internal error, `2` usage, `10` runtime Python, `11` environment ownership, `12` dependencies, `13` paths/state/schema, `14` functional self-check, and `15` Qt/platform.

## Headless alpha smoke test

This does not require PySide6. It creates temporary fixtures and exercises UTF/legacy encoding, CR/LF/CRLF conversion, editing, Python `regex` replacement, streaming save/reopen, crash recovery, and external-change protection:

```bash
PYTHONPATH=src python scripts/alpha_smoke.py
```

To retain the generated files:

```bash
PYTHONPATH=src python scripts/alpha_smoke.py --workdir /tmp/uniti-smoke
```

A successful run returns JSON with `"ok": true`.

## Test suite

```bash
.venv/bin/python -m pytest
.venv/bin/python -m compileall -q src scripts benchmarks tests
```

Qt runtime tests run automatically when PySide6 is installed; otherwise those tests are explicitly skipped while all core/app contracts continue to run.

## Alpha runtime checklist

After installing `.[ui,dev]` on the Mac, run:

```bash
.venv/bin/python -m pytest -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_a16_startup_bootstrap_acceptance.py tests/ui
QT_QPA_PLATFORM=offscreen .venv/bin/python -m uniti --self-check --deep --json
.venv/bin/uniti
```

Manual checks: open/save UTF-8, Windows-1252, UTF-16 LE/BE and UTF-32 LE/BE files; verify LF/CRLF/CR insertion and conversion; Cut/Copy/Paste; CJK IME composition; regex group colors, paired references, diagnostics, zero-width markers, navigation, replacement, and capture-report readability; invalid-byte boxes/inspector; recovery after an intentional unclean exit; and horizontal navigation on a very long line.

## Architecture invariants

1. Qt never becomes the document store.
2. Opening a file never requires decoding the whole file.
3. File offsets are 64-bit.
4. Original source bytes remain addressable while their backing file is safe.
5. Encoding conversion is explicit.
6. Reinterpretation and conversion are separate operations.
7. Mixed EOL state is represented, not silently normalized.
8. The third-party Python `regex` package is authoritative.
9. Long document work stays off the UI thread.
10. Search-result count does not dictate GUI object count.
11. Save is streaming, atomic, and external-change conscious.
12. `uniti.core` remains independent of PySide6.
13. Bootstrap mutates only an ownership-validated UNITI virtual environment.
14. Normal startup never invokes pip or repairs dependencies.
15. Startup phase order, state persistence, logging, cleanup, and failure codes are centralized.

> **A small editor built on a serious text engine.**
