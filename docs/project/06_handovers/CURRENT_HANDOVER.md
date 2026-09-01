# UNITI Current Handover

Captured: 2026-09-01

This is a continuation snapshot, not a controlling specification. Resolve conflicts using the authority order in the [Documentation System](../00_governance/DOCUMENTATION_SYSTEM.md).

## Canonical repository state

- Repository: `https://github.com/PJTraut/tools-uniti.git`
- Canonical branch: `main`
- Implemented milestone: `v0.001a16` startup/bootstrap/initialization
- Product completion commit: `8bde00f638097f920a7f13973db2cab1a1af59a0`
- Current display/package metadata: `v0.001a16` / `0.1a16`
- Latest immutable tag: `v0.001a15` at `10f419e`
- a16 tag: none, by explicit instruction
- Integration state: implementation committed and verified locally; remote ancestry and normal push remain

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
- [a16 completion snapshot](history/2026-09-01-v0.001a16-complete.md)

## Implemented lifecycle

The repository now contains the Python compatibility shim, Qt-free bootstrap package, managed runtime marker/lock safety, dependency install/validation/fingerprints, schema-1 setup/settings persistence, ordered startup coordinator, capability and cleanup services, fast/deep self-check, pre-Qt application CLI, and startup diagnostics integration.

Source bootstrap uses exactly `.venv`; local mode is explicit. Bootstrap mutation is limited to ownership-validated UNITI environments. Normal startup validates imports/versions and never invokes pip.

## Verification state

Every implementation slice passed its focused red/green tests. Release closure at `8bde00f` produced:

```text
357 passed, 1 skipped
```

The a16 acceptance contract reported `3 passed`. Managed source bootstrap, matching installed/imported `0.1a16` metadata, compileall, headless smoke, deep offscreen self-check, import boundaries, Markdown links, and `git diff --check` passed.

The sole skip was `tests/core/test_save.py:141`, where extended attributes are unsupported by the active Python/platform.

During verification, a now-fixed symlink-resolution defect caused an early bootstrap run to invoke the base Python executable instead of `.venv/bin/python`. Commit `8bde00f` preserves the managed interpreter path, checks installed UNITI metadata against canonical metadata, and includes a symlink regression. The base Python currently reports an editable `uniti-editor 0.1a16`; it was not uninstalled because its pre-verification ownership/state was not established. Future bootstrap runs are confined to the managed interpreter.

## Active and queued work

There is no approved active or queued product milestone. The roadmap is intentionally empty. Parked capabilities remain outside current architecture/scope and carry no sequence or version commitment.

## Remaining integration gate

1. commit this verification record and historical snapshot;
2. re-run the committed-tree verification;
3. fetch `origin` and verify `origin/main` is an ancestor of local `main`; and
4. push `main` normally without force or tag creation.

## Next safe action

Complete the remote ancestry check and approved normal push. Do not begin a new milestone until it is explicitly approved and sequenced in the roadmap.
