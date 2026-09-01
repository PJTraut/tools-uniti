# UNITI Current Status

Date: 2026-09-01

## Canonical baseline

| Item | Current value |
|---|---|
| Repository branch | `main` |
| Baseline when a16 usability work resumed | `052f733` — `docs: record v0.001a16 verification` |
| Active product milestone | `v0.001a16` — Usable Test Alpha |
| Latest implemented a16 workstream | startup/bootstrap/initialization foundation at `8bde00f` |
| Display version metadata | `v0.001a16` |
| PEP 440 package metadata | `0.1a16` |
| Latest immutable release tag | `v0.001a15` at `10f419e` |
| Queued milestones | `v0.001a17` through `v0.001a23` |

The `v0.001a15` tag remains immutable. The post-tag Qt completion fix at `6b81185` and the startup/bootstrap workstream are implemented on `main`. They are foundations inside a16; they do not satisfy the complete Usable Test Alpha exit criteria and do not close the product milestone.

## Implemented a16 foundation

- explicit source/local bootstrap under a discovered Python 3.12+;
- safe environment ownership, adoption, partial-state retention, locking, and repair;
- canonical managed dependency install, validation, and fingerprinting;
- atomic setup/settings schemas and bounded lifecycle logs;
- ordered BOOT→READY startup coordination and failure taxonomy;
- runtime/filesystem/resource/Qt capabilities and bounded cleanup;
- stable fast/deep self-check reports and offscreen functional coverage; and
- completed startup state in diagnostics.

## Active a16 outcome

The remaining a16 work is deliberately implementation-led: make UNITI usable as a routine basic editor and use it daily to expose friction and defects. The active scope covers editor commands/navigation, bounded undo, editor and Find/Replace zoom, soft wrap, reload/revert, the floating modeless Find/Replace workflow, safe replacement, assignable hotkeys, persisted UI state, status indicators, and Western/Cyrillic fixed-pitch font coverage.

The authoritative exit contract is the [a16 Usable Test Alpha plan](../02_plans/v0.001a16-usable-test-alpha.md). Planned behavior is not treated as current until its tests and acceptance evidence pass.

## Recorded verification evidence

The startup/bootstrap workstream closure at `8bde00f` recorded:

```text
357 passed, 1 skipped
```

Compilation, headless alpha smoke, managed-runtime bootstrap, deep offscreen self-check, import boundaries, documentation links, and `git diff --check` also passed at that historical baseline. Fresh verification for active a16 work supersedes this count as implementation proceeds.

## Known usability gaps

- Find/Replace is still an embedded bottom panel rather than the approved floating modeless utility.
- Editor zoom, independent F/R zoom, soft wrap, Go to Line, Reload/Revert, and configurable hotkeys are not yet complete.
- The current core history is not yet capped at 50 document transactions, and Find/Replace fields do not yet provide the approved independent bounded histories.
- Required a16 state persistence, report placement, status indicators, literal/regex mode split, and complete navigation behavior are still active work.
- The a16 dogfood, macOS GUI smoke, and no-known-integrity-defect gates have not yet closed.

See [Scope](SCOPE.md), [Architecture](ARCHITECTURE.md), [Development](DEVELOPMENT.md), [Roadmap](../02_plans/ROADMAP.md), and [Implemented](../03_implemented/README.md).
