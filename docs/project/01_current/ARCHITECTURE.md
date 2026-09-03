# UNITI Current Architecture

Date: 2026-09-03
Baseline: verified a19 implementation through `06d644d` plus the a19 freeze tree on local `main`

## Lifecycle boundary

UNITI now has two deliberately separate execution paths:

```text
explicit bootstrap
host Python 3.12+
    -> scripts/bootstrap.py compatibility shim
    -> uniti.bootstrap discovery / ownership / dependencies
    -> source .venv or application-local venv
    -> managed Python -m uniti

ordinary application startup
application CLI parsed before Qt
    -> StartupCoordinator phases 01-12
    -> validated owned runtime and installed dependencies
    -> paths / schemas / settings / resources / cleanup / recovery
    -> lazy Qt capabilities and UNITIMainWindow
```

Only explicit bootstrap may create or repair a runtime and invoke `<managed-python> -m pip`. Ordinary `uniti` startup does not invoke pip, install packages, access the network, or mutate dependencies.

## Managed runtime ownership

`uniti.bootstrap.environment.EnvironmentManager` is the sole owner of virtual-environment mutation. Source mode uses exactly `<source-root>/.venv`; local mode uses `AppPaths.local_runtime_dir`. A schema-1 `.uniti-runtime.json` marker records owner, deterministic environment ID, mode, resolved path, source provenance, host/runtime identities, timestamps, dependency fingerprint, and health.

A missing target receives an unhealthy marker before `venv.EnvBuilder(clear=False)` runs. Partial environments therefore remain explicit and repairable. Existing source `.venv` directories may be adopted only after interpreter/venv validation. Existing unmarked local targets and every owner/mode/ID/path mismatch are refused. Exclusive lock files reject live concurrent bootstrap and preserve stale lock evidence.

`uniti.bootstrap.dependencies` reads canonical declarations from `pyproject.toml`, installs source mode editable and local mode non-editable, validates UNITI/`regex`/PySide6 metadata and imports, runs managed `pip check`, and records a deterministic fingerprint. A healthy matching runtime uses a validation-only fast path unless `--repair` is supplied.

## Startup state machine

`uniti.app.startup.StartupCoordinator` owns this strict order:

```text
BOOT
  -> 01 RUNTIME_IDENTITY
  -> 02 ENVIRONMENT_VALIDATION
  -> 03 DEPENDENCY_VALIDATION
  -> 04 APPLICATION_PATHS
  -> 05 SCHEMA_MIGRATIONS
  -> 06 SETTINGS_LOAD
  -> 07 RESOURCE_CALIBRATION
  -> 08 STALE_STATE_CLEANUP
  -> 09 RECOVERY_DISCOVERY
  -> 10 GUI_CAPABILITIES
  -> 11 SESSION_RESTORE
  -> 12 READY
```

The coordinator owns ordering, phase timing, atomic state updates, safe failure translation, bounded JSONL logging, and reverse-order cleanup. Application callbacks construct services and import PySide6 only in GUI phases. Exit codes separate usage, runtime, ownership, dependencies, state/schema, functional, and Qt/platform failures.

`setup-state.json` and schema-1 settings use shared durable JSON replacement with file and parent syncing where supported. Malformed files are copied to timestamped `.invalid` siblings before replacement; future schemas fail without modification. Startup logs rotate at 5 MiB and retain ten rotations.

## Paths, capabilities, and cleanup

`AppPaths` distinguishes config, data, state, and cache roots and derives the local runtime, setup state, logs, temp artifacts, sessions, recovery journals, and settings paths. Bounded probes report runtime, memory, CPU, disk, file handles, ownership, write/fsync/atomic replace, mmap, xattrs, Qt, fonts, clipboard, input method, screens, and DPI.

Cleanup has authority only inside UNITI temp, session, and rotated-log roots. It recognizes known prefixes or schema records, preserves live/active sessions, applies seven-day temp/session and thirty-day log thresholds, inspects at most 200 entries, and removes at most 100. Recovery journals and search spill files are outside this authority.

## Document ownership model

The lifecycle wraps rather than replaces the established editor engine:

