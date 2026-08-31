# UNITI Phase 1B Document Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add progressive source coordinate mapping, compact line indexing, lazy hybrid editing, and the first `Document` facade without making file open proportional to file size.

**Architecture:** Safe bounded decoded windows are the common primitive. `OffsetMapper` and `LineIndex` build progressive caches over immutable `ByteSource`; `PieceTable` references original bytes plus Unicode edit-store blocks and keeps the final original source tail unmeasured until needed; `Document` composes those services without Qt.

**Tech Stack:** Python 3.12+, pytest, standard-library `array`, `bisect`, dataclasses, existing Phase-1A `ByteSource`/decoder/encoding services.

**Spec:** `docs/superpowers/specs/2026-08-31-uniti-phase1b-document-model-design.md`

## Global Constraints

- Display/project version for the completed slice: `v0.001a2`; Python package version: `0.1a2`.
- `uniti.core` must not import PySide6/Qt.
- `Document.open()` must not decode/index the complete file.
- Original bytes remain addressable through `ByteSource`.
- Mapping/index work is progressive and cached.
- File/document offsets remain 64-bit capable.
- Mixed EOL semantics are preserved.
- Invalid source bytes remain represented as Phase-1A replacement/error semantics.
- Piece operations are half-open Unicode character ranges.
- No deliberate 1 GiB limit.

---

### Task 1: Safe progressive decoded spans

**Files:**
- Modify: `src/uniti/core/decoder.py`
- Modify: `src/uniti/core/__init__.py`
- Modify: `tests/core/test_decoder.py`

**Interfaces:**
- Consumes: `ByteSource`, existing `decode_span()`.
- Produces: `iter_decoded_spans(source, encoding, *, start=0, end=None, chunk_size=65536)`.

- [ ] **Step 1: Add failing UTF-8/UTF-16 split-window tests**

```python
def test_iter_decoded_spans_keeps_utf8_character_intact(tmp_path):
    path = tmp_path / "utf8.txt"
    path.write_bytes("AB€CD".encode("utf-8"))
    with ByteSource.open(path) as source:
        spans = list(iter_decoded_spans(source, "utf-8", chunk_size=4))
    assert "".join(span.text for span in spans) == "AB€CD"
    assert not any(span.errors for span in spans)


def test_iter_decoded_spans_keeps_utf16_surrogate_pair_intact(tmp_path):
    path = tmp_path / "utf16.txt"
    path.write_bytes("A😀B".encode("utf-16-le"))
    with ByteSource.open(path) as source:
        spans = list(iter_decoded_spans(source, "utf-16-le", chunk_size=4))
    assert "".join(span.text for span in spans) == "A😀B"
    assert not any(span.errors for span in spans)
```

- [ ] **Step 2: Run the two tests and verify RED because `iter_decoded_spans` does not exist.**

Run: `PYTHONPATH=src pytest tests/core/test_decoder.py -q`

- [ ] **Step 3: Implement encoding-family safe chunk ends and `iter_decoded_spans`.**

Use bounded source inspection only around candidate ends. UTF-8 may retreat at most four bytes; UTF-16 aligns to two bytes and retreats two bytes when a high surrogate would be separated from its low surrogate; UTF-32 aligns to four bytes. Guarantee forward progress even when `chunk_size` is smaller than one encoded character.

- [ ] **Step 4: Add tests for BOM first span, invalid UTF-8 preservation, bounded start/end validation, and full concatenation across many small spans.**

- [ ] **Step 5: Run decoder tests and full suite; verify GREEN.**

Run: `PYTHONPATH=src pytest tests/core/test_decoder.py -q && PYTHONPATH=src pytest -q`

- [ ] **Step 6: Commit.**

```bash
git add src/uniti/core/decoder.py src/uniti/core/__init__.py tests/core/test_decoder.py
git commit -m "feat: add safe progressive decoded spans"
```

### Task 2: Sparse OffsetMapper

**Files:**
- Create: `src/uniti/core/offsets.py`
- Create: `tests/core/test_offsets.py`
- Modify: `src/uniti/core/__init__.py`

**Interfaces:**
- Consumes: `ByteSource`, `iter_decoded_spans()`.
- Produces: `OffsetCheckpoint`, `OffsetMapper.byte_to_char()`, `.char_to_byte()`, `.total_chars()` and progressive frontier properties.

- [ ] **Step 1: Write failing round-trip and lazy-frontier tests.**

```python
def test_utf8_character_boundaries_round_trip(tmp_path):
    path = tmp_path / "map.txt"
    path.write_bytes("Aé中Z".encode("utf-8"))
    with ByteSource.open(path) as source:
        mapper = OffsetMapper(source, "utf-8", checkpoint_bytes=3)
        assert mapper.char_to_byte(3) == 6
        assert mapper.byte_to_char(6) == 3


def test_small_mapping_does_not_index_entire_large_source(tmp_path):
    path = tmp_path / "large.txt"
    path.write_bytes(("0123456789\n" * 20_000).encode())
    with ByteSource.open(path) as source:
        mapper = OffsetMapper(source, "utf-8", checkpoint_bytes=1024)
        assert mapper.char_to_byte(10) == 10
        assert mapper.indexed_byte_end < source.size
        assert not mapper.complete
```

