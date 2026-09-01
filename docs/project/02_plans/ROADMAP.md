# UNITI Ordered Roadmap

Date: 2026-09-01

This file is the authoritative sequence of approved outstanding product milestones. UNITI proceeds usability first, then integrity, scale, intelligence, recovery, cross-platform proof, hardening, and beta stabilization.

## Outstanding milestones

| Order | Milestone | Status | Goal |
|---:|---|---|---|
| 1 | [`v0.001a16` — Usable Test Alpha](v0.001a16-usable-test-alpha.md) | **active** | Become usable enough for routine daily editing and search dogfooding. |
| 2 | [`v0.001a17` — Text Integrity Alpha](v0.001a17-text-integrity-alpha.md) | queued | Make text preservation and deliberate transformation explicit invariants. |
| 3 | [`v0.001a18` — Large-File Alpha](v0.001a18-large-file-alpha.md) | queued | Prove the bounded large-file architecture at realistic scale. |
| 4 | [`v0.001a19` — Regex Intelligence Alpha](v0.001a19-regex-intelligence-alpha.md) | queued | Make regex handling a defining UNITI capability. |
| 5 | [`v0.001a20` — Recovery & Session Alpha](v0.001a20-recovery-session-alpha.md) | queued | Prevent casual work loss across crashes and restarts. |
| 6 | [`v0.001a21` — Cross-Platform Alpha](v0.001a21-cross-platform-alpha.md) | queued | Prove one canonical architecture on macOS, Windows, and Linux. |
| 7 | [`v0.001a22` — Dogfood / Performance Alpha](v0.001a22-dogfood-performance-alpha.md) | queued | Measure and harden sustained real-world use with minimal new scope. |
| 8 | [`v0.001a23` — Beta Candidate](v0.001a23-beta-candidate.md) | queued | Freeze features and satisfy the beta stabilization gate. |

The startup/bootstrap/initialization foundation already delivered during a16 is retained in [`03_implemented`](../03_implemented/README.md) as a completed workstream. It does not close the active Usable Test Alpha milestone.

## Queue rules

- Normally exactly one milestone is active; later approved milestones remain queued in the order above.
- A milestone may contain several independently verified workstreams. Their records move to `03_implemented` without removing the parent milestone from this roadmap.
- A milestone leaves this roadmap only when its complete acceptance gate passes with fresh evidence.
- Parked capabilities are not implicit roadmap items and carry no version or delivery promise.
- Reordering or changing scope requires an explicit roadmap and decision update.

See [Project Grammar](../00_governance/GRAMMAR.md), [Current Status](../01_current/STATUS.md), and the [Parked Capability Catalog](../04_parked/CATALOG.md).
