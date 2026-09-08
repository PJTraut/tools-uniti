# UNITI Beta Feedback Log

Started: 2026-09-07

This log records summarized user observations, implementation dispositions, verification, and remaining qualification. An entry is not an approved implementation commitment. Early source-checkout feedback does not open or satisfy the [B1 feedback gate](02_plans/v0.001b1-real-world-feedback-beta.md).

The B2 anchor report is resolved as expected engine behavior in [BF-011](#bf-011--make-raw-regex-flags-and-line-anchors-explicit); the resulting [regex guide](../regex-flags.md) explains the defaults.

Current identity: `v0.001b2` / `0.1b2`, advanced from A22 at the user's direction under [ADR-0007](05_decisions/ADR-0007-beta-source-version-and-qualification.md). All reviewed BF-001–BF-010 source changes through `3e20214` are committed and integrated on GitHub `main`. The [feedback transition plan](02_plans/2026-09-08-b1-feedback-b2-transition-plan.md) records implementation and remaining checks.

B2 is the active source beta. A22 real-use, A23 executable/health delivery, A24 stabilization, and B1 independent executable feedback remain open release qualification. Version promotion does not close affected-host or native input checks. [Current Status](01_current/STATUS.md) owns the exact baseline and latest evidence.

## 2026-09-08 execution and evidence map

| Feedback | Planned task | Current evidence state | Remaining gate |
|---|---:|---|---|
| BF-001 | 2 | Flushed first-use progress and durability-warning correction reviewed and integrated on `main` | Affected Windows first-use confirmation |
| BF-002 | 3 | Startup, Quit, retained-window, and recovery-scheduling corrections integrated on `main` | Distribute and confirm explicit Quit/relaunch on the affected Windows and Mac hosts |
| BF-003 | 4 | Compact inspection and centered U+0020 marker reviewed and integrated on `main` | Native Windows and affected-host confirmation |
| BF-004 | 4 | Hotkey access, persistence, reset/disable, and existing/new-window propagation integrated on `main` | Native Windows/AltGr and affected-host confirmation |
| BF-005 | 7 | Paper/Slate profiles, custom editor/storage, and the native System-preview palette correction reviewed and integrated on `main` | Broader physical native rendering and color-dialog qualification |
| BF-006 | 8 | Bundled Noto fallback and bounded shaped LTR editing reviewed and integrated on `main` through `3e20214`; complete local gate passed | Native Windows/macOS/Linux IME qualification and same-commit hosted gate |
| BF-007 | 6 | Full Find/Replace Lucide control set reviewed and integrated on `main` | Native affected-host visual confirmation |
| BF-008 | 6 | `\\N :` capture rows with aligned content, preserving `Match N of M`, reviewed and integrated on `main` | Native affected-host visual/accessibility confirmation |
| BF-009 | 5 | 80% gutter typography and progressive wrapped-row width reviewed and integrated on `main` | Manual affected-host visual confirmation |
| BF-010 | 5 | Current/on-save EOL wording and all-view post-save refresh reviewed and integrated on `main` | Manual affected-host confirmation |

Historical starting-checkpoint evidence on `5724f6c` is 1,476 passed with six platform-policy skips in 93.01 seconds; native Cocoa combined smoke passed explicit Quit and session restore. Candidate `3e20214` contains the complete reviewed feedback code series, including the native System-preview correction and Task 8's wrapped-row-seam IME fix; its complete local suite passed 1,646 tests with six expected skips. The latest hosted-green checkpoint remains `aab3f3c`: run `34253008439` passed all four macOS, Windows, Linux/Python 3.12, and Linux/latest lanes, including full suite, native/offscreen smoke, deep self-check, and sustained checks. Later runs `34253913469`, `34253932056`, `34256598416`, and [run `34256794807`](https://github.com/PJTraut/tools-uniti/actions/runs/34256794807) on `23507ca` did not execute because GitHub reported an account billing/payment or spending-limit block; no gate was weakened. These checks do not replace native IME, affected-host, or predecessor milestone evidence.

Use sequential `BF-NNN` identifiers. Record the report date, environment, observation, impact, evidence limits, and later disposition. Keep personal information, machine identifiers, user paths, and raw reports out of this log. Link any subsequently approved work and verification to its entry.

## BF-001 — Slow Windows first launch with limited progress feedback

- Reported: 2026-09-07.
- Status: implemented, independently reviewed, and integrated on GitHub `main`; affected Windows first-use confirmation remains open.
- Environment: remote Windows host; first launch from a source checkout using `uniti.bat`. Exact build, Python version, Windows version, and elapsed time were not recorded.
- Observation: user reported that the first start was very slow. A Python warning about a return statement inside a finally block appeared during startup.
- Impact: the initial wait and warning made it unclear whether setup was progressing or startup had failed.
- Requested behavior: show a visible message during first-use initialization, before lengthy preparation begins. Suggested wording from the user: `// prepping UNITI for first use`.
- Implementation: commit `63dab08` emits the exact flushed stderr line `// prepping UNITI for first use` before runtime creation, source-runtime adoption, or the first dependency installation. Callbacks report only real creation/adoption/repair, installation, validation, and launch boundaries. Explicit repair uses repair wording; healthy launches remain quiet; `--no-launch` output and JSON stdout remain parseable.
- Warning correction: the durability cleanup no longer returns from `finally`. Expected open/fsync failures and close failures retain their established result behavior, while an unexpected fsync exception still propagates if close also fails.
- Verification: the focused bootstrap, durability, and launcher gate passed 68 tests with four Windows-only skips. The full source suite passed 1,488 tests with six platform-policy skips; deep self-check passed all 21 checks; native Cocoa combined smoke passed. The durability source compiled with `SyntaxWarning` promoted to an error on the owned Python 3.12 runtime and Python 3.14. Independent review found no remaining blocking issue.
- Evidence limits: single-machine timing observations were 14.06 seconds for a disposable fresh source bootstrap and 1.32 seconds for a healthy managed JSON self-check launch. These are local macOS observations, not performance thresholds or affected-Windows confirmation. The warning was corrected separately from the unmeasured cause of the user's delay.
- Disposition: requested progress and warning behavior implemented at `63dab08` and included in hosted-green synchronized checkpoint `aab3f3c`. Keep the affected Windows first-use flow open until confirmed.

## BF-002 — Windows and macOS terminals remain occupied after exit

- Reported: 2026-09-07.
- Severity: critical; blocks further user testing.
- Status: corrections integrated on GitHub `main`; distribution and affected-host confirmation pending. Remains a critical testing blocker.
- Environment: reported on both Windows PC and Mac. The Windows launch used `uniti.bat` on a remote host, as in BF-001; the Mac launch command was not recorded. Exact builds and runtime versions were not recorded.
- Observation: user reported that on EXIT the terminal still hangs and UNITI does not release it.
- Exit clarification: both explicit application Quit and window-close cause the reported problem on Mac; explicit application Quit causes it on Windows PC.
- Follow-up reported: after closing the occupied terminal, opening a new terminal, and launching UNITI again, startup fails. The supplied Windows transcript shows an active `.venv` and a launch via `uniti.bat`; the user also references the Mac `.command` launcher, but no Mac error transcript was supplied.
- Relaunch failure: startup reports `SESSION_RESTORE: unexpected internal startup failure`, suggests `python scripts/bootstrap.py --repair`, and returns to the command prompt. No repair attempt or outcome was reported.
- Impact: the launching terminal does not return to an available command prompt after the user exits UNITI.
- Additional impact: the next launch can fail after the user closes the occupied terminal.
- Expected behavior: exiting UNITI completes shutdown and returns control to the launching terminal.
- Clarified window-close behavior: while the service remains active, retain a visible editor window so users can open documents and see UNITI is running. Closing the last window resolves its tabs and leaves an empty window; explicit Quit ends the service and releases the terminal.
- Confirmed startup cause on Mac: startup logs identify an assertion when restoring a session with no windows. Commit `fadc36f` replaces that assertion with a new-window fallback. Historical source state from earlier on 2026-09-08: a read-only remote check found GitHub `main` at `ca75966`, before that fix was integrated.
- Confirmed Quit defect: with background work paused, the scheduler deferred the foreground final session write, and the publication queue could wait indefinitely for an older deferred write. Regression tests reproduced both waits.
- Correction verified locally before integration: foreground tasks bypass background pause; Quit cancels superseded session writes only before execution and waits for any running atomic write. Resumed tasks mark their public future running at worker entry, preventing cancelled queued work from executing or an active write from being mistaken for cancelled work.
- Validation: regression coverage includes foreground session publication during pause, Quit with and without a queued paused write, cancellation before/after resumed execution, and full-process Quit/relaunch plus abrupt termination after a zero-window session. Native macOS checks passed for paused Quit, ordinary Quit, terminal-termination simulation, and relaunch; deep self-check passed all 21 checks. Independent review verified the resumed-write race correction.
- Full local gate after the retained-window correction: 1,446 tests passed with six platform-specific skips on macOS; source compilation, documentation links, and `git diff --check` passed. Offscreen/native combined smoke and all 21 deep self-checks passed. Native macOS process checks covered retained-window close followed by Quit, paused Quit, abrupt termination and relaunch, and legacy zero-window restoration. The skips include Windows launcher/native-path checks, so this is not Windows verification.
- Window-close correction verified locally before integration: the last editor window remains visible with Open and Quit available, and its timers and file operations stay active. Ordinary close preserves all tabs while session restoration is pending. A failed Quit followed by window-close cannot delete the retained window through a closed publication-queue error.
- Additional finding during BF-007 verification: window-close smoke stalled when a recovery successor occupied the only admitted worker slot while waiting for its predecessor. The predecessor was waiting for admission on another worker. An isolated baseline reproducer confirmed that this scheduling race predates the Lucide changes.
- Additional correction verified locally before integration: serial recovery work is submitted only after its predecessor completes, preserving operation order without consuming a worker slot while waiting. The returned future retains running/cancellation/result behavior. Regressions verify worker availability with successful, failed, and cancelled predecessors; independent review also checked a long operation chain and cancellation before execution.
- Latest validation with BF-007: 1,453 tests passed with six platform-specific skips; native macOS combined smoke completed window-close, explicit Quit, and session restore. This does not replace verification on the affected Windows and Mac hosts.
- Historical integration update, 2026-09-08: local `main` and GitHub `origin/main` first synchronized at `aab3f3c`; the later complete feedback source candidate is `3e20214`, included in synchronized documentation checkpoint `23507ca`. Hosted run `34253008439` succeeded in all four lanes on `aab3f3c`, including full suite, native/offscreen smoke, deep self-check, and sustained checks. Repository synchronization and hosted automation are not affected-host confirmation.
- Remaining uncertainty: the Windows commit and underlying exception were not supplied. Paused background work reproduces a Quit hang locally, but has not been confirmed as the trigger on the affected hosts.
- Next action: distribute the zero-window startup, Quit, and retained-window corrections and verify the user's actual flows on Windows and macOS. Do not clear the blocker solely on local checks.
- Resolution gate: explicit Quit returns control to the terminal and releases the service; relaunch after terminal closure succeeds with preserved session/recovery state. Verify the reported flows on both Windows and macOS before clearing the testing blocker.

## BF-003 — Refine visible whitespace using InDesign as a reference

- Reported: 2026-09-07; implementation approved 2026-09-08 after comparison with the user-provided character table.
- Status: centered marker correction implemented, independently reviewed, and integrated on GitHub `main`; native Windows and affected-host beta confirmation pending.
- Follow-up reported 2026-09-08: the normal-space marker for U+0020 is not centered within the whitespace gap. Expected behavior: center the visible marker within the space's actual layout width. Exact host, font, and zoom were not recorded.
- Environment: Windows PC and macOS; default held combination also specified for Linux.
- Reference: Adobe's [hidden-character glossary](https://helpx.adobe.com/indesign/desktop/language-and-proofing/glyphs-characters-and-expressions/hidden-character-glossary.html) and the supplied character table informed the compact marks. UNITI keeps physical line-ending identity rather than adopting paragraph/soft-return semantics.
- Implemented ordinary marks: space `·`, tab `»`, LF `␊`, CR `␍`, CRLF `␍␊`. Automatic visual wrapping has no end-of-line marker.
- Implemented special marks: em/en spaces use different bar widths with dots; NBSP uses a caret; narrow NBSP a caret with dot; thin space a downward caret with dot; hair space two dots; ideographic space a box with dot. Zero-width space uses a stem with endpoint rings, non-joiner outward arrows, joiner a joining arch, word joiner an I-beam, and direction marks directional flags. BOM uses a diamond with dot; other invisible characters use a diamond. These are theme-aware drawings, independent of installed symbol fonts.
- Co-located invisible runs use a compact aggregate; held details retain each distinct character identity. Marker placement accounts for UTF-16 layout offsets after supplementary characters such as emoji.
- Held inspection: `Ctrl+Alt` on Windows/Linux and `Cmd+Option` on macOS temporarily shows a bounded Unicode key at the bottom of the viewport, listing visible marker types and their code points. Compact marks remain in place; adjacent labels do not overlap. Release of either required modifier or application deactivation hides the key.
- Whitespace filtering: Off, EOL, Spaces & Tabs, Invisible Unicode, and All retain their category boundaries during inspection. Holding the combination does not change the saved mode.
- Selected-character inspection: the same gesture shows the code point and Unicode name for exactly one selected code point in the focused editor, including ordinary visible text and supplementary characters, even with whitespace Off. Multi-code-point grapheme inspection remains future work.
- Display-only behavior: inspection preserves document contents, cursor, selection, and layout. Existing visible rendering and marker budgets remain in place. The key limits its rows and summarizes additional types when space is restricted.
- Scope boundary: screenshot autoreplace commands, font expansion, and RTL editing are not part of this implementation. Symbol-font evaluation remains under the broader font work.
- Configuration: see BF-004.
- Centering implementation: commit `1c2d25a`, with real-zoom regression correction `1d3660c`, replaces the offset point-plus-glyph rendering with a centered filled antialiased dot. The marker is centered in the actual U+0020 layout gap after the editor rebuilds its font metrics at 50%, 100%, 200%, and 300% zoom, at device-pixel ratios 1 and 2, including fractional bounds.
- Verification: the prescribed focused UI/settings/hotkey matrix passed all 87 tests. The eight zoom/display-scale centroid cases place both axes within 0.2 logical pixels of the gap midpoint; the prior rendering failed all eight horizontal cases. Existing coverage retains marker categories, inspection behavior, document bytes, cursor/selection behavior, theme tokens, and the 4,096-marker budget. The earlier full local suite passed 1,476 tests with six platform-specific skips, all 12 inspection tests passed on native macOS, and native combined smoke confirmed explicit Quit and session restore. Source compilation, changed-document local links, and `git diff --check` passed. Independent review found no remaining blocking issues. Commits `1c2d25a` and `1d3660c` are included in synchronized checkpoint `c7c1521`; Windows native modifier/rendering checks and affected-host beta confirmation remain pending.

## BF-004 — Configure the Unicode inspection combination in Hotkeys

- Reported: 2026-09-07; implementation approved 2026-09-08.
- Status: implemented, reviewed, and integrated on `main`; native Windows/AltGr and affected-host confirmation pending.
- Menu access: the top-level **Hotkeys** entry opens the existing modeless command configuration panel. **Editor View → Hold to inspect Unicode** now exposes the shared inspection combination.
- Configuration: native platform modifier labels, Apply Hold Shortcut, Reset Hold Shortcut, and current/default display. Choose at least two distinct modifiers, or clear all to disable. Category/all resets also restore this setting.
- Persistence: the portable combination is saved in settings and applied to existing and newly opened editor views. Invalid stored values fall back to the default. Inspection uses a modifier-only hold gesture and does not consume ordinary command events.
- Shutdown confirmation: the existing **File → Quit** action requests service shutdown; Qt can place Quit in the native application menu on macOS. Closing the last editor window retains the visible empty editor, as requested in BF-002.
- Verification: configuration tests cover assignment, invalid combinations, reset, disabled inspection, persisted reload, effective custom bindings, and presence of Quit/Hotkeys actions.

## BF-005 — Theme editing and more packaged themes

- Reported: 2026-09-07.
- Status: implemented, independently reviewed, and integrated on `main`; native qualification remains open.
- Environment: UNITI desktop on Windows PC and macOS.
- Request: allow users to edit themes and provide more ready-to-use packaged themes.
- Implementation: named Paper and Slate profiles join System/Light/Dark. **View → Theme → Edit Themes** can clone a profile, rename and edit every supported UI/editor color, preview across service windows and Find/Replace, then Apply, Cancel, Reset, or delete custom profiles. Packaged profiles are read-only and Standard/High Contrast remains an independent axis.
- Storage: one bounded schema-1 `theme-profiles.json` beside settings atomically stores custom profiles and the active selection. Invalid or damaged data falls back without rewriting the damaged file; profile limits are 32 custom profiles, 64-character names/ids, and 128 KiB total.
- Verification: 154 focused settings/theme/window/Find/Replace/icon tests passed; an installed-wheel, Qt-free check loaded Paper and Slate with all 32 roles; offscreen Paper/Slate visuals were reviewed. Hosted run `34253008439` passed all four lanes on `aab3f3c`. A separate native Cocoa check exposed a System-preview link-color leak; reviewed correction `e045b0f`, included in candidate `3e20214`, passed 21 native theme, five native window, and 30 offscreen tests. A clean native rerun on the integrated intermediate tree passed all 21 theme/editor tests. Broader native rendering and color-dialog qualification remains open.
- Related feedback: include whitespace markers and temporary Unicode detail from BF-003 when assessing readability across themes.
- Companion icon choice: the user approved [Lucide](https://lucide.dev/) SVG assets for interface actions and chose Find/Replace as the starting point; implementation tracked in BF-007. Treat interface icons separately from Unicode glyphs representing document characters.
- Disposition: implemented at `aab3f3c`; keep native qualification open after B2 source promotion.

## BF-006 — Broader left-to-right font support: Indian scripts, Chinese, and Korean

- Reported: 2026-09-07.
- Status: bundled fallback and shaped LTR editing implemented, independently reviewed, and integrated on GitHub `main` through `3e20214`; native input qualification remains open.
- Environment: UNITI desktop on Windows PC and macOS.
- Request: expand font support beyond Latin and Cyrillic to more left-to-right scripts, particularly those used in India. The user subsequently added Chinese and Korean.
- Scope constraint: left-to-right support only for this phase. The user explicitly deferred right-to-left support; RTL and mixed-direction editing are outside this planned expansion for now.
- Font implementation: 13 pinned official Noto faces and complete notices are bundled as application-only fallback, totaling 19,683,928 bytes. The platform-resolved monospace face remains primary and retains its fixed-pitch/Latin/Cyrillic facts. Han fallback order follows locale; plain text does not claim simultaneous SC/TC regional forms for the same code point.
- Covered scripts: representative glyph, shaping, editing, and rendering tests cover Devanagari, Bengali, Gujarati, Gurmukhi, Kannada, Malayalam, Odia, Tamil, Telugu, Simplified/Traditional Chinese, Korean, Latin/Cyrillic, tabs, and emoji. Emoji may use host fallback.
- Layout/editing: bounded Qt shaping now owns text, selection/match, hit-test, caret, tab, wrapping, and UTF-16 geometry. User navigation/deletion follows extended grapheme boundaries; explicit code-point selection and held inspection remain exact. IME surrounding/replacement offsets use UTF-16, and a virtual preedit row pans temporarily to keep the composition caret visible without changing document history, saved scroll, or wrap mode.
- Bounds: public windows remain at most 8,192 code points; horizontal work advances one window; shaped wrap emits at most 512 rows per request, caches at most 512 layouts, and retains the existing 2,048-row block bound. Cold deep variable-width positions may remain pending through several event-loop advances instead of publishing approximate geometry. Inherited logical-line indexing can still perform additional work.
- Verification: 211 expanded focused tests passed; the review-fix covering matrix passed 129 tests, and final rereview passed six targeted plus ten independent EOL-ownership probes. Candidate `3e20214` passed 1,646 tests with six expected skips. The unchanged scroll, typing, and giant-line performance gates passed with p95 medians 6.016, 10.055, and 3.623 ms; the 72-interaction mixed-script scenario passed with 4.428 ms p95 and 26.031 ms maximum. The exact 18.77 MiB font payload, hashes, notices, installed-wheel resources, and real Qt fallback ordering were independently reviewed.
- Qualification limit: synthetic IME tests do not certify physical Windows/macOS/Linux Chinese or Korean composition, commit, and cancellation. RTL and mixed-direction behavior remains outside scope. See the [LTR text layout contract](../../docs/ltr-text-layout.md).
- Disposition: implementation and the complete local gate are complete on source candidate `3e20214`, integrated on GitHub `main`; keep BF-006 open for native IME and same-commit hosted qualification.

## BF-007 — Lucide UI icons, starting with Find/Replace

- Reported: 2026-09-07.
- Status: complete Find/Replace control pass implemented, independently reviewed, and integrated on `main`; native affected-host confirmation remains open.
- Request: implement Lucide for the UI. The user chose the Find/Replace panel as a good starting point.
- Follow-up implementation: the remaining `F>`/`R>` labels now use search/replace SVGs, clear uses the complete circle-x glyph without duplicate painting, and existing Previous/Next SVG controls remain. Existing handlers, keyboard commands, compact targets, tooltips, accessible names, and Cancel text remain available.
- Assets: eleven SVGs from Lucide 1.42.0, pinned to upstream commit `3859eb20fabe7fd95652fcd4395843b6c0bcdd01`, bundled with complete upstream ISC/MIT notices. Git enforces exact LF asset bytes on Windows checkouts. Icons require no font installation or runtime download.
- Appearance: icons follow the application palette, including native disabled-state opacity, and render at the requested device pixel ratio. Independent review identified and verified a correction for translucent macOS palette colors.
- Validation: the affected Find/Replace/capture/icon suite passed 72 tests, and the asset follow-up passed eight icon tests plus a real `core.autocrlf=true` checkout regression. Hosted run `34253008439` passed all four lanes on `aab3f3c`. Windows checkout bytes are verified, while affected-host visual confirmation remains pending.
- Follow-up scope: other UI surfaces can adopt the shared icon renderer later. This change does not implement the whitespace visualization or font expansion requests.

## BF-008 — Match window label notation

- Reported: 2026-09-08.
- Status: capture-group interpretation and aligned layout implemented, independently reviewed, and integrated on `main`.
- Request: in the Match window, use `\1 :` for the first match, `\2 :` for the second, and so on.
- Approved interpretation, 2026-09-08: apply the backslash-number notation to capture-group rows, where the numbering already denotes regex capture groups. Preserve the existing `Match N of M` whole-match occurrence headers.
- Alignment: use a shared tab stop after the label so matched content starts in the same column on every row, including labels with multiple digits.
- Implementation: model roles expose label and preview separately. A bounded delegate measures one shared label column, so `\\1 :` through `\\100 :`, named-group metadata, and occurrence suffixes do not shift preview content. Display and accessible text remain complete and readable; `Match N of M` headers are unchanged.
- Disposition: implemented at `7a6ef08`; the 72-test affected Find/Replace/capture/icon suite passed. Native visual/accessibility confirmation remains open.

## BF-009 — Smaller editor line numbers

- Reported: 2026-09-08.
- Status: implemented, independently reviewed, and integrated on GitHub `main`; manual affected-host visual confirmation pending.
- Request: display editor line numbers at a smaller font size than the document text.
- Implementation: commit `14e6a5a` gives line numbers their own font and metrics at 80% of the editor point size while retaining the editor baseline and row height. Gutter width uses the actual gutter font and indexed line-number range, recalculates as progressive indexing advances, and rebuilds on zoom without changing editor text sizing, hit testing, or scroll steps.
- Review correction: commit `e2dbbae` settles gutter width before rendering wrapped rows when progressive indexing crosses a digit boundary. If the new width changes wrap columns, row preparation is rebuilt before painting or hit testing. A synthetic 100,019-line restoration regression verifies immediate six-digit fit at 300% zoom.
- Verification: the combined Task 5 focused matrix passed all 150 tests. Eight initial gutter regressions passed at 50%, 100%, 200%, and 300% zoom, covering smaller ink, six-digit fit, baseline/spacing, selection after scrolling, scroll steps, logical-line numbering under wrapping, and editor-font restoration. After the review correction, the focused gutter/wrap/view-state set passed 11 tests and the covering text-view/Unicode matrix passed all 64 tests. Independent review found no remaining blocking issue.
- Evidence limits: Qt rendering checks ran offscreen. Manual macOS Retina and affected-host visual acceptance remain pending. The later `8fae49d` portability correction retained the exact 80% point-size rule while allowing integer-pixel glyph-height rounding.
- Disposition: the approved 80% gutter scale and progressive six-digit width correction are included in hosted-green synchronized checkpoint `aab3f3c`. Keep manual affected-host confirmation open.

## BF-010 — EOL markers unchanged when the status line updates

- Reported: 2026-09-08.
- Status: diagnosed, implemented, independently reviewed, and integrated on GitHub `main`; manual affected-host confirmation pending.
- Observation: after changing EOL, the bottom status/reporting line updates, but the visible EOL characters in the editor view remain unchanged.
- Diagnosis: the conversion menu selects output policy for the next save; it does not immediately change current document bytes. Visible markers correctly continue to show the source line endings before save. Core save/reload authority already changed the document and its markers after a successful save, but sibling views could retain stale EOL reports, and the status wording did not clearly distinguish current encoding/EOL from the pending output policy.
- Expected behavior: before save, keep markers tied to the current document and state the pending conversion explicitly. After a successful save, refresh status, reports, and painted markers in every view that shares the document.
- Implementation: commit `8272daf` changes status wording to forms such as `UTF-8, LF (on save: UTF-8, CRLF)`. A successful save now cancels old EOL work, dismisses stale dialogs, replaces or invalidates cached reports, updates status, and repaints every shared-document view across service windows; incomplete bounded inspections schedule fresh analysis. Failed or cancelled saves retain current authority.
- Verification: the combined Task 5 focused matrix passed all 150 tests. EOL/save coverage includes two distinct views in separate service windows; LF, CR, CRLF, and mixed sources; every explicit target; synchronous and progressive saves across 24 combinations; real markers before and after save; exact saved/reopened bytes; shared report/status refresh; failed and cancelled saves; return to Keep Source; and mixed-byte preservation. Independent review found no remaining blocking issue.
- Evidence limits: the original report did not record source/target types, save state, platform, or build. Automated coverage establishes the corrected contract, while manual affected-host confirmation remains pending.
- Disposition: diagnosis and shared-view refresh implemented at `8272daf` and included in hosted-green synchronized checkpoint `aab3f3c`. Keep manual affected-host confirmation open.

## BF-011 — Make raw regex flags and line anchors explicit

- Reported: 2026-09-08, on B2.
- Observation: `^(\d+)\D([^\r\n]+)` returned zero matches while its `(?m)` form matched numbered lines; the user expected editor-style per-line anchors by default.
- Investigation: the supplied file begins with a heading rather than a digit. UNITI and its pinned regex engine both return zero anchored matches without multiline and 15 with it, including across small streaming windows. The initial three-line sample produces one match when it begins the document; a preceding heading produces zero. Native panel checks also confirmed cursor position does not alter these results.
- Disposition: resolved as expected raw engine behavior, acknowledged by the user. No regex behavior change is required.
- Documentation: the [Regex Flags Guide](../regex-flags.md) explains `i`, `m`, `s`, `x`, flag combinations/scopes, Unicode options, and strict document anchors. The [User Manual](../user-manual.md) and [User Cheat Sheet](../user-cheat-sheet.md) make the defaults and common workflows discoverable.

## BF-012 — Full Unicode case folding misses a match with one-character search windows

- Found: 2026-09-08 during documentation-example verification, on B2; this is an internal finding, not a user report.
- Status: open; no source correction is included in the documentation change.
- Reproduction: compile `(?fi)straße` or `(?V1)(?i)straße` and search `STRASSE` through `search_document(..., options=SearchOptions(window_chars=1))`. Direct engine matching returns `(0, 7)`; UNITI returns no matches.
- Evidence boundary: windows of 8 and the default 65,536 characters return the expected match. A default-window probe with 65,531 preceding ASCII characters also passes. A failure with the production default window has not been reproduced; the one-character-window result still requires investigation before claiming complete streaming equivalence for full case folding.
- Next action: isolate partial-match/context retention behavior, add a regression, and verify the eventual correction across boundary positions and unchanged search limits. The four standard flag examples and scoped/ASCII/Unicode-line-boundary examples are verified separately.