```text
QApplication / UNITIMainWindow
    -> UNITITextView (custom QAbstractScrollArea)
    -> EditorState
    -> Document
    -> PieceTable + DocumentLineIndex + History
    -> EditStore + immutable SourcePiece ranges
    -> OffsetMapper + decoder
    -> ByteSource (mmap preferred, bounded fallback)
```

`src/uniti/core` and `src/uniti/regex` remain Qt-free. Qt owns presentation and input only; it never becomes the document store.

`EditHistory` retains at most 50 immutable document transactions. When the oldest transaction is evicted, its state is folded into the retained baseline so modified/save-point semantics remain correct. Typing, backspace, and delete may coalesce while contiguous; cursor movement, selection changes, save, Undo/Redo, and explicit operations break coalescing. `Document.replace_many` applies all non-overlapping original-coordinate replacements as one transaction.

`Document.snapshot()` captures one immutable revision and a forked source handle for background work. Index, navigation, EOL, search, replacement-plan, and save results publish only while their document revision and destination identity remain current. A stale result is discarded; it never replaces newer text or format state.

## Resource and task authority

`uniti.resources.ResourceManager` is the sole application authority for host profile, live resource state, disposable cache, worker capacity, admission, background pause, and observable task state. It uses the packaged schema-1 [`performance_policy.toml`](../../../src/uniti/resources/performance_policy.toml) rather than duplicating thresholds in UI or benchmark code.

```text
read-only host profile + one-second live samples
    -> ResourceManager
       -> ResourceState: Normal | Busy | Constrained | Critical
       -> CacheManager byte budget and priority eviction
       -> PriorityWorkerPool active worker limit
       -> TaskCoordinator admission / priority / cancellation / progress
    -> TaskBridge queued Qt snapshots
       -> status text, task progress, diagnostics, nonmodal pressure notice
```

Normal hosts use up to eight workers while reserving one logical core for the GUI. Busy and constrained states reduce worker/cache capacity; critical state clears disposable cache and admits only one worker. Recovery requires two healthier samples to prevent oscillation. `Pause Background Work` defers index, EOL, and prefetch tasks but never foreground Save, navigation, search, replacement, or recovery work.

`TaskCoordinator` snapshots carry a monotonically increasing generation. Listener callbacks and Qt signals are wake-ups without state payloads; GUI consumers reread the authoritative latest snapshot and ignore an already-applied generation. Latest-request slots for regex analysis and capture resolution serialize work per Find/Replace window, retain only the newest pending generation, and dispose superseded request resources.

Cache entries carry explicit intent—visible, nearby, search, index, recent, inactive, or stale—and are byte-accounted. Closing a document evicts only its disposable entries. User text, edit history, recovery state, and unsaved changes are never disposable cache.

## Text-format authority and inspection

`core.text_format` owns the exact input/output grammar. Encoding profiles are indivisible values: `UTF-8`, `UTF-8 BOM`, `Windows-1252`, UTF-16 LE/BE with and without BOM, and UTF-32 LE/BE with and without BOM. Omission of `BOM` always means no BOM. Line endings are a separate `PRESERVE | LF | CRLF | CR` policy, never a hidden property of an encoding choice.

`core.text_inspection` performs bounded preview decoding and a bounded initial EOL sample before a tab is constructed. Its `EncodingAssessment` and `EOLReport` remain separate because uncertain or contradictory encoding evidence is serious, while mixed line endings are usually remediable. Confidence below `0.75`, contradictory BOM evidence, or malformed preview bytes requires an exact-profile modal. After Open becomes usable, full streaming EOL analysis runs through `TaskCoordinator` against a snapshot and publishes only for the current revision. Mixed EOL opens a separate modeless report and never normalizes automatically.

`Document` remains authoritative for `source_profile`, `saved_output_format`, `output_format`, source EOL evidence, dirty state, and history. Reinterpretation reopens immutable source bytes under another exact profile and is blocked while the document is dirty. A pending codec, byte-order, BOM, or EOL change is metadata-dirty even before the logical text changes.

The status bar renders encoding and EOL as one compact statement. A saved UTF-8 CRLF document displays `UTF-8, CRLF`; a pending conversion displays `UTF-8, CRLF -> UTF-16 LE BOM, LF`. Editor line/column, zoom, wrap, and size remain independent status fields.

## Verified Save and Save As transaction

