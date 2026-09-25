# UNITI

**Unicode Intelligent Text Interchange** — a focused cross-platform power text editor built around text correctness, explicit encoding/EOL state, large-file editing, and Python `regex`.

UNITI is a private source beta, currently `v0.001b3` (`0.1b3` in Python packaging). All reviewed BF-001–BF-057 feedback changes are committed and integrated on GitHub `main`. B3 Find/Replace Rework & Editor Refinement Beta is active. Native input, affected-host, executable, and release qualification remain open; see the [source-version decision](docs/project/05_decisions/ADR-0008-b3-version-and-qualification.md). The canonical project/display version is stored in `VERSION`; Python packaging uses the PEP 440-normalized equivalent.

## User documentation

- [User Manual](docs/user-manual.md) — getting started, everyday workflows, text formats, recovery, and troubleshooting.
- [User Cheat Sheet](docs/user-cheat-sheet.md) — common actions, regex flags, and quick reminders.
- [Regex Flags Guide](docs/regex-flags.md) — line anchors, examples, scoped flags, and Unicode options.

## Project documentation

- [Project record](docs/project/README.md) — documentation grammar, progression, and ownership.
- [Current status](docs/project/01_current/STATUS.md) — canonical baseline and verification state.
- [Ordered roadmap](docs/project/02_plans/ROADMAP.md) — approved outstanding milestones in implementation sequence.
- [Current handover](docs/project/06_handovers/CURRENT_HANDOVER.md) — concise continuation context and next safe action.
- [Feedback implementation and remaining checks](docs/project/BETA_FEEDBACK.md) — feedback changes, clarifications, and qualification status.

## Beta capabilities

The current source beta includes:

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
- one user-scoped UNITI service that keeps an empty editor window available after the last window-close, exits on explicit Quit, forwards secondary launches, and owns multiple windows, detachable tabs, horizontal/vertical splits, and shared-document views;
- generation-published startup sessions with active-first lazy restore, SHA-256 external-change choices, seven-day saved-document continuity, and bounded per-document Undo/Redo restoration;
- semantic crash-recovery journals that preserve transactions, Undo/Redo, save points, and evidence until an explicit recovery choice;
- third-party `regex` search with engine-reconciled group identities, inline-switch and replacement-reference highlighting, structured diagnostics, and deterministic zero-width results;
- integrated application ResourceManager with cache pressure, active/inactive document priorities, and shared background scheduling;
- custom PySide6 `QAbstractScrollArea` editor viewport — Qt never owns the document;
- tabs, native menus, persisted System/Light/Dark plus named Paper/Slate application themes, editable custom theme profiles, Cut/Copy/Paste, IME composition support, and an operational status bar;
- one service-owned topmost asynchronous regex-aware Find/Replace panel with persisted field state and Undo/Redo, complete theme-aware Lucide controls, cursor-relative Previous/Next independent of Find All, and a right-docked Match Report whose `\\N` capture labels share an aligned content column;
- compact whitespace markers with distinct special-space and zero-width symbols, plus a held marker-type inspection key (`Ctrl+Alt` on Windows/Linux, `Cmd+Option` on macOS), configurable through **Hotkeys → Editor View**; a Word-Alt+X-style `Ctrl+Alt+X` toggle between typed hex and the actual character;
- separate **Reinterpret As** and **Convert on Save** controls;
- source-aware inserted-EOL policy, explicit current-versus-on-save status, all-shared-view EOL refresh after save, invalid-byte viewport annotations, character inspector, settings paths, and diagnostics;
- line numbers at 80% of the document point size with the document baseline and progressive width correction; and
- application-bundled Noto fallback for nine Indic scripts, Simplified/Traditional Chinese, and Korean; bounded Qt-shaped LTR text, grapheme-safe navigation/deletion, UTF-16-aware IME replacement, and virtual preedit painting that keeps the composition caret visible; and
- explicit Python 3.12+ bootstrap into a UNITI-owned source or application-local virtual environment;
- ownership markers, exclusive bootstrap locks, dependency fingerprints, explicit repair, and validation-only normal startup;
- atomic schema-1 setup/settings state, ordered BOOT→READY startup phases, bounded lifecycle logs, and narrow stale-artifact cleanup; and
- explicit macOS, Windows, and Linux path/identity policy; capability-driven `full` / `file_synced` / `unsafe` publication results; pointer repair from complete session generations; native shortcut and fixed-font resolution; and
- fast/deep self-checks for runtime, dependencies, paths, schemas, resources, filesystem primitives, regex intelligence, text fidelity, recovery/session continuity, large-file behavior, offscreen Qt, and bounded cross-platform evidence.