- [ ] **Step 2: Run and verify RED due to missing `uniti.core.offsets`.**

Run: `PYTHONPATH=src pytest tests/core/test_offsets.py -q`

- [ ] **Step 3: Implement monotonically increasing checkpoints and forward scan.**

Store checkpoints in a list beginning with the first visible byte boundary and char zero. Scan via `iter_decoded_spans`; append checkpoint entries at completed span boundaries. Use `bisect` to choose the nearest preceding checkpoint and decode at most the local checkpoint interval for exact mapping.

- [ ] **Step 4: Add failing tests for UTF-16/32, BOM prefix, byte-inside-character rejection, EOF, invalid UTF-8 replacement mapping, and requests beyond EOF.**

- [ ] **Step 5: Implement the missing edge behavior and verify all offset tests GREEN.**

Run: `PYTHONPATH=src pytest tests/core/test_offsets.py -q`

- [ ] **Step 6: Run the full suite and commit.**

```bash
PYTHONPATH=src pytest -q
git add src/uniti/core/offsets.py src/uniti/core/__init__.py tests/core/test_offsets.py
git commit -m "feat: add sparse source offset mapper"
```

### Task 3: Compact progressive LineIndex

**Files:**
- Create: `src/uniti/core/lines.py`
- Create: `tests/core/test_lines.py`
- Modify: `src/uniti/core/__init__.py`

**Interfaces:**
- Consumes: `ByteSource`, `iter_decoded_spans()`.
- Produces: `LineIndex` with compact line-start offsets and progressive lookup.

- [ ] **Step 1: Write failing mixed-EOL and compact-storage tests.**

```python
def test_line_index_records_mixed_line_starts(tmp_path):
    path = tmp_path / "lines.txt"
    path.write_bytes(b"a\r\nb\nc\rd")
    with ByteSource.open(path) as source:
        index = LineIndex(source, "utf-8", chunk_size=2)
        assert index.line_start(0) == 0
        assert index.line_start(1) == 3
        assert index.line_start(2) == 5
        assert index.line_start(3) == 7


def test_line_offsets_use_compact_unsigned_64_bit_array(tmp_path):
    path = tmp_path / "lines.txt"
    path.write_bytes(b"a\nb\n")
    with ByteSource.open(path) as source:
        index = LineIndex(source, "utf-8")
        index.total_lines()
        assert index._starts.typecode == "Q"
        assert index._starts.itemsize == 8
```

- [ ] **Step 2: Run and verify RED due to missing line index.**

Run: `PYTHONPATH=src pytest tests/core/test_lines.py -q`

- [ ] **Step 3: Implement progressive scanning with pending-CR state and `array('Q')`.**

Initialize line zero at the first visible byte boundary. When a decoded CR is seen, defer committing its next-line start until the next character determines CR versus CRLF. Append the byte boundary after the logical ending.

- [ ] **Step 4: Add failing tests for CRLF across windows, UTF-16/UTF-32, BOM line zero, `line_for_byte`, `ensure_byte`, `ensure_line`, empty files, and lazy frontier.**

- [ ] **Step 5: Implement lookup with `bisect_right` over the compact array; verify GREEN.**

Run: `PYTHONPATH=src pytest tests/core/test_lines.py -q`

- [ ] **Step 6: Run full suite and commit.**

```bash
PYTHONPATH=src pytest -q
git add src/uniti/core/lines.py src/uniti/core/__init__.py tests/core/test_lines.py
git commit -m "feat: add compact progressive line index"
```

### Task 4: EditStore and lazy hybrid PieceTable

**Files:**
- Create: `src/uniti/core/pieces.py`
- Create: `tests/core/test_pieces.py`
- Modify: `src/uniti/core/__init__.py`

**Interfaces:**
- Consumes: `ByteSource`, `OffsetMapper`, `decode_span()`.
- Produces: `EditRef`, `EditStore`, `SourcePiece`, `EditPiece`, `PieceTable` editing/read API.

- [ ] **Step 1: Write failing insert/read tests that assert the unresolved-tail invariant.**

```python
def test_insert_splits_source_tail_without_counting_entire_document(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("abcdefghij", encoding="utf-8")
    with ByteSource.open(path) as source:
        mapper = OffsetMapper(source, "utf-8", checkpoint_bytes=4)
        table = PieceTable(source, "utf-8", mapper, EditStore())
        table.insert(3, "XYZ")
        assert table.read(0, 8) == "abcXYZde"
        assert table.piece_count == 3
        assert table._pieces[-1].char_length is None
```

- [ ] **Step 2: Run and verify RED due to missing pieces module.**

Run: `PYTHONPATH=src pytest tests/core/test_pieces.py -q`

- [ ] **Step 3: Implement append-only `EditStore`, piece dataclasses, split-at-character, insert, and bounded read.**

