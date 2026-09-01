# UNITI Current Handover

Captured: 2026-09-01

This is a continuation snapshot, not a controlling specification. Resolve conflicts using the authority order in the [Documentation System](../00_governance/DOCUMENTATION_SYSTEM.md).

## Canonical repository state

- Repository: `https://github.com/PJTraut/tools-uniti.git`
- Canonical branch: `main`
- Remote baseline: `origin/main` at `052f733`
- Latest a16 feature checkpoint: `fe7bf17` — launcher application-option forwarding
- Active milestone: `v0.001a16` — Usable Test Alpha
- Current display/package metadata: `v0.001a16` / `0.1a16`
- Latest immutable tag: `v0.001a15` at `10f419e`
- a16 tag: none

Local `main` contains the complete automatically verified a16 implementation sequence and is ahead of `origin/main`. Push remains intentionally withheld until the remaining interactive a16 gates are completed and the user approves the push. Inspect `git status` and `git log origin/main..HEAD` for the exact continuation state.

## Canonical records

- [Current status](../01_current/STATUS.md)
- [Current scope](../01_current/SCOPE.md)
- [Current architecture](../01_current/ARCHITECTURE.md)
- [Development workflow](../01_current/DEVELOPMENT.md)
- [Ordered roadmap](../02_plans/ROADMAP.md)
- [Active a16 exit contract](../02_plans/v0.001a16-usable-test-alpha.md)
- [Active a16 implementation plan](../02_plans/v0.001a16-implementation-plan.md)
- [Implemented startup/bootstrap workstream](../03_implemented/milestones/2026-09-01-uniti-v0.001a16-startup-bootstrap.md)
- [Parked capabilities](../04_parked/CATALOG.md)
- [Architecture decisions](../05_decisions/README.md)

## Implemented and verified in the active a16 sequence

- 50-transaction document history and coalesced typing/deletion;
- editor navigation, Go to Line, protected Reload/Revert, clipboard commands, zoom, fixed-pitch Western/Cyrillic coverage, progressive soft wrap, persistence, and status;
- floating modeless Find/Replace with literal/regex separation, independent zoom/geometry/report state, capture-only reports, and separate 50-step field histories;
- focus-owned Undo/Redo and clipboard routing across the editor, Find, and Replace areas;
- scoped shared command registry and persistent Hotkeys popup;
- single-step undoable Replace and Replace All with no streamed disk-rewrite bypass; and
- root macOS and Windows launchers through the canonical bootstrap path.

The first end-to-end launcher probe exposed and then corrected a bootstrap parsing defect: application options such as `--version` are now forwarded in order, while `--` protects filenames that overlap bootstrap switches.

Fresh evidence at the feature checkpoint:

```text
411 passed, 4 skipped in 10.72s
compileall: pass
alpha_smoke.py: ok=true
deep offscreen self-check: status=pass, exit_code=0
./uniti.command --version: v0.001a16
```

The skips are one xattr capability case and three Windows launcher cases unavailable on macOS.

## Exact active-plan position

Tasks 1–7 and Task 8 automated steps 1–4 in the [a16 implementation plan](../02_plans/v0.001a16-implementation-plan.md) are complete. Task 8 steps 5–6 remain open:

1. run UNITI interactively on macOS through `./uniti.command`;
2. exercise representative Western and Cyrillic editing, navigation, search, replace, save, reload, restart, persistence, and hotkey workflows;
3. capture every blocking/basic usability or text-integrity failure as a failing automated test before fixing it; and
4. freeze a16 only when no acceptance gap remains.

Do not move a16 to `03_implemented`, activate a17, tag a16, or push milestone completion before those gates close.

## Queue

After a16, implement in sequence: `v0.001a17` Text Integrity, `v0.001a18` Large-File, `v0.001a19` Regex Intelligence, `v0.001a20` Recovery & Session, `v0.001a21` Cross-Platform, `v0.001a22` Dogfood/Performance, and `v0.001a23` Beta Candidate.

## Next safe action

Launch `./uniti.command`, perform the interactive macOS smoke and real editing/search dogfood checklist, and report any friction with exact reproduction steps. If the gates are clean, record the evidence, complete Task 8 steps 5–6, move a16 to `03_implemented`, activate a17, rerun verification, then request the final push decision.
