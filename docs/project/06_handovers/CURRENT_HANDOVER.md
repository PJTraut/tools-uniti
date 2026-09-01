# UNITI Current Handover

Captured: 2026-09-01

This is a continuation snapshot, not a controlling specification. Resolve conflicts using the authority order in the [Documentation System](../00_governance/DOCUMENTATION_SYSTEM.md).

## Canonical repository state

- Repository: `https://github.com/PJTraut/tools-uniti.git`
- Canonical branch: `main`
- Implemented milestone: `v0.001a16` startup/bootstrap/initialization
- Current display/package metadata: `v0.001a16` / `0.1a16`
- Latest immutable tag: `v0.001a15` at `10f419e`
- a16 tag: none, by explicit instruction
- Integration state: local release-closure verification in progress; normal push follows the final clean-tree gate

The `v0.001a15` tag must not move. Its artifacts remain exact historical products of `10f419e` and do not include the post-tag Qt fix or a16.

## Canonical records

- [Status](../01_current/STATUS.md)
- [Scope](../01_current/SCOPE.md)
- [Architecture](../01_current/ARCHITECTURE.md)
- [Development workflow](../01_current/DEVELOPMENT.md)
- [Ordered roadmap](../02_plans/ROADMAP.md)
- [Implemented a16 milestone](../03_implemented/milestones/2026-09-01-uniti-v0.001a16-startup-bootstrap.md)
- [Implemented a16 design](../03_implemented/designs/2026-09-01-uniti-v0.001a16-startup-bootstrap-design.md)
- [Implemented a16 execution plan](../03_implemented/milestones/2026-09-01-uniti-v0.001a16-startup-bootstrap-implementation.md)
- [Parked capabilities](../04_parked/CATALOG.md)
- [Architecture decisions](../05_decisions/README.md)
- [Post-a15 historical snapshot](history/2026-08-31-v0.001a15-post-hotfix.md)

## Implemented lifecycle

The repository now contains the Python compatibility shim, Qt-free bootstrap package, managed runtime marker/lock safety, dependency install/validation/fingerprints, schema-1 setup/settings persistence, ordered startup coordinator, capability and cleanup services, fast/deep self-check, pre-Qt application CLI, and startup diagnostics integration.

Source bootstrap uses exactly `.venv`; local mode is explicit. Bootstrap mutation is limited to ownership-validated UNITI environments. Normal startup validates imports/versions and never invokes pip.

## Verification state

Every implementation slice passed its focused red/green tests. Bootstrap, app/UI, resource, core/smoke, deep offscreen self-check, and a16 acceptance gates are included in the final closure command set. The exact full-suite count and release-closure commit are added to this handover and the dated a16 snapshot after committed-tree verification.

The extended-attribute save test may be the sole explicit skip where the active platform/runtime does not support xattrs.

## Active and queued work

There is no approved active or queued product milestone. The roadmap is intentionally empty. Parked capabilities remain outside current architecture/scope and carry no sequence or version commitment.

## Remaining integration gate

1. complete focused and full a16 verification;
2. record the exact clean commit and test count in current/history handovers;
3. re-run the committed-tree verification;
4. fetch `origin` and verify `origin/main` is an ancestor of local `main`; and
5. push `main` normally without force or tag creation.

## Next safe action

Finish the release-closure verification and integration gate above. Do not begin a new milestone until it is explicitly approved and sequenced in the roadmap.