Keep only the final source tail unresolved. Splitting a source piece maps `source_char_start + local_offset` through `OffsetMapper`. Edit pieces are split by slicing `EditRef` metadata; edit text itself is never copied during a split.

- [ ] **Step 4: Add failing delete/replace tests across source and edit pieces, multibyte source text, invalid source bytes, empty operations, and boundary validation.**

```python
def test_replace_across_source_and_edit_pieces(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("abcdef", encoding="utf-8")
    with ByteSource.open(path) as source:
        mapper = OffsetMapper(source, "utf-8")
        table = PieceTable(source, "utf-8", mapper, EditStore())
        table.insert(3, "XYZ")
        table.replace(2, 7, "!")
        assert table.read(0, table.total_chars()) == "ab!ef"
```

- [ ] **Step 5: Implement delete/replace and normalization that removes empty pieces and merges adjacent compatible edit slices only when trivial.**

- [ ] **Step 6: Verify piece tests and full suite GREEN; commit.**

```bash
PYTHONPATH=src pytest tests/core/test_pieces.py -q
PYTHONPATH=src pytest -q
git add src/uniti/core/pieces.py src/uniti/core/__init__.py tests/core/test_pieces.py
git commit -m "feat: add lazy hybrid piece table"
```

### Task 5: Document facade and v0.001a2 integration

**Files:**
- Create: `src/uniti/core/document.py`
- Create: `tests/core/test_document.py`
- Modify: `src/uniti/core/__init__.py`
- Modify: `src/uniti/__init__.py`
- Modify: `VERSION`
- Modify: `pyproject.toml`
- Modify: `README.md`

**Interfaces:**
- Consumes: all Phase-1A/1B core services.
- Produces: `Document.open`, `.read`, `.insert`, `.delete`, `.replace`, `.total_chars`, `.modified`, `.close`, `.offset_mapper`, and `.source_line_index`.

- [ ] **Step 1: Write failing lazy-open and editing tests.**

```python
def test_document_open_is_lazy_and_editable(tmp_path):
    path = tmp_path / "large.txt"
    path.write_bytes((b"0123456789\n" * 20_000))
    doc = Document.open(path)
    try:
        assert not doc.offset_mapper.complete
        assert not doc.source_line_index.complete
        doc.insert(5, "X")
        assert doc.read(0, 12) == "01234X56789\n"
        assert not doc.offset_mapper.complete
        assert doc.modified
    finally:
        doc.close()
```

- [ ] **Step 2: Run and verify RED due to missing document facade.**

Run: `PYTHONPATH=src pytest tests/core/test_document.py -q`

- [ ] **Step 3: Implement ownership/lifetime, encoding override metadata, editing delegation, and modified state.**

`Document.open()` detects encoding from bounded samples unless overridden, then constructs mapper/source-index/store/table without requesting total characters or total lines. `source_line_index` remains explicitly source-based after edits; no stale edited-document line API is exposed.

- [ ] **Step 4: Add tests for encoding override, context manager, Unicode editing, total character count on demand, and unchanged Phase-1A imports.**

- [ ] **Step 5: Update display/package versions to `v0.001a2` / `0.1a2` and README phase status.**

- [ ] **Step 6: Run complete verification.**

```bash
PYTHONPATH=src pytest -q
PYTHONPATH=src python -m compileall -q src scripts tests
git diff --check
grep -R "PySide6\|PyQt" src/uniti/core && exit 1 || true
```

- [ ] **Step 7: Commit.**

```bash
git add src tests VERSION pyproject.toml README.md
git commit -m "feat: add UNITI document facade for v0.001a2"
```

### Task 6: Large-file and regression acceptance

**Files:**
- Modify: `scripts/core_probe.py`
- Create: `tests/core/test_phase1b_acceptance.py`

**Interfaces:**
- Consumes: `Document`, `OffsetMapper`, `LineIndex`, PieceTable.
- Produces: repeatable acceptance evidence for lazy behavior and 64-bit source offsets.

- [ ] **Step 1: Add an acceptance test using a sparse source above 1 GiB plus an early edit.**

The fixture writes a short UTF-8 prefix, seeks beyond `1 << 30`, writes a short suffix, and verifies `ByteSource.read()` at the high offset remains valid while `Document.open()` and an early edit do not complete the offset or line index. Do not call `total_chars()` on the sparse zero-filled gap because embedded NUL bytes are legitimate text and a complete scan is intentionally outside this smoke test.

- [ ] **Step 2: Extend `scripts/core_probe.py` to report mapper/index completion and a bounded initial document read without forcing full indexing.**

- [ ] **Step 3: Run acceptance plus full suite and compile verification.**

```bash
PYTHONPATH=src pytest tests/core/test_phase1b_acceptance.py -q
PYTHONPATH=src pytest -q
PYTHONPATH=src python -m compileall -q src scripts tests
git diff --check
```

- [ ] **Step 4: Commit.**

```bash
git add scripts/core_probe.py tests/core/test_phase1b_acceptance.py
git commit -m "test: add Phase 1B large-file acceptance probe"
```
