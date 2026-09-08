# B1 Feedback Closure and B2 Transition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve every outstanding BF-001–BF-010 item, integrate verified changes into canonical `main`, and qualify `v0.001b2` without losing the existing release evidence requirements.

**Architecture:** Preserve the service/document ownership, bounded viewport, shared Find/Replace panel, settings store, and theme/icon policies. Implement defects in small commits; implement theme and multilingual-font extensions as separate workstreams. Keep B1 stabilization evidence separate from B2 feature qualification.

**Tech Stack:** Python 3.12+, PySide6 6.8+, the existing pinned `regex` dependency, bundled Lucide SVGs, and the user-selected Noto font collection.

**Spec:** [Beta feedback](../BETA_FEEDBACK.md), [current architecture](../01_current/ARCHITECTURE.md), [B1 governing design](v0.001b1-real-world-feedback-beta-design.md), and the proposed defaults in this plan.

**Status:** Execution in progress on 2026-09-08. Candidate `3e20214` contains the complete reviewed BF-001–BF-010 code series and passed the final local candidate gate. Native IME/affected-host qualification and release gates remain open. Latest hosted-green checkpoint is `aab3f3c` in run `34253008439`; later runs were blocked before execution by GitHub account billing/payment or spending limits. This document does not mark feedback resolved, change the product version, or by itself publish anything.

**Execution rulings:** Keep the platform-resolved monospace face primary and treat bundled Noto as ordered application fallback. Order Han families from the host locale because plain text carries no per-range SC/TC language metadata. Use extended-grapheme boundaries for user navigation/deletion while preserving exact code-point selection/inspection; Unicode graphemes are not claimed to equal every script syllable. Cold deep variable-width geometry may resolve progressively within fixed materialization bounds rather than publishing approximate positions; inherited logical-line indexing is not newly bounded. Long preedit pans only its virtual row to keep the composition caret visible. These choices cost a possible visible wait for cold deep mixed-script jumps, locale-dependent Han regional forms, and host fallback for emoji. RTL/mixed-direction editing and physical native IME qualification remain outside the implemented claim. Hosted jobs blocked before execution provide no pass/fail evidence and do not alter any gate.

- Ruling: retain the approved A22, A23, A24, and B1 release gates. Source integration does not qualify B1/B2; replacing that policy would require explicit metadata, roadmap, admission, distribution, and cohort-rule rework.
- Ruling: apply `\1 :`, `\2 :` labels to capture-group rows and preserve whole-match `Match N of M` headers. If the request was intended for whole matches, the presentation must change without reinterpreting regex group identity.
- Ruling: the user's explicit synchronization direction moves reviewed work onto canonical `main` before version-gate closure while retaining A22 metadata and separate review boundaries. If that integration timing proves wrong, revert the feature commits without rewriting history.
- Ruling: cold deep variable-width geometry resolves progressively within bounded work. The cost is a visible wait for some mixed-script jumps; unknown-prefix geometry never produces an approximate caret or hit target.

## Baseline and release interpretation

- Task 1 began on isolated `work/b2-feedback` at `5724f6c`; local `main` matched it. `VERSION`, `src/uniti/__init__.py`, and `pyproject.toml` identify A22 (`v0.001a22` / `0.1a22`).
- Historical starting observation: the read-only ancestry check initially found `origin/main` at `ca75966`, with local `main` zero commits behind and seven ahead. The six feedback commits `fadc36f`, `09fe356`, `fbeeb0f`, `20b1e02`, `fbe1b6e`, and `0322939` were already present, followed by documentation commit `5724f6c`; none requires reapplication. The controller subsequently pushed `5724f6c`; hosted run `34247594588` was pending at that time.
- Fresh checkpoint verification is 1,476 passed tests and six skips in 93.01 seconds, deep self-check 21/21, and native Cocoa combined smoke with explicit Quit/session restore. This is a source baseline, not a B2 qualification gate.
- The feedback additions were preserved in documentation commit `5724f6c`; Task 1 continues in the isolated checkout without disturbing the user's original checkout or running service.
- Before Task 1, the existing roadmap was A22 → A23 → A24 → B1 and B2 had no milestone record. Calling these reports “B1 feedback” does not establish that the formal executable B1 gate has passed.
- Release-policy answer: retain the existing gates. B1 requires qualified same-commit executable builds, fourteen calendar days on the qualifying behavior candidate, and three independent human testers covering macOS, Windows, and Linux. Behavior corrections reset the qualifying-candidate clock as specified by the B1 design.
- Alternative if the user chooses a source-checkout beta policy: record a decision explicitly replacing the affected admission/distribution/cohort rules, define source-build qualification and tester criteria, and update the roadmap before promotion. Do not silently label missing executable or human evidence as passing.
- Treat the theme/font extensions and new presentation requests as B2 scope where they exceed B1's feature freeze. Per the user's 2026-09-08 integration direction, land all reviewed in-scope fixes and features on canonical `main` and synchronize the remote promptly, using separate reviewable commits or series for B1 fixes and B2 features. Keep A22 metadata/milestone state and require the full predecessor/B1 closure boundary before B2 release promotion. All ten feedback entries must meet their agreed acceptance criteria before B2 is presented as ready for testing.

