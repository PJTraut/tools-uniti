# UNITI Current Handover

Captured: 2026-09-02

This is a continuation snapshot, not a controlling specification. Resolve conflicts using the authority order in the [Documentation System](../00_governance/DOCUMENTATION_SYSTEM.md).

## Canonical repository state

- Repository: `https://github.com/PJTraut/tools-uniti.git`
- Canonical branch: `main`
- Remote baseline: `origin/main` at `e36348d`
- Local a18 implementation sequence: `d56da90` through `99e9597`, followed by the a18 freeze closure
- Latest implemented milestone: `v0.001a18` — Large-File Alpha
- Active milestone: `v0.001a19` — Regex Intelligence Alpha
- Current display/package metadata: `v0.001a18` / `0.1a18`
- Latest immutable tag: `v0.001a15` at `10f419e`
- a16/a17/a18 tags: none

a18 is implemented and verified locally on `main`. The remote still ends at the synchronized a17 closure, so a push is the next integration decision; no tag is implied.

## Canonical records

- [Current status and exact a18 evidence](../01_current/STATUS.md)
- [Current scope](../01_current/SCOPE.md)
- [Current architecture](../01_current/ARCHITECTURE.md)
- [Development and performance workflow](../01_current/DEVELOPMENT.md)
- [Ordered roadmap](../02_plans/ROADMAP.md)
- [Active a19 scope](../02_plans/v0.001a19-regex-intelligence-alpha.md)
- [Implemented a18 milestone](../03_implemented/milestones/2026-09-02-uniti-v0.001a18-large-file-alpha.md)
- [Implemented a18 design](../03_implemented/designs/2026-09-02-uniti-v0.001a18-large-file-design.md)
- [Implemented a18 execution plan](../03_implemented/milestones/2026-09-02-uniti-v0.001a18-large-file-implementation.md)
- [Historical a18 handover](history/2026-09-02-v0.001a18-large-file-alpha.md)
- [Parked capabilities](../04_parked/CATALOG.md)
- [Architecture decisions](../05_decisions/README.md)

## a18 closure

a18 makes daily-use performance measurable and resource-aware. The app now profiles the local CPU/core/RAM/disk/load envelope, adapts cache and worker capacity, coordinates long work through observable cancellable tasks, and reports pressure/progress without modal interruption. Open/EOL, far navigation, Find All, Replace All planning, Save, and Save As use bounded snapshot work with stale-result protection. Compact indexes, sparse wrap checkpoints, spillable stores/plans, streaming cache intent, and verified progressive output keep authoritative text/history separate from disposable resources.

Fresh closure evidence:

```text
674 passed, 4 skipped
compileall and git diff --check: pass
deep self-check: pass, including text-integrity and large-file
offscreen and native Cocoa combined smoke: pass
controlled 100 MiB routine: 11/11 PASS
sparse 1 GiB design target: 3/3 PASS
native Cocoa 10 MiB quick: 11/11 PASS
```

Selected schema-1 results are in `benchmarks/baselines/`. No known data-loss, text-integrity, stale-result, output-identity, or blocking basic-usability defect remains.

## Active and queued work

`v0.001a19` Regex Intelligence Alpha is active at order 1. `v0.001a20` Recovery & Session, `v0.001a21` Cross-Platform, `v0.001a22` Dogfood/Performance, and `v0.001a23` Beta Candidate remain queued at orders 2–5.

Extension-sensed file-type profiles and syntax highlighting remain parked with no target version. They cannot enter a19 implicitly; promotion requires re-evaluation and an explicit roadmap decision.

## Next safe action

Review the a18 freeze evidence and, when approved, push local `main` normally to `origin/main`. Then design a19 from its active scope before implementation. Do not create or move a release tag unless separately requested.
