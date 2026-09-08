# UNITI Beta Feedback Log

Started: 2026-09-07

This log collects summarized user observations for later triage, planning, and action. An entry is not an approved implementation commitment. Early source-checkout feedback does not open or satisfy the [B1 feedback gate](02_plans/v0.001b1-real-world-feedback-beta.md).

Planning update, 2026-09-08: the [B1 feedback closure and B2 transition plan](02_plans/2026-09-08-b1-feedback-b2-transition-plan.md) covers BF-001–BF-010, and its proposed successor scope is recorded in the [B2 Feedback Refinement Beta milestone](02_plans/v0.001b2-feedback-refinement-beta.md). The existing executable release policy is retained. A22 real-use days, A23 executable/health delivery, A24 qualification, and B1 private executable human feedback remain prerequisites; preparing these records does not close an entry, complete B1, or change the A22 release identity.

## 2026-09-08 execution and evidence map

| Feedback | Planned task | Current evidence state | Remaining gate |
|---|---:|---|---|
| BF-001 | 2 | Progress and warning corrections implemented, reviewed, and on GitHub `main` | Affected Windows first-use confirmation; hosted qualification still running |
| BF-002 | 3 | Corrections and platform-fixture follow-ups on GitHub `main`; macOS source checks passed | Affected Windows/Mac distribution and confirmation remain open |
| BF-003 | 4 | Compact inspection and centered U+0020 marker implemented, reviewed, and on GitHub `main` | Native Windows and affected-host beta confirmation |
| BF-004 | 4 | Configuration implemented locally | Cross-window/restart and Windows/affected-host evidence |
| BF-005 | 7 | `NOT RUN` | Editable themes, presets, persistence, contrast qualification |
| BF-006 | 8 | `NOT RUN` | Selected Noto packaging, shaping, navigation, and IME qualification |
| BF-007 | 6 | Initial Lucide controls implemented locally | F>/R>, clear/navigation reconciliation and native evidence |
| BF-008 | 6 | Capture-group interpretation approved; implementation `NOT RUN` | Preserve `Match N of M`; implement and verify aligned group rows |
| BF-009 | 5 | `NOT RUN` | 80% gutter typography and zoom/layout qualification |
| BF-010 | 5 | `NOT RUN` | Pending-versus-current EOL wording and post-save view refresh |

Fresh baseline evidence on checkpoint `5724f6c` is 1,476 passed with six platform-policy skips in 93.01 seconds; native Cocoa combined smoke passed explicit Quit and session restore. The reviewed integration checkpoint `c7c1521` is synchronized between local `main` and GitHub `origin/main`; it contains the BF-001 startup work, the BF-003 centering work, and Windows qualification-fixture corrections for UTF-8 source decoding, exact LF bytes, and platform runtime-path selection. Hosted run `34250570707` is still in progress and is not recorded as passing. These checks do not replace any remaining feedback gate or predecessor milestone evidence.

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
- Disposition: requested progress and warning behavior implemented at `63dab08` and included in synchronized checkpoint `c7c1521`. Keep the affected Windows first-use flow open until confirmed; hosted run `34250570707` remains in progress.

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
- Integration update, 2026-09-08: local `main` and GitHub `origin/main` both point to `c7c1521`, which contains these lifecycle corrections and the later Windows qualification-fixture corrections. Hosted run `34250570707` is still in progress; synchronization is not affected-host confirmation or a hosted green result.
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
- Status: implemented locally; native Windows and affected-host beta confirmation pending.
- Menu access: the top-level **Hotkeys** entry opens the existing modeless command configuration panel. **Editor View → Hold to inspect Unicode** now exposes the shared inspection combination.
- Configuration: native platform modifier labels, Apply Hold Shortcut, Reset Hold Shortcut, and current/default display. Choose at least two distinct modifiers, or clear all to disable. Category/all resets also restore this setting.
- Persistence: the portable combination is saved in settings and applied to existing and newly opened editor views. Invalid stored values fall back to the default. Inspection uses a modifier-only hold gesture and does not consume ordinary command events.
- Shutdown confirmation: the existing **File → Quit** action requests service shutdown; Qt can place Quit in the native application menu on macOS. Closing the last editor window retains the visible empty editor, as requested in BF-002.
- Verification: configuration tests cover assignment, invalid combinations, reset, disabled inspection, persisted reload, effective custom bindings, and presence of Quit/Hotkeys actions.

## BF-005 — Theme editing and more packaged themes

