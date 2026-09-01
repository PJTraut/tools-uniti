# UNITI Current Status

Date: 2026-09-01

## Canonical baseline

| Item | Current value |
|---|---|
| Repository branch | `main` |
| Implemented product-code baseline | `6b81185` — `fix: deliver regex results through Qt event loop` |
| Latest immutable release tag | `v0.001a15` at `10f419e` |
| Display version metadata | `v0.001a15` |
| PEP 440 package metadata | `0.1a15` |
| Next milestone | `v0.001a16` startup/bootstrap/initialization |

Documentation-only commits follow `6b81185`; they do not change application behavior or version metadata. The `v0.001a15` tag must remain at `10f419e`. The Qt completion fix at `6b81185` is intentionally post-tag and will be included by the next version rather than by moving the existing tag.

## Verification evidence

The supplied real macOS/PySide6 offscreen verification at `6b81185` completed with:

```text
286 passed, 1 skipped
```

The single skip was `tests/core/test_save.py:141` because extended attributes were unsupported by that Python/platform combination. The two Qt Find/Replace regressions fixed by `6b81185` also passed independently before the full suite.

Earlier sandbox validation for the tagged `10f419e` candidate included the full Qt-optional test accounting, `compileall`, `git diff --check`, headless smoke coverage, import-boundary checks, and targeted large-file/search performance gates. The real Mac run closes the earlier PySide6 runtime gap for the tested environment.

## Active development

[`v0.001a16`](../02_plans/v0.001a16-startup-bootstrap.md) is the only approved outstanding product milestone. Its current phase is design finalization; application-code implementation has not started.

No later product milestone is queued. Ideas outside current architecture or scope are recorded in the [parked catalog](../04_parked/CATALOG.md), without sequence or version commitments.

## Known limitations and constraints

- The planned host-Python bootstrap and self-check lifecycle is not yet implemented.
- Normal source development still uses a manually created repository `.venv`.
- Extended-attribute preservation remains capability-dependent and may be explicitly skipped when unavailable.
- Existing `v0.001a15` wheel, source archive, and Git bundle were produced from `10f419e` and therefore do not include `6b81185`.
- Platform installers with embedded runtimes remain outside current scope.

See [Scope](SCOPE.md), [Architecture](ARCHITECTURE.md), [Development](DEVELOPMENT.md), and the ordered [Roadmap](../02_plans/ROADMAP.md).
