# UNITI Phase 1B Document Model Design

## Status

Approved implementation slice derived from **UNITI Architecture v0.1 — Unicode Intelligent Text Interchange** and the completed Phase 1A core foundation.

## Goal

Build the first editable UNITI document model without sacrificing lazy file opening, byte fidelity, 64-bit-capable offsets, or Qt independence.

Phase 1B establishes the coordinate and edit contracts required by the future virtual viewport:

1. safe progressive decoding windows;
2. sparse byte↔character checkpoints;
3. compact progressive line indexing;
4. a hybrid source/edit piece table;
5. a `Document` facade that opens immediately and resolves source metrics lazily.

The display/project version for this slice is **`v0.001a2`**. Python packaging uses the PEP 440 normalized **`0.1a2`**.

## Non-goals for this slice

- Qt/PySide6 viewport or widgets;
- regex search/indexing;
- syntax highlighting;
- undo/redo;
- crash recovery;
- edited-document save/encoding conversion;
- tree/B-tree optimization of the piece sequence;
- whole-document eager indexing at open.

## Architectural invariants

1. `uniti.core` imports no Qt modules.
2. `Document.open()` does not decode the complete file.
3. Original bytes remain in `ByteSource`; source pieces never copy them.
4. File and document offsets use Python integers with no 32-bit assumptions.
5. Mapping and line indexing are progressive and cache their work.
6. Source decoding windows end on encoding-safe character boundaries.
7. Invalid source bytes continue to occupy one visible replacement character and remain represented by Phase 1A `DecodeError` records.
8. The piece table stores inserted text as Unicode in an append-only edit store.
9. At most one source piece may have unresolved character length; it is the final source tail.
10. No API introduces a deliberate 1 GiB ceiling.

## 1. Safe progressive decoded windows

Phase 1A `decode_span()` is exact only when the requested range ends on a complete encoded character. Phase 1B adds `iter_decoded_spans()` to `uniti.core.decoder`.

The iterator produces bounded `DecodedSpan` objects whose boundaries are safe for the supported initial codec families:

- UTF-8 / UTF-8-SIG: move candidate ends backward over continuation bytes and, when needed, over a lead byte whose sequence is incomplete;
- UTF-16 LE/BE: align to 2-byte code units and do not split a valid surrogate pair;
- UTF-32 LE/BE: align to 4-byte code units;
- other codecs: bounded chunks are accepted as byte-aligned; stateful codecs that cannot provide stable Phase-1A byte boundaries continue to fail explicitly.

The first span preserves BOM-prefix semantics already implemented by `decode_span()`.

Public interface:

```python
def iter_decoded_spans(
    source: ByteSource,
    encoding: str,
    *,
    start: int = 0,
    end: int | None = None,
    chunk_size: int = 65_536,
) -> Iterator[DecodedSpan]: ...
```

## 2. Sparse OffsetMapper

`OffsetMapper` owns progressive translation between source byte boundaries and original-source Unicode character boundaries.

A checkpoint is:

```python
@dataclass(frozen=True, slots=True)
class OffsetCheckpoint:
    byte_offset: int
    char_offset: int
```

Checkpoint zero reflects the decoder's visible-character convention. For BOM-bearing encodings the first visible character boundary maps after the BOM, while the logical source character offset remains zero.

The mapper maintains monotonically increasing checkpoints roughly every 64 KiB of source bytes. It scans only as far as required by a mapping request and caches the new frontier.

Public interface:

```python
class OffsetMapper:
    def __init__(self, source: ByteSource, encoding: str, *, checkpoint_bytes: int = 65_536): ...
    @property
    def indexed_byte_end(self) -> int: ...
    @property
    def indexed_char_end(self) -> int: ...
    @property
    def complete(self) -> bool: ...
    def byte_to_char(self, byte_offset: int) -> int: ...
    def char_to_byte(self, char_offset: int) -> int: ...
    def total_chars(self) -> int: ...
```

`byte_to_char()` accepts only actual visible character boundaries. A byte inside a multibyte character raises `ValueError` rather than returning an ambiguous coordinate.

`char_to_byte()` scans forward only until the requested character boundary exists. Asking past EOF raises `ValueError`.

## 3. Compact progressive immutable-source LineIndex

`LineIndex` stores immutable-source line-start byte offsets in `array('Q')`, not one Python object per line. Line zero always begins at the first visible byte boundary (after a BOM where applicable).

Line indexing is encoding-aware and progressive. It consumes the same safe decoded windows and records the byte boundary following each logical line ending:

- CRLF is one ending;
- LF is one ending;
- CR is one ending;
- a CR at the end of a decoded window remains pending until the first character of the next window is known.

Public interface:

```python
class LineIndex:
    def __init__(self, source: ByteSource, encoding: str, *, chunk_size: int = 65_536): ...
    @property
    def indexed_byte_end(self) -> int: ...
    @property
    def complete(self) -> bool: ...
    @property
    def indexed_line_count(self) -> int: ...
    def ensure_byte(self, byte_offset: int) -> None: ...
    def ensure_line(self, line_index: int) -> None: ...
    def line_start(self, line_index: int) -> int: ...
    def line_for_byte(self, byte_offset: int) -> int: ...
    def total_lines(self) -> int: ...
```

