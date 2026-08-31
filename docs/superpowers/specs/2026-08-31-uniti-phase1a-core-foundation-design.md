# UNITI Phase 1A Core Foundation Design

## Status

Approved implementation slice derived from **UNITI Architecture v0.1 — Unicode Intelligent Text Interchange**.

## Goal

Create the first executable UNITI codebase while preserving the architecture's hard rules: UNITI owns text, files remain byte-addressable, decoding is lazy and loss-aware, EOL state is explicit, long operations are streamable, and the core has no Qt dependency.

## Scope

Phase 1A implements only the contracts on which later editing and viewport work depend:

1. Python package and test harness.
2. `ByteSource`: immutable random-access byte source using `mmap` where practical and bounded file reads as fallback.
3. Encoding metadata plus deterministic first-pass detection from samples.
4. `Decoder`: decode bounded byte windows, preserve undecodable bytes as explicit error spans, and expose local byte↔character boundaries.
5. `EOLAnalyzer`: streaming counts for LF, CRLF, and CR with mixed-state classification.
6. Streaming raw copy/save primitive proving that a large untouched source can be written without loading it into Python memory.

The following are deliberately deferred to the next slice because they depend on the contracts above:

- hybrid piece table and edit store;
- document-wide sparse offset checkpoint index;
- line index;
- Qt/PySide6 viewport;
- regex scanning and capture visualization;
- crash recovery and undo/redo.

## Architecture boundaries

### `uniti.core.byte_source`

Owns file opening, file identity, random reads, chunk iteration, and close semantics. It returns `bytes` only for explicitly requested bounded ranges. It never exposes a whole-file `bytes` representation.

### `uniti.core.encoding`

Defines immutable encoding metadata and a first-pass detector. Detection order for this slice is:

1. UTF-8/UTF-16/UTF-32 BOM;
2. UTF-32 structural null-byte heuristic;
3. UTF-16 structural null-byte heuristic;
4. strict UTF-8 validation on samples, tolerating only multibyte sequences cut by a sample edge;
5. conservative Windows-1252 fallback with low confidence.

The result exposes confidence and alternatives; it must not claim certainty for legacy text. A later slice may plug in a statistical detector behind this interface.

### `uniti.core.decoder`

Decodes only requested byte ranges. It returns `DecodedSpan` containing:

- display text;
- original byte start/end;
- encoding;
- explicit `DecodeError` records containing original byte ranges and raw bytes;
- local character boundary offsets used to map a character boundary back to the corresponding byte boundary.

Invalid bytes are displayed as U+FFFD but remain recoverable through the source and `DecodeError` records. The decoder must not silently discard them.

Decoding uses a UNITI codec-error sentinel backed by thread-local error-span records. Any codec decode error, including malformed UTF-16/UTF-32 sequences, becomes one visible U+FFFD plus a `DecodeError` containing the exact original byte range. Valid characters are re-encoded only to reconstruct local byte boundaries; unstable/stateful codecs fail explicitly rather than returning incorrect offsets. UTF BOM bytes at byte zero remain prefix metadata and are excluded from visible text while remaining represented in the first character boundary.

### `uniti.core.eol`

Decodes bounded byte chunks incrementally using the document encoding, then counts logical CRLF/LF/CR sequences in decoded text. This is required for UTF-16/UTF-32, where raw CR/LF bytes are separated by zero bytes. A pending CR is carried across decoded chunk boundaries so CRLF remains one logical EOL. It reports counts and one of `LF`, `CRLF`, `CR`, `MIXED`, or `NONE`.

### `uniti.core.streaming`

Streams a `ByteSource` into a destination path via a temporary file, flush + fsync, and atomic replace. This first path is byte-preserving and proves the save mechanism; encoding/EOL transforms will layer onto the same streaming writer later.

## Public interfaces

```python
class ByteSource:
    @classmethod
    def open(cls, path: str | os.PathLike[str], *, prefer_mmap: bool = True) -> "ByteSource": ...
    @property
    def path(self) -> pathlib.Path: ...
    @property
    def size(self) -> int: ...
    def read(self, start: int, length: int) -> bytes: ...
    def iter_chunks(self, *, start: int = 0, end: int | None = None, chunk_size: int = 1 << 20) -> Iterator[bytes]: ...
    def close(self) -> None: ...
```

```python
@dataclass(frozen=True)
class EncodingInfo:
    detected: str
    confidence: float
    bom: bytes | None
    user_override: bool = False
    output_encoding: str | None = None
    alternatives: tuple[str, ...] = ()
```

```python
@dataclass(frozen=True)
class DecodeError:
    byte_start: int
    byte_end: int
    raw: bytes

@dataclass(frozen=True)
class DecodedSpan:
    text: str
    byte_start: int
    byte_end: int
    encoding: str
    errors: tuple[DecodeError, ...]
    char_boundaries: tuple[int, ...]

    def byte_offset_for_char_boundary(self, char_boundary: int) -> int: ...
```

```python
@dataclass(frozen=True)
class EOLReport:
    lf: int
    crlf: int
    cr: int
    kind: Literal["LF", "CRLF", "CR", "MIXED", "NONE"]

def analyze_eol(
    source: ByteSource,
    chunk_size: int = 1 << 20,
    *,
    encoding: str = "utf-8",
) -> EOLReport: ...
```

## Performance constraints

- All file offsets and sizes use Python integers and are treated as 64-bit-capable values.
- Opening a file performs `stat` and mapping/opening only; it never decodes the whole file.
- Default processing chunk is 1 MiB or smaller where tests request it.
- No production API returns a complete file as one object.
- Tests include chunk-boundary cases and a sparse-file >1 GiB random read when supported by the filesystem.

## Error handling

- Negative offsets/lengths and out-of-range reads raise `ValueError`.
- Reads that extend beyond EOF raise `ValueError`; callers must request explicit valid ranges.
- Closed sources raise `ValueError` on use.
- Unknown encodings propagate Python codec lookup errors rather than guessing.
- Streaming copy removes its temporary file on failure and leaves the target untouched until atomic replace.

## Testing

Tests are test-first and use real temporary files, not mocked filesystem APIs. The suite verifies:

- zero-byte and normal files;
- random bounded reads and chunk iteration;
- no 32-bit offset assumptions through a sparse >1 GiB file;
- BOM and strict UTF-8 detection;
- conservative fallback for invalid UTF-8;
- preservation and display marking of invalid UTF-8, Windows-1252, UTF-16 and UTF-32 spans;
- UTF BOM prefix handling and UTF-8 multibyte local byte↔character boundaries;
- CRLF split across chunks and encoding-aware UTF-16/UTF-32 EOL analysis;
- mixed and no-EOL classification;
- byte-identical streaming copy and atomic target replacement.

## Acceptance for Phase 1A

The slice is complete when the full test suite passes, `uniti.core` imports without PySide6 installed, and a smoke script can open and inspect a sparse >1 GiB source without allocating memory proportional to file size.
