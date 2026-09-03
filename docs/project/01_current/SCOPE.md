# UNITI Current Scope

Date: 2026-09-03
Version: `v0.001a19` / `0.1a19`

## Product boundary

UNITI is a focused, cross-platform power text editor for Unicode correctness, explicit encoding/EOL control, bounded large-file editing, advanced third-party-regex search/replace, and a safe diagnosable desktop startup lifecycle. It is an editor rather than an IDE, project platform, plugin host, package manager, or cloud service.

The a19 Regex Intelligence Alpha is implemented and verified. UNITI combines a18's bounded large-file behavior and a17's exact text-integrity rules with engine-validated regex authoring, deterministic zero-width behavior, and bounded asynchronous capture reports. a20 Recovery & Session Alpha is the active planned milestone.

## Included lifecycle capabilities

- standard-library bootstrap shim and validated discovery of host Python 3.12+;
- source `.venv` and explicit application-local virtual-environment modes;
- ownership marker, deterministic environment identity, partial-state retention, source adoption, local-target refusal, exclusive locks, and explicit repair;
- canonical `pyproject.toml` dependency selection, managed-Python pip invocation, import/metadata validation, `pip check`, and fingerprints;
- pre-Qt application CLI, version output, fast/deep self-check including `regex-intelligence`, `text-integrity`, and `large-file`, combined `--smoke`, human/JSON reporting, and lifecycle exit codes;
- ordered BOOT→READY startup coordination with per-phase atomic state and bounded JSONL logs;
- schema-1 setup/settings persistence, legacy settings migration, malformed-file preservation, and future-schema refusal;
- platform application paths, runtime/filesystem/resource/Qt capability reporting, narrow stale cleanup, and per-process session records;
- completed startup/setup diagnostics passed into the UI without re-probing; and
- root macOS and Windows launchers that enter the same bootstrap/application path.

## Included editor capabilities

