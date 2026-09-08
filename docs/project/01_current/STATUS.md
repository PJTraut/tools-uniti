# UNITI Current Status

Date: 2026-09-08

## Canonical baseline

| Item | Current value |
|---|---|
| Starting documentation checkpoint | Isolated `work/b2-feedback` at `5724f6cb3081d30b2962ecaefb623be2358331b8`; local `main` pointed to the same commit when Task 1 began |
| Initial remote ancestry | The first read-only check found `origin/main` at `ca759668ea08f6a254ca6c516c04f39c85bf6a0e`; local `main` was seven commits ahead and zero behind |
| Complete feedback code candidate | `3e20214`; contains reviewed BF-001–BF-010 implementation, including the native System-preview and wrapped-row-seam IME corrections |
| Latest hosted-green feedback checkpoint | `aab3f3c`; run `34253008439` passed all four lanes, including full suite, deep self-check, native/offscreen smoke, and sustained checks |
| Current hosted constraint | Runs `34253913469` and `34253932056` did not execute because GitHub reported an account billing/payment or spending-limit block; no result exists for their commits |
| Verified A20 implementation sequence | `fabd036` through `f829d01`, preceded by design/plan commits `c9cd792` and `06dd906`, followed by the A20 freeze closure |
| Verified A21 Editor Layout and Visibility sequence | `23d6c2d` through `dcf04c6`, plus schema-reporting repair `fcfd5ea`; preceded by design/plan commits `9477197` and `61c1f19` |
| A21 Cross-Platform candidate/remediation sequence | `09ad62b` through `8b24f4b`; preceded by plan commit `a3a4d81` |
| Latest implemented milestone | `v0.001a21` — Cross-Platform Alpha at hosted-proven commit `8b24f4b` |
| Active product milestone | `v0.001a22` — Dogfood / Performance Alpha |
| Display/package metadata | `v0.001a22` / `0.1a22` in `VERSION`, `pyproject.toml`, and `src/uniti/__init__.py` |
| Latest immutable release tag | `v0.001a15` at `10f419e` |
| Queued milestones | `v0.001a23`, `v0.001a24`, `v0.001b1`; proposed successor `v0.001b2` remains behind all predecessor gates |

The retained release policy remains in force. A22 is still active because no qualifying real-use day is recorded; seven distinct days therefore remain `NOT RUN`. A23 executable/health delivery, A24 same-candidate qualification, and the B1 private executable human-feedback gate remain queued and `NOT RUN`. B1 has not been completed or promoted by the source-checkout feedback in [BF-001–BF-010](../BETA_FEEDBACK.md). Proposed B2 scope is recorded in the [B2 Feedback Refinement Beta milestone](../02_plans/v0.001b2-feedback-refinement-beta.md), but it is not active and the product identity remains A22.

The six feedback commits after the initially observed remote `ca75966` are already present and must not be reapplied: `fadc36f` (zero-window restore), `09fe356` (Quit with paused work), `fbeeb0f` (retained last window), `20b1e02` (initial Find/Replace Lucide icons), `fbe1b6e` (recovery scheduling), and `0322939` (compact whitespace and held Unicode inspection). Historical documentation checkpoint `5724f6c` follows them. The reviewed series through candidate `3e20214` adds first-use progress and the durability-warning fix, centered markers and hotkey propagation, EOL truth/all-view refresh, 80% gutter text, complete Find/Replace SVGs and aligned capture rows, packaged/editable theme profiles, bundled Noto fallback, and bounded shaped LTR editing. No version promotion, tag, release, installer, or tester distribution followed from this integration.

## Integrated feedback behavior

