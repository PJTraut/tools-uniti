# UNITI Current Handover

Captured: 2026-09-08

This is a continuation snapshot. [Current Status](../01_current/STATUS.md) owns the baseline and verification evidence; the [Documentation System](../00_governance/DOCUMENTATION_SYSTEM.md) defines authority.

## Current version and Git state

- Display/package identity: `v0.001a22` / `0.1a22`, consistent in `VERSION`, `src/uniti/__init__.py`, and `pyproject.toml`.
- Active milestone: A22 Dogfood / Performance Alpha. A21 Cross-Platform Alpha is the latest completed milestone.
- Complete reviewed feedback source candidate: `3e20214`, committed and integrated on GitHub `main`. All BF-001–BF-010 implementation is present.
- Synchronization verified before this documentation refresh: local `main` and `origin/main` matched `23507ca`, with a clean working tree and zero commits ahead or behind. Changes after source candidate `3e20214` were documentation-only.
- Latest immutable release tag: `v0.001a15` at `10f419e`. Feedback integration did not create a beta identity, release, or native distribution.

B1/B2 names in feedback and planning records identify intended release work. They do not describe the current installed version or completed qualification. Earlier checkpoints such as `5724f6c`, `aab3f3c`, and `b152f0e` remain historical evidence; their changes must not be reapplied.

## Integrated feedback behavior

- First-use bootstrap reports flushed progress; healthy startup stays quiet. The durability cleanup warning is corrected.
- Last-window close retains a usable empty editor. Explicit Quit shuts down the service and releases the terminal; paused-work and serial-recovery scheduling fixes are integrated. Legacy zero-window sessions restore safely.
- Whitespace markers are centered, Unicode inspection has configurable held modifiers, line numbers use 80% font size, and EOL status distinguishes current bytes from conversion on save across all shared views.
- Find/Replace uses the complete Lucide controls; capture labels and previews align without changing whole-match headers.
- System/Light/Dark are joined by Paper/Slate and editable custom profiles. Native System-preview palette restoration is corrected.
- Bundled Noto fallback, bounded shaped LTR layout, grapheme-aware editing, UTF-16 IME offsets, exact-width wrapping, and visible preedit carets are integrated. RTL/mixed-direction editing remains outside scope.

Per-item implementation and remaining host checks are in the [Beta Feedback Log](../BETA_FEEDBACK.md). Runtime ownership and document/recovery boundaries are in [Architecture](../01_current/ARCHITECTURE.md); supported behavior is in [Scope](../01_current/SCOPE.md).

## Verification and its limits

Recorded local evidence on source candidate `3e20214`:

- Full suite: 1,646 passed, six expected platform skips in 95.63 seconds.
- Compilation, diff checks, all 21 deep self-checks, 108 native Cocoa targeted tests, and native/offscreen combined smoke passed.
- Unchanged scroll, typing, giant-line, and mixed-script performance gates passed, as did all four local hosted-profile sustained families.
- The isolated wheel contained all 40 expected resources; mixed text and Find/Replace rendered from the installed wheel.

These are existing candidate results, not tests rerun for this documentation refresh. Exact timings, resource inventory, platform skip policy, and historical A21/A22 evidence remain in [Current Status](../01_current/STATUS.md) and the linked milestone records.

The latest complete four-lane hosted feedback pass is [run `34253008439`](https://github.com/PJTraut/tools-uniti/actions/runs/34253008439) on earlier checkpoint `aab3f3c`. The latest attempt checked on 2026-09-08, [run `34256794807`](https://github.com/PJTraut/tools-uniti/actions/runs/34256794807) on `23507ca`, reports failure with zero executed steps in all four jobs. GitHub annotations cite failed account payments or a spending-limit block. No executed source-test result exists for that attempt.

## Remaining work

1. Obtain affected Windows and Mac confirmation of first use, last-window close, explicit Quit, terminal prompt return, and relaunch. BF-002 remains a critical testing blocker until those reports exist.
2. Qualify physical Chinese/Korean IME composition, commit, and cancellation on Windows, macOS, and Linux, plus the remaining native visual, hotkey, theme, and EOL checks in the feedback log. Synthetic events do not close physical input qualification.
3. Complete all four hosted lanes on the integrated candidate once GitHub allows jobs to execute.
4. Complete the retained release sequence: seven distinct qualifying A22 real-use days; A23 executable health/recovery delivery; A24 same-candidate qualification; then B1 private executable feedback over fourteen calendar days with three independent testers covering macOS, Windows, and Linux. These gates remain open; source integration and automated runs do not replace them.
5. Promote to B2 only after the predecessor gates and final candidate qualification pass. No version bump, tag, release, or tester communication is implied by this handover.

Use the [Roadmap](../02_plans/ROADMAP.md) for ordering, the [feedback transition plan](../02_plans/2026-09-08-b1-feedback-b2-transition-plan.md) for completed and remaining tasks, and [Development](../01_current/DEVELOPMENT.md) for bootstrap and validation commands. Historical implementation details remain in [Implemented](../03_implemented/README.md), dated handovers, and Git history.
