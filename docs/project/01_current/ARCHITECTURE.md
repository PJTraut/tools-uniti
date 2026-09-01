# UNITI Current Architecture

Date: 2026-09-01
Baseline: implemented product code through `6b81185`

## Ownership model

UNITI separates the virtual document engine from its PySide6 presentation. The document model owns content and coordinates; Qt owns windows, input events, painting, and GUI-thread presentation only.

```text
QApplication / uniti.app.application
    -> UNITIMainWindow
    -> UNITITextView (custom QAbstractScrollArea)
    -> EditorState
    -> Document
    -> PieceTable + DocumentLineIndex + History
    -> EditStore + immutable SourcePiece ranges
    -> OffsetMapper + decoder
    -> ByteSource (mmap preferred, bounded fallback)
```

`src/uniti/core` and `src/uniti/regex` do not import PySide6. UI commands mutate content through `EditorState` and `Document`; no `QTextDocument`, `QPlainTextEdit`, or other Qt text store is authoritative.

## Open and decode path

`ByteSource` provides immutable random byte access. Encoding detection selects a supported decoder without exposing a BOM as visible text. Bounded decoded spans retain exact character-to-byte boundaries and malformed-byte annotations. `OffsetMapper`, source line indexing, and edited-document line indexing are progressive so opening cost does not scale with total file length.

`Document` combines source identity, encoding/EOL metadata, piece-table editing, navigation, history, save policy, recovery integration, and revision tracking behind the main core facade.

## Editing and rendering path

`EditorState` owns cursor, selection, navigation, clipboard mutations, and inserted-newline behavior. `UNITITextView` paints only visible logical lines and horizontal windows from bounded document reads. It renders selections, the cursor, invalid-byte boxes, IME preedit text, and visible match intersections without mirroring the file into Qt.

Sequential edit-store runs coalesce. Huge-line End/vertical navigation and viewport operations use bounded window APIs rather than materializing complete lines.

## Search path

```text
FindReplacePanel
    -> ResourceManager priority workers
    -> uniti.regex search/replace using regex==2026.5.9
    -> MatchStore (memory pages with spill storage)
    -> revision validation
    -> queued Qt completion signal
    -> visible match overlays and capture inspector
```

Search execution is cancellable and timeout-aware. Difficult unbounded-context patterns fail explicitly rather than silently retaining an entire prefix. Find All stores compact results independently of GUI objects. Document edits invalidate revision-bound results. Worker completion is delivered through a queued Qt signal, and the panel remains busy until the GUI thread applies the result.

## Save path

```text
Document
    -> external FileIdentity validation
    -> streaming source/edit segment writer
    -> optional explicit encoding/EOL conversion
    -> temporary sibling file + flush/fsync
    -> atomic replacement
    -> supported metadata preservation
```

Untouched source regions may be copied byte-for-byte where safe. Conversion is strict and explicit. Save rejects unsafe overwrites when the source file identity changed externally. Supported platforms preserve relevant file mode/metadata and sync the containing directory after replacement.

## Recovery path

```text
Document edit listener
    -> RecoveryManager single-thread executor
    -> versioned JSONL recovery journal
    -> bounded durability interval
    -> explicit flush on save, close, discovery, and shutdown
```

The typing path queues recovery work without synchronous fsync. Recovery discovery validates source identity before replay and preserves distinct source/output encoding and EOL metadata.

## Resource ownership

One application `ResourceManager` owns cache budgets, pressure state, active/inactive document priority, and the shared `PriorityWorkerPool`. Disposable mapper, index, and search caches register by owner and priority. Pressure escalates immediately and recovers with hysteresis; closing a document evicts only that document's disposable resources. User edits and history are never treated as reclaimable cache.

`UNITIMainWindow` updates active-tab priority. Find/Replace, background EOL analysis, and other long work share the scheduler. `RecoveryManager` has its own serialized durability executor because recovery ordering differs from disposable background computation.

## Application services

`uniti.app.application` constructs one `ResourceManager` and one `RecoveryManager`, creates application paths/settings, launches `UNITIMainWindow`, and shuts services down in `finally` paths. OS-appropriate config, state, cache, recovery, and diagnostics paths are implemented; the planned formal bootstrap/setup-state lifecycle is not yet implemented.

## Platform boundary

PySide6 is optional for importing and testing the core. When installed, the desktop UI provides native clipboard/IME/platform integration. Platform capability differences, such as unsupported extended attributes, are represented explicitly rather than treated as universal guarantees.
