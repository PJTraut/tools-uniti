# UNITI

**Current project version:** `v0.001a1`
**Python package version:** `0.1a1`

**Unicode Intelligent Text Interchange** — a focused, cross-platform power text editor.

The project is being built from the frozen UNITI Architecture v0.1. The first implementation slice proves the byte-oriented core before any custom Qt viewport work.

## Current build scope

Phase 1A establishes:

- immutable file-backed byte access without whole-file copies;
- encoding metadata and deterministic first-pass detection;
- error-preserving lazy decoding;
- byte/local-character mapping within decoded windows;
- EOL analysis over byte streams;
- streaming byte-preserving copy/save primitives.

The piece table, global sparse offset index, custom `UNITITextView`, and regex UI follow after these contracts are proven.

## Phase 1A status

The initial headless core now proves the low-level file contracts. It does **not** yet contain an editor viewport or editing model.

Implemented in Phase 1A:

- `ByteSource`: mmap-preferred immutable byte access with bounded-read fallback;
- first-pass encoding metadata/detection;
- bounded loss-aware decoding with invalid-byte records;
- local byte↔character boundary mapping for decoded windows;
- encoding-aware streaming LF/CRLF/CR analysis;
- atomic byte-preserving streaming copy/save primitive;
- `scripts/core_probe.py` for headless inspection.

Next implementation slice:

1. sparse document-wide offset checkpoints;
2. compact line index;
3. hybrid piece table + Unicode edit store;
4. document facade that composes those services.

Only after those contracts are stable should the custom PySide6 `UNITITextView` become authoritative UI work.

### Core probe

```bash
PYTHONPATH=src python scripts/core_probe.py path/to/file.txt --window 256
```
