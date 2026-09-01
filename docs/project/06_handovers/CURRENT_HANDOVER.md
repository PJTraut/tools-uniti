# UNITI Current Handover

Captured: 2026-09-01

This is a continuation snapshot, not a controlling specification. Resolve conflicts using the authority order in the [Documentation System](../00_governance/DOCUMENTATION_SYSTEM.md).

## Canonical repository state

- Repository: `https://github.com/PJTraut/tools-uniti.git`
- Canonical branch: `main`
- Baseline when a16 usability work resumed: `052f733`
- Active milestone: `v0.001a16` — Usable Test Alpha
- Current display/package metadata: `v0.001a16` / `0.1a16`
- Latest implemented a16 workstream: startup/bootstrap/initialization at `8bde00f`
- Latest immutable tag: `v0.001a15` at `10f419e`
- a16 tag: none

The working tree contains active a16 work, including the approved root macOS/Windows launchers and this project-record reconciliation. Inspect `git status` rather than assuming a clean tree. Preserve those changes when continuing.

## Canonical records

- [Current status](../01_current/STATUS.md)
- [Current scope](../01_current/SCOPE.md)
- [Current architecture](../01_current/ARCHITECTURE.md)
- [Development workflow](../01_current/DEVELOPMENT.md)
- [Ordered roadmap](../02_plans/ROADMAP.md)
- [Active a16 exit contract](../02_plans/v0.001a16-usable-test-alpha.md)
- [Active a16 implementation plan](../02_plans/v0.001a16-implementation-plan.md)
- [Implemented startup/bootstrap workstream](../03_implemented/milestones/2026-09-01-uniti-v0.001a16-startup-bootstrap.md)
- [Parked capabilities](../04_parked/CATALOG.md)
- [Architecture decisions](../05_decisions/README.md)
- [Corrected startup-foundation snapshot](history/2026-09-01-v0.001a16-startup-foundation.md)

## Active work

a16 exists to make UNITI usable for daily editing/search dogfooding, not to add more architecture. Required work includes core editor commands/navigation, 50-transaction document Undo, independent 50-step Find and Replace histories, editor and F/R zoom, soft wrap, reload/revert, floating modeless Find/Replace, literal/regex mode separation, capture-only reports, atomic Replace All, assignable persisted hotkeys, UI-state persistence, status indicators, and Western/Cyrillic fixed-pitch fonts.

No user manual or feature documentation is required during this milestone. Maintain only current architecture, durable decisions/principles, project grammar, planning state, and handover continuity.

## Queue

After a16, implement in sequence:

1. `v0.001a17` Text Integrity Alpha;
2. `v0.001a18` Large-File Alpha;
3. `v0.001a19` Regex Intelligence Alpha;
4. `v0.001a20` Recovery & Session Alpha;
5. `v0.001a21` Cross-Platform Alpha;
6. `v0.001a22` Dogfood / Performance Alpha; and
7. `v0.001a23` Beta Candidate.

## Verification state and acceptance gate

The historical startup/bootstrap closure recorded `357 passed, 1 skipped`, plus compile, smoke, deep self-check, import-boundary, link, and diff checks. Those results prove that implemented workstream only; active a16 changes require fresh verification.

a16 does not freeze until the full automated suite, deep self-check, and macOS GUI smoke are green; real editing/search dogfooding has found no remaining blocking/basic usability defect; and no known data-loss or text-integrity bug remains.

## Next safe action

Continue the [a16 implementation plan](../02_plans/v0.001a16-implementation-plan.md) test-first. Do not promote a16 to `03_implemented`, tag it, or push milestone completion until every acceptance gate has current evidence.