Every output is streamed to a sibling temporary, flushed and synced, then reread before replacement. Verification proves exact BOM presence or absence, codec/byte order, strict decoding when applicable, requested EOL policy, logical-text equality, byte length, and SHA-256. The destination is atomically replaced only after verification; destination identity is checked from UI preflight through staging and again before commit. Failure or cancellation discards the temporary and preserves destination bytes and document state.

Interactive Save and Save As run preparation, writing, syncing, and verification through `FileOperationController` and `TaskCoordinator`. Only the source tab is temporarily locked; other tabs, repainting, and task cancellation remain responsive. A verified temporary carries an identity seal so GUI-thread commit does not rehash the output, while any post-verification mutation is still refused. The synchronous document methods remain compatibility helpers rather than menu handlers.

Same-profile `PRESERVE` is the sole malformed-byte exception: unresolved annotated source spans are copied byte-for-byte. Encoding or EOL transformation is blocked until malformed spans are resolved. Strict output encoding reports an unrepresentable character and document position rather than substituting bytes.

In-place `Document.save()` advances the current tab's save point only after verified replacement and rebuilds its immutable source services. `Document.export_copy()` writes a different resolved path without changing the source tab's path, format, history, dirty state, or save point. `UNITIMainWindow` coordinates the application-owned Save As path/format dialog, normal existing-file confirmation, exact encoding-change confirmation, dirty-open-target blocking, and the second clean-open-target replacement confirmation. A successful different-path export opens a new active tab; a successful replacement of an already-open clean target reloads and reuses that tab instead of duplicating it.

## Editor presentation and command flow

`UNITITextView` continues to paint only visible document content through the custom virtual viewport. It selects a concrete fixed-pitch font with Western/Latin and Cyrillic coverage, applies clamped 50–300% font scaling, and handles primary-modifier wheel zoom without transferring text ownership to Qt.

Soft wrap is display-only and defaults off. `ui.wrap_index.WrappedRowIndex` incrementally maps logical lines to visual rows at the current viewport width, retains sparse checkpoints plus at most four 512-row detail blocks, and never constructs a whole-document Qt layout. Wrap therefore does not insert EOLs or change document coordinates. Unwrapped giant lines render bounded horizontal text windows rather than materializing the full line.

Input flows through `EditorState` for insertion/deletion, clipboard operations, selection, Unicode-category word movement, page movement, document start/end, and line navigation. `UNITITextView` interprets double-click as word selection, triple-click as visual-line selection, and quadruple-click as logical-line selection through the terminating line break. Reload/Revert asks before discarding modifications, reopens through `Document.open`, and installs a fresh history. The status bar receives cursor, exact saved/pending format, size, editor zoom, and `Wrap`/`No Wrap` state from the active view.

## Desktop UI reference principles

UNITI uses CotEditor as a menu, navigation, and shortcut-presentation reference without copying its product scope or Cocoa text-storage architecture. The applicable principles are:

1. follow native desktop conventions so the application behaves predictably on its host platform;
2. keep common editing approachable while retaining precise power-user controls;
3. prefer a small, coherent surface over accumulating top-level menus and options;
4. prioritize accurate, predictable plain-text behavior over novelty;
5. keep command names, menu placement, focus behavior, and shortcut display consistent; and
6. preserve accessibility, localization, and keyboard operation as first-class UI constraints.

These principles are derived from CotEditor's published [design philosophy](https://github.com/coteditor/CotEditor#design-philosophy) and concrete [main-menu definition](https://github.com/coteditor/CotEditor/blob/main/CotEditor/Storyboards/Base.lproj/Main.storyboard). They are reference constraints, not an external dependency and not authority over UNITI's document, regex, resource, or cross-platform boundaries.

## Floating Find/Replace

`FindReplaceWindow` is a modeless, mouse-resizable Qt tool window over the active `UNITITextView`. A native size grip supplements edge resizing. The document remains editable while the window is visible. Its Find and Replace inputs use explicit immutable snapshot histories capped independently at 50 steps; focus routing sends Undo/Redo and clipboard commands to the active field before falling back to the document.