## Global constraints

- Preserve one `UNITIService`, one document authority per source, and one shared Find/Replace surface.
- Explicit Quit shuts down the service and releases the launching terminal; closing the last window keeps an empty visible editor available.
- Preserve bytes, undo/redo, selections, recovery evidence, and external-change protections. Do not reinterpret display changes as document edits.
- Keep whitespace category filtering, the 4,096-marker frame budget, and bounded line-terminator reads.
- Retain tabs `»` and EOL `␊` / `␍` / `␍␊`. Keep held Unicode inspection and its configurable shortcut.
- Noto is the selected font collection. Initial expansion is left-to-right only; RTL/mixed-direction editing remains deferred.
- Preserve independent appearance and contrast settings; High Contrast retains the current 7:1 primary-text and 4.5:1 marker contrast requirements.
- Keep raw tester documents, screenshots, paths, machine identities, and support archives outside Git. Commit summarized observations and synthetic regression fixtures only.
- No release tag, public release, updater, or public package is inferred by advancing source metadata to B2.
- The user's 2026-09-08 direction authorizes synchronizing reviewed in-scope work to canonical `main` and the remote. Integration does not itself change version metadata, close a gate, create a tag/release, or authorize tester communication.

## Coverage and order

| Feedback | Outstanding deliverable | Task | Acceptance |
|---|---|---:|---|
| BF-001 | First-use progress and Python warning correction | 2 | Early flushed progress; quiet valid launch; warning removed without weakening durability |
| BF-002 | Distribution/build verification and affected-host closure | 1, 3 | Windows/Mac Quit releases terminal; relaunch restores; last-close retains usable window |
| BF-003 | Center normal-space dot; finish native validation | 4 | One centered dot across zoom/DPI; all other marks and hold behavior retained |
| BF-004 | Validate configuration across windows and restarts | 4 | Menu access, persistence, reset/disable, native hold/release |
| BF-005 | Editable themes and additional packaged presets | 7 | Preview/apply/cancel/reset, persistence, consistent UI and contrast |
| BF-006 | Noto for Indian scripts, Chinese, Korean | 8 | Bundled fallback, shaping, layout, navigation and IME qualification |
| BF-007 | F>/R> SVGs; reconcile clear and navigation icons | 6 | All requested controls use the shared SVG renderer with accessible descriptions |
| BF-008 | Backslash-number labels and aligned content | 6 | Shared content column at single/multiple-digit labels and every F/R zoom |
| BF-009 | Smaller line numbers | 5 | 80% gutter font, aligned baselines, correct gutter geometry at every editor zoom |
| BF-010 | EOL status/viewport consistency | 5 | Current versus pending EOL explicit; successful save refreshes every shared view |
| All | Main integration and B2 qualification | 9–11 | Same-candidate gates, feedback disposition, version/doc consistency |

## Task 1: Establish the candidate and milestone boundaries

**Files:** modify `docs/project/01_current/STATUS.md`, `docs/project/06_handovers/CURRENT_HANDOVER.md`, `docs/project/02_plans/ROADMAP.md`, and `docs/project/BETA_FEEDBACK.md`; create `docs/project/02_plans/v0.001b2-feedback-refinement-beta.md`. Create a decision record under `docs/project/05_decisions/` only if release policy is changed.

