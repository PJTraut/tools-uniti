# UNITI

**Current project version:** `v0.001a2`
**Python package version:** `0.1a2`

**Unicode Intelligent Text Interchange** — a focused, cross-platform power text editor.

UNITI is being built from the frozen Architecture v0.1. The current work is still the Qt-independent text engine; the custom viewport deliberately comes later.

## Current build scope

Phase 1A established the immutable byte and decoding foundation. Phase 1B adds the first editable document model without making open time proportional to file size.

Implemented through `v0.001a2`:

- mmap-preferred immutable `ByteSource` with bounded-read fallback;
- deterministic first-pass UTF/legacy encoding metadata;
- loss-aware bounded decoding with exact invalid-byte spans;
- safe progressive decoded windows across UTF-8/16/32 character boundaries;
- sparse progressive source byte↔character checkpoints;
- compact progressive immutable-source line index backed by `array("Q")`;
- append-only Unicode `EditStore`;
- lazy hybrid source/edit `PieceTable`;
- `Document` facade for lazy open, bounded reads, insert, delete and replace;
- encoding-aware EOL analysis;
- atomic byte-preserving streaming source copy/save primitive.

### Important line-index distinction

`Document.source_line_index` indexes the **immutable source bytes**. It is intentionally not exposed as an edited-document line index: inserted text has no original byte coordinate, so presenting those source offsets as current document line positions would be incorrect. A piece-aware edited-document line layer belongs above the piece table in a later phase.

## Next implementation slice

1. piece-aware current-document line/navigation model;
2. bounded document view extraction suitable for a virtual viewport;
3. edit transactions / undo-redo primitives;
4. then the first PySide6 `UNITITextView` proof.

Regex search and capture visualization follow after the document/view contracts are stable.

### Core probe

```bash
PYTHONPATH=src python scripts/core_probe.py path/to/file.txt --window 256
```
