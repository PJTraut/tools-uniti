# UNITI Ordered Roadmap

Date: 2026-09-08

B2 Feedback Refinement Beta is the active source-development milestone. The user-directed version move is recorded in [ADR-0007](../05_decisions/ADR-0007-beta-source-version-and-qualification.md). All reviewed BF-001–BF-010 source changes are integrated; the version is `v0.001b2` / `0.1b2`.

## Active development and outstanding qualification

| Order | Milestone | Status | Remaining purpose |
|---|---|---|---|
| 1 | [`v0.001b2` — Feedback Refinement Beta](v0.001b2-feedback-refinement-beta.md) | **active** | Validate the integrated beta source and close native input, affected-host, and hosted checks. |
| 2 | [`v0.001a22` — Dogfood / Performance Alpha](v0.001a22-dogfood-performance-alpha.md) | queued qualification | Record the seven required distinct real-use days; implemented performance infrastructure remains in use. |
| 3 | [`v0.001a23` — Executable Health & Recovery Alpha](v0.001a23-executable-health-recovery-alpha.md) | queued | Deliver and qualify native executable startup, health, and recovery. |
| 4 | [`v0.001a24` — Beta Candidate](v0.001a24-beta-candidate.md) | queued | Satisfy the complete executable stabilization gate. |
| 5 | [`v0.001b1` — Real-World Feedback Beta](v0.001b1-real-world-feedback-beta.md) | queued qualification | Complete qualified private executable feedback over fourteen calendar days with three independent testers covering macOS, Windows, and Linux. |

The historical milestone names remain stable links to their acceptance requirements. They are not future version downgrades. Outstanding qualification follows rows 2–5 before qualified executable release; advancing the source label does not mark any of them passed.

## Current work

The [feedback transition plan](2026-09-08-b1-feedback-b2-transition-plan.md) records completed implementation and remaining work. The [feedback log](../BETA_FEEDBACK.md) tracks each BF item. The [current status](../01_current/STATUS.md) separates local tests, hosted results, physical input checks, and release evidence.

A21 Cross-Platform Alpha and earlier completed milestones remain in [Implemented](../03_implemented/README.md). A22 source infrastructure and the beta feedback code are implemented, but unfinished milestone acceptance records remain here.

## Queue rules

- B2 is the one active development milestone. Earlier unfinished milestone requirements remain queued for release qualification under ADR-0007.
- Source identity and qualified release readiness are recorded separately; missing evidence remains `NOT RUN` or pending.
- A milestone moves to implemented history only after its complete acceptance gate passes with evidence.
- Parked capabilities remain outside the queue. Scope changes require an explicit roadmap and decision update.

See [Project Grammar](../00_governance/GRAMMAR.md) and the [Parked Capability Catalog](../04_parked/CATALOG.md).