- first use prints flushed setup progress before blocking environment/dependency work; valid healthy startup remains quiet, and durability cleanup no longer triggers the Python `return`-in-`finally` warning;
- the critical zero-window restore, paused-Quit, retained-window, and serial-recovery scheduling corrections are in `main`, but closure still requires distribution and confirmation on the affected Windows and Mac hosts;
- the ordinary-space marker is centered from real layout bounds across 50–300% zoom, and the persisted Unicode hold combination is reachable from Hotkeys and applies to existing and new windows;
- line numbers use an independent 80% font while preserving the editor baseline/row height, and progressive wrapped-row preparation settles gutter width before paint and hit testing;
- pending EOL conversion is stated as “on save”; committed markers remain truthful before save, and successful save refreshes every view sharing the document;
- Find/Replace uses the complete Lucide control set, while capture rows expose `\\N :` labels separately and align every preview to one measured column without changing `Match N of M` headers; and
- Paper and Slate are complete named profiles. Users can clone and edit profiles, preview across service windows, apply/cancel/reset/delete, and persist custom profiles plus active selection in one bounded atomic file. Packaged profiles are read-only and contrast remains independent;
- bundled Noto fallback preserves the native monospace primary, orders Han fallback by locale, and covers the selected Indic, Chinese, and Korean samples without OS font installation or runtime download; and
- bounded shaped windows, grapheme-aware navigation/deletion, UTF-16 IME offsets, exact-width wrapping, and virtual preedit panning share Qt geometry while exact code-point inspection remains available.

BF-006 implementation is complete in candidate `3e20214`, but native Windows/macOS/Linux Chinese/Korean IME qualification remains open. RTL and mixed-direction behavior is outside scope. See the [LTR text layout contract](../../../docs/ltr-text-layout.md).

## Implemented A21 Cross-Platform behavior

- one Qt-free policy classifies only macOS, Windows, and Linux, selects absolute native application roots, and keeps existing-file/native lexical identity consistent without hard-coded shared-code drive or separator assumptions;
- one durability adapter reports `full`, `file_synced`, or `unsafe`; settings, setup, Save, sessions, recovery, compaction, and pointer repair preserve the last complete state instead of direct-overwrite fallback;
- session discovery validates at most 200 complete generations and repairs a missing/stale pointer only after a usable scanned generation restores under one-writer authority;
- real POSIX `sh`, Windows `cmd.exe`, and PowerShell launcher contracts cover Unicode, spaces, metacharacters, working directory, interpreter discovery, and exit propagation;
- native Qt standard shortcuts, portable bounded overrides, and one concrete fixed-pitch Latin/Cyrillic editor font are resolved only after `QApplication`;
- deep self-check, diagnostics export, and combined smoke expose bounded categorized/capability facts without raw roots, document/IPC content, or session/recovery paths; smoke includes a Unicode/spaced source and real local-instance forwarding; and
- a standard-library owned-runtime CI driver enforces exact per-family skip sets, 2 MiB per-file/8 MiB aggregate sanitizer budgets, seven-day metadata, and a fixed parsed artifact allowlist. The pinned read-only workflow's four fail-closed lanes passed on the same source commit; successful jobs uploaded no artifacts.

## Implemented A21 Editor Layout and Visibility behavior

- every pane has direct Dock/Undock, Split Right, Split Down, and Assign Document controls; splitting creates an independent view and assignment never replaces an existing tab;
- undocking transfers one view transactionally into another service window, persists the source window/pane/tab return anchor, and docks back exactly when available with bounded deterministic fallbacks;
- the one service-owned Find/Replace surface is a bottom-only full-width dock that follows the active window while attached and remains one modeless topmost tool while detached;
- Find/Replace placement, detached geometry, options, results, zoom, report state, and bounded input Undo/Redo survive host moves and session restoration without a second panel;
- whitespace visualization is display-only with Off, EOL, Spaces & Tabs, Invisible Unicode, and All modes; logical LF/CRLF/CR labels use bounded terminator reads, and marker painting is capped at 4,096 operations per frame with visible overflow aggregation; and
- System/Light/Dark appearance and Standard/High Contrast are independent global settings. Complete editor tokens meet the verified High Contrast thresholds of 7:1 for primary text and 4.5:1 for whitespace markers.

## Implemented A20 behavior

- one user-scoped service is the only document/settings/session/recovery writer; secondary launches forward bounded activation/file requests and exit;
- closing the final window leaves the service running, while explicit Quit offers Save/Discard/Cancel once per unique modified document;
- multiple top-level windows, detachable tab groups, horizontal/vertical splits, and independent views share one authoritative document and Undo/Redo history per source;
- one service-owned Find/Replace panel follows the most recently focused live view and persists complete bounded field state/history, options, geometry, visibility, zoom, and report state;
- Find Previous and Find Next search relative to the cursor and wrap without requiring Find All; Find All remains a separate revision-bound result-store operation;
- durable startup sessions restore bounded window/pane/tab/view state, the active approved document first, other histories lazily, and saved-document Undo/Redo only when exact saved bytes remain compatible;
- SHA-256 is the saved-history authority; externally changed or missing files require explicit Open Disk/Locate Matching File, Skip, or Discard choices and are never overwritten automatically;
- recovery v3 records semantic transactions, Undo/Redo, save points, metadata, checkpoints, and terminal state; v1/v2 remain readable, truncated prefixes remain visible, and recovered evidence retires only after replacement durability exists; and
- all hashing, serialization, compression, fsync, discovery, replay, compaction, and saved-session publication work is scheduled off the GUI thread.

