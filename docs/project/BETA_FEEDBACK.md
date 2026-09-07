# UNITI Beta Feedback Log

Started: 2026-09-07

This log collects summarized user observations for later triage, planning, and action. An entry is not an approved implementation commitment. Early source-checkout feedback does not open or satisfy the [B1 feedback gate](02_plans/v0.001b1-real-world-feedback-beta.md).

Use sequential `BF-NNN` identifiers. Record the report date, environment, observation, impact, evidence limits, and later disposition. Keep personal information, machine identifiers, user paths, and raw reports out of this log. Link any subsequently approved work and verification to its entry.

## BF-001 — Slow Windows first launch with limited progress feedback

- Reported: 2026-09-07.
- Status: awaiting triage; retained for later planning and action.
- Environment: remote Windows host; first launch from a source checkout using `uniti.bat`. Exact build, Python version, Windows version, and elapsed time were not recorded.
- Observation: user reported that the first start was very slow. A Python warning about a return statement inside a finally block appeared during startup.
- Impact: the initial wait and warning made it unclear whether setup was progressing or startup had failed.
- Requested behavior: show a visible message during first-use initialization, before lengthy preparation begins. Suggested wording from the user: `// prepping UNITI for first use`.
- Evidence: user clarified that this was the first start. Repository inspection shows bootstrap captures dependency-installation output instead of streaming progress. The cause of the reported delay has not been measured, and the warning has not been established as its cause.
- Later review: measure first-run setup and subsequent-launch timing; assess setup progress/status messaging; review the startup warning separately from performance.
- Disposition: no implementation scheduled; priority and acceptance criteria await triage.

## BF-002 — Windows and macOS terminals remain occupied after exit

- Reported: 2026-09-07.
- Severity: critical; blocks further user testing.
- Status: local corrections verified; distribution and affected-host confirmation pending. Remains a critical testing blocker.
- Environment: reported on both Windows PC and Mac. The Windows launch used `uniti.bat` on a remote host, as in BF-001; the Mac launch command was not recorded. Exact builds and runtime versions were not recorded.
- Observation: user reported that on EXIT the terminal still hangs and UNITI does not release it.
- Exit clarification: both explicit application Quit and window-close cause the reported problem on Mac; explicit application Quit causes it on Windows PC.
- Follow-up reported: after closing the occupied terminal, opening a new terminal, and launching UNITI again, startup fails. The supplied Windows transcript shows an active `.venv` and a launch via `uniti.bat`; the user also references the Mac `.command` launcher, but no Mac error transcript was supplied.
- Relaunch failure: startup reports `SESSION_RESTORE: unexpected internal startup failure`, suggests `python scripts/bootstrap.py --repair`, and returns to the command prompt. No repair attempt or outcome was reported.
- Impact: the launching terminal does not return to an available command prompt after the user exits UNITI.
- Additional impact: the next launch can fail after the user closes the occupied terminal.
- Expected behavior: exiting UNITI completes shutdown and returns control to the launching terminal.
- Clarified window-close behavior: while the service remains active, retain a visible editor window so users can open documents and see UNITI is running. Closing the last window resolves its tabs and leaves an empty window; explicit Quit ends the service and releases the terminal.
- Confirmed startup cause on Mac: startup logs identify an assertion when restoring a session with no windows. Local commit `fadc36f` replaces that assertion with a new-window fallback. A read-only remote check found GitHub `main` at `ca75966`, without that fix.
- Confirmed Quit defect: with background work paused, the scheduler deferred the foreground final session write, and the publication queue could wait indefinitely for an older deferred write. Regression tests reproduced both waits.
- Local correction: foreground tasks bypass background pause; Quit cancels superseded session writes only before execution and waits for any running atomic write. Resumed tasks mark their public future running at worker entry, preventing cancelled queued work from executing or an active write from being mistaken for cancelled work.
- Validation: regression coverage includes foreground session publication during pause, Quit with and without a queued paused write, cancellation before/after resumed execution, and full-process Quit/relaunch plus abrupt termination after a zero-window session. Native macOS checks passed for paused Quit, ordinary Quit, terminal-termination simulation, and relaunch; deep self-check passed all 21 checks. Independent review verified the resumed-write race correction.
- Full local gate after the retained-window correction: 1,446 tests passed with six platform-specific skips on macOS; source compilation, documentation links, and `git diff --check` passed. Offscreen/native combined smoke and all 21 deep self-checks passed. Native macOS process checks covered retained-window close followed by Quit, paused Quit, abrupt termination and relaunch, and legacy zero-window restoration. The skips include Windows launcher/native-path checks, so this is not Windows verification.
- Local window-close correction: the last editor window remains visible with Open and Quit available, and its timers and file operations stay active. Ordinary close preserves all tabs while session restoration is pending. A failed Quit followed by window-close cannot delete the retained window through a closed publication-queue error.
- Remaining uncertainty: the Windows commit and underlying exception were not supplied. Paused background work reproduces a Quit hang locally, but has not been confirmed as the trigger on the affected hosts.
- Next action: distribute the zero-window startup, Quit, and retained-window corrections and verify the user's actual flows on Windows and macOS. Do not clear the blocker solely on local checks.
- Resolution gate: explicit Quit returns control to the terminal and releases the service; relaunch after terminal closure succeeds with preserved session/recovery state. Verify the reported flows on both Windows and macOS before clearing the testing blocker.

