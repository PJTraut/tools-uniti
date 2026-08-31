# UNITI Phase 1A Core Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first testable UNITI core that opens large files without whole-file copies, detects basic encodings, decodes bounded windows without losing invalid bytes, analyzes EOLs across chunks, and performs atomic streaming byte-preserving saves.

**Architecture:** Keep all implemented code under `uniti.core` with no Qt imports. `ByteSource` owns immutable byte access; encoding and decoder services consume bounded samples/windows; EOL analysis and streaming save operate through `ByteSource.iter_chunks()` so file size does not dictate Python heap size.

**Tech Stack:** Python 3.12+, pytest, standard library `mmap`/`codecs`/`tempfile`/`os`, third-party `regex` declared as a mandatory project dependency for later phases; PySide6 declared as the UI dependency but not imported by `uniti.core`.

**Spec:** `docs/superpowers/specs/2026-08-31-uniti-phase1a-core-foundation-design.md`

## Global Constraints

- Product name: UNITI — Unicode Intelligent Text Interchange.
- Core document code remains independent of Qt.
- Opening a file never requires decoding the whole file.
- Original bytes remain addressable.
- File offsets are 64-bit capable.
- Mixed EOL is represented, not silently normalized.
- Save is streaming and crash-conscious.
- No feature may introduce a deliberate 1 GB ceiling.
- Python `regex` is the authoritative future regex engine and remains a declared dependency.

---

### Task 1: Package scaffold and import boundary

**Files:**
- Create: `pyproject.toml`
- Create: `src/uniti/__init__.py`
- Create: `src/uniti/core/__init__.py`
- Create: `tests/test_package.py`

**Interfaces:**
- Consumes: none.
- Produces: importable `uniti` package with `__version__`, and `uniti.core` that imports without PySide6.

- [ ] **Step 1: Write the failing package test**

```python
import importlib.util


def test_core_import_does_not_require_pyside6():
    import uniti.core

    assert uniti.core is not None
    assert importlib.util.find_spec("uniti") is not None
```

- [ ] **Step 2: Run test and verify RED**

Run: `PYTHONPATH=src pytest tests/test_package.py -q`

Expected: collection/import failure because `uniti` does not exist.

- [ ] **Step 3: Create minimal package and project metadata**

`pyproject.toml` must use setuptools with `src` layout, require Python `>=3.12`, declare `regex==2026.5.9`, and declare `PySide6>=6.8` as an optional `ui` extra. `src/uniti/__init__.py` exposes `__version__ = "0.1.0a0"`; `src/uniti/core/__init__.py` contains no Qt imports.

- [ ] **Step 4: Run package test and verify GREEN**

Run: `PYTHONPATH=src pytest tests/test_package.py -q`

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src tests/test_package.py
git commit -m "build: establish UNITI core package"
```

### Task 2: Immutable large-file ByteSource

**Files:**
- Create: `src/uniti/core/byte_source.py`
- Create: `tests/core/test_byte_source.py`
- Modify: `src/uniti/core/__init__.py`

**Interfaces:**
- Consumes: standard library filesystem and mmap APIs.
- Produces: `ByteSource.open(path, prefer_mmap=True)`, `.path`, `.size`, `.read(start, length)`, `.iter_chunks(start=0, end=None, chunk_size=1<<20)`, `.close()`, and context-manager support.

- [ ] **Step 1: Write failing tests for bounded reads, chunks, zero-byte files, and argument validation**

```python
from pathlib import Path
import pytest
from uniti.core.byte_source import ByteSource


def test_byte_source_reads_requested_range(tmp_path: Path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"0123456789")
    with ByteSource.open(path) as source:
        assert source.size == 10
        assert source.read(3, 4) == b"3456"


def test_byte_source_iterates_bounded_chunks(tmp_path: Path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"abcdefghij")
    with ByteSource.open(path) as source:
        assert list(source.iter_chunks(start=2, end=9, chunk_size=3)) == [b"cde", b"fgh", b"i"]


def test_empty_file_is_supported(tmp_path: Path):
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")
    with ByteSource.open(path) as source:
        assert source.size == 0
        assert source.read(0, 0) == b""
        assert list(source.iter_chunks()) == []


