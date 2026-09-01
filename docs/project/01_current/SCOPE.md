# UNITI Current Scope

Date: 2026-09-01
Version: `v0.001a16` / `0.1a16`

## Product boundary

UNITI is a focused, cross-platform power text editor for Unicode correctness, explicit encoding/EOL control, bounded large-file editing, advanced third-party-regex search/replace, and a safe diagnosable desktop startup lifecycle. It is an editor rather than an IDE, project platform, plugin host, package manager, or cloud service.

The a16 usability milestone is implemented and verified, including its real-use corrections and native macOS smoke. a17 Text Integrity is the active planned milestone; its intended changes are not current behavior until implemented and verified.

## Included lifecycle capabilities

- standard-library bootstrap shim and validated discovery of host Python 3.12+;
- source `.venv` and explicit application-local virtual-environment modes;
- ownership marker, deterministic environment identity, partial-state retention, source adoption, local-target refusal, exclusive locks, and explicit repair;
- canonical `pyproject.toml` dependency selection, managed-Python pip invocation, import/metadata validation, `pip check`, and fingerprints;
- pre-Qt application CLI, version output, fast/deep self-check, human/JSON reporting, and lifecycle exit codes;
- ordered BOOT→READY startup coordination with per-phase atomic state and bounded JSONL logs;
- schema-1 setup/settings persistence, legacy settings migration, malformed-file preservation, and future-schema refusal;
- platform application paths, runtime/filesystem/resource/Qt capability reporting, narrow stale cleanup, and per-process session records;
- completed startup/setup diagnostics passed into the UI without re-probing; and
- root macOS and Windows launchers that enter the same bootstrap/application path.

## Included editor capabilities

- mmap-preferred immutable byte sources with bounded fallback reads;
- UTF-8, Windows-1252, UTF-16 LE/BE, and UTF-32 LE/BE detection and handling;
- explicit reinterpretation versus convert-on-save and malformed-byte preservation;
- CR, LF, CRLF, mixed-EOL analysis, source-aware insertion, and explicit output conversion;
- progressive byte/character and line indexes without whole-file opening decodes;
- hybrid source/edit piece table, selections, atomic transactions, and a 50-transaction document Undo/Redo history;
- coalesced typing/backspace/delete plus Unicode-aware word, page, document, line, and Shift-extended navigation;
- Cut, Copy, Paste, Select All, Go to Line, and protected Reload/Revert;
- word, visual-line, and logical-line-through-break selection by double, triple, and quadruple click;
- fixed-pitch Western/Latin and Cyrillic rendering, independent editor zoom, primary-modifier wheel zoom, and progressive display-only soft wrap;
- streaming atomic Save/Save As with external-file identity and supported metadata protection;
- asynchronous crash-recovery journals and validated replay;
- authoritative `regex==2026.5.9`, cancellable/windowed search, compact revision-bound matches, and document-transaction replacement;
- mouse-resizable floating Find/Replace with explicit Literal/Regex selection, equal-height inputs that divide the space above a compact bottom-anchored control stack, grouped batch/match actions, an unrestricted collapsible capture splitter, capture-only reports, independent zoom/geometry/report state, report-position cycling, and separate 50-step field histories;
- one-step undoable Replace All with no disk-rewrite history bypass;
- a scoped shared command registry and persisted Hotkeys popup for window, editor, and Find/Replace commands;
- a compact `File | Edit | Format | View | Find | Tools | Hotkeys` menu bar with native shortcut display and no duplicate pre-Cot top-level command groupings;
- PySide6 tabs, custom virtual viewport, clipboard, IME, menus, zoom/wrap status, inspections, diagnostics, and recovery surfaces; and
- centralized cache pressure, active/inactive document priority, and shared background workers.

## Architectural invariants

1. Qt never owns authoritative document text.
2. Core/regex/resource modules remain independent of PySide6.
3. Opening a file never requires decoding the whole file.
4. Immutable source bytes remain addressable while file identity is safe.
5. Encoding reinterpretation and output conversion remain separate.
6. Mixed EOL state is represented, not silently normalized.
7. Third-party Python `regex` remains authoritative.
8. Long document work stays off the GUI thread.
9. Search-result count does not dictate GUI object count or unbounded RAM.
10. Save remains streaming, atomic, and external-change conscious.
11. User edits/history are document state, not disposable cache.
12. Replace All is one document transaction and one Undo operation.
13. Focus selects editor, Find-field, or Replace-field command/history ownership.
14. Bootstrap mutates only an ownership-validated UNITI runtime.
15. Ordinary startup never invokes pip or dependency repair.
16. Managed environments are never deleted, cleared, or silently replaced.
17. Capability checks and cleanup remain bounded and confined to UNITI-owned paths.
18. No deliberate 1 GiB ceiling is introduced; at least 1 GiB remains the design target.

## Approved future scope

`v0.001a17` is active and `v0.001a18`–`v0.001a23` remain queued. All are approved future changes, not current behavior. See the [Ordered Roadmap](../02_plans/ROADMAP.md).

## Parked outside the approved roadmap

Host-Python installation, embedded Python, signed polished installers, updater, accounts, telemetry, network-dependent normal startup, project/workspace systems, plugins, LSP, Git UI, integrated terminal, AI/cloud features, hex editing, full programming-language syntax highlighting, CJK typography specialization, and elaborate preferences remain outside the approved roadmap.

See the [Parked Capability Catalog](../04_parked/CATALOG.md) for rationale and re-evaluation triggers.