- Reported: 2026-09-07.
- Status: recorded for later planning and action; implementation pending.
- Environment: UNITI desktop on Windows PC and macOS.
- Request: allow users to edit themes and provide more ready-to-use packaged themes.
- Existing capability: System, Light, and Dark appearance modes, with separate Standard and High Contrast options. These settings do not currently expose a theme editor or a broader collection of named presets.
- Planning scope: define editable colors and other appearance properties, choose the initial packaged theme collection, and determine how users preview, save, select, and reset custom themes. Exact presets and editing controls have not yet been specified.
- Related feedback: include whitespace markers and temporary Unicode detail from BF-003 when assessing readability across themes.
- Companion icon choice: the user approved [Lucide](https://lucide.dev/) SVG assets for interface actions and chose Find/Replace as the starting point; implementation tracked in BF-007. Treat interface icons separately from Unicode glyphs representing document characters.
- Disposition: retained for later triage; no theme implementation changes made.

## BF-006 — Broader left-to-right font support: Indian scripts, Chinese, and Korean

- Reported: 2026-09-07.
- Status: recorded for later planning and action; implementation pending.
- Environment: UNITI desktop on Windows PC and macOS.
- Request: expand font support beyond Latin and Cyrillic to more left-to-right scripts, particularly those used in India. The user subsequently added Chinese and Korean.
- Scope constraint: left-to-right support only for this phase. The user explicitly deferred right-to-left support; RTL and mixed-direction editing are outside this planned expansion for now.
- Preferred font collection: the user endorsed **Noto**. Evaluate Noto Sans Mono for Latin/Cyrillic, the appropriate Noto Sans families for Indian scripts, and regional Noto Sans Mono CJK variants for Chinese and Korean. Noto is a collection of complementary fonts; exact files, weights, fallback ordering, and packaging remain planning decisions. See the [Noto family guidance](https://notofonts.github.io/noto-docs/website/use/) and [CJK distribution guide](https://github.com/notofonts/noto-cjk/blob/main/Sans/README.md).
- Existing capability: the editor font policy selects a concrete fixed-pitch font and checks representative Latin and Cyrillic coverage. Coverage and editing behavior for additional scripts have not been established by those checks.
- Planning scope: agree the initial script priorities; candidates include Devanagari, Bengali, Gujarati, Gurmukhi, Kannada, Malayalam, Odia, Tamil, and Telugu. These are planning examples, not a confirmed support list. Assess suitable fonts, fallback behavior, and whether any fonts should be packaged with UNITI.
- Chinese and Korean scope: assess Han character coverage for Simplified and Traditional Chinese, and Hangul coverage for Korean; clarify any additional Hanja requirements during planning. Include font fallback, mixed Latin/Asian text, and full-width character layout.
- Validation scope: verify shaping and combining marks as well as glyph availability; test mixed-script text, cursor movement, selection, deletion, wrapping, and line metrics on Windows and macOS. Check that the current fixed-pitch assumptions accommodate the selected scripts.
- Input validation: include Chinese and Korean IME composition, candidate selection, commit, and cancellation, checking that composition and committed text display correctly without disturbing document contents or cursor positions.
- Related feedback: single-character Unicode inspection in BF-003 must account for displayed characters composed of multiple code points when its behavior is defined.
- Disposition: retained for later triage; no font or text-layout implementation changes made.

## BF-007 — Lucide UI icons, starting with Find/Replace

- Reported: 2026-09-07.
- Status: implemented and verified locally; wider UI rollout remains future work.
- Request: implement Lucide for the UI. The user chose the Find/Replace panel as a good starting point.
- Follow-up reported 2026-09-08: consider SVG replacements for the F/R panel's `F>` and `R>` indicators, circled `(x)` clear controls, and `[<]` / `[>]` Previous/Next controls. Retain this as beta feedback for later review, using the agreed Lucide direction. Some clear/navigation controls already have SVG implementations locally; compare the running beta build and intended appearance before planning further changes. No UI changes made for this follow-up.
- Implemented scope: Lucide icons for Find All, Replace All, Previous/Next Match, Replace Current Match, per-field clear controls, Cancel, and the Match Report visibility toggle. Existing handlers, keyboard commands, compact button widths, tooltips, and accessible names remain available. Cancel keeps its text label.
- Assets: nine SVGs from Lucide 1.42.0, pinned to upstream commit `3859eb20fabe7fd95652fcd4395843b6c0bcdd01`, bundled with complete upstream ISC/MIT notices. Icons require no font installation or runtime download.
- Appearance: icons follow the application palette, including native disabled-state opacity, and render at the requested device pixel ratio. Independent review identified and verified a correction for translucent macOS palette colors.
- Validation: the final full suite passed 1,453 tests with six platform-specific skips after the separate BF-002 recovery scheduling correction. Native macOS icon checks and combined smoke passed. A built wheel includes all nine SVGs and upstream notices; wheel-only imports rendered the icons and panel successfully. Light, dark, and high-contrast previews were inspected. Windows native verification remains pending.
- Follow-up scope: other UI surfaces can adopt the shared icon renderer later. This change does not implement the whitespace visualization or font expansion requests.

## BF-008 — Match window label notation

- Reported: 2026-09-08.
- Status: capture-group interpretation approved; implementation pending.
- Request: in the Match window, use `\1 :` for the first match, `\2 :` for the second, and so on.
- Approved interpretation, 2026-09-08: apply the backslash-number notation to capture-group rows, where the numbering already denotes regex capture groups. Preserve the existing `Match N of M` whole-match occurrence headers.
- Alignment: use a shared tab stop after the label so matched content starts in the same column on every row, including labels with multiple digits.
- Disposition: the default scope is approved for plan execution; aligned report layout and label implementation remain pending. No UI or matching behavior changes have been made for BF-008 yet.

## BF-009 — Smaller editor line numbers

- Reported: 2026-09-08.
- Status: recorded for later planning and action; implementation pending.
- Request: display editor line numbers at a smaller font size than the document text. The exact size or relative scale remains to be chosen.
- Disposition: retained as beta feedback; no rendering changes made.

## BF-010 — EOL markers unchanged when the status line updates

- Reported: 2026-09-08.
- Status: recorded for later triage, planning, and action.
- Observation: after changing EOL, the bottom status/reporting line updates, but the visible EOL characters in the editor view remain unchanged.
- Expected behavior: make the relationship between the selected EOL setting, the status line, and the displayed line-ending markers consistent and clear.
- Evidence limits: source/target EOL types, whether the document had been saved, and the affected platform/build were not recorded. Later review should distinguish a pending conversion-on-save setting from the document's current line endings.
- Disposition: retained as beta feedback; no diagnosis or implementation changes made.