Line indexes are zero-based internally. UI presentation may later add one.

## 4. EditStore and hybrid PieceTable

Inserted/replacement text is stored in an append-only Unicode `EditStore`.

```python
@dataclass(frozen=True, slots=True)
class EditRef:
    block: int
    start: int
    length: int

class EditStore:
    def append(self, text: str) -> EditRef: ...
    def read(self, ref: EditRef, start: int = 0, end: int | None = None) -> str: ...
```

The piece table uses two piece types:

```python
@dataclass(slots=True)
class SourcePiece:
    byte_start: int
    byte_end: int
    source_char_start: int
    char_length: int | None

@dataclass(slots=True)
class EditPiece:
    ref: EditRef
```

`source_char_start` is the character position in the immutable original source, not the current edited document.

The crucial lazy invariant is:

> Only the final source tail may have `char_length=None`.

An initial document therefore consists of one unresolved source tail and requires no full scan. Splitting that tail for an edit asks `OffsetMapper` only for the needed original character boundary. The left source piece becomes measured; the remaining right tail stays unresolved.

PieceTable interface:

```python
class PieceTable:
    def __init__(self, source: ByteSource, encoding: str, mapper: OffsetMapper, edit_store: EditStore): ...
    def insert(self, char_offset: int, text: str) -> None: ...
    def delete(self, start: int, end: int) -> None: ...
    def replace(self, start: int, end: int, text: str) -> None: ...
    def read(self, start: int, end: int) -> str: ...
    def total_chars(self) -> int: ...
    @property
    def piece_count(self) -> int: ...
```

Operations use half-open character ranges. Empty inserts are no-ops. Deletes/replaces validate `0 <= start <= end <= document_length` but only force full source measurement when the requested boundary itself requires EOF knowledge.

Source reads use `OffsetMapper` to translate piece-local original character ranges to byte ranges and `decode_span()` to produce text. Edit reads come directly from `EditStore`.

The Phase 1B implementation uses a Python list of pieces. This intentionally proves semantics first. The public PieceTable interface allows a balanced tree/B-tree replacement later without changing `Document`.

## 5. Document facade

`Document` owns the lifetime and composition of the Phase 1B core services.

```python
class Document:
    @classmethod
    def open(cls, path: str | os.PathLike[str], *, encoding: str | None = None) -> "Document": ...
    @property
    def source(self) -> ByteSource: ...
    @property
    def encoding_info(self) -> EncodingInfo: ...
    @property
    def offset_mapper(self) -> OffsetMapper: ...
    @property
    def source_line_index(self) -> LineIndex: ...
    @property
    def modified(self) -> bool: ...
    def read(self, start: int, end: int) -> str: ...
    def insert(self, char_offset: int, text: str) -> None: ...
    def delete(self, start: int, end: int) -> None: ...
    def replace(self, start: int, end: int, text: str) -> None: ...
    def total_chars(self) -> int: ...
    def close(self) -> None: ...
```

`Document.source_line_index` is explicitly the immutable-source line index. It is not a current edited-document line index; inserted Unicode text has no original source byte offset. A piece-aware document line/navigation layer is deferred rather than exposing stale source offsets after edits.

`Document.open()` performs only:

1. `ByteSource.open()`;
2. bounded encoding detection unless an override is supplied;
3. construction of empty/lazy mapper, line index, edit store, and piece table.

It does not build the complete offset or line index.

An encoding override is represented as `EncodingInfo(..., confidence=1.0, user_override=True, output_encoding=encoding)`.

## Error handling

- Negative/out-of-range document character positions raise `ValueError`.
- Byte offsets inside multibyte characters raise `ValueError` in `byte_to_char()`.
- Character requests beyond EOF raise `ValueError`.
- Closed `Document` delegates source-use failures through existing `ByteSource` semantics.
- Empty replacement text is equivalent to delete; empty delete range is a no-op.

## Testing and acceptance

Phase 1B is accepted when all Phase 1A tests remain green and new tests prove:

- safe decoded windows do not turn valid characters split at chunk candidates into replacement errors;
- UTF-8, UTF-16 and UTF-32 mappings round-trip character boundaries;
- an offset request near the start does not index the entire source;
- >1 GiB source byte offsets remain usable;
- line starts are correct for LF/CRLF/CR, mixed endings, BOMs, and multibyte encodings;
- the line-start store is `array('Q')` backed;
- insertion, deletion and replacement work across source/edit piece boundaries;
- invalid source bytes remain visible/preserved through piece-table reads;
- opening a document leaves mapper and immutable-source line index incomplete for a multi-chunk source;
- edits near the beginning do not require whole-file character counting;
- `uniti.core` remains Qt-independent;
- the complete test suite and Python compile check pass.