Still unqualified in the current beta: native Chinese/Korean IME composition on Windows, macOS, and Linux, plus affected-host confirmation of the critical shutdown correction. Explicitly deferred: right-to-left/mixed-direction editing, multi-code-point inspection labels, project/workspace concepts, plugins, LSP, Git UI, terminal, AI/cloud features, hex editing, full syntax highlighting, and polished platform installers. See the [LTR text layout and editing contract](docs/ltr-text-layout.md) for behavior and bounds.

## Requirements

- Python 3.12+
- `regex==2026.5.9`
- PySide6 6.8+ for the desktop UI

The core can be installed/tested without Qt. PySide6 is an optional dependency so the text engine remains headless-testable.

## Regex flags and line anchors

Regex mode uses raw engine defaults: `^` matches the start of the document. Add `(?m)` for line-start matching, for example `(?m)^(\d+)\D([^\r\n]+)` for numbered entries. Use `(?i)` for case-insensitive matching, `(?s)` for dots that include newlines, and `(?x)` for readable patterns with spacing and comments. Flags can combine, such as `(?im)`. See the [regex guide](docs/regex-flags.md) for examples, strict document anchors, scoped flags, and line-ending details.

## Bootstrap and launch

From a source checkout, use an existing Python 3.12 or newer to create or adopt the repository `.venv`, install canonical dependencies there, validate it, and launch UNITI:

```bash
python3.12 scripts/bootstrap.py --dev
```

For a normal desktop launch, double-click `uniti.command` on macOS or `uniti.bat` on Windows. The POSIX launcher also supports Linux. Both launchers locate this checkout, preserve the caller's working directory, forward each argument exactly once, run only the same safe bootstrap flow, and return its exit code. From a macOS or Linux terminal:

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

The first launch prints `// prepping UNITI for first use` before creating or adopting `.venv` and installing the UI dependencies, then reports the real setup stages as they begin. Healthy launches stay quiet. Pass `--dev` when the managed environment should also include development dependencies.

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

Bootstrap options include `--local`, `--dev`, `--repair`, `--no-launch`, and `--self-check [--deep] [--json]`. Use `--` before filenames beginning with `-`. Pass `--no-restore` to launch with no previous session restored (any filenames given still open); this does not skip crash/autosave recovery prompts.

### Linux system dependencies

PySide6/Qt needs a handful of system libraries pip cannot install; on a minimal or headless-derived install they may be missing. The exact list this project's own CI installs on Ubuntu (`.github/workflows/a21-cross-platform.yml`) via `apt-get install`:

```
libegl1 libfontconfig1 libgl1 libx11-xcb1 libxcb-cursor0 libxcb-icccm4 \
libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
libxcb-shape0 libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1 \
libxkbcommon-x11-0 xauth xvfb
```

On a non-Debian distro, install the equivalent packages from your package manager. Missing these typically shows as Qt failing to load the `xcb` platform plugin at launch.

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

## A21 cross-platform CI

The read-only `A21 cross-platform` workflow defines four explicit source lanes: macOS 15/Python 3.12, Windows 2025/Python 3.12, Ubuntu 24.04/Python 3.12, and Ubuntu 24.04 on the newest stable Python 3.x. Each lane exercises the public launcher to create a clean UNITI-owned runtime before running the common CI driver.

The driver validates runtime ownership and dependencies, runs the complete suite with exact platform skip accounting, compiles all Python sources, and executes deep self-check plus offscreen and native Qt smoke. CI does not use dependency caches, package builds, deployment credentials, or write permissions. On failure only, parsed and redacted evidence below `ci-results/sanitized` is retained for seven days; raw logs, document paths/content, IPC data, and arbitrary files are excluded.

The latest complete four-lane feedback pass is on `aab3f3c`. The subsequent source candidate `3e20214` passed its complete local gate, but GitHub blocked all jobs for documentation checkpoint `23507ca` before execution because of account payments or spending limits. See [Current status](docs/project/01_current/STATUS.md) for dated run evidence; source integration does not establish hosted qualification.

## Beta runtime checklist

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
