# ADR-0007: Beta Source Version and Release Qualification

Date: 2026-09-08
Status: accepted

## Context

Reviewed BF-001–BF-010 changes are already integrated on `main` through source candidate `3e20214`. The earlier transition policy retained A22 version metadata until every predecessor release gate closed. The user has now directed the project to move beyond A22 to reflect the implemented beta updates.

## Decision

1. Advance the source display identity to `v0.001b2` and Python package identity to `0.1b2`. B2 Feedback Refinement Beta becomes the active development milestone.
2. Separate source version advancement from qualified executable delivery. The source beta identifies the integrated feedback work; it does not certify unfinished qualification or create a release/tag.
3. Carry the outstanding A22 real-use, A23 executable health/recovery, A24 stabilization, and B1 independent executable feedback requirements forward as open release qualification. Do not mark those milestones completed or move their plans to implemented history without evidence.
4. Keep physical IME, affected-host BF-002 confirmation, and same-commit hosted validation open. Existing source tests and developer checks do not substitute for these results.
5. Preserve existing settings, session, recovery, and bootstrap ownership schemas. This promotion changes version metadata and project records; it does not migrate or discard user state.
6. Retain ADR-0006's native executable product boundary for qualified distribution. Source launchers remain the current development entry until that work is delivered. No public release, native build distribution, or tester communication is authorized by the version change alone.

## Consequences

The previous requirement to keep A22 metadata and postpone B2 activation until all predecessor gates pass is superseded. Their technical acceptance criteria remain outstanding. The roadmap names B2 as the one active development milestone and keeps unfinished predecessor records queued for release qualification. Historical A22 identities, benchmark baselines, workflow names, and test fixtures remain valid evidence labels.

The three version declarations and managed installed metadata must agree. Existing launch, bootstrap, application, and self-check coverage validates the promotion; platform and human evidence remains tied to the exact candidate that produced it.

## Affected records

- [Current status](../01_current/STATUS.md)
- [Roadmap](../02_plans/ROADMAP.md)
- [B2 milestone](../02_plans/v0.001b2-feedback-refinement-beta.md)
- [Feedback transition plan](../02_plans/2026-09-08-b1-feedback-b2-transition-plan.md)
- [Executable boundary](ADR-0006-executable-health-recovery-boundary.md)