## Storage and safety policy

| State | Implemented bound/policy |
|---|---|
| Document Undo/Redo persistence | newest 50 transactions or 32 MiB decoded per document, first limit reached |
| Find history | at most 50 states |
| Replace history | at most 50 states |
| Combined Find/Replace persistence | 4 MiB decoded; current field state survives history pruning |
| Saved session/history union | 256 MiB physical cap across current and previous generation |
| Closed saved-document retention | seven days, subject to the aggregate cap |
| Session structure | 1 MiB manifest; 32 windows; 128 leaves; 256 views; 128 documents |
| Recovery compaction | 64 MiB per journal, publish before retirement |
| Low-space reserve | 512 MiB; suppress convenience history before recovery durability |

Aggregate pruning removes oldest closed-document history first, then inactive-open history, then oldest active-document transactions; current state is never evicted. Low-space tests use injected capacity and controlled write/fsync failures only—no test fills, reserves, or truncates the real filesystem to manufacture LOWDISK.

## Feedback integration verification

Historical starting-checkpoint verification on `5724f6c` reported:

```text
full pytest: 1476 passed, 6 skipped in 93.01s
deep self-check: pass, 21/21 checks
native Cocoa combined smoke: pass; explicit Quit and session restore passed
```

Focused workstream gates and independent reviews passed for Tasks 2, 4, 5, 6, 7, and 8. Task 8 passed 211 expanded focused tests, a 129-test review-fix matrix, and final scoped rereview with six targeted plus ten independent EOL-ownership probes. Candidate `3e20214` passed the complete source suite with 1,646 tests and six expected platform skips in 95.63 seconds, compilation, diff checks, all 21 deep self-checks, 108 native Cocoa targeted tests, and both native Cocoa and offscreen combined smoke including Quit/session restore. Its rebuilt isolated wheel contains 40 exact resources: 13 fonts, 11 SVGs, two themes, and 14 manifest/notice files; mixed text and Find/Replace render from the installed wheel. The uncontended unchanged scroll, typing, and giant-line gates passed with p95 medians 6.016, 10.055, and 3.623 ms, and the 72-action mixed-script scenario passed at 4.428 ms p95/26.031 ms maximum. All four local hosted-profile sustained families passed five measured cycles plus warmup with no contention. These timings and sustained results are local supporting evidence. Hosted run `34253008439` remains the latest complete four-lane gate on earlier checkpoint `aab3f3c`; same-commit hosted automation is externally blocked. Neither local automation nor focused native checks satisfy physical IME, affected-host, A22 dogfood-day, A23, A24, or B1 gates.

## Historical A21 verification

Fresh local verification on the hosted-proven A21 candidate tree reported:

```text
full pytest: 1257 passed, 6 skipped in 51.55s
compileall and git diff --check: pass
deep self-check: pass, 21/21 checks including cross-platform
offscreen combined smoke: pass; full durability, font, shortcuts, instance forwarding, service/session/history, and explicit Quit facts
native Cocoa combined smoke: pass with the same invariants and qt_platform=cocoa
```

The six skips exactly match `ci/a21-skip-policy.json`: one Windows native-path test, three Windows `cmd.exe` launcher tests, one Windows PowerShell launcher test, and one filesystem-backed local-endpoint test. Optional xattr availability is now a capability fact rather than a skip. The acceptance suite retains its AST guard against real low-disk creation and all reversible docking, one-panel placement, display-only byte integrity, terminator, contrast, and marker-budget coverage.

The local quick run recorded representative medians of 12.501 ms open-to-usable, 469.549 ms sparse navigation completion, 42.553 ms capture report, 46.430 ms Save completion, and 35.809/47.743 ms session open/completion with 17.562 MiB retained RSS. These are evidence only; thresholds and committed baselines were unchanged, and no real LOWDISK state was created.