An explicit `Literal | Regex` selector owns search semantics. Literal mode escapes the query and alone displays Case Sensitive and Whole Word options. Regex mode hides those controls and sends raw syntax and inline switches such as `(?i)` to the authoritative third-party engine. The Find and Replace input editors receive equal vertical stretch and divide all space remaining above the controls. Mode/report options, Find All/Replace All, Previous/Next/Replace, and Cancel/status form one compact stack anchored to the bottom of the controls frame. F/R zoom changes field fonts and their minimum readable height without restoring a fixed field height. Search remains cancellable and revision-bound.

Regex-mode authoring uses immutable Qt-free `RegexAnalysis` values. A cheap structural pass provides pending presentation immediately, and a 150 ms quiet interval submits engine compilation off the GUI thread. The pinned engine owns validity, group counts/names, duplicate-name and branch-reset semantics, and replacement expansion. UNITI reconciles lexical spans with those engine facts before assigning group/color identities; disagreement withholds all uncertain identity color rather than publishing a partial claim. Pattern and replacement fields share identities across opening/closing delimiters, names, and references, expose paired-span emphasis, and render structured warning/error spans plus accessible diagnostic text. Interactive expressions remain editable beyond 65,536 code points but cannot compile, search, or replace.

The capture report is the collapsible second child of an unrestricted `QSplitter`, so it can be resized to any useful Bottom or Right proportion or dragged closed. `Report: Hidden | Bottom | Right` remains the explicit selector. The scoped `Cycle Report Position` command rotates those locations with default portable binding `Ctrl+Alt+R`. Capture rendering remains groups `1..N` only, with delimiters between current and next matches. It is backed by `CaptureReportModel`, not one widget per row. Resolution runs off-thread against an immutable snapshot, reads at most 65,536 characters per match, retains at most five previews of at most 80 characters per group, caps one payload at 1 MiB, and emits one explicit unavailable record instead of a misleading partial group list.

Find All runs against an immutable document snapshot through the shared task coordinator and installs its complete revision-bound `MatchStore` on the active editor view. Match records use compact fixed-size pages and spill to an owned temporary file after their memory budget; visible lookup stays indexed without one Qt object per match. The virtual viewport queries only intersections with each visible text window and paints every visible result with a clear theme-derived highlight. Pattern changes, edits, replacement, and document changes cancel or clear stale results.

Every analysis/search/report publication is sealed to the relevant expression generation and text; document-backed results additionally require the captured document identity/revision, result-store identity, and match index. Stale or canceled work closes its snapshots/stores/plans and never mutates visible state. Capture resolution probes one character beyond its bounded context only to distinguish an exact end from an artificial boundary; it does not measure the whole document on the bounded path.

Single Replace and Replace All return through the authoritative `Document`. Engine-emitted zero-width matches are first-class stored results: navigation advances by stored result index, rendering uses explicit insertion markers, wrapping is result-index based, and each zero-width replacement applies exactly once. Replace All builds a compact, spillable `ReplacementPlan` off the GUI thread, rejects stale or over-budget application, and rebuilds piece ranges in one monotonic pass. The admitted plan is one document transaction and one Undo operation. The UI does not use the core streaming-rewrite service for Replace All because a disk rewrite would bypass the history contract.

Editor zoom/wrap and Find/Replace zoom/geometry/report placement persist independently through `SettingsStore`.

## Command registry

`app.commands.CommandRegistry` is the Qt-free authority for command definitions, defaults, current shortcuts, categories, and `WINDOW`/`EDITOR`/`FIND_REPLACE` collision scopes. `UNITIMainWindow` creates shared `QAction` handlers from that registry. Editor and modeless-window dispatch use focus-aware action/shortcut forwarding, including interception of native text-control shortcuts so Find/Replace fields keep ownership.

`HotkeysPopup` is a modeless editor over the same registry. It exposes the six approved horizontal categories and Default/Current bindings, and performs assignment, clearing, collision rejection, selected/category/all resets, and portable-text persistence. The three former report-location commands are represented by the single `find.report_cycle` action. Menus and customized shortcuts therefore do not maintain competing handler paths.

### Compact menu definition

UNITI's application-owned menu bar is consolidated to:

```text
File | Edit | Format | View | Find | Tools | Hotkeys
```