## BF-003 — Refine visible whitespace using InDesign as a reference

- Reported: 2026-09-07.
- Status: reference comparison and user requirements recorded for later planning and action; implementation pending.
- Environment: Windows PC and macOS; default held combination also specified for Linux.
- Request: improve UNITI's visible whitespace, informed by Adobe InDesign's hidden-character display.
- Reference: Adobe's [hidden-character glossary](https://helpx.adobe.com/indesign/desktop/language-and-proofing/glyphs-characters-and-expressions/hidden-character-glossary.html) documents compact marks including `·` for ordinary spaces, `»` for tabs, `¶` for paragraph ends, and `↵` for soft returns, with distinct symbols for special spaces. Adobe's [display guidance](https://helpx.adobe.com/indesign/desktop/language-and-proofing/glyphs-characters-and-expressions/view-or-show-hidden-characters.html) describes nonprinting marks displayed in the layer color.
- Current UNITI rendering: spaces use dots, tabs use a drawn arrow across their width, line endings use `LF`/`CRLF`/`CR` labels, and invisible Unicode uses bordered text badges such as `NBSP` and `ZWSP`. Badge width can exceed the character's layout width and paint over neighboring text.
- Proposed direction: compact symbols with consistent theme-aware marker color, preserving text layout and avoiding overlapping badges. Keep precise character identity accessible through inspection and retain the distinction between LF, CRLF, and CR.
- User clarification — preserve Unicode detail: show compact markers normally, and temporarily reveal detailed Unicode labels while a key combination is held. Restore compact markers when the combination is released; this is a hold action, not a toggle.
- Selected default: `Ctrl+Alt` on Windows/Linux and `Cmd+Option` on macOS. The user selected this option over `Shift+Alt` / `Shift+Option`.
- Whitespace filtering: the current whitespace setting controls which whitespace overlays appear in both compact and detailed views. Off remains off; EOL, Spaces & Tabs, Invisible Unicode, and All retain their category boundaries. Holding the combination must not enable every category or change the saved whitespace mode.
- Single-character inspection: the same held combination must also display Unicode information for a single selected character, including an ordinary visible character. Preserve the selection and document contents. Multi-character selection behavior and the treatment of a displayed character composed of multiple Unicode code points need definition during planning.
- Detail presentation: retain exact character identity, with code point information available for single-character inspection. Decide the placement of temporary detail so it remains readable without obscuring adjacent text. Selected-character inspection is a separate use of the same gesture; whitespace overlays continue to follow the selected whitespace setting.
- Interaction acceptance: release of either required modifier ends inspection; leaving the application must not leave the detailed display stuck on. The gesture must not edit text, move the cursor, alter selection, or persist a temporary inspection state.
- Related configuration request: expose this held combination in the Hotkeys configuration panel; tracked in BF-004.
- Symbol-font recommendation for planning: evaluate [Noto Sans Symbols](https://notofonts.github.io/noto-docs/specimen/NotoSansSymbols/) and [Noto Sans Symbols2](https://notofonts.github.io/noto-docs/specimen/NotoSansSymbols2/) as companion Unicode symbol fonts. For compact whitespace overlays, consider drawing simple dots, arrows, and zero-width indicators directly for controlled sizing and alignment. Exact glyph mappings remain to be chosen and verified; displayed markers must not replace document characters.
- Semantic boundary: InDesign distinguishes paragraph and soft-return semantics; these must not be assumed equivalent to UNITI's physical line-ending encodings. Automatic visual wrapping must not appear as an inserted break.
- Next review: choose the exact symbols and detail presentation, then verify every whitespace mode with the combination held/released, single-character selection, special and zero-width spaces, adjacent invisible runs, mixed line endings, soft wrapping, zoom, and light/dark/high-contrast themes within the existing visible-rendering budget. Verify native modifier behavior on Windows and macOS.
- Disposition: requirements retained in beta feedback as requested; no rendering or input behavior change made yet.

## BF-004 — Configure the Unicode inspection combination in Hotkeys

- Reported: 2026-09-07.
- Status: recorded for later planning and action; implementation pending.
- Environment: Windows PC and macOS, with portable shortcut settings.
- Request: provide a hotkey configuration panel, including configuration of the shared held combination for whitespace detail and single-character Unicode inspection from BF-003.
- Existing capability: UNITI already has a top-level Hotkeys entry opening a modeless configuration panel with command categories, Default/Current bindings, assignment, clearing, collision reporting, and reset controls. The new held inspection gesture is not currently exposed there.
- Proposed extension: add a clearly labeled hold-to-inspect setting under Editor View in the existing panel. Display native platform modifier names, allow the combination to be changed, and provide reset to the selected default (`Ctrl+Alt` on Windows/Linux; `Cmd+Option` on macOS).
- Expected behavior: persist the configured combination across launches and apply it consistently to open and newly opened editor views. Explain that the keys must remain held and that whitespace detail respects the whitespace setting. Both whitespace detail and single-character inspection use the same configured combination.
- Planning checks: distinguish a modifier-only held gesture from an ordinary command shortcut; validate allowed combinations and interactions with existing shortcuts; ensure configuration and resets do not alter document contents or leave inspection active.
- Disposition: extend the existing panel when BF-003 is planned; no hotkey configuration changes made yet.

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
- Implemented scope: Lucide icons for Find All, Replace All, Previous/Next Match, Replace Current Match, per-field clear controls, Cancel, and the Match Report visibility toggle. Existing handlers, keyboard commands, compact button widths, tooltips, and accessible names remain available. Cancel keeps its text label.
- Assets: nine SVGs from Lucide 1.42.0, pinned to upstream commit `3859eb20fabe7fd95652fcd4395843b6c0bcdd01`, bundled with complete upstream ISC/MIT notices. Icons require no font installation or runtime download.
- Appearance: icons follow the application palette, including native disabled-state opacity, and render at the requested device pixel ratio. Independent review identified and verified a correction for translucent macOS palette colors.
- Validation: the final full suite passed 1,453 tests with six platform-specific skips after the separate BF-002 recovery scheduling correction. Native macOS icon checks and combined smoke passed. A built wheel includes all nine SVGs and upstream notices; wheel-only imports rendered the icons and panel successfully. Light, dark, and high-contrast previews were inspected. Windows native verification remains pending.
- Follow-up scope: other UI surfaces can adopt the shared icon renderer later. This change does not implement the whitespace visualization or font expansion requests.