The new offscreen `session_restore` scenario measured median 6.703 ms open-to-usable, 3.353 ms GUI heartbeat p95, 1.640 ms cancellation, 22.578 MiB peak RSS growth, and 12.844 MiB retained growth. Native Cocoa measured 6.709 ms open-to-usable, 1.767 ms heartbeat p95, 5.974 ms maximum heartbeat, 1.468 ms cancellation, 23.219 MiB peak growth, and 13.469 MiB retained growth. Both runs proved storage/load callbacks ran on worker threads and all thirteen scenarios passed. These A20 runs were not selected as committed JSON baselines; the recorded [a19 routine](../../../benchmarks/baselines/v0.001a19-mac15-8-routine.json), [a19 native quick](../../../benchmarks/baselines/v0.001a19-mac15-8-native-quick.json), and [a18 sparse 1 GiB target](../../../benchmarks/baselines/v0.001a18-mac15-8-design-target.json) remain inherited evidence.

Authoritative hosted workflow [run 33945017353](https://github.com/PJTraut/tools-uniti/actions/runs/33945017353) passed on exact commit `8b24f4b1fa16e0491b1d08e6824e40e3c44ceafd`:

| Required job | Runner / runtime | Qt / plugins | Font / durability | Complete pytest |
|---|---|---|---|---|
| [macos-py312](https://github.com/PJTraut/tools-uniti/actions/runs/33945017353/job/101249420423) | `macos-15`; CPython `3.12.10` | Qt `6.11.2`; `offscreen` / `cocoa` | Menlo; `full` | 1257 passed, 6 skipped |
| [windows-py312](https://github.com/PJTraut/tools-uniti/actions/runs/33945017353/job/101249420366) | `windows-2025`; CPython `3.12.10` | Qt `6.11.2`; `offscreen` / `windows` | Cascadia Mono; `file_synced` | 1256 passed, 7 skipped |
| [linux-py312](https://github.com/PJTraut/tools-uniti/actions/runs/33945017353/job/101249420400) | `ubuntu-24.04`; CPython `3.12.14` | Qt `6.11.2`; `offscreen` / `xcb` | DejaVu Sans Mono; `full` | 1256 passed, 7 skipped |
| [linux-latest](https://github.com/PJTraut/tools-uniti/actions/runs/33945017353/job/101249420399) | `ubuntu-24.04`; CPython `3.14.7` | Qt `6.11.2`; `offscreen` / `xcb` | DejaVu Sans Mono; `full` | 1256 passed, 7 skipped |

Every job also passed compilation, all 21 deep checks, offscreen and native smoke, and its exact checked-in skip policy. Native smoke proved the expected `cocoa`, `windows`, or `xcb` plugin, full application invariants, and explicit Quit. Windows intentionally reports `file_synced` because its safe replace contract does not claim POSIX directory-fsync semantics. No distributable package was produced.

## Known boundary

No known shared-code session-writer race, silent admitted-history loss, external-file overwrite, recovery-evidence loss, unsafe instance takeover, cursor-navigation dependency on Find All, GUI freeze, unbounded allocation, platform launcher corruption, native-path defect, or inherited text-integrity/regex blocker remains in local or four-lane hosted evidence. BF-002 nevertheless remains a critical user-testing blocker until the integrated shutdown/relaunch corrections are distributed and confirmed on the affected Windows and Mac hosts.

UNITI does not install a permanent OS daemon. The desktop service retains an empty visible editor window when the user closes the last window, and exits on explicit Quit, logout, shutdown, or process termination. Legacy zero-window sessions remain restorable. Project/workspace semantics, cloud sync, collaboration, plugins, LSP, syntax highlighting, permanent background services, polished installers, multi-code-point grapheme inspection, and RTL/mixed-direction editing remain outside the implemented boundary. User-authored theme profiles and configurable held single-code-point Unicode inspection are implemented.

The complete A21 Cross-Platform milestone/design/plan and its Editor Layout and Visibility workstream are retained in [Implemented](../03_implemented/README.md). A22 Dogfood / Performance Alpha remains active. A23, A24, B1, and proposed B2 remain successors in that order. See [Scope](SCOPE.md), [Architecture](ARCHITECTURE.md), [Development](DEVELOPMENT.md), [Roadmap](../02_plans/ROADMAP.md), and the [Current Handover](../06_handovers/CURRENT_HANDOVER.md).