**Consumes:** actual Git/version state and existing milestone evidence. **Produces:** an exact baseline, the selected release path, and a BF-by-BF evidence checklist.

- [x] Preserve the feedback changes in documentation commit `5724f6c`; the clean checkpoint recorded branch `work/b2-feedback` and exact HEAD `5724f6cb3081d30b2962ecaefb623be2358331b8`. No unrelated files were included.
- [x] Fetch remote refs read-only and record `origin/main...main`: initially zero behind/seven ahead from remote `ca75966`; inventory `fadc36f`, `09fe356`, `fbeeb0f`, `20b1e02`, `fbe1b6e`, and `0322939` as already present. No change was reapplied.
- [x] Reconcile stale status/handover fields with A22 metadata and dated evidence while preserving historical A21/A22 counts under their original candidates.
- [x] Record the retained release policy and enumerate A22's seven remaining real-use days, A23 executable/health delivery, A24 qualification, and B1 human feedback as prerequisites. Missing evidence remains `NOT RUN`.
- [x] Add proposed/queued B2 with the exact BF-001–BF-010 scope and roadmap link. A22 remains active and B1 is not claimed complete.
- [x] Use isolated branch/worktree `work/b2-feedback` for the documentation checkpoint, preserving the user's original checkout and running service. The execution plan retains separate review boundaries for B1 fixes and B2 features while allowing reviewed work to integrate promptly.

**Check:** PASS on 2026-09-08. Metadata agrees across its three sources; every feedback ID maps to a task and evidence state; remote ancestry is recorded; A22 remains active; no previous milestone is closed based on this plan alone.

## Task 2: First-run progress and durability warning — BF-001

**Files:** modify `src/uniti/bootstrap/cli.py`, `src/uniti/bootstrap/environment.py`, `src/uniti/bootstrap/dependencies.py`, and `src/uniti/core/durability.py`; tests in `tests/bootstrap/test_cli.py`, `tests/bootstrap/test_environment.py`, `tests/bootstrap/test_dependencies.py`, `tests/core/test_durability.py`, and `tests/test_launchers.py`.

**Design:** emit the exact user-requested line `// prepping UNITI for first use` before environment creation or first dependency installation. Report creating runtime, installing dependencies, validating, and launching as actual stages. Use flushed stderr so `--no-launch` command output and JSON stdout remain parseable. A valid subsequent launch must not claim first-use setup; explicit repair uses repair wording. Never show a fabricated percentage.

- [x] Add a regression that captures progress before the injected slow environment/dependency operation is allowed to complete; assert the first-use line precedes it. Cover initial, adopted, repair, healthy fast-path, failure, no-launch, and JSON-forwarding cases.
- [x] Add an optional progress callback at the environment/dependency operation boundaries; wire the CLI to flushed stderr. Keep existing return values, lock ownership, captured bounded failure diagnostics, and exit codes.

```python
# CLI progress sink; callbacks are emitted at real operation boundaries.
def report_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)
```

- [x] Reproduce the `return`-inside-`finally` warning using the newest supported Python. Add durability cases for open failure, fsync failure, close failure, and an unexpected exception during fsync with a failing close.
- [x] Remove control flow from `finally` in `sync_directory`. Return the fsync outcome after cleanup; preserve propagation of unexpected exceptions. A close failure must not turn failed synchronization into success.
- [x] Run focused bootstrap/durability/launcher tests and compile with warnings treated as errors on Python 3.14+; measure actual fresh and healthy-launch timings without introducing a performance claim from dependency-download time.

```bash
.venv/bin/python -m pytest -q tests/bootstrap tests/core/test_durability.py tests/test_launchers.py
.venv/bin/python -W error::SyntaxWarning -m compileall -f -q src/uniti/core/durability.py
```

**Commit:** `fix: show first-use progress and remove durability cleanup warning`.

## Task 3: Close the critical shutdown/relaunch defect — BF-002

