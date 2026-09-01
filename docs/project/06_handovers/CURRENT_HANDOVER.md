# UNITI Current Handover

Captured: 2026-09-01

This is a continuation snapshot, not a controlling specification. Resolve conflicts using the authority order in the [Documentation System](../00_governance/DOCUMENTATION_SYSTEM.md).

## Canonical repository state

- Repository: `https://github.com/PJTraut/tools-uniti.git`
- Canonical branch: `main`
- Implemented product-code baseline: `6b81185` — `fix: deliver regex results through Qt event loop`
- Latest immutable tag: `v0.001a15` at `10f419e`
- Current display/package metadata: `v0.001a15` / `0.1a15`
- Documentation system series: local commits on `main` after `6b81185`
- Expected handoff state: clean working tree; local documentation commits not pushed or tagged

The tag `v0.001a15` must not be moved. The post-tag Qt fix belongs to the next milestone history.

## Current project records

- [Status](../01_current/STATUS.md)
- [Scope](../01_current/SCOPE.md)
- [Architecture](../01_current/ARCHITECTURE.md)
- [Development workflow](../01_current/DEVELOPMENT.md)
- [Ordered roadmap](../02_plans/ROADMAP.md)
- [Active `v0.001a16` milestone](../02_plans/v0.001a16-startup-bootstrap.md)
- [Parked capabilities](../04_parked/CATALOG.md)
- [Architecture decisions](../05_decisions/README.md)
- [Imported post-`a15` snapshot](history/2026-08-31-v0.001a15-post-hotfix.md)

## Latest product verification

Real macOS/PySide6 offscreen verification at `6b81185`:

```text
286 passed, 1 skipped
```

The skip is the capability-dependent extended-attribute case in `tests/core/test_save.py:141`. The two Qt Find/Replace regressions corrected by `6b81185` passed independently before the full run.

## Active and queued work

`v0.001a16` is active in design finalization. Its goal is a formal host-Python bootstrap, UNITI-owned isolated runtime, phased initialization, setup-state persistence, diagnostics integration, and fast/deep self-check lifecycle. Application-code implementation and the version advance have not started.

There are no additional approved product milestones in the queue. Items in `04_parked` are outside current scope and have no delivery commitment.

## Constraints and external gates

- Host Python 3.12+ is the accepted bootstrap prerequisite for `a16`; UNITI must not mutate host/system packages.
- Existing `a15` artifacts were built from `10f419e` and exclude `6b81185`.
- macOS is the first intended external runtime acceptance environment for `a16`; Windows and Linux must be included in discovery/path design.
- No push, tag, release artifact, or tag movement occurs without fresh verification and explicit integration direction.

## Next safe action

Finalize and approve the detailed `v0.001a16` technical design—module boundaries, setup-state schema, environment ownership proof, dependency-metadata handling, relaunch behavior, failure taxonomy, and platform discovery—before changing application code.
