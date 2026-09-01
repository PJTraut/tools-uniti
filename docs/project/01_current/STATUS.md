# UNITI Current Status

Date: 2026-09-01

## Canonical baseline

| Item | Current value |
|---|---|
| Repository branch | `main` |
| Remote baseline | `origin/main` at `052f733` |
| Verified a16 implementation checkpoint | `fe7bf17` — launcher application-option forwarding |
| Local integration state | `main` contains unpushed a16 commits after `origin/main`; do not push until a16 is approved for push |
| Active product milestone | `v0.001a16` — Usable Test Alpha |
| Display/package metadata | `v0.001a16` / `0.1a16` |
| Latest immutable release tag | `v0.001a15` at `10f419e` |
| Queued milestones | `v0.001a17` through `v0.001a23` |

The `v0.001a15` tag remains immutable. The post-tag Qt completion fix, the startup/bootstrap workstream, the root launchers, and the a16 usability implementation are on local `main`. The a16 product milestone remains active because its interactive macOS and real-use acceptance gates have not yet been recorded.

## Implemented a16 behavior

- document Undo/Redo is capped at 50 transactions, with coalesced typing/backspace/delete and correct save-point behavior;
- Cut, Copy, Paste, Select All, Go to Line, Reload/Revert, page/document/Unicode-word navigation, and Shift selection dispatch through the editor state;
- editor zoom, primary-modifier wheel zoom, fixed-pitch Western/Cyrillic font selection, progressive soft wrap, and zoom/wrap status indicators are implemented;
- editor zoom and wrap persist through the existing settings store;
- Find/Replace is a floating modeless utility with independent zoom and geometry, separate 50-step Find and Replace histories, focus-owned editing commands, and Hidden/Bottom/Right report placement;
- literal and raw-regex modes are explicit; Case Sensitive and Whole Word belong only to literal mode; capture reports show groups `1..N` and exclude group `0`;
- Replace and Replace All mutate the authoritative `Document`; Replace All is one atomic undoable transaction and never bypasses history through a disk rewrite;
- the top-level Hotkeys popup exposes the six approved horizontal categories, Default/Current columns, assignment, clearing, collision detection, selected/category/all resets, scoped dispatch, and persisted overrides; and
- root macOS and Windows launchers use the canonical bootstrap path and forward arguments and exit status.

## Fresh verification evidence

At the `fe7bf17` implementation checkpoint:

```text
411 passed, 4 skipped in 10.72s
```

The four skips are one platform xattr capability case and three Windows launcher cases unavailable on macOS. The following gates also exited zero:

- `python -m compileall -q src scripts tests`;
- `python scripts/alpha_smoke.py` with `"ok": true`;
- deep offscreen self-check with top-level `"status": "pass"` and `"exit_code": 0`; and
- the integrated a16 acceptance checks for atomic Replace All, persisted UI state, focused command ownership, and status indicators;
- focused bootstrap/launcher coverage; and
- the real root launcher returning `v0.001a16` for `./uniti.command --version`.

## Remaining a16 gates

- run the interactive macOS GUI smoke through `./uniti.command`;
- use UNITI for representative real editing, search, replace, save, reload, and restart work;
- add a failing automated test before correcting every blocking/basic usability or text-integrity defect discovered; and
- confirm that no known data-loss or text-integrity defect remains after that use.

Automated implementation is green, but those human-observation gates are part of the milestone contract. Until they pass, a16 stays in `02_plans`, no a16 tag is created, and a17 remains queued.

See [Scope](SCOPE.md), [Architecture](ARCHITECTURE.md), [Development](DEVELOPMENT.md), [Roadmap](../02_plans/ROADMAP.md), and [the active a16 plan](../02_plans/v0.001a16-usable-test-alpha.md).
