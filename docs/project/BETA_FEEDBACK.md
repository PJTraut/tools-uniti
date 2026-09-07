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
