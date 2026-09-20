# ADR-0012: B4 Source Version and Release Qualification

Date: 2026-09-20
Status: accepted

## Context

Since [ADR-0008](ADR-0008-b3-version-and-qualification.md) advanced the source identity to `v0.001b3` / `0.1b3`, a further batch of reviewed feedback has been implemented and integrated on `main`: BF-019's Match Report label-sizing fix (unifying the label and content columns onto one `QTextLayout` rendering path after native confirmation showed the original fix incomplete), BF-070's "full editor parity" rework for Compare (swapping its bespoke text widget for real `UNITITextView` panes, a standalone frameless window, zoom sync, cross-pane current-line highlight, intra-line diff highlighting, a right-click context menu, and a hotkey that toggles it open/closed like Find), BF-072's Match Report replacement-preview tab-rendering fix, BF-073's Character Inspector rework (list+detail redesign replacing the table, a default hotkey that also toggles the dialog, zoom via mouse/keyboard, a large glyph-preview area, frameless window chrome, persisted geometry/zoom, expanded Unicode properties with codepoint display, and an arrow-key navigation fix), BF-075's per-view settings (whitespace mode, editor theme, tab width, and syntax-profile choice are now per-view instead of a single global setting broadcast to every open document), and a new generic toggle-window state-management mechanism (`UNITIMainWindow._toggle_window`/`_on_toggle_window_closed`, backed by generic `Settings.toggle_window_geometry`/`toggle_window_zoom_percent` dictionaries) that Compare and Character Inspector both now share for open/close tracking and geometry/zoom persistence. The user has directed the project to advance the source identity again to reflect this integrated work.

## Decision

1. Advance the source display identity to `v0.001b4` and Python package identity to `0.1b4`. B4 — Compare, Character Inspector & Per-View Settings Beta becomes the active development milestone, taking B3's position 1 on the [Roadmap](../02_plans/ROADMAP.md). B3 is superseded as the active source milestone, exactly as B3 itself superseded B2 under ADR-0008 — B3 does not move to [Implemented](../03_implemented/README.md), since its own carried-forward native-host and hosted-CI evidence (including B2's original BF-001–BF-010 range) remains outstanding per the [Beta Feedback Log](../BETA_FEEDBACK.md); that evidence is tracked per-item there, not gated on the milestone document itself.
2. As with B2→B3, separate source version advancement from qualified executable delivery. This source beta identifies integrated feedback work; it does not certify unfinished qualification or create a release/tag.
3. Carry the outstanding A22 real-use, A23 executable health/recovery, A24 stabilization, and B1 independent executable feedback requirements forward unchanged as open release qualification, exactly as ADR-0008 carried them past B3. Do not mark those milestones completed or move their plans to implemented history without evidence.
4. Keep every native-host confirmation opened by B2, B3, or B4 work open: physical IME qualification, affected-host BF-002 confirmation, same-commit hosted validation, BF-019's label-sizing fix (fixed in code this batch, but not yet re-confirmed natively), and any other item in the feedback log still marked pending as of this ADR. Local source tests and developer checks do not substitute for these results.
5. Preserve existing settings, session, recovery, and bootstrap ownership schemas. `Settings` gained two new generic fields (`toggle_window_geometry`, `toggle_window_zoom_percent`); both are additive with safe empty-dict defaults and require no schema-version bump, consistent with how prior additive `Settings`/session fields have been handled. This promotion changes version metadata and project records; it does not migrate or discard user state.
6. Retain ADR-0006's native executable product boundary for qualified distribution. Source launchers remain the current development entry until that work is delivered. No public release, native build distribution, or tester communication is authorized by the version change alone.

## Consequences

The B3 requirement to keep advancing only after its own predecessor gates passed is superseded for source identity purposes, exactly as ADR-0008 superseded B2's equivalent requirement; the outstanding A22–B1 acceptance criteria remain open regardless of source label. The roadmap names B4 as the one active development milestone and keeps every unfinished predecessor record queued for release qualification. Historical A21/B2/B3 identities, benchmark baselines, workflow names, and test fixtures remain valid evidence labels for the work performed under them.

The three version declarations and managed installed metadata must agree. The existing full local suite (2,058 passed, 6 platform-only skips at the time of this ADR) validates the promotion; platform and human evidence remains tied to the exact candidate that produced it, and none of it is retroactively claimed for `v0.001b4` merely by the version bump.

## Affected records

- [Current status](../01_current/STATUS.md)
- [Roadmap](../02_plans/ROADMAP.md)
- [B4 milestone](../02_plans/v0.001b4-compare-character-inspector-and-per-view-settings-beta.md)
- [B3 milestone](../02_plans/v0.001b3-find-replace-and-editor-refinement-beta.md) (superseded as active; its own outstanding evidence remains open)
- [Beta Feedback Log](../BETA_FEEDBACK.md)
- [Executable boundary](ADR-0006-executable-health-recovery-boundary.md)
