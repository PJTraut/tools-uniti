# UNITI Ordered Roadmap

Date: 2026-09-08

This file is the authoritative sequence of approved outstanding product milestones. With Cross-Platform Alpha implemented, UNITI proceeds through sustained dogfood/performance hardening, executable health/recovery delivery, beta-candidate stabilization, and bounded real-world beta feedback.

## Outstanding milestones

| Order | Milestone | Status | Goal |
|---:|---|---|---|
| 1 | [`v0.001a22` — Dogfood / Performance Alpha](v0.001a22-dogfood-performance-alpha.md) | **active** | Measure and harden sustained real-world use with minimal new scope. |
| 2 | [`v0.001a23` — Executable Health & Recovery Alpha](v0.001a23-executable-health-recovery-alpha.md) | queued | Deliver native executable startup with guided offline diagnosis, repair, recovery, and Safe Session behavior. |
| 3 | [`v0.001a24` — Beta Candidate](v0.001a24-beta-candidate.md) | queued | Freeze features and satisfy the beta stabilization gate. |
| 4 | [`v0.001b1` — Real-World Feedback Beta](v0.001b1-real-world-feedback-beta.md) | queued | Promote the green A24 candidate and stabilize private executable builds through bounded cross-platform user feedback. |
| 5 | [`v0.001b2` — Feedback Refinement Beta](v0.001b2-feedback-refinement-beta.md) | proposed / queued | Qualify the integrated BF-001–BF-010 changes and promote the release identity after predecessor gates pass. |

The complete a21 Cross-Platform Alpha, including its Editor Layout and Visibility workstream, a20 Recovery & Session Alpha, a19 Regex Intelligence Alpha, a18 Large-File Alpha, a17 Text Integrity Alpha, a16 Usable Test Alpha, and earlier verified work are retained in [`03_implemented`](../03_implemented/README.md).

## Proposed B2 follow-up

Implementation update, 2026-09-08: all reviewed BF-001–BF-010 source changes through `3e20214` are committed and integrated on GitHub `main`, with a complete local candidate pass. The product remains `v0.001a22` / `0.1a22`. Native IME, affected-host, same-commit hosted, and predecessor release gates remain open; see [Current Status](../01_current/STATUS.md) and the [feedback evidence map](../BETA_FEEDBACK.md).

Requested follow-up, 2026-09-08: [B1 feedback closure and B2 transition plan](2026-09-08-b1-feedback-b2-transition-plan.md) covers outstanding BF-001–BF-010. Its proposed successor scope is recorded in the [B2 milestone](v0.001b2-feedback-refinement-beta.md). The retained policy requires A22's seven real-use days, A23 executable/health delivery, A24 qualification, and B1 executable human feedback in order. Missing evidence remains `NOT RUN`; this proposal does not mark an existing milestone complete or activate B2.

## Queue rules

- Normally exactly one milestone is active; later approved milestones remain queued in the order above.
- A milestone may contain several independently verified workstreams. Their records move to `03_implemented` without removing the parent milestone from this roadmap.
- A milestone leaves this roadmap only when its complete acceptance gate passes with fresh evidence.
- Parked capabilities are not implicit roadmap items and carry no version or delivery promise.
- Reordering or changing scope requires an explicit roadmap and decision update.

See [Project Grammar](../00_governance/GRAMMAR.md), [Current Status](../01_current/STATUS.md), and the [Parked Capability Catalog](../04_parked/CATALOG.md).