**Files:** existing corrections in `src/uniti/app/service.py`, `src/uniti/app/recovery_manager.py`, `src/uniti/ui/main_window.py`, and session/resource scheduling modules; regression owners `tests/app/test_service.py`, `tests/app/test_session_orchestration.py`, `tests/app/test_recovery_manager.py`, `tests/test_alpha_smoke.py`; evidence in the feedback log.

**Consumes:** the baseline's existing fixes. **Produces:** supported-platform and affected-host evidence, plus narrowly scoped fixes only if a new reproduction fails.

- [ ] Run existing pause/publication/recovery ordering and lifecycle regressions. Inspect failures before editing; do not replace already-correct scheduling logic.
- [ ] On native Mac and Windows, verify: ordinary Quit; Quit with paused work; last-window close leaves a usable empty editor; Open from that window; subsequent Quit; relaunch with restored session; legacy zero-window restore.
- [ ] With synthetic documents and an owned test process, terminate the terminal/process and relaunch. Assert session/recovery choices remain usable and the startup failure does not recur. Never terminate the user's actual service to test this.
- [ ] Record candidate identity on each affected tester host, then reproduce their original workflow there. Require terminal prompt return, process exit, released instance ownership, and successful subsequent launch.
- [ ] Keep BF-002 critical/open if affected-host confirmation is unavailable. Native developer smoke is supporting evidence, not a substitute for the log's closure requirement.

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/app/test_service.py tests/app/test_session_orchestration.py tests/app/test_recovery_manager.py tests/test_alpha_smoke.py
QT_QPA_PLATFORM=cocoa .venv/bin/python -m uniti --smoke
```

Use the owned Windows interpreter and `QT_QPA_PLATFORM=windows` for its native smoke; retain Linux's existing source/native gates too.

**Commit:** only reproducible additional fixes, followed by a separate evidence update when closure is established.

## Task 4: Center spaces and finish inspection/hotkey verification — BF-003/004

**Files:** modify `src/uniti/ui/text_view.py`; test `tests/ui/test_unicode_inspection.py`, `tests/ui/test_text_view_contract.py`, `tests/ui/test_hotkeys.py`, `tests/app/test_settings.py`; inspect `src/uniti/ui/unicode_inspection.py` and `src/uniti/ui/main_window.py` only if validation exposes a defect.

**Finding:** normal space currently draws both a point and a middle-dot glyph at `center - 2`. Fixed glyph placement and integer rounding do not center the visible ink at different font sizes. An exploratory pixel reproduction failed at 50/100/200/300% and normal/Retina scale; that exploratory test was removed when the user clarified feedback-only mode.

- [x] Reinstate a regression rendering an isolated real marker into a transparent QImage at 50/100/200/300% and device scale 1/2. Use fractional layout boundaries. Compare the alpha-weighted pixel centroid against `(x1 + x2) / 2` and the row midpoint within 0.2 logical pixels; prove failure before fixing.
- [x] Replace the duplicate mark with one filled, antialiased circular dot using floating-point layout coordinates and the existing space color. Scale its diameter with the editor font and keep it small enough for the actual gap. Save/restore painter state.

```python
center = QPointF((x1 + x2) / 2.0, y + self._line_height / 2.0)
# Draw one circle around this point; do not also draw a text glyph.
```

- [x] Inspect adjacent spaces, a space after an emoji, and light/dark/high-contrast output. Assert text bytes and cursor/selection are unchanged and the existing marker budget still passes.
- [x] Verify each whitespace mode with hold/release; one selected code point with mode Off; app deactivation; custom/disabled/reset combination; restart; multiple windows; new windows after configuration.
- [ ] Test physical Cmd+Option on Mac and Ctrl+Alt on Windows, including interaction with typing, AltGr where available, and existing command shortcuts. Any input conflict must be resolved without swallowing text or changing the persisted whitespace mode.

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/ui/test_unicode_inspection.py tests/ui/test_text_view_contract.py tests/ui/test_hotkeys.py tests/app/test_settings.py
```

**Commit:** `fix: center normal-space markers across zoom and display scale` plus a separate hotkey fix only if needed.

## Task 5: Gutter typography and EOL consistency — BF-009/010

**Files:** modify `src/uniti/ui/text_view.py`, `src/uniti/ui/main_window.py`, and `src/uniti/ui/status_bar.py` if status wording needs changing; tests `tests/ui/test_text_view_contract.py`, `tests/ui/test_progressive_save.py`, `tests/core/test_save.py`; create `tests/ui/test_eol_display.py`.

