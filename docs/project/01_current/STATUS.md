# UNITI Current Status

Date: 2026-09-01

## Canonical baseline

| Item | Current value |
|---|---|
| Repository branch | `main` |
| Implemented milestone | `v0.001a16` startup/bootstrap/initialization |
| Display version metadata | `v0.001a16` |
| PEP 440 package metadata | `0.1a16` |
| Latest immutable release tag | `v0.001a15` at `10f419e` |
| Outstanding milestone | none |

The `v0.001a15` tag remains immutable. The post-tag Qt completion fix at `6b81185`, the project-documentation system, and the full a16 lifecycle are included in current `main`. No a16 tag is created by this completion instruction.

## Implemented a16 outcome

- explicit source/local bootstrap under a discovered Python 3.12+;
- safe environment ownership, adoption, partial-state retention, locking, and repair;
- canonical managed dependency install/validation/fingerprinting;
- atomic setup/settings schemas and bounded lifecycle logs;
- exact BOOT→READY startup coordination and failure taxonomy;
- runtime/filesystem/resource/Qt capabilities and bounded cleanup;
- stable fast/deep self-check reports and offscreen functional coverage; and
- completed startup state in diagnostics.

## Verification evidence

Focused task-level red/green gates and the a16 acceptance contract pass on the development macOS/Python 3.12/PySide6 environment. The final full-suite count and exact committed baseline are recorded in the current and historical handovers after closure verification.

The capability-dependent extended-attribute save test may remain the single explicit skip when xattrs are unavailable in the active Python/platform combination.

## Planned work

There is no approved active or queued product milestone. The [Roadmap](../02_plans/ROADMAP.md) is intentionally empty. New work must be approved and sequenced there before becoming active.

Ideas outside current architecture or scope remain in the [Parked Capability Catalog](../04_parked/CATALOG.md) without version or delivery commitments.

## Known limitations

- A supported host Python must already be installed; UNITI does not install Python.
- Platform installers, embedded runtimes, signing, shortcuts, and updater remain outside scope.
- Extended attributes, clipboard selection, IME, display topology, and mmap are reported capabilities rather than universal guarantees.
- Local bootstrap installs from a validated source checkout; it is not a signed distribution channel.

See [Scope](SCOPE.md), [Architecture](ARCHITECTURE.md), [Development](DEVELOPMENT.md), and [Implemented](../03_implemented/README.md).
