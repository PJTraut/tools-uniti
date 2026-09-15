# UNITI Ordered Roadmap

Date: 2026-09-08

B3 Find/Replace Rework & Editor Refinement Beta is the active source-development milestone. The user-directed version move is recorded in [ADR-0008](../05_decisions/ADR-0008-b3-version-and-qualification.md), continuing [ADR-0007](../05_decisions/ADR-0007-beta-source-version-and-qualification.md)'s B1→B2 pattern. All reviewed BF-012–BF-057 source changes are integrated; the version is `v0.001b3` / `0.1b3`.

## Active development and outstanding qualification

| Order | Milestone | Status | Remaining purpose |
|---|---|---|---|
| 1 | [`v0.001b3` — Find/Replace Rework & Editor Refinement Beta](v0.001b3-find-replace-and-editor-refinement-beta.md) | **active** | Validate the integrated beta source and close native input, affected-host, and hosted checks. |
| — | [`v0.001b2` — Feedback Refinement Beta](v0.001b2-feedback-refinement-beta.md) | superseded as active; own evidence queued | BF-001–BF-010 native-host and hosted-CI confirmation remains open, tracked per item in the feedback log. |
| 2 | [`v0.001a22` — Dogfood / Performance Alpha](v0.001a22-dogfood-performance-alpha.md) | queued qualification | Record the seven required distinct real-use days; implemented performance infrastructure remains in use. |
| 3 | [`v0.001a23` — Executable Health & Recovery Alpha](v0.001a23-executable-health-recovery-alpha.md) | queued | Deliver and qualify native executable startup, health, and recovery. |
| 4 | [`v0.001a24` — Beta Candidate](v0.001a24-beta-candidate.md) | queued | Satisfy the complete executable stabilization gate. |
| 5 | [`v0.001b1` — Real-World Feedback Beta](v0.001b1-real-world-feedback-beta.md) | queued qualification | Complete qualified private executable feedback over fourteen calendar days with three independent testers covering macOS, Windows, and Linux. |

The historical milestone names remain stable links to their acceptance requirements. They are not future version downgrades. Outstanding qualification follows rows 2–5 (plus B2's own carried-forward evidence) before qualified executable release; advancing the source label does not mark any of them passed.

## Current work

The [feedback transition plan](2026-09-08-b1-feedback-b2-transition-plan.md) records the B1→B2 implementation and remaining work; B2→B3 has no separate transition plan document beyond [ADR-0008](../05_decisions/ADR-0008-b3-version-and-qualification.md) and the [B3 milestone](v0.001b3-find-replace-and-editor-refinement-beta.md) itself. The [feedback log](../BETA_FEEDBACK.md) tracks each BF item. The [current status](../01_current/STATUS.md) separates local tests, hosted results, physical input checks, and release evidence.

A21 Cross-Platform Alpha and earlier completed milestones remain in [Implemented](../03_implemented/README.md). A22 source infrastructure and the beta feedback code are implemented, but unfinished milestone acceptance records remain here.

## Queue rules

- B3 is the one active development milestone. Earlier unfinished milestone requirements, including B2's own outstanding evidence, remain queued for release qualification under ADR-0007 and ADR-0008.
- Source identity and qualified release readiness are recorded separately; missing evidence remains `NOT RUN` or pending.
- A milestone moves to implemented history only after its complete acceptance gate passes with evidence.
- Parked capabilities remain outside the queue. Scope changes require an explicit roadmap and decision update.

See [Project Grammar](../00_governance/GRAMMAR.md) and the [Parked Capability Catalog](../04_parked/CATALOG.md).
