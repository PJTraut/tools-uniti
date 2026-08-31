# UNITI

**Unicode Intelligent Text Interchange** — a focused cross-platform power text editor built around text correctness, explicit encoding/EOL state, large-file editing, and Python `regex`.

UNITI is a private alpha. The canonical project/display version is stored in `VERSION`; Python packaging uses the PEP 440-normalized equivalent.

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
- third-party `regex` search, named/repeated capture offsets, Find/Replace, Replace All, and streaming regex rewrite;
- cancellable priority workers and memory/cache policy primitives;
- custom PySide6 `QAbstractScrollArea` editor viewport — Qt never owns the document;
- tabs, native File/Edit/Search menus, operational status bar;
- regex-aware Find/Replace fields, compact match index, visible-only match overlays, capture inspector;
- separate **Reinterpret As** and **Convert on Save** controls;
- EOL controls, character inspector, settings paths, and diagnostics.

Explicitly deferred beyond this alpha: project/workspace concepts, plugins, LSP, Git UI, terminal, AI/cloud features, hex editing, full syntax highlighting, and polished platform installers.

## Requirements

- Python 3.12+
- `regex==2026.5.9`
- PySide6 6.8+ for the desktop UI

The core can be installed/tested without Qt. PySide6 is an optional dependency so the text engine remains headless-testable.

## macOS development install

From the repository:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[ui,dev]'
```

Launch UNITI:

```bash
uniti
```

Or open one or more files directly:

```bash
uniti ~/Documents/example.txt ~/Documents/data.csv
```

The module launcher is equivalent:

```bash
python -m uniti
```

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
PYTHONPATH=src pytest
python -m compileall -q src scripts tests
```

Qt runtime tests run automatically when PySide6 is installed; otherwise those tests are explicitly skipped while all core/app contracts continue to run.

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

> **A small editor built on a serious text engine.**
