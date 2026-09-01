# UNITI Current Scope

Date: 2026-09-01

## Product boundary

UNITI is a focused, cross-platform power text editor for Unicode correctness, explicit encoding and EOL control, bounded large-file editing, and advanced search/replace through Python's third-party `regex` package. It is deliberately an editor rather than an IDE, project platform, plugin host, or cloud service.

This document describes implemented behavior through product-code baseline `6b81185`. Planned `v0.001a16` startup/bootstrap behavior is not part of current scope until implemented and verified.

## Included capabilities

### Text and byte fidelity

- mmap-preferred immutable byte sources with bounded fallback reads;
- UTF-8, Windows-1252, UTF-16 LE/BE, and UTF-32 LE/BE detection and handling, including supported BOM and BOM-less cases;
- explicit reinterpretation versus convert-on-save behavior;
- preservation and annotation of malformed source bytes, distinct from genuine U+FFFD text;
- CR, LF, CRLF, and mixed-EOL analysis;
- source-aware insertion EOL policy independent from output conversion policy; and
- byte/character offset mapping and progressive line indexes without whole-file opening decodes.

### Editing and persistence

- hybrid source/edit piece table with coalesced ordinary typing;
- selections, insertion, deletion, replacement, transactions, undo, and redo;
- bounded giant-line navigation and horizontal viewport rendering;
- streaming atomic Save and Save As;
- external-file identity protection before overwrite;
- supported POSIX mode and metadata preservation; and
- incremental asynchronous crash-recovery journals with validated replay.

### Search and replace

- authoritative `regex==2026.5.9` semantics;
- windowed, cancellable search with timeouts and bounded retained context;
- named, repeated, branch-reset, and duplicate-named capture handling aligned with the engine;
- compact/paged `MatchStore` result storage bound to document revision;
- visible-only UI match overlays and capture inspection;
- transactional small Replace All; and
- explicit streaming atomic rewrite for sufficiently large Replace All operations.

### Desktop application

- PySide6 application shell and custom `QAbstractScrollArea` text viewport;
- tabs, native file/edit/search commands, clipboard operations, and IME composition;
- encoding, reinterpretation, conversion, EOL, character-inspection, settings, diagnostics, and recovery surfaces;
- application-wide bounded resource manager, cache pressure policy, and priority worker scheduling; and
- queued Qt event-loop delivery of completed regex work.

## Architectural invariants

1. Qt never owns authoritative document text.
2. `uniti.core` remains independent of PySide6.
3. Opening a file never requires decoding the whole file.
4. File offsets remain 64-bit-capable through Python integers.
5. Immutable source bytes remain addressable while their file identity is safe.
6. Encoding reinterpretation and output conversion remain separate operations.
7. Mixed EOL state is represented rather than silently normalized.
8. Third-party Python `regex` remains authoritative for regex semantics.
9. Long document work stays off the GUI thread.
10. Search-result count does not dictate GUI object count or unbounded RAM.
11. Save remains streaming, atomic, and external-change conscious.
12. User edits and history are durable document state, not disposable cache.
13. Resource reclamation is centralized and bounded by host safety margins.
14. No deliberate 1 GiB ceiling is introduced; at least 1 GiB remains the design target.

## Outside current scope

The project/workspace layer, plugins, LSP, Git UI, integrated terminal, AI/cloud features, hex editing, full programming-language syntax highlighting, and polished platform installers with embedded runtimes are parked. They are not hidden roadmap commitments.

See the [Parked Capability Catalog](../04_parked/CATALOG.md) for rationale and re-evaluation triggers.
