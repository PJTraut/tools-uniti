# UNITI Current Status

Date: 2026-09-01

## Canonical baseline

| Item | Current value |
|---|---|
| Repository branch | `main` |
| Remote baseline | `origin/main` at `052f733` |
| Verified a16 implementation checkpoint | `05ef391` — resizable and regrouped Find/Replace UI |
| Local integration state | `main` contains unpushed a16 completion commits after `origin/main`; push remains a separate user decision |
| Latest implemented milestone | `v0.001a16` — Usable Test Alpha |
| Active product milestone | `v0.001a17` — Text Integrity Alpha |
| Display/package metadata | `v0.001a16` / `0.1a16` |
| Latest immutable release tag | `v0.001a15` at `10f419e` |
| Queued milestones | `v0.001a18` through `v0.001a23` |

The `v0.001a15` tag remains immutable. The post-tag Qt completion fix, startup/bootstrap workstream, launchers, and complete a16 usability milestone are on local `main`. a16 is implemented without a new tag; version metadata remains at the last implemented product milestone until a17 implementation deliberately advances it.

## Implemented a16 behavior

- document Undo/Redo is capped at 50 transactions, with coalesced typing/backspace/delete and correct save-point behavior;
- Cut, Copy, Paste, Select All, Go to Line, Reload/Revert, page/document/Unicode-word navigation, and Shift selection dispatch through editor state;
- double-click selects a word, triple-click selects a visual line, and quadruple-click selects the complete logical line through its line break;
- editor zoom, primary-modifier wheel zoom, fixed-pitch Western/Cyrillic font selection, progressive soft wrap, persistence, and zoom/wrap status are implemented;
- Find/Replace is a mouse-resizable floating utility with independent keyboard/mouse zoom, geometry, separate 50-step histories, explicit Literal/Regex modes, grouped batch/match actions, and an unrestricted collapsible capture splitter;
- report placement remains `Hidden | Bottom | Right` and rotates through one scoped, configurable `Ctrl+Alt+R` command;
- literal and raw-regex modes are explicit; Case Sensitive and Whole Word belong only to literal mode; capture reports show groups `1..N` and exclude group `0`;
- Replace and Replace All mutate the authoritative `Document`; Replace All is one atomic undoable transaction and never bypasses history through a disk rewrite;
- the compact menu bar is `File | Edit | Format | View | Find | Tools | Hotkeys`, with the former top-level Navigation, Search, F/R View, Encoding, and EOL artifacts removed;
- Hotkeys exposes the six approved horizontal categories, native Default/Current display, assignment, clearing, collision detection, selected/category/all resets, scoped dispatch, and portable persisted overrides; and
- root macOS and Windows launchers use the canonical bootstrap path and forward arguments and exit status.

## a16 completion evidence

Fresh verification after the final usability corrections reported:

```text
419 passed, 4 skipped in 10.36s
compileall: pass
alpha_smoke.py: ok=true
deep offscreen self-check: status=pass, exit_code=0
Qt-free core/regex/resource boundary: pass
./uniti.command --version: v0.001a16
native Qt platform: cocoa
native F/R resize, capture resize/collapse, action groups, Literal/Regex modes, report-cycle hotkey: pass
```

The four skips are one platform xattr capability case and three Windows launcher cases unavailable on macOS. Real-use feedback exposed the remaining basic usability defects: legacy menu accumulation, missing focus-owned F/R mouse zoom, missing multiple-click selection units, and constrained/ambiguous F/R controls. Each correction was locked by automated coverage before the final full and native-macOS runs. No known data-loss or text-integrity defect remains at this baseline.

All five a16 acceptance gates are therefore recorded as passed. The milestone scope and execution plan now reside in [`03_implemented`](../03_implemented/README.md), and a17 is the active outstanding milestone.

See [Scope](SCOPE.md), [Architecture](ARCHITECTURE.md), [Development](DEVELOPMENT.md), [Roadmap](../02_plans/ROADMAP.md), and [the implemented a16 milestone](../03_implemented/milestones/2026-09-01-uniti-v0.001a16-usable-test-alpha.md).