- mmap-preferred immutable byte sources with bounded fallback reads;
- exact UTF-8, Windows-1252, UTF-16 LE/BE, and UTF-32 LE/BE profiles, with BOM/no-BOM as part of the profile;
- bounded confidence/evidence inspection, serious exact-profile confirmation, explicit reinterpretation versus convert-on-save, and annotated malformed-byte preservation;
- separate CR, LF, CRLF, mixed-EOL analysis/reporting, source-aware insertion, modeless mixed-EOL choices, and explicit output conversion;
- compact progressive byte/character and line indexes with bounded detail caches and no whole-file opening decode;
- hybrid source/edit piece table, selections, atomic transactions, and a 50-transaction document Undo/Redo history;
- coalesced typing/backspace/delete plus Unicode-aware word, page, document, line, and Shift-extended navigation;
- Cut, Copy, Paste, Select All, Go to Line, and protected Reload/Revert;
- word, visual-line, and logical-line-through-break selection by double, triple, and quadruple click;
- fixed-pitch Western/Latin and Cyrillic rendering, independent editor zoom, primary-modifier wheel zoom, bounded giant-line windows, and progressive display-only soft wrap with sparse checkpoints and bounded row blocks;
- staged, flushed, verified, and atomic Save/Save As with exact BOM/byte-order/EOL/logical-text checks, external-file identity, and supported metadata protection;
- application-owned Save As filename/encoding/EOL selection, exact encoding-change warnings, normal/double overwrite confirmation, dirty-open-target blocking, copy/export source-state preservation, and duplicate-tab avoidance;
- asynchronous crash-recovery journals and validated replay;
- authoritative `regex==2026.5.9`, immutable pattern/replacement analysis, engine-reconciled group identities, inline-switch and reference highlighting, structured diagnostics, and a 65,536-code-point interactive expression bound;
- snapshot-based cancellable search, compact spillable revision-bound match storage, deterministic zero-width navigation/rendering/replacement, spillable replacement plans, safe apply admission, and one-transaction replacement;
- mouse-resizable system-topmost Find/Replace with Regex/Case/Whole-word checkboxes, per-field clear controls, 150 ms off-thread latest-generation analysis, equal-height inputs above one compact `F+ | R+ … << | >> | R` action row, clear visible-only result highlighting, a toggleable right-docked Match Report, bounded asynchronous current/next capture-only reports, independent zoom/geometry/report state, and separate 50-step field histories;
- one-step undoable Replace All with no disk-rewrite history bypass;
- a scoped shared command registry and persisted Hotkeys popup for window, editor, and Find/Replace commands;
- a compact `File | Edit | Format | View | Find | Tools | Hotkeys` menu bar with persisted application-wide System/Light/Dark themes, native shortcut display, and no duplicate pre-Cot top-level command groupings;
- PySide6 tabs, custom virtual viewport, clipboard, IME, menus, compact saved/pending format plus zoom/wrap/resource/task status, inspections, diagnostics, and recovery surfaces;
- progressive Open, background full EOL analysis, cancellable far navigation, Find All, Replace All planning, and verified Save/Save As without GUI-thread long work;
- source-tab-only locking during output, cancellation cleanup, immutable revision/identity snapshots, and stale-result refusal;
- read-only CPU generation/core/RAM/disk/load profiling, live Normal/Busy/Constrained/Critical resource state, adaptive worker/cache limits, coalesced nonmodal pressure indication, and a user-controlled background-work pause that does not pause Save; and
- deterministic isolated quick/routine/design-target performance suites with adjustable central gates, regex-intelligence/integrity/cleanup facts, selected JSON baselines, and native Cocoa coverage.

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
19. Codec, byte order, and BOM presence form one exact encoding profile; omission of BOM means no BOM.
20. Encoding uncertainty/malformed evidence and line-ending remediation remain separate decisions.
21. Every committed output is verified before atomic replacement; a failed transaction changes neither destination bytes nor document state.
22. Save is in-place; Save As to another resolved path exports without retargeting the source tab and opens or reloads exactly one target tab.
23. Same-profile `PRESERVE` is the only unresolved-malformed-byte save path; transformations remain blocked.
24. Long work consumes immutable snapshots and may publish only for its captured document revision and file identity.
25. ResourceManager is the sole worker, task, cache, and live-pressure authority; authoritative state is never disposable cache.
26. Sequential scans use streaming intent and must not populate reusable decoded-span cache.
27. Visible rendering, wrapped-row detail, line detail, match storage, and replacement planning remain explicitly bounded or spillable.
28. Interactive Open, far navigation, search, replacement planning, Save, and Save As preserve GUI responsiveness and cancellability according to the packaged performance policy.
29. Cross-thread task notifications are wake-ups; consumers apply only the coordinator's newest monotonically generated snapshot.
30. Regex analysis and capture reports publish only for the current expression generation, document identity/revision, result-store identity, and requested match index.
31. A capture report reads at most 65,536 characters per match, retains at most five 80-character previews per group, and caps its payload at 1 MiB.
32. Each engine-emitted zero-width result is stored, navigated, rendered, and replaced exactly once.

## Approved future scope

`v0.001a20` is active and `v0.001a21`–`v0.001a23` remain queued. All are approved future changes, not current behavior. See the [Ordered Roadmap](../02_plans/ROADMAP.md).

## Parked outside the approved roadmap

Editor whitespace visualization and expanded keyboard-driven Unicode inspection, Host-Python installation, embedded Python, signed polished installers, updater, accounts, telemetry, network-dependent normal startup, project/workspace systems, plugins, LSP, Git UI, integrated terminal, AI/cloud features, hex editing, full programming-language syntax highlighting, CJK typography specialization, and elaborate preferences remain outside the approved roadmap.

See the [Parked Capability Catalog](../04_parked/CATALOG.md) for rationale and re-evaluation triggers.
