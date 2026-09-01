# UNITI Current Handover

Captured: 2026-09-01

This is a continuation snapshot, not a controlling specification. Resolve conflicts using the authority order in the [Documentation System](../00_governance/DOCUMENTATION_SYSTEM.md).

## Canonical repository state

- Repository: `https://github.com/PJTraut/tools-uniti.git`
- Canonical branch: `main`
- Remote baseline: `origin/main` at `052f733`
- Final a16 implementation checkpoint: `7d8866a` — editor interactions and glyph-boundary selection
- Latest implemented milestone: `v0.001a16` — Usable Test Alpha
- Active milestone: `v0.001a17` — Text Integrity Alpha
- Current display/package metadata: `v0.001a16` / `0.1a16`
- Latest immutable tag: `v0.001a15` at `10f419e`
- a16 tag: none

Local `main` contains the completed a16 sequence and project-record closure after `origin/main`. No tag or push is implied by milestone completion; inspect `git status` and `git log origin/main..HEAD`, then obtain or confirm the user's integration decision before changing the remote.

## Canonical records

- [Current status](../01_current/STATUS.md)
- [Current scope](../01_current/SCOPE.md)
- [Current architecture](../01_current/ARCHITECTURE.md)
- [Development workflow](../01_current/DEVELOPMENT.md)
- [Ordered roadmap](../02_plans/ROADMAP.md)
- [Active a17 scope](../02_plans/v0.001a17-text-integrity-alpha.md)
- [Implemented a16 milestone](../03_implemented/milestones/2026-09-01-uniti-v0.001a16-usable-test-alpha.md)
- [Implemented a16 execution plan](../03_implemented/milestones/2026-09-01-uniti-v0.001a16-usable-test-alpha-implementation.md)
- [Parked capabilities](../04_parked/CATALOG.md)
- [Architecture decisions](../05_decisions/README.md)

## a16 closure

a16 now includes the 50-step document and F/R histories, core editor commands/navigation/wrap/zoom, floating modeless Find/Replace, atomic undoable Replace All, persistent scoped Hotkeys, compact CotEditor-reference menus, native shortcut display, focus-owned editor/F/R wheel zoom, double/triple/quadruple-click selection, and root macOS/Windows launchers.

Fresh completion evidence:

```text
416 passed, 4 skipped in 10.92s
compileall: pass
alpha_smoke.py: ok=true
deep offscreen self-check: status=pass, exit_code=0
Qt-free core/regex/resource boundary: pass
./uniti.command --version: v0.001a16
native cocoa open/edit/save/find/hotkeys/menu/zoom smoke: pass
```

The skips are one xattr capability case and three Windows-only launcher checks unavailable on macOS. User dogfood exposed legacy menu accumulation, missing F/R mouse zoom, and missing multiple-click selection behavior; these were corrected under failing automated tests. No known data-loss or text-integrity defect remains.

## Active and queued work

`v0.001a17` Text Integrity is active. `v0.001a18` Large-File, `v0.001a19` Regex Intelligence, `v0.001a20` Recovery & Session, `v0.001a21` Cross-Platform, `v0.001a22` Dogfood/Performance, and `v0.001a23` Beta Candidate remain queued in that order.

## Next safe action

First decide whether to fast-forward push the completed local a16 sequence. If development continues locally instead, turn the approved a17 scope into a test-first executable implementation plan before changing version metadata or code.