@pytest.mark.parametrize("start,length", [(-1, 1), (0, -1), (8, 3)])
def test_invalid_read_ranges_raise(tmp_path: Path, start: int, length: int):
    path = tmp_path / "data.bin"
    path.write_bytes(b"0123456789")
    with ByteSource.open(path) as source:
        with pytest.raises(ValueError):
            source.read(start, length)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=src pytest tests/core/test_byte_source.py -q`

Expected: import failure because `uniti.core.byte_source` does not exist.

- [ ] **Step 3: Implement ByteSource minimally**

Use an open binary file plus `mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ)` only when the file is non-empty and `prefer_mmap` is true. Fall back to `seek/read` if mmap creation raises `OSError`, `ValueError`, or `BufferError`. Validate all ranges before access. `iter_chunks` repeatedly calls `read` with at most `chunk_size` bytes.

- [ ] **Step 4: Add sparse >1 GiB failing test**

```python
def test_sparse_file_supports_offsets_above_one_gib(tmp_path: Path):
    path = tmp_path / "large.bin"
    marker_offset = (1 << 30) + 12345
    with path.open("wb") as handle:
        handle.seek(marker_offset)
        handle.write(b"UNITI")
    with ByteSource.open(path) as source:
        assert source.size == marker_offset + 5
        assert source.read(marker_offset, 5) == b"UNITI"
```

- [ ] **Step 5: Run sparse test and verify it passes without special-case code**

Run: `PYTHONPATH=src pytest tests/core/test_byte_source.py::test_sparse_file_supports_offsets_above_one_gib -q`

Expected: `1 passed` on filesystems supporting sparse files; if the sandbox filesystem cannot create sparse files, skip only on an explicit `OSError` from fixture creation.

- [ ] **Step 6: Run all ByteSource tests and verify GREEN**

Run: `PYTHONPATH=src pytest tests/core/test_byte_source.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/uniti/core tests/core/test_byte_source.py
git commit -m "feat: add immutable byte source"
```

### Task 3: Encoding metadata and first-pass detector

**Files:**
- Create: `src/uniti/core/encoding.py`
- Create: `tests/core/test_encoding.py`
- Modify: `src/uniti/core/__init__.py`

**Interfaces:**
- Consumes: `ByteSource`.
- Produces: `EncodingInfo` and `detect_encoding(source, sample_size=65536) -> EncodingInfo`.

- [ ] **Step 1: Write failing BOM and strict UTF-8 tests**

```python
from pathlib import Path
from uniti.core.byte_source import ByteSource
from uniti.core.encoding import detect_encoding


def detect(tmp_path: Path, payload: bytes):
    path = tmp_path / "sample.txt"
    path.write_bytes(payload)
    with ByteSource.open(path) as source:
        return detect_encoding(source)


def test_utf8_bom_is_authoritative(tmp_path: Path):
    info = detect(tmp_path, b"\xef\xbb\xbfhello")
    assert info.detected == "utf-8-sig"
    assert info.bom == b"\xef\xbb\xbf"
    assert info.confidence == 1.0


def test_valid_utf8_without_bom_is_detected(tmp_path: Path):
    info = detect(tmp_path, "café 世界".encode("utf-8"))
    assert info.detected == "utf-8"
    assert info.bom is None
    assert info.confidence >= 0.95
```

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONPATH=src pytest tests/core/test_encoding.py -q`

Expected: import failure because `uniti.core.encoding` does not exist.

- [ ] **Step 3: Implement EncodingInfo and BOM/UTF-8 detection**

`EncodingInfo` is frozen and stores `detected`, `confidence`, `bom`, `user_override=False`, `output_encoding=None`, and `alternatives=()`. Sample beginning, midpoint, and end for files larger than `sample_size * 3`; strict UTF-8 validation succeeds only if each sample is valid after ignoring only a multibyte sequence cut by that sample edge.

- [ ] **Step 4: Add failing UTF-16/UTF-32 heuristic and legacy fallback tests**

