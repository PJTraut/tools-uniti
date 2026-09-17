# UNITI Current Scope

Date: 2026-09-17
Version: `v0.001b3` / `0.1b3`

## Product boundary

UNITI is a focused, cross-platform power text editor for Unicode correctness, explicit encoding/EOL control, bounded large-file editing, advanced third-party-regex search/replace, and a safe diagnosable desktop startup lifecycle. It is an editor rather than an IDE, project platform, plugin host, package manager, or cloud service.

The a20 Recovery & Session Alpha, a21 Editor Layout and Visibility workstream, and a21 Cross-Platform Alpha are implemented and verified. B3 Find/Replace Rework & Editor Refinement Beta is active. All reviewed BF-012–BF-068 feedback code, plus BF-040/042, is committed and integrated on GitHub `main` and is now identified as B3 under [ADR-0008](../05_decisions/ADR-0008-b3-version-and-qualification.md). Outstanding release gates remain open. The earlier `aab3f3c` remains the latest hosted-green feedback checkpoint; no hosted run exists yet for the B3 candidate.

## Included lifecycle capabilities

- standard-library bootstrap shim and validated discovery of host Python 3.12+;
- source `.venv` and explicit application-local virtual-environment modes;
- ownership marker, deterministic environment identity, partial-state retention, source adoption, local-target refusal, exclusive locks, and explicit repair;
- canonical `pyproject.toml` dependency selection, managed-Python pip invocation, import/metadata validation, `pip check`, and fingerprints;
- pre-Qt application CLI, version output, fast/deep self-check including `regex-intelligence`, `text-integrity`, and `large-file`, combined `--smoke`, human/JSON reporting, and lifecycle exit codes;
- ordered BOOT→READY startup coordination with per-phase atomic state, bounded JSONL logs, flushed first-use setup progress, quiet healthy launches, and warning-free durability cleanup;
- schema-1 setup and schema-3 settings persistence, legacy settings migration, malformed-file preservation, and future-schema refusal;
- platform application paths, runtime/filesystem/resource/Qt capability reporting, narrow stale cleanup, durable generation sessions, and recovery journals;
- explicit macOS/Windows/Linux classification, absolute native application roots, case-correct path identity, and capability-driven `full` / `file_synced` / `unsafe` publication without direct-overwrite fallback;
- one user-scoped service/instance lease with bounded local activation/file forwarding, a retained empty editor window after last-window close, and explicit service-wide Quit;
- startup recovery discovery and active-first lazy restoration of admitted windows, panes, views, saved histories, and the global Find/Replace state;
- bounded complete-generation scan and post-restore pointer repair when the current session pointer is missing or stale;
- completed startup/setup diagnostics passed into the UI without re-probing; and
- POSIX and Windows launchers that preserve Unicode/spaced/metacharacter arguments through real native shells; bounded export-safe self-check/diagnostics/smoke facts; and a pinned read-only four-lane CI definition with exact skip verification and sanitized failure-only artifacts.

## Included editor capabilities

