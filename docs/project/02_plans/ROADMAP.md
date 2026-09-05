# UNITI Ordered Roadmap

Date: 2026-09-05

This file is the authoritative sequence of approved outstanding product milestones. With Recovery & Session Alpha implemented, UNITI proceeds through cross-platform proof, hardening, and beta stabilization.

## Outstanding milestones

| Order | Milestone | Status | Goal |
|---:|---|---|---|
| 1 | [`v0.001a21` — Cross-Platform Alpha](v0.001a21-cross-platform-alpha.md) | **active** | Prove one canonical architecture on macOS, Windows, and Linux. |
| 2 | [`v0.001a22` — Dogfood / Performance Alpha](v0.001a22-dogfood-performance-alpha.md) | queued | Measure and harden sustained real-world use with minimal new scope. |
| 3 | [`v0.001a23` — Beta Candidate](v0.001a23-beta-candidate.md) | queued | Freeze features and satisfy the beta stabilization gate. |

The complete a20 Recovery & Session Alpha, a19 Regex Intelligence Alpha, a18 Large-File Alpha, a17 Text Integrity Alpha, a16 Usable Test Alpha, and earlier verified work are retained in [`03_implemented`](../03_implemented/README.md).

The a21 Editor Layout and Visibility workstream is also implemented and retained there. Its completion does not close the active Cross-Platform Alpha parent milestone, whose implementation resumes at Task 4.

## Queue rules

- Normally exactly one milestone is active; later approved milestones remain queued in the order above.
- A milestone may contain several independently verified workstreams. Their records move to `03_implemented` without removing the parent milestone from this roadmap.
- A milestone leaves this roadmap only when its complete acceptance gate passes with fresh evidence.
- Parked capabilities are not implicit roadmap items and carry no version or delivery promise.
- Reordering or changing scope requires an explicit roadmap and decision update.

See [Project Grammar](../00_governance/GRAMMAR.md), [Current Status](../01_current/STATUS.md), and the [Parked Capability Catalog](../04_parked/CATALOG.md).
