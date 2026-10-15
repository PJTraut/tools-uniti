# UNITI Project Record

This directory is the tool-neutral source of truth for UNITI's development state, delivery sequence, historical implementation, scope boundaries, architectural decisions, and development handovers.

Current product identity: `v0.001b4` / `0.1b4`. B4 is the active source beta; B2 and B3 are superseded as active, and qualified executable delivery remains gated by the outstanding checks in [ADR-0012](05_decisions/ADR-0012-b4-version-and-qualification.md), which continues [ADR-0008](05_decisions/ADR-0008-b3-version-and-qualification.md)'s and [ADR-0007](05_decisions/ADR-0007-beta-source-version-and-qualification.md)'s patterns. A separate file-type environment and USFM track runs alongside it ([ADR-0013](05_decisions/ADR-0013-environment-framework-ownership-boundary.md)–[ADR-0019](05_decisions/ADR-0019-named-environment-windows-groups-and-project-tabs.md)). See [Current Status](01_current/STATUS.md) for the synchronized baseline and verification evidence.

[Beta Feedback Log](BETA_FEEDBACK.md) records user observations, implemented corrections and features, verification, and remaining host qualification. The [Feature Wishlist](FEATURE_WISHLIST.md) holds future ideas raised in passing that are not yet scoped or committed.

User-facing instructions are in the [User Manual](../user-manual.md), [User Cheat Sheet](../user-cheat-sheet.md), and [Regex Flags Guide](../regex-flags.md). These describe the implemented interface, and the [Environments](../environments/README.md) pages cover each file-type environment and link here for release qualification.

## Reading order

1. [`00_governance`](00_governance/DOCUMENTATION_SYSTEM.md) defines the documentation system and [project grammar](00_governance/GRAMMAR.md).
2. [`01_current`](01_current/STATUS.md) describes the implemented product now: status, scope, architecture, and development workflow.
3. [`02_plans`](02_plans/ROADMAP.md) contains approved outstanding milestones in implementation order.
4. [`03_implemented`](03_implemented/README.md) retains completed milestone plans and their governing designs.
5. [`04_parked`](04_parked/README.md) records ideas outside current architecture or scope.
6. [`05_decisions`](05_decisions/README.md) preserves consequential architecture and project-policy decisions.
7. [`06_handovers`](06_handovers/CURRENT_HANDOVER.md) provides the concise continuation snapshot and immutable historical snapshots.

## Authority

Implemented facts and future intent are deliberately separate. Repository code, tests, version metadata, Git state, accepted decisions, and `01_current` determine what UNITI is today. `02_plans` determines what the project has approved for future implementation. A handover links these records but never overrides them.

See [Documentation System](00_governance/DOCUMENTATION_SYSTEM.md) for the complete authority order and conflict rules.

## Maintenance cycle

When a milestone is approved, add it to the ordered roadmap and create its plan under `02_plans`. When its acceptance criteria pass with fresh verification, move the plan to `03_implemented`, update every affected current-state document, remove it from the outstanding roadmap queue, and refresh the current handover.

Ideas outside the current product architecture or scope belong in `04_parked`. They enter `02_plans` only after explicit re-evaluation and an accepted decision.