```python
def test_utf16le_without_bom_uses_null_structure(tmp_path: Path):
    info = detect(tmp_path, "Alpha Beta\n".encode("utf-16-le"))
    assert info.detected == "utf-16-le"
    assert 0.7 <= info.confidence < 1.0


def test_invalid_utf8_falls_back_conservatively(tmp_path: Path):
    info = detect(tmp_path, b"Price \x96 10\x80")
    assert info.detected == "windows-1252"
    assert info.confidence < 0.8
    assert "iso-8859-1" in info.alternatives
```

- [ ] **Step 5: Run new tests and verify RED for missing heuristic/fallback behavior**

Run: `PYTHONPATH=src pytest tests/core/test_encoding.py -q`

Expected: at least the UTF-16 or legacy test fails until implemented.

- [ ] **Step 6: Implement structural UTF-32/UTF-16 heuristics and conservative fallback**

Check four byte lanes first for UTF-32LE/BE null structure, then even/odd lanes for UTF-16LE/BE. Only after structural Unicode checks should boundary-aware strict UTF-8 validation run. Otherwise return Windows-1252 at confidence `0.35` with `("iso-8859-1",)` alternative.

- [ ] **Step 7: Run detector tests and verify GREEN**

Run: `PYTHONPATH=src pytest tests/core/test_encoding.py -q`

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/uniti/core tests/core/test_encoding.py
git commit -m "feat: add first-pass encoding detection"
```

### Task 4: Error-preserving bounded decoder and local offset mapping

**Files:**
- Create: `src/uniti/core/decoder.py`
- Create: `tests/core/test_decoder.py`
- Modify: `src/uniti/core/__init__.py`

**Interfaces:**
- Consumes: `ByteSource`, codec name, bounded byte range.
- Produces: `DecodeError`, `DecodedSpan`, and `decode_span(source, start, length, encoding) -> DecodedSpan`; `DecodedSpan.byte_offset_for_char_boundary(index) -> int` maps local character boundaries to absolute byte offsets.

- [ ] **Step 1: Write failing UTF-8 boundary mapping test**

```python
from pathlib import Path
from uniti.core.byte_source import ByteSource
from uniti.core.decoder import decode_span


def test_utf8_span_maps_character_boundaries_to_bytes(tmp_path: Path):
    path = tmp_path / "utf8.txt"
    path.write_bytes("Aé中Z".encode("utf-8"))
    with ByteSource.open(path) as source:
        span = decode_span(source, 0, source.size, "utf-8")
    assert span.text == "Aé中Z"
    assert span.char_boundaries == (0, 1, 3, 6, 7)
    assert span.byte_offset_for_char_boundary(3) == 6
```

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONPATH=src pytest tests/core/test_decoder.py -q`

Expected: import failure because decoder module does not exist.

- [ ] **Step 3: Implement valid-text DecodedSpan path**

Decode valid text first with explicit local byte-boundary reconstruction. The final implementation replaces Python `surrogateescape` with UNITI's codec-error sentinel because malformed UTF-16/UTF-32 spans cannot be losslessly round-tripped by the built-in handler.

- [ ] **Step 4: Add failing invalid-byte preservation tests**

```python
def test_invalid_utf8_bytes_are_visible_and_preserved(tmp_path: Path):
    path = tmp_path / "bad.txt"
    path.write_bytes(b"A\xffB")
    with ByteSource.open(path) as source:
        span = decode_span(source, 0, 3, "utf-8")
    assert span.text == "A\ufffdB"
    assert len(span.errors) == 1
    assert span.errors[0].byte_start == 1
    assert span.errors[0].byte_end == 2
    assert span.errors[0].raw == b"\xff"
    assert span.char_boundaries == (0, 1, 2, 3)


def test_undefined_cp1252_byte_is_preserved(tmp_path: Path):
    path = tmp_path / "bad-1252.txt"
    path.write_bytes(b"A\x81B")
    with ByteSource.open(path) as source:
        span = decode_span(source, 0, 3, "windows-1252")
    assert span.text == "A\ufffdB"
    assert span.errors[0].raw == b"\x81"
```

- [ ] **Step 5: Run and verify RED for display/error records**

Run: `PYTHONPATH=src pytest tests/core/test_decoder.py -q`

Expected: invalid-byte assertions fail until codec error spans are converted into U+FFFD plus `DecodeError` records.

