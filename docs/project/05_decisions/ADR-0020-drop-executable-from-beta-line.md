# ADR-0020: Drop the Native Executable from the Beta Line

Date: 2026-11-04
Status: accepted

## Context

[ADR-0006](ADR-0006-executable-health-recovery-boundary.md) made a native executable the product boundary for beta, and [ADR-0007](ADR-0007-beta-source-version-and-qualification.md), [ADR-0008](ADR-0008-b3-version-and-qualification.md) and [ADR-0012](ADR-0012-b4-version-and-qualification.md) carried the A22 real-use, A23 executable health/recovery, A24 stabilization and B1 independent executable feedback gates forward unchanged through B2, B3 and B4. No executable has been built. A23, A24 and B1 cannot be started, let alone passed, without one, so they have blocked "qualified" status for every beta source version while the project has kept shipping features through source launchers.

The user has directed that the executable be dropped from the beta line.

## Decision

1. The native executable is no longer a requirement of the beta line. Beta is delivered and tested from source through the existing launchers and `scripts/bootstrap.py`.
2. **A23 (Executable Health & Recovery Alpha), A24 (Beta Candidate) and B1 (Real-World Feedback Beta) are deferred, not passed.** Their plans stay in place as the record of what an executable release would need. They are removed from the active qualification queue and gate nothing in B4 or later source versions. They are not moved to Implemented.
3. ADR-0006's executable boundary is deferred, not reversed. If a native executable is wanted later, ADR-0006's boundary, and A23/A24/B1's criteria, are the starting point.
4. **A22 stays open.** Its remaining item, seven distinct active local dogfood days over the approved workflow set, does not need an executable. Real-use evidence still has to be recorded.
5. Evidence that is not executable-specific stays open and is tracked per item: affected-host BF-002 confirmation (Windows and Mac, from source), physical Chinese/Korean IME qualification, same-commit hosted CI, and the live-app checklist sections still marked undone. Dropping the executable does not close any of them.
6. No release, tag, native build distribution or tester communication is authorized by this decision. The latest immutable tag stays `v0.001a15`.

## Consequences

"Qualified" for the beta line now means: A22's seven days recorded, the open per-item native-host and hosted-CI evidence closed, and the live-app checklist completed. It no longer includes an executable, a 14-day three-tester executable feedback period, or an executable stabilization gate.

Documents that say qualified executable delivery is outstanding are historical as of ADR-0012 and read together with this ADR. Existing wording about outstanding A23/A24/B1 requirements in ADR-0007, ADR-0008 and ADR-0012 is left as written.

## Affected records

- [Roadmap](../02_plans/ROADMAP.md)
- [Current status](../01_current/STATUS.md)
- [Executable boundary](ADR-0006-executable-health-recovery-boundary.md) (deferred)
- [A23](../02_plans/v0.001a23-executable-health-recovery-alpha.md), [A24](../02_plans/v0.001a24-beta-candidate.md), [B1](../02_plans/v0.001b1-real-world-feedback-beta.md) (deferred)