**Gutter default proposed:** line-number font at 80% of document point size; same row baseline and line spacing as the text. Preserve the minimum gutter width and compute additional width from the actual gutter font and largest visible number. Do not shrink document text or alter hit testing/scroll steps.

- [x] Add a rendering regression at 50/100/200/300% for smaller line-number ink, baseline alignment, six-digit numbers, selection clicks, scrolling, and wrap continuation rows.
- [x] Give the gutter its own QFont/QFontMetrics derived from the editor font. Set that font only while painting numbers; restore the editor font before content/markers. Recompute gutter width when zoom or document line-number range changes.
- [x] Add synthetic LF, CR, CRLF, and mixed-EOL integration cases that select an output EOL, save, inspect actual bytes, reopen, and observe all views sharing the document. Cover failed/cancelled save and Keep Source.
- [x] Establish whether BF-010 occurs before save or after successful save. `set_output_eol` configures conversion on save; markers currently describe committed content. Preserve that truth: before save, status must distinguish current source EOL from “on save” target. After successful save/document rebinding, invalidate EOL analysis and repaint every affected view from the new authority.
- [x] Immediate document-wide conversion was not selected; markers remain tied to committed bytes until successful save.

```python
# Synthetic integration acceptance: LF source converted to CRLF.
assert source_before_save == b"one\ntwo\n"
assert saved_bytes == b"one\r\ntwo\r\n"
assert all(label == "CRLF" for label in painted_eol_labels_after_save)
```

**Commits:** `fix: distinguish pending EOL conversion and refresh saved markers`; `feat: reduce editor line-number size`.

## Task 6: F/R SVGs and aligned Match labels — BF-007/008

**Files:** modify `src/uniti/ui/find_replace.py`, `src/uniti/ui/capture_report.py`, and `src/uniti/ui/icons.py`; add a bounded `src/uniti/ui/capture_report_delegate.py`; update bundled Lucide assets/notices only if an additional glyph is required. Tests: `tests/ui/test_icons.py`, `tests/ui/test_find_replace_contract.py`; create `tests/ui/test_capture_report.py`.

**Approved interpretation:** use `\1 :`, `\2 :` for capture-group rows, preserving `Match N of M` occurrence headers. `CaptureReportModel` lists group rows below whole-match headers; the implemented presentation keeps those identities distinct.

**Layout:** label and content are separate model/delegate fields. A shared measured tab stop places content at one x-coordinate. Literal tabs/spaces in preview text are data, not padding; named groups and occurrence suffixes must not shift the content start. Keep accessible plain-text rows and all bounded report semantics.

- [x] Compare the running beta panel with local `20b1e02`: clear and Previous/Next already have Lucide action icons; `F>` and `R>` remain text labels. Avoid duplicate replacement work.
- [x] Replace F>/R> with search/replace SVG labels using the shared renderer, with Find/Replace accessible names and tooltips. For clear controls, use a circle-x SVG if a complete SVG circle is required and remove the redundant custom painted circle. Preserve click targets, focus behavior, disabled state, and theme tint.
- [x] Add `LabelRole` and `ContentRole` model roles for report data rows. Expose each separately while keeping `DisplayRole`/`AccessibleTextRole` readable. The delegate computes one label-column width across the bounded current report and paints content after that width plus a measured tab gap.
- [x] Preserve unmatched groups, empty matches, repeated-capture counts, named groups, truncation, current/next separators, loading/unavailable rows, and revision cancellation. Do not change regex numbering or replacement expansion.
- [x] Test groups/occurrences 1, 9, 10, and 100, long names, CJK text, empty/unmatched rows, and every F/R zoom. Assert identical content-start x-coordinates; assert accessible text includes both identity and preview. Verify attached/detached and right-report placements.

```python
# For the capture-group interpretation, the model contract is:
assert group_one_label == "\\1 :"
assert group_ten_label == "\\10 :"
assert group_one_content_x == group_ten_content_x
```

**Commits:** `feat: complete SVG controls in Find and Replace`; `feat: align Match report labels and content`.

