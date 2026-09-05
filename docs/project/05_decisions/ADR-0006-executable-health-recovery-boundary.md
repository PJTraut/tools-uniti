# ADR-0006: Executable-Only Product and Health/Recovery Boundary

Date: 2026-09-05
Status: accepted

## Context

UNITI currently ships as source with host-Python bootstrap, shell launchers, a console entry point, command-line self-check/smoke modes, and phase failures that can terminate before a GUI presents repair guidance. Beta requires a native executable, while normal users should not maintain Python or learn command syntax to diagnose startup.

Health/repair must not weaken existing session, recovery, saved-history, one-service, or text-integrity authority. It must also remain useful when Python or Qt cannot start, without turning UNITI into an updater, installer, package manager, privileged helper, or cloud service.

## Decision

1. A23 makes the native application bundle the only supported public product entry. Developer/CI scripts remain private automation and carry no end-user compatibility contract.
2. Target-native standalone bundles embed Python, PySide6/Qt, regex, and required dependencies. Normal product startup never selects or repairs host Python.
3. A small Python/Qt-independent native launcher owns critical bundle preflight, private readiness/open-event handoff, and minimal fatal-runtime guidance.
4. A Qt-free `HealthEngine` classifies read-only quick/deep findings. It does not repair or display UI.
5. A separate `RepairEngine` produces sealed, previewed, consent-based repair plans that mutate only allowlisted UNITI-owned application state, verify results, and roll back where safe.
6. One service-owned Health & Recovery Center presents health, repair, Safe Session, diagnostics, and existing recovery actions without replacing `RecoveryManager` authority.
7. Repairs are offline and local-only. Bundle/runtime damage recommends reinstall; no repair invokes a shell, package manager, network, elevation, or arbitrary command.
8. Repair quarantine retains affected owned state for seven days or 128 MiB, never pruning user documents, valid recovery evidence, or current rollback state.
9. Native OS launch/open events forward to the one running service through a private bounded protocol. They do not define a public CLI.
10. Public console/shell launch surfaces retire only after executable parity and three-OS evidence pass.

## Consequences

- ADR-0001 remains authoritative for source-development runtime ownership. After A23 implementation it no longer defines the shipped user's startup responsibility.
- Startup failures become typed health outcomes whenever the embedded Qt application can run; failures below that boundary remain launcher-owned.
- UNITI gains a native launcher, health model, repair transaction/quarantine authority, unified Health & Recovery UI, and target-native bundle build/evidence policy.
- The application bundle grows because it embeds its runtime, so allowlisted inventory and 10%/20% size-regression gates become required.
- Unsigned SHA-256 manifests diagnose accidental corruption but do not authenticate a publisher or resist malicious bundle replacement.
- Signing, notarization, installers, updating, and network repair remain separate future architecture decisions.

## Affected records

- [A23 milestone](../02_plans/v0.001a23-executable-health-recovery-alpha.md)
- [A23 design](../02_plans/v0.001a23-executable-health-recovery-design.md)
- [A24 Beta Candidate](../02_plans/v0.001a24-beta-candidate.md)
- [ADR-0001: Host Python runtime policy](ADR-0001-host-python-runtime-policy.md)
- [Parked Capability Catalog](../04_parked/CATALOG.md)