- mmap-preferred immutable byte sources with bounded fallback reads;
- exact UTF-8, Windows-1252, UTF-16 LE/BE, and UTF-32 LE/BE profiles, with BOM/no-BOM as part of the profile;
- bounded confidence/evidence inspection, serious exact-profile confirmation, explicit reinterpretation versus convert-on-save, and annotated malformed-byte preservation;
- separate CR, LF, CRLF, mixed-EOL analysis/reporting, source-aware insertion, modeless mixed-EOL choices, explicit output conversion, truthful current/on-save wording, and post-save refresh across all shared views;
- compact progressive byte/character and line indexes with bounded detail caches and no whole-file opening decode;
- hybrid source/edit piece table, selections, atomic transactions, and a document Undo/Redo history persisted to the first of 50 transactions or 32 MiB decoded;
- coalesced typing/backspace/delete plus Unicode-aware word, page, document, line, and Shift-extended navigation;
- Cut, Copy, Paste, Select All, Go to Line, and protected Reload/Revert;
- word, visual-line, and logical-line-through-break selection by double, triple, and quadruple click;
- platform-monospace-primary rendering with 13 application-bundled Noto fallback faces covering representative Latin/Cyrillic, nine Indic scripts, Simplified/Traditional Chinese, and Korean glyphs; locale-ordered Han fallback; independent editor zoom; and no OS font installation or runtime download;
- bounded Qt-shaped LTR windows for text/selection/match geometry, hit testing, caret, tabs and wrapping; extended-grapheme navigation/deletion; UTF-16-aware IME queries/replacements; exact code-point inspection; preedit row panning; 80% line-number typography on the shared baseline; bounded giant-line windows; and progressive display-only soft wrap;
- staged, flushed, verified, and atomic Save/Save As with exact BOM/byte-order/EOL/logical-text checks, external-file identity, and supported metadata protection;
- application-owned Save As filename/encoding/EOL selection, exact encoding-change warnings, normal/double overwrite confirmation, dirty-open-target blocking, copy/export source-state preservation, and duplicate-tab avoidance;
- semantic recovery-journal v3 transactions, Undo/Redo, save points, metadata, checkpoints, prefix-safe discovery, v1/v2 compatibility, and validated replay without changing the original file;
- authoritative `regex==2026.5.9`, immutable pattern/replacement analysis, engine-reconciled group identities, inline-switch and reference highlighting, structured diagnostics, and a 65,536-code-point interactive expression bound;
- snapshot-based cancellable search, compact spillable revision-bound match storage, deterministic zero-width navigation/rendering/replacement, spillable replacement plans, safe apply admission, and one-transaction replacement;
- one service-owned Find/Replace surface that is either a full-width bottom dock following the active window or one modeless topmost detached tool, with Regex/Case/Whole-word checkboxes, complete Lucide field/action controls, persisted field state and Undo/Redo, 150 ms off-thread latest-generation analysis, cursor-relative Previous/Next that do not require Find All, clear visible-only result highlighting, and a toggleable right-docked Match Report with bounded asynchronous current/next capture reports and aligned `\\N :` label/content columns;
- one-step undoable Replace All with no disk-rewrite history bypass;
- held Unicode inspection through a bounded visible-marker key and single-selected-code-point readout, with a persisted modifier combination in Hotkeys → Editor View;
- a scoped shared command registry and persisted Hotkeys popup for window, editor, and Find/Replace commands;
- a compact `File | Edit | Format | View | Find | Tools | Hotkeys` menu bar with application-wide System/Light/Dark/Paper/Slate and custom theme profiles, editable complete color roles, independent Standard/High Contrast, native shortcut display, and no duplicate pre-Cot top-level command groupings;
- PySide6 multi-window shells, binary horizontal/vertical split panes, per-pane assign/split/dock controls, reversible view transfers with persisted return anchors, detachable tabs, independent synchronized views of one authoritative document, custom virtual viewport, clipboard, IME, menus, compact status, inspections, diagnostics, and one Recovery Center;
- display-only Off, EOL, Spaces & Tabs, Invisible Unicode, and All whitespace modes with distinct special-space/zero-width symbols and LF `␊`, CR `␍`, CRLF `␍␊` markers, bounded terminator reads, and at most 4,096 marker operations per frame including visible overflow aggregation;
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
33. Exactly one service owns documents, settings, sessions, recovery, windows, and one global Find/Replace panel for one application-data identity.
34. Closing the final editor window does not terminate the service; explicit Quit resolves Save/Discard/Cancel once per unique modified document before shutdown.
35. Every view owns its cursor, selection, scroll, wrap viewport, and zoom while every view of one source shares one authoritative document and history.
36. Durable session publication writes/syncs bounded packs before the manifest and the manifest before the current pointer; the previous complete generation remains available through successful replacement.
37. Saved history is SHA-256-authorized, retained for seven days subject to a 256 MiB aggregate cap, and never permits an automatic overwrite after an external change.
38. Find and Replace histories retain at most 50 states each and together at most 4 MiB decoded; their current values are preserved when older states are pruned.
39. Recovery journals are not disposable history: 64 MiB journals compact publish-before-retire, and the 512 MiB free-space reserve suppresses convenience-history writes before recovery evidence.
40. Low-space tests inject capacity and write failures; they never consume real filesystem space to manufacture LOWDISK.
41. Dock/undock transfers one view transactionally and preserves its source return anchor without moving or cloning document/history authority.
42. Exactly one service-owned Find/Replace surface exists through attached and detached placement changes.
43. Whitespace visualization consumes only committed visible text, never changes document coordinates or bytes, and admits no more than 4,096 marker draws per frame.
44. Theme appearance and contrast are independent global settings; complete theme specifications own both application palettes and editor overlay tokens.

## Approved future scope

`v0.001a21` is implemented and retained in the historical records. `v0.001b3` is the active source beta; the unfinished A22 real-use, A23 Executable Health & Recovery, A24 Beta Candidate, and B1 Real-World Feedback requirements remain open release qualification, alongside B2's own still-open native/hosted evidence for BF-001–BF-010. BF-006 implementation is present in candidate `3e20214`; physical Windows/macOS/Linux Chinese/Korean IME qualification remains open. See the [LTR text layout contract](../../../docs/ltr-text-layout.md) and [Ordered Roadmap](../02_plans/ROADMAP.md).

## Parked outside the approved roadmap

Host-Python installation, signed polished installers, notarization, updater, network repair, accounts, cloud telemetry, network-dependent normal startup, project/workspace systems, plugins, LSP, Git UI, integrated terminal, AI/cloud features, hex editing, and full programming-language syntax highlighting remain outside the approved roadmap. Embedded native application bundles and local executable health/repair are approved future A23 scope but are not implemented behavior. Content-level right-to-left/bidi editing (Arabic + Hebrew; BF-064), per-character Unicode-property inspection over a multi-character selection (BF-065), and per-category syntax color editing (BF-063, [ADR-0011](../05_decisions/ADR-0011-syntax-category-color-editing.md)) are now implemented — see [Current Handover](../06_handovers/CURRENT_HANDOVER.md); native IME qualification remains open, and the application's own chrome intentionally stays left-to-right.

See the [Parked Capability Catalog](../04_parked/CATALOG.md) for rationale and re-evaluation triggers.