## Task 7: Packaged themes and theme editing — BF-005

**Files:** modify `src/uniti/ui/theme.py`, `src/uniti/app/settings.py`, `src/uniti/ui/main_window.py`, `pyproject.toml`; create `src/uniti/app/theme_profiles.py`, `src/uniti/ui/theme_editor.py`, and `src/uniti/ui/assets/themes/`; tests in `tests/ui/test_theme.py`, `tests/app/test_settings.py`, and new `tests/ui/test_theme_editor.py`/`tests/app/test_theme_profiles.py`.

**Proposed scope:** retain System/Light/Dark and the separate contrast axis. Add Paper (warm light) and Slate (muted dark) as two packaged starting profiles; allow cloning a profile, editing its UI/editor colors, live preview, Apply, Cancel, Reset, and deletion of user profiles. Keep packaged profiles read-only. No theme marketplace, scripting, or cloud sync.

**Interfaces:** Qt-free immutable `ThemeProfile` carries `id`, `name`, `base_mode`, and a complete string-color mapping. `ThemeProfileStore.load()`/`save()` manage versioned profiles under the existing user configuration root. `theme.py` converts validated profiles into the existing complete `ThemeSpec`; the editor uses a draft profile until Apply.

- [x] Define schema 1: id/name/base_mode/colors; reject unknown keys, invalid colors and unsupported roles. Proposed bounds: 32 custom profiles, 64 characters per name, 128 KiB total file. Use the existing atomic JSON durability helper and recover invalid settings to the selected built-in without overwriting the damaged file.
- [x] Start Paper with base `#FBF7EF` and text `#28251F`; Slate with base `#202830` and text `#E8EDF2`. Fill every existing palette/editor role from the corresponding light/dark profile, then review selection, matches, errors, markers, disabled states, and control icons together. Do not ship partial token maps.
- [x] Test profile round-trip, invalid schema/color/bounds, atomic-write failure, unknown selected profile, and existing-settings migration before implementing storage.
- [x] Build the editor from role labels and color controls; selecting a role previews across all service windows and F/R. Cancel restores the exact pre-preview global theme. Apply persists the profile and active id together without altering unrelated settings.
- [x] Retain High Contrast as a validated overlay; reject edits that violate its existing thresholds rather than silently reducing contrast. In Standard mode, keep explicit contrast feedback visible in the editor.
- [ ] Automated multi-window/restart/reset/delete, installed-wheel loading, and offscreen Paper/Slate review passed. Native palette and color-dialog qualification remains open; a Cocoa System-preview equality failure is under investigation.

**Commit:** `feat: add packaged and editable theme profiles` after the isolated theme tests pass.

## Task 8: Noto fallback and broader LTR text support — BF-006

**Files:** modify `src/uniti/ui/font_policy.py`, `src/uniti/ui/text_view.py`, `src/uniti/ui/regex_input.py`, `src/uniti/ui/capture_report_delegate.py`, and `pyproject.toml`; create `src/uniti/ui/assets/fonts/manifest.json` and licensed font resources. Tests: `tests/ui/test_font_policy.py`, `tests/ui/test_text_view_contract.py`; create `tests/ui/test_multilingual_text.py`. Extend the existing benchmark scenarios for representative mixed-script text.

**Proposed initial coverage:** Latin/Cyrillic via Noto Sans Mono; Devanagari, Bengali, Gujarati, Gurmukhi, Kannada, Malayalam, Odia, Tamil, Telugu through their Noto Sans families; Simplified/Traditional Chinese and Korean through appropriate Noto CJK regional families. Verify every named script before claiming it supported. RTL and mixed-direction editing remain outside scope.

**Architecture:** register bundled fonts per application, not into the host OS. Keep Latin fixed-pitch facts separate from fallback coverage. Shape visible text with Qt and derive painting, cursor placement, selection, hit testing and wrapping from compatible layout boundaries; installing more glyphs alone does not establish correct editing.

