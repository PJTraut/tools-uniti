# UNITI Current Architecture

Date: 2026-09-08
Baseline: A22 identity retained; complete reviewed feedback code candidate `3e20214`; latest hosted-green checkpoint `aab3f3c`

Display/package version: `v0.001a22` / `0.1a22`. The feedback candidate is integrated on GitHub `main`; [Current Status](STATUS.md) owns synchronization and qualification evidence.

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
    -> StartupCoordinator phases 01-13
    -> validated owned runtime and installed dependencies
    -> paths / Qt capabilities / single-instance arbitration
    -> schemas / settings / resources / cleanup / recovery / session
    -> UNITIService and zero or more UNITIMainWindow shells
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
  -> 05 GUI_CAPABILITIES
  -> 06 INSTANCE_ARBITRATION
  -> 07 SCHEMA_MIGRATIONS
  -> 08 SETTINGS_LOAD
  -> 09 RESOURCE_CALIBRATION
  -> 10 STALE_STATE_CLEANUP
  -> 11 RECOVERY_DISCOVERY
  -> 12 SESSION_RESTORE
  -> 13 READY
```

The coordinator owns ordering, phase timing, atomic state updates, safe failure translation, bounded JSONL logging, and reverse-order cleanup. Application callbacks construct services and import PySide6 only in GUI phases. Exit codes separate usage, runtime, ownership, dependencies, state/schema, functional, and Qt/platform failures.

`setup-state.json` and schema-3 settings use shared durable JSON replacement with file and parent syncing where supported. Malformed files are copied to timestamped `.invalid` siblings before replacement; settings schemas 0–2 migrate forward and future schemas fail without modification. Startup logs rotate at 5 MiB and retain ten rotations.

## Paths, capabilities, and cleanup

`AppPaths` classifies only macOS, Windows, and Linux. macOS uses Library/Application Support plus Library/Caches, Windows uses an absolute Local AppData root or the absolute home fallback, and Linux uses absolute XDG roots or explicit home fallbacks. Shared native-path normalization keeps existing-file identity authoritative while applying Windows lexical case folding only where required. Config, data, state, and cache roots derive the local runtime, setup state, logs, temporary artifacts, cache-based process sessions, durable sessions, recovery journals, instance lease/endpoint identity, and settings paths without publishing those roots in export-safe evidence. Bounded probes report runtime, memory, CPU, disk, file handles, ownership, write/fsync/atomic replace, mmap, xattrs, Qt, fonts, clipboard, input method, screens, and DPI.

All durable publication routes through one adapter reporting `full`, `file_synced`, or `unsafe`. File sync plus atomic replacement is mandatory; unavailable parent-directory sync is an explicit `file_synced` result rather than false success or data loss. An unsafe result preserves the last complete settings/setup/session/recovery/document state and never falls back to direct overwrite.

Cleanup has authority only inside UNITI temp, session, and rotated-log roots. It recognizes known prefixes or schema records, preserves live/active sessions, applies seven-day temp/session and thirty-day log thresholds, inspects at most 200 entries, and removes at most 100. Recovery journals and search spill files are outside this authority.

## Process, window, and durable-session authority

One process-lifetime `UNITIService` owns settings, the `ResourceManager`, `SessionStore`, `RecoveryManager`, one `DocumentRegistry`, one `WindowManager`, and one global Find/Replace panel. `QLockFile` and a bounded, versioned `QLocalServer` protocol permit exactly one writer for one user/application-data identity. A secondary launch forwards activation and up to 128 normalized file requests to the primary, receives bounded per-path outcomes, and exits; an unreachable live owner is an error, never permission to create a second writer.

`QApplication.setQuitOnLastWindowClosed(False)` makes windows service clients rather than process owners. The service may own zero or more `UNITIMainWindow` shells. Each shell contains a binary horizontal/vertical splitter tree whose leaves own tab groups. Every pane title row exposes Assign Document, Split Right, Split Down, and Dock/Undock. Splitting creates an independent view of the active document; assignment selects or creates a view without replacing another tab. Undocking transactionally transfers exactly one view to another service window and stores its source window/pane/tab return anchor. Docking returns it there when possible and otherwise follows bounded deterministic fallbacks. Each source path still resolves through the registry to one authoritative `Document`, while each view retains an independent cursor, anchor, preferred column, scroll positions, wrap viewport, zoom, and optional return anchor.

Ordinary window close affects its views but does not terminate the service. Closing the last editor window resolves its unsaved-document choices and leaves an empty visible window with Open and Quit available. Pending session restoration blocks ordinary window close before any live tabs are removed. Service-owned teardown can still close every window, and startup accepts legacy zero-window sessions by creating a new editor window. Explicit Quit first gathers every unique modified document, offers Save/Discard/Cancel once per document, and aborts without partial shutdown on Cancel. After all choices succeed, the service publishes the final durable session, completes the corresponding recovery transition, closes owned components, releases the local endpoint/lease, and exits.

`AppPaths.durable_session_dir` holds immutable content-addressed history packs, bounded generation manifests, and an atomically replaced current pointer; it is distinct from cache process-session records and `AppPaths.recovery_dir`. Publication writes and syncs packs before their manifest, then the manifest before the pointer. The immediately previous complete generation remains available until a later complete publication succeeds. Startup validates at most 200 complete generations, selects the newest usable numeric generation when the pointer is missing or stale, and repairs the pointer only after usable state is restored under explicit one-writer authority. Disk serialization, compression, hashing, fsync, replay, compaction, scan, and cleanup run through background tasks, never the GUI thread.

The manifest is limited to 1 MiB decoded, 32 windows, 128 pane leaves, 256 views, and 128 documents. One document pack is limited to 32 MiB encoded and decoded. Saved history keeps the newest 50 logical transactions or 32 MiB decoded per document, whichever boundary arrives first. Find and Replace retain at most 50 history states each within one shared 4 MiB decoded pack. The physical saved-session/history union is capped at 256 MiB and prunes oldest closed history, then inactive-open history, then active-document transactions while retaining current state. Compatible closed-document history expires after seven days.

Every saved history association includes SHA-256 over the exact saved bytes. File metadata is only a fast path. A mismatch offers Open Disk, Skip, or Discard; a missing path offers Locate Matching File, Skip, or Discard, and a located file must hash-match before history import. Restoration constructs bounded window/pane placeholders first, restores the active approved document first, and schedules other sealed history work lazily. No identity decision overwrites a source file.

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

`EditHistory` retains at most 50 immutable document transactions in-process and exports the newest compatible history within the 32 MiB decoded persistence bound. When the oldest transaction is evicted, its state is folded into the retained baseline so modified/save-point semantics remain correct. Typing, backspace, and delete may coalesce while contiguous; cursor movement, selection changes, save, Undo/Redo, and explicit operations break coalescing. `Document.replace_many` applies all non-overlapping original-coordinate replacements as one transaction.

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

The status bar renders encoding and EOL as one compact statement. A saved UTF-8 CRLF document displays `UTF-8, CRLF`; a pending conversion explicitly displays forms such as `UTF-8, LF (on save: UTF-8, CRLF)`. Markers continue to describe committed document content before save. After a successful save, every registered view of the shared document invalidates or replaces its EOL report, updates status, and repaints from the new authority. Editor line/column, zoom, wrap, and size remain independent status fields.

## Verified Save and Save As transaction

Every output is streamed to a sibling temporary, flushed and synced, then reread before replacement. Verification proves exact BOM presence or absence, codec/byte order, strict decoding when applicable, requested EOL policy, logical-text equality, byte length, and SHA-256. The destination is atomically replaced only after verification; destination identity is checked from UI preflight through staging and again before commit. Failure or cancellation discards the temporary and preserves destination bytes and document state.

Interactive Save and Save As run preparation, writing, syncing, and verification through `FileOperationController` and `TaskCoordinator`. Only the source tab is temporarily locked; other tabs, repainting, and task cancellation remain responsive. A verified temporary carries an identity seal so GUI-thread commit does not rehash the output, while any post-verification mutation is still refused. The synchronous document methods remain compatibility helpers rather than menu handlers.

Same-profile `PRESERVE` is the sole malformed-byte exception: unresolved annotated source spans are copied byte-for-byte. Encoding or EOL transformation is blocked until malformed spans are resolved. Strict output encoding reports an unrepresentable character and document position rather than substituting bytes.

In-place `Document.save()` advances the current tab's save point only after verified replacement and rebuilds its immutable source services. `Document.export_copy()` writes a different resolved path without changing the source tab's path, format, history, dirty state, or save point. `UNITIMainWindow` coordinates the application-owned Save As path/format dialog, normal existing-file confirmation, exact encoding-change confirmation, dirty-open-target blocking, and the second clean-open-target replacement confirmation. A successful different-path export opens a new active tab; a successful replacement of an already-open clean target reloads and reuses that tab instead of duplicating it.

## Editor presentation and command flow

`UNITITextView` continues to paint only visible document content through the custom virtual viewport. The font policy retains the concrete platform-preferred monospace primary and its pitch/Latin/Cyrillic facts, then registers 13 pinned Noto faces as application-only fallback. Han family order follows locale; plain text has no language metadata for claiming simultaneous SC/TC forms of one code point. Shared bounded Qt layouts own text, selection/match, hit-test, caret, tab, wrap, and UTF-16 geometry. User navigation and ordinary deletion follow extended-grapheme boundaries, while explicit single-code-point selection and held inspection remain exact. One shortcut policy resolves standard actions through Qt native keys, admits only valid portable persisted overrides, and reports bounded unknown/invalid/conflicting entries. The view applies clamped 50–300% font scaling and handles primary-modifier wheel zoom without transferring text ownership to Qt. Its gutter derives a separate font at 80% of the document point size, uses the common fallback-aware baseline and row envelope, and settles progressive digit-width changes before wrapped-row paint and hit testing. Global whitespace modes are Off, EOL, Spaces & Tabs, Invisible Unicode, and All. Markers are transient overlays over committed text, reuse each visible row's shaped geometry, classify logical LF/CRLF/CR through at most a two-character terminator read, and admit at most 4,096 draw operations per frame; overflow is represented by one `+N` marker. Compact special-space and zero-width marks are drawn by `whitespace_painter`; ordinary U+0020 uses one antialiased dot centered from its real layout bounds, tabs use `»`, and line endings use `␊`/`␍`/`␍␊`. Release or application deactivation clears inspection. Text, document code-point offsets, selections, clipboard contents, search, history, recovery, and saved bytes remain authoritative and unchanged by display geometry.

Public shaped windows contain at most 8,192 code points. Horizontal checkpoints accumulate actual shaped widths; unknown prefixes remain pending rather than emitting approximate caret geometry. Wrap advances read at most one 8,192-code-point window, add at most 512 rows, retain at most 512 layout/provider entries and use the existing 2,048-row block bound. Exact pixel width participates in wrap caching. Cold distant variable-width positions can require several event-loop advances, and inherited logical-line discovery may perform additional indexing outside these materialization bounds. See the [LTR text layout contract](../../../docs/ltr-text-layout.md).

IME surrounding text, selection, replacement, cursor and formatting positions convert through bounded UTF-16 maps, including supplementary characters and deletion-only commits. Preedit is a virtual shaped projection that never enters document history. When long composition would place its caret outside a narrow viewport, only the virtual row pans; painting, hit testing and query geometry share the pan, while document scroll/wrap settings remain unchanged and cancellation or commit restores ordinary geometry.

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

## Global Find/Replace dock

`ui.icons` provides palette-aware `QIcon` rendering for a pinned eleven-icon Lucide SVG subset packaged with its upstream ISC/MIT notices. Find/Replace uses these icons for Find/Replace field indicators, complete circle-x clearing, actions, cancellation, and report visibility. SVG and notice bytes are forced to LF in Git so Windows checkout conversion cannot change pinned assets. Icons render at the requested device pixel ratio and are tinted from the current palette, preserving native disabled-state opacity. No icon font, runtime download, or additional Python dependency is required.

`FindReplaceWindow` is the one service-owned `QDockWidget` over the most recently focused live `UNITITextView`, regardless of which UNITI window contains that view. Attached placement occupies the full bottom dock area and follows the active editor window. Detached placement reparents that same surface as one modeless, resizable, system-topmost tool; it remains visible when UNITI is inactive on macOS. Closing the final editor window hides the surface without terminating or duplicating it. The document remains editable while the panel is visible. Its Find and Replace inputs use explicit immutable snapshot histories capped independently at 50 states and jointly at 4 MiB persisted; focus routing sends Undo/Redo and clipboard commands to the active field before falling back to the document. Current text, cursor/selection, Undo/Redo, options, placement, detached geometry, visibility, zoom, report visibility, and the surviving target view are restored without automatically executing Find All or Replace. Each input has a Lucide circle-x control that clears only that input.

The `Regex`, `Case`, and `Whole word` checkboxes own search semantics. With Regex clear, the query is escaped and Case/Whole word apply. With Regex checked, Case and Whole word remain visible but disabled with their state preserved, while raw syntax and inline switches such as `(?i)` go to the authoritative third-party engine. The Find and Replace input editors receive equal vertical stretch and divide all space remaining above the controls. The single action row uses bundled Lucide icons for Find All, Replace All, Previous Match, Next Match, and Replace Current Match, with full tooltips and accessible names; Cancel/status remains below it. F/R zoom changes field fonts and their minimum readable height without restoring a fixed field height. Search remains cancellable and revision-bound.

Regex-mode authoring uses immutable Qt-free `RegexAnalysis` values. A cheap structural pass provides pending presentation immediately, and a 150 ms quiet interval submits engine compilation off the GUI thread. The pinned engine owns validity, group counts/names, duplicate-name and branch-reset semantics, and replacement expansion. UNITI reconciles lexical spans with those engine facts before assigning group/color identities; disagreement withholds all uncertain identity color rather than publishing a partial claim. Pattern and replacement fields share identities across opening/closing delimiters, names, and references, expose paired-span emphasis, and render structured warning/error spans plus accessible diagnostic text. Interactive expressions remain editable beyond 65,536 code points but cannot compile, search, or replace.

The capture report is the resizable right child of a horizontal `QSplitter`. One compact control uses Lucide panel-close and panel-open icons with matching Hide/Show Match Report tooltips and accessible names. The scoped `Toggle Match Report` command retains command ID `find.report_cycle` and default portable binding `Ctrl+Alt+R`; legacy Bottom settings normalize to open/right. Capture rendering remains groups `1..N` only, with delimiters between current and next matches and unchanged `Match N of M` occurrence headers. `CaptureReportModel` exposes `\\N :` labels and preview content separately while retaining readable display/accessibility text. A bounded delegate measures one shared label column per model/font revision so previews align even for multiple digits, names, and occurrence suffixes. Resolution runs off-thread against an immutable snapshot, reads at most 65,536 characters per match, retains at most five previews of at most 80 characters per group, caps one payload at 1 MiB, and emits one explicit unavailable record instead of a misleading partial group list.

Find Previous and Find Next are always available when the expression is valid: they search directly before or after the active cursor and wrap without requiring Find All. Find All separately runs against an immutable document snapshot through the shared task coordinator and installs its complete revision-bound `MatchStore` on the active editor view. Match records use compact fixed-size pages and spill to an owned temporary file after their memory budget; visible lookup stays indexed without one Qt object per match. The virtual viewport queries only intersections with each visible text window and paints every visible result with a clear theme-derived highlight. Pattern changes, edits, replacement, and document changes cancel or clear stale results.

Every analysis/search/report publication is sealed to the relevant expression generation and text; document-backed results additionally require the captured document identity/revision, result-store identity, and match index. Stale or canceled work closes its snapshots/stores/plans and never mutates visible state. Capture resolution probes one character beyond its bounded context only to distinguish an exact end from an artificial boundary; it does not measure the whole document on the bounded path.

Single Replace and Replace All return through the authoritative `Document`. Engine-emitted zero-width matches are first-class stored results: navigation advances by stored result index, rendering uses explicit insertion markers, wrapping is result-index based, and each zero-width replacement applies exactly once. Replace All builds a compact, spillable `ReplacementPlan` off the GUI thread, rejects stale or over-budget application, and rebuilds piece ranges in one monotonic pass. The admitted plan is one document transaction and one Undo operation. The UI does not use the core streaming-rewrite service for Replace All because a disk rewrite would bypass the history contract.

The `View → Theme` submenu applies System, Light, Dark, packaged Paper/Slate, or a custom profile plus independent `Standard` or `High Contrast` at application scope. Each complete profile supplies every palette, disabled, and editor role; packaged profiles are read-only. The theme editor clones and edits drafts, previews them across all service windows and Find/Replace, and provides Apply, Cancel, Reset, rename, and custom-profile deletion. One bounded schema-1 `theme-profiles.json` beside settings is the atomic authority for custom definitions and active selection; invalid data falls back without overwriting the damaged file. Verified High Contrast combinations preserve the existing 7:1 primary-text and 4.5:1 marker thresholds. Editor zoom/wrap/whitespace mode and Find/Replace zoom/placement/geometry/report visibility continue to persist independently.

## Command registry

`app.commands.CommandRegistry` is the Qt-free authority for command definitions, defaults, current shortcuts, categories, and `WINDOW`/`EDITOR`/`FIND_REPLACE` collision scopes. `UNITIMainWindow` creates shared `QAction` handlers from that registry. Editor and modeless-window dispatch use focus-aware action/shortcut forwarding, including interception of native text-control shortcuts so Find/Replace fields keep ownership.

`HotkeysPopup` is a modeless editor over the same registry. It exposes the six approved horizontal categories and Default/Current bindings, and performs assignment, clearing, collision rejection, selected/category/all resets, and portable-text persistence. Match Report visibility is represented by the single legacy-compatible `find.report_cycle` action ID. Menus and customized shortcuts therefore do not maintain competing handler paths. Editor View also exposes the persisted hold-to-inspect combination, with native modifier labels, at least two distinct modifiers or an empty disabled setting, and default/category/all resets. This modifier-only gesture is separate from command bindings.

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
| `View` | `Theme`, `Editor View`, and `F/R View` submenus for appearance/contrast, independent zoom, editor wrap/whitespace, panel attachment, and Match Report visibility. |
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

`RecoveryManager` serializes semantic v3 transactions, Undo, Redo, save-point, metadata, checkpoint, and terminal events independently from disposable background work while retaining v1/v2 readers. It validates checksummed length-bounded prefixes, preserves corrupt/truncated evidence for the Recovery Center, and begins a fresh durable binding before retiring a recovered candidate. Journals compact publish-before-retire at 64 MiB. Below the injected 512 MiB free-space reserve, nonessential saved-history writes are suppressed before recovery evidence; write/fsync failure remains visibly degraded until a successful durable flush. Resource pressure may reduce derived background work but never weakens recovery durability or save verification. Serial recovery operations submit each successor only after its predecessor completes; waiting dependencies do not occupy worker slots, including when resource pressure permits only one active worker.

## Self-check and diagnostics

`uniti.app.self_check` provides stable human and schema-1 JSON reports. Fast mode validates runtime ownership, dependencies, categorized application roots, state/settings, regex, resources, filesystem primitives, and PySide/Qt versions without exposing interpreter or application paths. Deep mode adds temporary encoding/endianness, EOL, mmap/fallback, raw-byte, regex replacement, streaming save/reopen, recovery replay, offscreen Qt/view, `regex-intelligence`, `text-integrity`, `large-file`, `recovery-session`, and `cross-platform`. The cross-platform result contains only family/version/plugin, categorized-root booleans, capability/durability, font, and launcher-mode facts. The recovery/session probe publishes and reloads a bounded session, validates exact hashes, proves external-change discovery preserves disk bytes, and replays semantic transaction/Undo/Redo state. Ordinary tests and measured scenarios cover failure injection, corruption, cancellation, integrity, and cleanup.

The application CLI's `--smoke` mode runs the core alpha probe plus a real service/session workflow below a Unicode/spaced path: pane splitting and reversible docking, one Find/Replace surface through attached/detached/follow-window placement, field Undo/Redo, global whitespace/theme settings, retained-last-window behavior, legacy zero-window/service-owned teardown, activation/new-window reuse, clean Quit, fresh-service restore, restored document/Find-Replace histories, native shortcut/font resolution, durability, and real primary/forwarded local-instance arbitration. Output contains bounded booleans and capability facts rather than document or IPC content. `QT_QPA_PLATFORM=offscreen` provides the deterministic gate; Cocoa, Windows, and XCB/Xvfb provide native lanes.

The completed startup snapshot is passed into `UNITIMainWindow`. Diagnostics combine it with the authoritative resource manager's CPU generation/core profile, current load/memory/RSS/disk state, cache budget/use, active worker limit, queue, background pause state, and active task progress. In-app diagnostics retain user-facing document paths; export-safe diagnostics omit document/task/runtime roots and startup payloads.

## Cross-platform verification boundary

The standard-library `scripts/a21_ci.py` discovers only the ownership-marked runtime, runs every phase with `shell=False`, writes bounded JSON/JUnit evidence, verifies an exact per-family skip allowlist, and sanitizes only a fixed input/output set. Parsed failure artifacts remove stdout/stderr/properties, redact workspace/home/temp/runner roots, enforce 2 MiB per-file and 8 MiB aggregate input budgets, and carry seven-day retention metadata.

The pinned read-only workflow defines exactly macOS 15/Python 3.12, Windows 2025/Python 3.12, Ubuntu 24.04/Python 3.12, and Ubuntu 24.04/newest stable Python lanes. Each begins with the public launcher and a clean owned runtime, then runs complete pytest, compile, deep self-check, offscreen smoke, native smoke, sustained checks, and skip verification. Sanitized evidence uploads only on failure. Hosted run `34253008439` passed all four lanes on checkpoint `aab3f3c`. Later runs `34253913469` and `34253932056` did not execute because GitHub reported a billing/payment or spending-limit block; this is an external evidence gap, not a passing or failing code result.

## Planned-change boundary

The complete a20 Recovery & Session Alpha, A21 Editor Layout and Visibility workstream, A21 Cross-Platform Alpha, A22 source work, and reviewed BF-001–BF-010 changes above are implemented architecture in candidate `3e20214`. The identity remains A22 because its real-use gate and the A23, A24, and B1 predecessors remain open. Physical Windows/macOS/Linux Chinese/Korean IME qualification and affected-host shutdown confirmation remain open. RTL/mixed-direction editing, multi-code-point inspection labels, extension-sensed file-type profiles, and syntax highlighting remain outside current scope.