- [ ] **Step 6: Implement invalid-byte records**

Register a UNITI decode-error handler that records each `UnicodeDecodeError` byte span and emits an internal sentinel. Convert each sentinel to one U+FFFD plus one exact `DecodeError`, including multi-byte malformed UTF-16/UTF-32 spans. Strip recognized BOM prefixes from visible text while starting `char_boundaries` after the BOM. Validate all reconstructed byte boundaries before returning the span.

- [ ] **Step 7: Add failing sliced-window absolute-offset test**

```python
def test_span_mapping_uses_absolute_source_offsets(tmp_path: Path):
    path = tmp_path / "slice.txt"
    path.write_bytes(b"xx" + "Aé".encode("utf-8") + b"yy")
    with ByteSource.open(path) as source:
        span = decode_span(source, 2, 3, "utf-8")
    assert span.char_boundaries == (0, 1, 3)
    assert span.byte_offset_for_char_boundary(2) == 5
```

- [ ] **Step 8: Run all decoder tests and verify GREEN**

Run: `PYTHONPATH=src pytest tests/core/test_decoder.py -q`

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/uniti/core tests/core/test_decoder.py
git commit -m "feat: add bounded loss-aware decoder"
```

### Task 5: Streaming EOL analysis

**Files:**
- Create: `src/uniti/core/eol.py`
- Create: `tests/core/test_eol.py`
- Modify: `src/uniti/core/__init__.py`

**Interfaces:**
- Consumes: `ByteSource.iter_chunks()`.
- Produces: frozen `EOLReport(lf, crlf, cr, kind)` and `analyze_eol(source, chunk_size=1<<20, *, encoding="utf-8") -> EOLReport`.

- [ ] **Step 1: Write failing homogeneous/mixed/none tests**

```python
from pathlib import Path
from uniti.core.byte_source import ByteSource
from uniti.core.eol import analyze_eol


def report(tmp_path: Path, payload: bytes, *, chunk_size: int = 1 << 20):
    path = tmp_path / "eol.txt"
    path.write_bytes(payload)
    with ByteSource.open(path) as source:
        return analyze_eol(source, chunk_size=chunk_size)


def test_lf_file(tmp_path: Path):
    result = report(tmp_path, b"a\nb\n")
    assert (result.lf, result.crlf, result.cr, result.kind) == (2, 0, 0, "LF")


def test_mixed_file(tmp_path: Path):
    result = report(tmp_path, b"a\r\nb\nc\r")
    assert (result.lf, result.crlf, result.cr, result.kind) == (1, 1, 1, "MIXED")


def test_no_eol(tmp_path: Path):
    result = report(tmp_path, b"single line")
    assert result.kind == "NONE"
```

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONPATH=src pytest tests/core/test_eol.py -q`

Expected: import failure because EOL module does not exist.

- [ ] **Step 3: Implement streaming EOL scanner**

Use `codecs.getincrementaldecoder(encoding)(errors="replace")` over `ByteSource.iter_chunks()`. Count CRLF/LF/CR in decoded text using string counts and carry a pending CR across decoded chunk boundaries. This keeps UTF-16/UTF-32 EOL semantics correct even when byte chunks split code units.

- [ ] **Step 4: Add failing CRLF-across-chunk test**

```python
def test_crlf_split_across_chunks_counts_once(tmp_path: Path):
    result = report(tmp_path, b"abc\r\ndef", chunk_size=4)
    assert (result.lf, result.crlf, result.cr, result.kind) == (0, 1, 0, "CRLF")
```

- [ ] **Step 5: Run EOL tests and verify GREEN**

Run: `PYTHONPATH=src pytest tests/core/test_eol.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/uniti/core tests/core/test_eol.py
git commit -m "feat: add streaming EOL analysis"
```

### Task 6: Atomic streaming byte-preserving save primitive

**Files:**
- Create: `src/uniti/core/streaming.py`
- Create: `tests/core/test_streaming.py`
- Modify: `src/uniti/core/__init__.py`

**Interfaces:**
- Consumes: `ByteSource` and destination path.
- Produces: `atomic_copy_source(source, destination, chunk_size=1<<20) -> pathlib.Path`.