- [x] Resolve exact upstream font files from the official Noto repositories during execution; pin revision, SHA-256, family/region, supported script and license in the manifest. Package complete upstream notices. The 13-face payload is 19,683,928 bytes and uses no runtime downloads.
- [x] Add clean-environment tests that load only the bundled resources and prove representative glyph coverage for each script. Assert a missing required asset reports a bounded capability failure rather than silently claiming coverage.
- [x] Audit code-point versus UTF-16 indices and fixed-cell assumptions in painting, selection, cursor movement, hit testing, horizontal windows, and wrap rows. Preserve code-point document offsets through explicit layout conversion; do not split surrogate pairs or corrupt combining sequences.
- [x] Add synthetic mixed-script cases covering Indic vowel signs/conjuncts, CJK full-width text, Hangul, Latin, emoji, tabs and zero-width characters. Test typing, selection, copy, deletion, undo/redo, save/reopen, and navigation against the documented code-point/grapheme behavior.
- [x] Define user cursor/backspace movement at extended-grapheme boundaries while keeping the document's code-point storage. Preserve exact single-code-point Unicode inspection; document where Unicode graphemes do not equal script syllables.
- [ ] Shaping/layout under zoom, scrolling and wrap passed focused and unchanged point-performance gates; the mixed-script scenario also passed. Native Chinese/Korean IME composition, commit and cancellation on Windows/macOS/Linux remains required.
- [x] Re-run theme, gutter, whitespace and Match coverage with final fallback fonts. The complete source suite, native targeted suite, deep self-check and combined smoke passed; physical native IME qualification remains separate.

**Commit series:** font resources/policy; necessary layout corrections with regressions; native input and packaging evidence. Each commit must preserve existing Latin/Cyrillic behavior.

## Task 9: Freeze the feedback candidate and integrate into main

**Files:** all accepted feature/fix commits; update `docs/project/BETA_FEEDBACK.md`, current status/scope/architecture/development/handover, and this task checklist.

- [x] Integrate each reviewed in-scope fix or feature commit/series into local canonical `main` through source candidate `3e20214`, preserving separate review boundaries and A22 version/milestone metadata while the [A22 plan](v0.001a22-dogfood-performance-implementation.md), [A23 plan](v0.001a23-executable-health-recovery-implementation.md), [A24 gate](v0.001a24-beta-candidate.md), and [B1 plan](v0.001b1-real-world-feedback-beta-implementation.md) remain open.
- [ ] Add the final reviewed documentation revision and synchronize the resulting `main` to the remote; record its exact integrated SHA without rewriting history.
- [x] Review the coverage table against the actual diff. Every BF implementation is present; physical/native/affected-host checks remain explicit and no item is closed merely because a commit exists.
- [x] Run one complete candidate gate after focused workstream gates. Candidate `3e20214` passed 1,646 tests with six expected platform skips in 95.63 seconds, compilation, 21/21 deep self-check, native/offscreen combined smoke, and diff checks.

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src scripts benchmarks tests
.venv/bin/python -m uniti --self-check --deep
QT_QPA_PLATFORM=offscreen .venv/bin/python -m uniti --smoke
QT_QPA_PLATFORM=cocoa .venv/bin/python -m uniti --smoke
git diff --check
```

- [x] Run the selected quick/baseline `scroll`, `typing`, and `giant_line` scenarios, the separate mixed-script scenario, and all four local hosted-profile sustained families against unchanged thresholds. Each selected scenario and every five-cycle-plus-warmup sustained family passed without contention on `3e20214`.
- [ ] Run the owned-runtime CI driver on Mac, Windows and both Linux lanes for `3e20214`, preserving exact skip policy. GitHub currently blocks jobs before execution; A23/A24/B1 bundle, clean-host, health/recovery, inventory and privacy gates remain governed by their open plans.
- [x] Build and inspect the wheel. The isolated install contains 40 exact resources—13 fonts, 11 SVGs, two themes, and 14 manifest/notice files—and renders mixed text and Find/Replace without a source checkout or network fallback.
- [ ] Build and qualify native distributions after the predecessor executable gates; the wheel inspection is not native distribution evidence.
- [x] Obtain independent review of the final source diff, especially durability/lifecycle, EOL save semantics, theme persistence and multilingual layout. Resolve blocking findings and re-run affected checks; final review on `3e20214` is clean.
- [x] Validate ancestry and fast-forward the reviewed source series through `3e20214` into local `main` without force-push, merge duplication, or history rewrite.
- [x] Verify final source candidate `3e20214` locally with the complete suite, compilation, deep self-check, native/offscreen smoke and wheel inspection.
- [ ] Push the final reviewed `main` revision and require all hosted lanes on that integrated commit. GitHub currently blocks new jobs before execution because of the reported account billing/payment or spending limit; do not represent that as a test failure or pass.
- [ ] Record the main SHA and evidence per feedback item. Preserve previous-candidate evidence as history.

## Task 10: Confirm B1 closure and advance the B2 identity

**Files:** `VERSION`, `src/uniti/__init__.py`, `pyproject.toml`, release/bundle manifests introduced by A23/B1, `README.md`, roadmap/current documents, and implemented-history indexes; create `tests/test_b2_identity.py`.

- [ ] Confirm the full predecessor chain and B1 closure are recorded before B2 release-identity promotion. B2-only feature code may already be integrated on `main`; do not count source-checkout reports or simulated days as qualifying independent executable feedback.
- [ ] Confirm Task 9's final integrated-candidate gate passed after all B2 features entered main. Under an explicitly revised source-beta policy, verify the recorded replacement gates and label the evidence accordingly.
- [ ] Add a failing identity test covering all three canonical version sources. Update display identity to `v0.001b2` and package identity to `0.1b2` in a separate promotion commit. Use static metadata parsing if the test runtime still has pre-promotion package metadata.

```python
from pathlib import Path
import tomllib
import uniti

