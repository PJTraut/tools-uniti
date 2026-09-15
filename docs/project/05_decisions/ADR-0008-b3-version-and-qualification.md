# ADR-0008: B3 Source Version and Release Qualification

Date: 2026-09-15
Status: accepted

## Context

Since [ADR-0007](ADR-0007-beta-source-version-and-qualification.md) advanced the source identity to `v0.001b2` / `0.1b2`, a large batch of further reviewed feedback (BF-012 through BF-057 in the [Beta Feedback Log](../BETA_FEEDBACK.md)) has been implemented and integrated on `main`: the P1 Find/Replace job/result-model refactor (BF-039) and its dependents (navigation redesign, per-match preview, interactive replace, saved recipes, current-group scope, clickable report rows), file-type syntax-highlighting profiles and their extension point (BF-027, BF-041), live EOL conversion and its CRLF/CR performance correction (BF-023, BF-051), a New File command (BF-047), configurable tab width (BF-028), the Find/Replace panel's move from `QMainWindow` docking into the editor pane tree (BF-048), a Match Report sizing correction that stopped the panel auto-expanding to fit report content (BF-056), and a menu-bar restructuring that folds Find into Edit and flattens several submenu wrappers into blocks (BF-057). The user has directed the project to advance the source identity again to reflect this integrated work.

## Decision

1. Advance the source display identity to `v0.001b3` and Python package identity to `0.1b3`. B3 — Find/Replace Rework & Editor Refinement Beta becomes the active development milestone, taking B2's position 1 on the [Roadmap](../02_plans/ROADMAP.md). B2 is superseded as the active source milestone, exactly as B2 itself superseded A22 under ADR-0007 — B2 does not move to [Implemented](../03_implemented/README.md), since its own BF-001–BF-010 native-host and hosted-CI evidence remains outstanding per the [Beta Feedback Log](../BETA_FEEDBACK.md); that evidence is tracked per-item there, not gated on the milestone document itself.
2. As with B2, separate source version advancement from qualified executable delivery. This source beta identifies integrated feedback work; it does not certify unfinished qualification or create a release/tag.
3. Carry the outstanding A22 real-use, A23 executable health/recovery, A24 stabilization, and B1 independent executable feedback requirements forward unchanged as open release qualification, exactly as ADR-0007 carried them past B2. Do not mark those milestones completed or move their plans to implemented history without evidence.
4. Keep every native-host confirmation opened by B2 or B3 work open: physical IME qualification, affected-host BF-002 confirmation, same-commit hosted validation, and the new native confirmations opened by this batch (BF-017's shortcut-delivery regressions, BF-019/BF-025's visual confirmations, and any other item in the feedback log still marked pending as of this ADR). Local source tests and developer checks do not substitute for these results.
5. Preserve existing settings, session, recovery, and bootstrap ownership schemas. This promotion changes version metadata and project records; it does not migrate or discard user state.
6. Retain ADR-0006's native executable product boundary for qualified distribution. Source launchers remain the current development entry until that work is delivered. No public release, native build distribution, or tester communication is authorized by the version change alone.

## Consequences

The B2 requirement to keep advancing only after its own predecessor gates passed is superseded for source identity purposes, exactly as ADR-0007 superseded A22's equivalent requirement; the outstanding A22–B1 acceptance criteria remain open regardless of source label. The roadmap names B3 as the one active development milestone and keeps every unfinished predecessor record queued for release qualification. Historical A21/A22/B2 identities, benchmark baselines, workflow names, and test fixtures remain valid evidence labels for the work performed under them.

The three version declarations and managed installed metadata must agree. The existing full local suite (1,830 tests, 6 platform-only skips at the time of this ADR) and deep self-check validate the promotion; platform and human evidence remains tied to the exact candidate that produced it, and none of it is retroactively claimed for `v0.001b3` merely by the version bump.

## Affected records

- [Current status](../01_current/STATUS.md)
- [Roadmap](../02_plans/ROADMAP.md)
- [B3 milestone](../02_plans/v0.001b3-find-replace-and-editor-refinement-beta.md)
- [B2 milestone](../02_plans/v0.001b2-feedback-refinement-beta.md) (superseded as active; its own outstanding evidence remains open)
- [Beta Feedback Log](../BETA_FEEDBACK.md)
- [Executable boundary](ADR-0006-executable-health-recovery-boundary.md)
