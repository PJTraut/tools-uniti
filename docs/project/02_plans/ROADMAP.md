# UNITI Ordered Roadmap

Date: 2026-09-02

This file is the authoritative sequence of approved outstanding product milestones. With Large-File Alpha implemented, UNITI proceeds through regex intelligence, recovery, cross-platform proof, hardening, and beta stabilization.

## Outstanding milestones

| Order | Milestone | Status | Goal |
|---:|---|---|---|
| 1 | [`v0.001a19` — Regex Intelligence Alpha](v0.001a19-regex-intelligence-alpha.md) | **active** | Make regex handling a defining UNITI capability. |
| 2 | [`v0.001a20` — Recovery & Session Alpha](v0.001a20-recovery-session-alpha.md) | queued | Prevent casual work loss across crashes and restarts. |
| 3 | [`v0.001a21` — Cross-Platform Alpha](v0.001a21-cross-platform-alpha.md) | queued | Prove one canonical architecture on macOS, Windows, and Linux. |
| 4 | [`v0.001a22` — Dogfood / Performance Alpha](v0.001a22-dogfood-performance-alpha.md) | queued | Measure and harden sustained real-world use with minimal new scope. |
| 5 | [`v0.001a23` — Beta Candidate](v0.001a23-beta-candidate.md) | queued | Freeze features and satisfy the beta stabilization gate. |

The complete a18 Large-File Alpha, a17 Text Integrity Alpha, a16 Usable Test Alpha, and earlier verified work are retained in [`03_implemented`](../03_implemented/README.md).

## Queue rules

- Normally exactly one milestone is active; later approved milestones remain queued in the order above.
- A milestone may contain several independently verified workstreams. Their records move to `03_implemented` without removing the parent milestone from this roadmap.
- A milestone leaves this roadmap only when its complete acceptance gate passes with fresh evidence.
- Parked capabilities are not implicit roadmap items and carry no version or delivery promise.
- Reordering or changing scope requires an explicit roadmap and decision update.

See [Project Grammar](../00_governance/GRAMMAR.md), [Current Status](../01_current/STATUS.md), and the [Parked Capability Catalog](../04_parked/CATALOG.md).