| Menu | Command ownership |
|---|---|
| `File` | Open, Save, Save As, Reload/Revert, Close, and Quit. |
| `Edit` | Undo/Redo, Cut/Copy/Paste, Select All, plus a `Navigation` submenu for Go to Line, page, document, and word movement. |
| `Format` | `Encoding` and `Line Endings` submenus; reinterpretation remains distinct from convert-on-save. |
| `View` | `Editor View` and `F/R View` submenus for independent zoom, editor wrap, and F/R report placement. |
| `Find` | Open Find/Replace, Find Next, and Find Previous. |
| `Tools` | Character Inspector and Diagnostics. |
| `Hotkeys` | Open the shortcut display/editor; do not duplicate the full command tree in a menu. |

The Hotkeys display retains the horizontal categories `File | Editing | Navigation | Find/Replace | Editor View | F/R View` and the columns `Command | Default | Current`. It renders native platform shortcut notation for display while persisting portable bindings. Every ordinary menu item displays the current binding from the same registry.

Keyboard Zoom In/Out/Reset and primary-modifier mouse-wheel zoom are focus-owned: the editor changes only editor zoom, while any control inside the floating F/R window changes only F/R zoom. The two persisted zoom values remain independent.

The pre-Cot top-level Navigation, Search, F/R View, Encoding, and EOL groupings no longer exist. Menu reachability, live native shortcut display, focus-scoped keyboard zoom, and focus-scoped wheel zoom are covered by the a16 UI contract tests.

## Progressive indexing and navigation

`OffsetMapper` retains sparse byte/character checkpoints and uses linear boundaries for fixed-width decoded spans or compact `array('I')` boundaries only where Unicode decoding requires them. Visible/nearby reads may cache a few spans; `ReadIntent.STREAMING` advances checkpoints without populating reusable span cache.

`DocumentLineIndex` stores compact per-chunk summaries and only a bounded LRU of local line-start details. Background index jobs publish revision-bound batches. Nearby movement stays direct; far Go to Line and document-end movement are submitted as cancellable navigation tasks so the GUI interaction returns immediately and the cursor moves only when the matching revision completes.

## Search, save, recovery, and resources

Third-party `regex==2026.5.9` remains authoritative. Search is cancellable, timeout-aware, revision-bound, compactly stored, and delivered to Qt through queued signals. Core streaming replacement remains available for future bounded large-file work but is not a UI Replace All path. Save uses the verified transaction above and remains streaming, atomic, metadata-aware where supported, and protected against external file replacement.

`RecoveryManager` serializes journal durability independently from disposable background work. Resource pressure may reduce derived background work but never weakens recovery durability or save verification.

## Self-check and diagnostics

`uniti.app.self_check` provides stable human and schema-1 JSON reports. Fast mode validates runtime ownership, dependencies, paths, state/settings, regex, resources, filesystem primitives, and PySide/Qt versions. Deep mode adds temporary encoding/endianness, EOL, mmap/fallback, raw-byte, regex replacement, streaming save/reopen, recovery replay, offscreen Qt/view, `regex-intelligence`, `text-integrity`, and `large-file`. The regex-intelligence check covers advanced engine metadata, bounded reports, zero-width search/replacement, and Undo; ordinary tests and measured scenarios separately cover structured diagnostics, cancellation, integrity, and cleanup. The large-file check verifies lazy access to a marker beyond 1 GiB, cache-free streaming intent, task cancellation, and artifact cleanup without embedding the 100 MiB benchmark suite.

The application CLI's `--smoke` mode runs the core alpha probe and a self-closing real `UNITIMainWindow` on the selected Qt platform. `QT_QPA_PLATFORM=offscreen` provides the automated platform gate; an unmodified macOS environment exercises native Cocoa separately.

The completed startup snapshot is passed into `UNITIMainWindow`. Diagnostics combine it with the authoritative resource manager's CPU generation/core profile, current load/memory/RSS/disk state, cache budget/use, active worker limit, queue, background pause state, and active task progress.

## Planned-change boundary

The complete a19 Regex Intelligence Alpha is implemented and verified current architecture. Its milestone, approved design, and execution record are retained in [`03_implemented`](../03_implemented/README.md). `v0.001a20` Recovery & Session Alpha is now the sole active milestone; a20 and queued a21+ behavior remain planned intent and are not current architecture. Editor whitespace visualization, expanded keyboard-driven Unicode inspection, extension-sensed file-type profiles, and syntax highlighting remain parked outside the approved roadmap.