- [ ] **Step 1: Write failing byte-identical copy test**

```python
from pathlib import Path
from uniti.core.byte_source import ByteSource
from uniti.core.streaming import atomic_copy_source


def test_atomic_copy_is_byte_identical(tmp_path: Path):
    source_path = tmp_path / "source.bin"
    target_path = tmp_path / "target.bin"
    payload = (b"UNITI\x00\xff\r\n" * 1000) + b"end"
    source_path.write_bytes(payload)
    with ByteSource.open(source_path) as source:
        result = atomic_copy_source(source, target_path, chunk_size=257)
    assert result == target_path
    assert target_path.read_bytes() == payload
```

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONPATH=src pytest tests/core/test_streaming.py -q`

Expected: import failure because streaming module does not exist.

- [ ] **Step 3: Implement atomic streaming copy**

Create the temporary file in the destination directory using `tempfile.mkstemp`, write each chunk from `source.iter_chunks`, `flush`, `os.fsync`, close, then `os.replace(temp_path, destination)`. In an exception path close any open descriptor and unlink the temporary path before re-raising.

- [ ] **Step 4: Add failing existing-target replacement test**

```python
def test_atomic_copy_replaces_existing_target(tmp_path: Path):
    source_path = tmp_path / "source.bin"
    target_path = tmp_path / "target.bin"
    source_path.write_bytes(b"new")
    target_path.write_bytes(b"old")
    with ByteSource.open(source_path) as source:
        atomic_copy_source(source, target_path, chunk_size=1)
    assert target_path.read_bytes() == b"new"
```

- [ ] **Step 5: Run streaming tests and verify GREEN**

Run: `PYTHONPATH=src pytest tests/core/test_streaming.py -q`

Expected: all tests pass.

- [ ] **Step 6: Run complete suite**

Run: `PYTHONPATH=src pytest -q`

Expected: all tests pass with no warnings.

- [ ] **Step 7: Commit**

```bash
git add src/uniti/core tests/core/test_streaming.py
git commit -m "feat: add atomic streaming source copy"
```

### Task 7: Core smoke probe and documentation

**Files:**
- Create: `scripts/core_probe.py`
- Modify: `README.md`
- Create: `tests/test_core_probe.py`

**Interfaces:**
- Consumes: `ByteSource`, `detect_encoding`, `decode_span`, `analyze_eol`.
- Produces: CLI smoke probe printing size, detected encoding, EOL classification, and first decoded text window without Qt.

- [ ] **Step 1: Write failing probe test**

```python
import subprocess
import sys
from pathlib import Path


def test_core_probe_reports_file_metadata(tmp_path: Path):
    path = tmp_path / "sample.txt"
    path.write_bytes(b"alpha\r\nbeta\r\n")
    result = subprocess.run(
        [sys.executable, "scripts/core_probe.py", str(path), "--window", "8"],
        check=True,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src"},
    )
    assert "size: 13" in result.stdout
    assert "encoding: utf-8" in result.stdout
    assert "eol: CRLF" in result.stdout
```

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONPATH=src pytest tests/test_core_probe.py -q`

Expected: failure because `scripts/core_probe.py` does not exist.

- [ ] **Step 3: Implement probe and document current scope**

Use `argparse`; open the source with `ByteSource`, detect encoding, analyze EOL using that detected encoding, decode at most `--window` bytes from byte 0, and print one field per line. The README must state that Phase 1A has no editor viewport yet and list the next slice as piece table + sparse offset index + line index.

- [ ] **Step 4: Run probe test and full suite**

Run: `PYTHONPATH=src pytest -q`

Expected: all tests pass with no warnings.

- [ ] **Step 5: Manual sparse-file smoke probe**

Create a sparse file whose marker lies above 1 GiB, open it with `ByteSource`, read the marker, and print process RSS before/after using `resource.getrusage` on Unix. The acceptance condition is successful read without allocation proportional to file size; this is a smoke measurement, not a stable CI assertion.

- [ ] **Step 6: Commit**

```bash
git add scripts/core_probe.py README.md tests/test_core_probe.py
git commit -m "docs: add UNITI core probe"
```
