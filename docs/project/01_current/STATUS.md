# UNITI Current Status

Date: 2026-09-20

## Canonical baseline

| Item | Current value |
|---|---|
| Current source identity | `v0.001b4` / `0.1b4` in `VERSION`, `src/uniti/__init__.py`, and `pyproject.toml` |
| Active development milestone | B4 Compare, Character Inspector & Per-View Settings Beta |
| Implemented feedback | All reviewed BF-019 (real fix), BF-070 (Compare full editor parity), BF-072, BF-073 (Character Inspector rebuild), and BF-075 (per-view settings) source changes, plus the shared toggle-window state-persistence mechanism, integrated on local `main` at `366ea42` (see the [B4 milestone plan](../02_plans/v0.001b4-compare-character-inspector-and-per-view-settings-beta.md) for the full item table) |
| Pre-promotion baseline | `3861e63`, the B3-era commit through which the B3 promotion below was verified |
| Promotion scope | Version metadata and project records; existing document, settings, session, and recovery schemas remain unchanged |
| Latest complete hosted feedback pass | `3607d1f` (B4 candidate with the environment track), [run `38531633321`](https://github.com/PJTraut/tools-uniti/actions/runs/38531633321), 2026-10-14: all four lanes (macOS, Windows, Linux 3.12 and latest) pass every step |
| Last recorded hosted account block | Resolved 2026-10-13 (account 2FA updated). Getting the lanes green took: byte-pinning the vendored `.sty` assets (CRLF checkout on Windows broke their SHA-256, so UNITI rejected them), LF test writes on every platform, a caret never inside CRLF, platform-neutral font and layout tests, and the Linux smoke reading its JSON past Qt's log lines |
| Latest completed milestone | A21 Cross-Platform Alpha at hosted-proven `8b24f4b` |
| Latest immutable release tag | `v0.001a15` at `10f419e`; no beta tag or native distribution is created by this source promotion |

The user directed the project to move beyond A22 after the beta feedback work was implemented, then beyond B2, then beyond B3 after this further batch. [ADR-0007](../05_decisions/ADR-0007-beta-source-version-and-qualification.md) advanced the source identity and activated B2; [ADR-0008](../05_decisions/ADR-0008-b3-version-and-qualification.md) advanced it to B3; [ADR-0012](../05_decisions/ADR-0012-b4-version-and-qualification.md) advances it again to B4, in each case while preserving unfinished release qualification. A22 real-use days, A23 executable health/recovery delivery, A24 stabilization, and B1 independent executable feedback remain open, as does B2's own BF-001–BF-010 and B3's own outstanding native-host and hosted-CI evidence. Those historical milestone names and the B2/B3 labels identify outstanding requirements, not the currently installed source version.

The critical BF-002 affected-host confirmation, physical Chinese/Korean IME qualification, and same-commit hosted validation also remain open. Source integration and version advancement do not supply those results. The [Roadmap](../02_plans/ROADMAP.md) records the revised development and qualification order.

## Environment track (2026-09-29 → 2026-10-09)

A separate engineering track alongside B4. It doesn't gate B4's qualification. Its order is the [roadmap's environment track queue](../02_plans/ROADMAP.md#environment-track-queue).

| Item | Current value |
|---|---|
| Branch | `usfm-field-test`, from `35f6fe4`. Merged into `main` (fast-forward from `21164ea`) on 2026-10-09 at the user's request, and pushed: `main`, `origin/main` and `usfm-field-test` are all at `bb06aab` (checked 2026-10-13). |
| Decisions | [ADR-0013](../05_decisions/ADR-0013-environment-framework-ownership-boundary.md)–[ADR-0019](../05_decisions/ADR-0019-named-environment-windows-groups-and-project-tabs.md) |
| Plans | Implemented: [USFM field test](../03_implemented/milestones/2026-10-07-usfm-field-test-plan.md); [projects and versification](../03_implemented/milestones/2026-10-07-usfm-projects-and-versification-plan.md) P1–P5; [field test round 2](../03_implemented/milestones/2026-10-08-usfm-field-test-round-2-plan.md) R1–R8; [field test round 3](../03_implemented/milestones/2026-10-08-usfm-field-test-round-3-plan.md) T1–T7; [per-chapter view](../03_implemented/milestones/2026-10-09-usfm-per-chapter-view-plan.md) C1–C4; [book lock](../03_implemented/milestones/2026-10-14-usfm-book-lock-plan.md) L1–L5; [spellcheck](../03_implemented/milestones/2026-10-13-usfm-spellcheck-plan.md) S1–S5. |
| User documentation | [Environments](../../environments/README.md) (one page per environment), [USFM Stylesheet Rules](../../usfm-stylesheet-rules.md) |
| Schema changes | None. New persisted values ride in existing `extra` blobs; the new user files (`recent-projects.json`, and per environment `Environments/<Environment>/groups.json`, `windows.json`, `projects.json`) sit next to the settings; `settings.json` gained an optional `read_only_folders` list without a schema bump. |

What it does:
- Every file lives in an environment. Opening asks "Open in <Environment> Environment / Open as Plain Text". USFM assumes a Paratext project: a USFM file outside one is plain text.
- Environment windows are named per environment ("USFM A", "USFM B", renameable) and have a toolbar: the window's name, the current file's group, the Plain Text / Standard / Preview mode switch and, for USFM, a Book/Chapter/Verse selector. Standard and Preview are shown in place, styled entirely from layered `.sty` stylesheets plus `uniti.sty` presentation rules, and Preview has a notes frame.
- In a USFM window a tab is a project, titled with its short name; changing the book changes it in the tab, asking before leaving unsaved changes. A tab's menu moves it, with all its books, between up to four splits and between windows.
- Each environment has its own groups. In USFM a group belongs to a project, colours its tab, and binds projects for side-by-side sync across windows, mapped by versification and across books.
- USFM covers `.sfm` and `.usfm`, nested `\+` markers, milestones and `\cat`.
- Paratext projects (`Settings.xml`) open with Open USFM Project…, and Recent Projects remembers them.
- Per-environment user configuration with **Configuration Files…**, reload on save, and a report of undefined markers on open.
- Read-only folders: files in them can't be changed or saved in place.
- **Footnote Categories** (2026-10-14, [plan](../03_implemented/milestones/2026-10-14-footnote-category-filter-plan.md)), per project tab: Preview shows only the notes of the checked `\cat` categories (and "None"); Standard and the source keep every note.
- **Check Spelling** (2026-10-14, [plan](../03_implemented/milestones/2026-10-13-usfm-spellcheck-plan.md) S1–S5), per project tab: wrong and unknown words underlined in all three modes from `SpellingStatus.xml` (deciding) and `hyphenatedWords.txt` (adding), read on a worker; one line cache per document; Plain Text underlines painted lines, Standard and Preview the words on screen.
- **USFM book lock** (2026-10-14, [plan](../03_implemented/milestones/2026-10-14-usfm-book-lock-plan.md) L1–L5): every project book opens locked (per open file, never remembered) and is unlocked to save; **Unlock Book / Lock Book** on the toolbar, the USFM menu and the Book list, tab and text right-click menus; Save or Discard when a book with changes leaves its tab; Close / Update for a book that isn't UTF-8 with CRLF; the project is Find/Replace's Current Group, stepped through book by book; multi-file Replace All lists its files, all unticked; no file is written without changes, in every environment.
- **Show One Chapter** (2026-10-09), per window: Plain Text, Standard and Preview show only the caret's chapter, and the caret stops at its edges; the Chapter selector, sync, Go to Chapter:Verse and Find change the chapter.
- **Live and frozen windows** (2026-10-13): only the active window and its splits follow edits; Standard and Preview in other windows re-render when their window is activated (`UNITIMainWindow.is_live_window`, `RichViewController.catch_up`). Before, every shown Preview of an edited book re-rendered on each keystroke, about 148 ms on a 281 KB Psalms.
- Psalm titles map as verse 0 in versification (ruCARS Ps 11:1 is NIV Ps 12's title), and Standard's top bar has no format buttons.

Local verification after round 3, 2026-10-09 → 2026-10-13:
- **Typing speed** on a 300 KB Psalms: a keystroke went from about 170 ms to 16 ms (19 ms with one chapter shown). Re-reading the book after an edit no longer builds per-character byte boundaries (60 ms → under 1 ms, `95e6a07`), and the reference map looks only at `\c`/`\v` candidates (20 ms → 4 ms, `bb06aab`), checked identical to the tokenizer on 3,000 random strings and every book of `ruCARSv3` and `usNIVv2`.
- **Full suite at `bb06aab`, 2026-10-13: 2,653 passed, 6 platform skips**, offscreen, nothing deselected, no crash.
- **With the spec-check fixes and live/frozen windows, 2026-10-13: 2,661 passed, 6 platform skips** (8 new tests), offscreen, no crash.
- **With the book lock, Check Spelling and the footnote category filter, at `282d612`, 2026-10-15: 2,770 passed, 6 platform skips**, offscreen, nothing deselected. `282d612` is pushed to `origin/main`. The live-app checks of those three ([checklist](../LIVE_APP_CHECKLIST.md) sections 9–11) are not yet done.


Spec check of round 3 and Show One Chapter, 2026-10-13, against the field-test feedback, the user's answers and the round 3 plan (code read, phase tests run, the app driven offscreen with throwaway projects). T1–T3, T5's group colours and sync, T6's menu and moves, T7's edit paths and C1–C4 conform; the full project name appears nowhere. Five deviations, **all fixed the same day**, each with a regression test that fails on the old code:
- **T4: the same book can't be open in two USFM windows.** Choosing a book in one window's Book list, or opening it with File › Open, moves it out of the other window (`EnvironmentBar.open_book` looks only in its own window, `environment_window.py:881`, then `open_path` moves the file). A window could be left with no tabs. Now a book open in another window of the environment gets a second view here (`UNITIMainWindow.open_in_other_environment_window`); a book from an ordinary window still moves in.
- **T5: sync can switch to another project's tab.** When the target split has another project's tab showing the same book in the same group, sync showed that tab instead of changing the book in the shown project's tab. The candidate must now be of the shown tab's project.
- **T6: the Find/Replace pane counts as a split.** With Find attached only 3 editor splits are allowed, and the tab menu's Move to Split and Unsplit could target Find's pane. Only panes holding documents now count (`_editor_pane_ids`).
- **T7: Save As writes into a read-only folder.** Neither Save As path checked the destination; both now refuse with a message (`_refuse_read_only_destination`).
- **T7 (minor):** Format/Minify on a read-only file raised an uncaught `DocumentReadOnlyError`; it now shows the read-only message. Closing a modified read-only file offered Save, which then failed; it now offers Discard or Cancel and points to Save As (`_ask_save_changes`).

Untested: Find's "All open documents" including a project tab's hidden books; a session saved with more than 4 splits isn't capped on restore.

Local verification of round 3, 2026-10-08. Each phase's full suite ran (from T3 on in a separate worktree at the phase's commit, importing that tree's code), with the same deselected test as below:
- T1 `9a575d1`: 2,564 passed (and the 2 tests it broke, fixed in the same commit); T2 `c58135b`: 2,573; T3 `95a3253`: 2,581; T4 `bb47e25`: 2,588; T5 `eff5ecd`: 2,593; T6 `5790d51`: 2,600; T7 `2a3ca75`: **2,605 passed**. Each with 6 platform skips.
- **The unexplained crash came back once.** The first T2 run stopped at 36% with no summary. macOS's crash report (`Python-2026-10-08-201356.ips`) shows `EXC_BREAKPOINT`/`SIGTRAP` (`brk 1`) inside `_PyEval_EvalFrameDefault` on the main thread (Python 3.12.4). `faulthandler` doesn't catch `SIGTRAP`, which is why nothing was printed. The test then running was `tests/core/test_snapshot.py::test_snapshot_freezes_edit_blocks_before_live_append` (number 986), a core test, which passes alone; the rerun passed in full. An earlier report the same day (`Python-2026-10-08-135925.ips`) is a `SIGSEGV`. Both point at interpreter state damaged earlier in the run, most likely by Qt objects from the UI tests, not at the test running when it crashed. From 2026-10-09 the suite also dumps tracebacks on `SIGTRAP` (`tests/conftest.py`), so the next occurrence shows where it happened.

Local verification at `d57dac5`, 2026-10-08:
- **Full suite: 2,547 passed, 6 platform skips.** `tests/performance/test_ux_scenarios.py::test_resource_recovery_scenario_restores_parallel_capacity` was deselected: it fails on this host and fails identically on `21164ea` in a clean worktree, so it predates this track. **Fixed 2026-10-09:** the `resource_recovery` benchmark scenario took its "normal" cache budget from the manager's first state, which is the host's real memory pressure: BUSY on this machine (about 10.6 of 51.5 GB free, so a 402 MB budget instead of NORMAL's 537 MB). Recovery was right; the comparison wasn't. The scenario now starts from a healthy NORMAL state, and `test_resource_recovery_scenario_holds_on_a_busy_host` forces a BUSY start. The test no longer needs to be left out.
- **One unexplained crash.** One full run on 2026-10-08 ended in a fault-handler crash. The later runs, including two with `-X faulthandler` and saved output, all passed, so it couldn't be reproduced and the test is unknown.
- **Speed.** Plain Text → Standard on a 220 KB book was measured offscreen in a window at 41 s before R1 and 0.86 s after.

User field check in the live app, 2026-10-08:
- **Standard/Preview switching speed:** acceptable.
- **Book list:** a book without `\h` must show its `\id` code alone. Changed the same day.
- **Undefined-markers report:** none found in the files tried so far.
- **Versification and sync, NIV (`usNIVv3`) against ruCARS (`ruCARSv3`):** run at the user's request on the real projects in `/Volumes/Win11Arm64/Paratext Projects`, read-only.
  - Psalms (3:1→3:2, 51:1→50:3, 23:1→22:1, 90:1→89:2, 119:176→118:176), Joel, Malachi, Numbers and Romans all land on the matching verse.
  - Three fixes came out of it: Paratext's own `.vrs` folder, `Custom.vrs` in any case, and a mapping onto a verse that doesn't exist (ruCARS Rom 16:25).
  - Book-file naming resolved every present book in both projects.

Not yet verified:
- the user trying round 3 in the live app: project tabs, named windows, per-environment and per-project groups, sync across windows, the tab menu and read-only folders;
- the user trying versification and sync in the live app;
- Paratext book-file numbering and `Settings.xml` fields beyond `usNIVv3` and `ruCARSv3`;
- any affected-host check.

## B4 source promotion

Fresh local validation on the B4 promotion working tree, 2026-09-20:

- The version identity was advanced in `VERSION`, `src/uniti/__init__.py`, and `pyproject.toml`; `tests/test_package.py::test_project_versions_are_canonical` passed against the new `v0.001b4`/`0.1b4` values.
- The owned development installation was refreshed through `scripts/bootstrap.py --dev --no-launch`; `--version` reports `v0.001b4`. This step was required: an initial full-suite run against the pre-refresh installation failed 8 tests (`test_deep_check_exercises_complete_core_matrix`, `test_complete_offscreen_startup_reaches_ready_without_pip`, `test_a18_deep_self_check_includes_large_file`, and all five `test_bf002_lifecycle.py::test_desktop_exit_releases_process_and_relaunches_saved_session` variants) with `installed UNITI metadata does not match the running release`; all 8 passed once the installed metadata was refreshed to `v0.001b4`.
- Local full suite at `366ea42` (this promotion's tip, post-refresh): **2,058 passed, 6 expected platform skips, no failures**.
- `git diff --check` passed (no whitespace errors) and the new/edited cross-referenced documents (ADR-0012, the B4 milestone plan) resolve to real files.

This validates the local source promotion only. Same-commit hosted, physical input, affected-host, and executable qualification remain pending — none has been attempted on `366ea42`. No historical performance or wheel result is relabelled as a fresh B4 measurement. The B3 source promotion verification below remains valid evidence for the commit it was captured on, not for this tip.

## B3 source promotion

Fresh local validation on the B3 promotion working tree, 2026-09-15:

- The owned development installation was refreshed through `scripts/bootstrap.py --dev --no-launch`; `--version` reports `v0.001b3`.
- Local full suite at `ca05d0b` (this promotion's tip): **1,830 passed, 6 expected platform skips**, including new regressions for BF-017 (single- and two-window Find/Replace zoom-shortcut delivery, using `QTest.keySequence`), BF-056 (match-report content no longer changes the panel's minimum size), and a rewritten BF-057 menu-structure test. One order-dependent flaky failure, `test_palette_change_rebuilds_group_formats_with_accessible_contrast`, was confirmed present on the pre-session code as well when the full file runs in a particular order, and passes in isolation; it is unrelated to this batch.
- All **21 deep self-checks** (`--self-check --deep --json`) passed, reporting identity `display_version: v0.001b3`, `package_version: 0.1b3`, confirming source/display/package/installed metadata agreement.
- `git diff --check` passed (no whitespace errors) and the new/edited cross-referenced documents (ADR-0008, the B3 milestone plan) resolve to real files.

This validates the local source promotion only. Same-commit hosted, physical input, affected-host, and executable qualification remain pending — none was attempted on `ca05d0b`. No historical performance or wheel result is relabelled as a fresh B3 measurement. The B2 source promotion verification below remains valid evidence for the commit it was captured on, not for this tip.

## B2 source promotion verification

Fresh local validation on the B2 promotion working tree based on `33c71d3`, 2026-09-08:

- The owned development installation was refreshed through bootstrap; `--version` reports `v0.001b2`, and source/display/package/installed metadata agree on `v0.001b2` / `0.1b2`.
- The initial suite found five assertions that required alpha labels (1,641 passed, six expected skips). Those assertions were updated to preserve canonical metadata and minimum-version checks across alpha/beta versions; all 65 focused tests passed.
- The complete rerun passed **1,646 tests with six expected platform skips in 95.17 seconds**.
- Compilation and all **21 deep self-checks** passed. Native Cocoa and offscreen combined smoke passed, including explicit Quit, session/history restoration, and instance forwarding.
- Relative documentation links and diff checks passed; independent review confirmed coherent B2 metadata and retained release requirements.

This validates the local source promotion. Same-commit hosted, physical input, affected-host, and executable qualification remain pending. No historical performance or wheel result is relabelled as a fresh B2 measurement.

## Integrated feedback behavior

- first use prints flushed setup progress before blocking environment/dependency work; valid healthy startup remains quiet, and durability cleanup no longer triggers the Python `return`-in-`finally` warning;
- the critical zero-window restore, paused-Quit, retained-window, and serial-recovery scheduling corrections are in `main`, but closure still requires distribution and confirmation on the affected Windows and Mac hosts;
- the ordinary-space marker is centered from real layout bounds across 50–300% zoom, and the persisted Unicode hold combination is reachable from Hotkeys and applies to existing and new windows;
- line numbers use an independent 80% font while preserving the editor baseline/row height, and progressive wrapped-row preparation settles gutter width before paint and hit testing;
- pending EOL conversion is stated as “on save”; committed markers remain truthful before save, and successful save refreshes every view sharing the document;
- Find/Replace uses the complete Lucide control set, while capture rows expose `\\N` labels separately and align every preview to one measured column without changing `Match N of M` headers; and
- Paper, Slate, Solarized Dark, Solarized Light, Monokai, Dracula, Gruvbox Dark, and Nord are complete named profiles. Users can clone and edit profiles, preview across service windows, apply/cancel/reset/delete, and persist custom profiles plus active selection in one bounded atomic file. Packaged profiles are read-only and contrast remains independent;
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
- closing the final window leaves the service running with a visible empty editor under the integrated BF-002 correction, while explicit Quit offers Save/Discard/Cancel once per unique modified document;
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
| Document Undo/Redo persistence | newest 100 transactions or 64 MiB decoded per document, first limit reached |
| Find history | at most 50 states |
| Replace history | at most 50 states |
| Combined Find/Replace persistence | 4 MiB decoded; current field state survives history pruning |
| Saved session/history union | 512 MiB physical cap across current and previous generation |
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

Focused workstream gates and independent reviews passed for Tasks 2, 4, 5, 6, 7, and 8. Task 8 passed 211 expanded focused tests, a 129-test review-fix matrix, and final scoped rereview with six targeted plus ten independent EOL-ownership probes. Candidate `3e20214` passed the complete source suite with 1,646 tests and six expected platform skips in 95.63 seconds, compilation, diff checks, all 21 deep self-checks, 108 native Cocoa targeted tests, and both native Cocoa and offscreen combined smoke including Quit/session restore. Its rebuilt isolated wheel contains 40 exact resources: 13 fonts, 11 SVGs, two themes, and 14 manifest/notice files; mixed text and Find/Replace render from the installed wheel. The uncontended unchanged scroll, typing, and giant-line gates passed with p95 medians 6.016, 10.055, and 3.623 ms, and the 72-action mixed-script scenario passed at 4.428 ms p95/26.031 ms maximum. All four local hosted-profile sustained families passed five measured cycles plus warmup with no contention. These timings and sustained results are local supporting evidence. Hosted run `34253008439` remains the latest complete four-lane gate on earlier checkpoint `aab3f3c`; later hosted attempts through `33c71d3` were blocked before execution by the account constraint above. Neither local automation nor focused native checks satisfy physical IME, affected-host, A22 dogfood-day, A23, A24, or B1 gates.

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

Documentation verification found [BF-012](../BETA_FEEDBACK.md#bf-012--full-unicode-case-folding-misses-a-match-with-one-character-search-windows): full Unicode case folding misses `STRASSE` for `(?fi)straße` and `(?V1)(?i)straße` with one-character search windows. Direct engine matching, windows of 8 and 65,536, and the recorded default-window boundary probe pass. The tiny-window discrepancy remains open; no production-default-window failure or source correction is claimed.

Before that new finding, recorded local and four-lane hosted evidence identified no shared-code session-writer race, silent admitted-history loss, external-file overwrite, recovery-evidence loss, unsafe instance takeover, cursor-navigation dependency on Find All, GUI freeze, unbounded allocation, platform launcher corruption, native-path defect, or inherited text-integrity/regex blocker. BF-002 nevertheless remains a critical user-testing blocker until the integrated shutdown/relaunch corrections are distributed and confirmed on the affected Windows and Mac hosts.

UNITI does not install a permanent OS daemon. The desktop service retains an empty visible editor window when the user closes the last window, and exits on explicit Quit, logout, shutdown, or process termination. Legacy zero-window sessions remain restorable. Project/workspace semantics (beyond the narrow bounded Open Folder by Type exception, [ADR-0009](../05_decisions/ADR-0009-bounded-open-folder-by-type.md)), cloud sync, collaboration, plugins, LSP, permanent background services, and polished installers remain outside the implemented boundary. User-authored theme profiles, configurable held single-code-point Unicode inspection, a bounded file-type syntax-highlighting extension point (BF-027, BF-041), content-level right-to-left/bidi editing for Arabic and Hebrew (BF-064; application chrome stays left-to-right, and native IME qualification remains open), and multi-code-point Unicode-property inspection over a selection (BF-065) are implemented; cross-row/multiline-aware highlighting and a syntax-color theme editor remain parked.

The complete A21 Cross-Platform milestone/design/plan and its Editor Layout and Visibility workstream are retained in [Implemented](../03_implemented/README.md). B4 Compare, Character Inspector & Per-View Settings Beta is active. Outstanding A22, A23, A24, and B1 release qualification remains recorded under ADR-0007; B3's advancement is recorded under ADR-0008; B4's own advancement is recorded under ADR-0012. See [Scope](SCOPE.md), [Architecture](ARCHITECTURE.md), [Development](DEVELOPMENT.md), [Roadmap](../02_plans/ROADMAP.md), and the [Current Handover](../06_handovers/CURRENT_HANDOVER.md).