assert Path("VERSION").read_text().strip() == "v0.001b2"
assert uniti.__display_version__ == "v0.001b2"
assert uniti.__version__ == "0.1b2"
assert tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"] == "0.1b2"
```

- [ ] Refresh the managed development installation through the existing bootstrap after the version bump; rerun metadata/launch tests. Rebuild B2-labelled distributions and tester information/manifests so embedded identities match the promotion SHA.
- [ ] Run source, hosted, clean-host and native smoke gates on the B2 promotion candidate, including upgrade from the previous tester settings/session. Document a rollback using the previous qualified build and copied state; do not require deleting sessions or automatic repair.
- [ ] Move only completed milestone/workstream records to implemented history, repair links, activate B2, and update current docs to the real product state. Keep BF-002 open if affected-host confirmation is still missing; that blocks readiness.

**Commit:** `chore: advance uniti to v0.001b2` after B1 closure and feedback implementation; qualification results follow as evidence commits. No automatic tag/public release.

## Task 11: Open the B2 testing round

- [ ] Prepare concise B2 notes mapping BF-001–BF-010 to changes and any explicit limitations, with launch/update instructions and the exact candidate identity.
- [ ] Supply qualified builds through the existing private distribution process only within the authorized scope. Do not send messages or files to testers without explicit authorization.
- [ ] Ask the affected Windows and Mac testers to repeat first start, ordinary close, explicit Quit/relaunch, whitespace/hold, EOL selection/save, F/R controls/Match rows, gutter sizing, theme persistence, and multilingual input.
- [ ] Start a separate B2 feedback section with the build identity and new observations. Do not overwrite B1 reports or treat historical passes as B2 human verification.

## Completion checklist

- [ ] Every BF-001–BF-010 requirement implemented and verified, or a clearly recorded user-approved scope change exists.
- [ ] Critical BF-002 closed on the affected Windows and Mac hosts.
- [ ] Canonical main contains the reviewed implementation and passes same-commit hosted gates.
- [ ] Formal predecessor gates passed, or an explicit replacement release-policy decision is recorded and satisfied.
- [ ] B2 identities, bundled resources, tester instructions and current documentation agree.
- [ ] B2-labelled builds qualify on required hosts; source-only testing is not represented as executable qualification.
- [ ] No public release/tag or tester communication inferred from this plan.

## Self-review

All ten feedback IDs are mapped above and implemented in the reviewed source candidate. The selected rulings retain the existing release gates and apply backslash-number labels to capture groups while preserving whole-match headers; their costs and reversal paths are explicit. Themes, fonts, report presentation and lifecycle remain separate reviewable workstreams. Physical IME, affected-host, executable, human-time and version-promotion prerequisites remain linked to their governing plans and are not represented as complete.
