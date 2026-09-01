# UNITI Current Handover

Captured: 2026-09-02

This is a continuation snapshot, not a controlling specification. Resolve conflicts using the authority order in the [Documentation System](../00_governance/DOCUMENTATION_SYSTEM.md).

## Canonical repository state

- Repository: `https://github.com/PJTraut/tools-uniti.git`
- Canonical branch: `main`
- Remote baseline: `origin/main` at `052f733`
- Final a17 implementation checkpoint: `c016007` — acceptance matrix, text-integrity self-check, and combined smoke
- Latest implemented milestone: `v0.001a17` — Text Integrity Alpha
- Active milestone: `v0.001a18` — Large-File Alpha
- Current display/package metadata: `v0.001a17` / `0.1a17`
- Latest immutable tag: `v0.001a15` at `10f419e`
- a16/a17 tags: none

Local `main` contains the completed a16 and a17 sequences after `origin/main`. No tag or push is implied by milestone completion. Inspect `git status` and `git log origin/main..HEAD`, then obtain or confirm the user's integration decision before changing the remote.

## Canonical records

- [Current status](../01_current/STATUS.md)
- [Current scope](../01_current/SCOPE.md)
- [Current architecture](../01_current/ARCHITECTURE.md)
- [Development workflow](../01_current/DEVELOPMENT.md)
- [Ordered roadmap](../02_plans/ROADMAP.md)
- [Active a18 scope](../02_plans/v0.001a18-large-file-alpha.md)
- [Implemented a17 milestone](../03_implemented/milestones/2026-09-01-uniti-v0.001a17-text-integrity-alpha.md)
- [Implemented a17 design](../03_implemented/designs/2026-09-01-uniti-v0.001a17-text-integrity-design.md)
- [Implemented a17 execution plan](../03_implemented/milestones/2026-09-01-uniti-v0.001a17-text-integrity-implementation.md)
- [Parked capabilities](../04_parked/CATALOG.md)
- [Architecture decisions](../05_decisions/README.md)

## a17 closure

a17 implements exact encoding/BOM profiles, separate serious encoding and remedial EOL decisions, bounded preview and full EOL inspection, modeless mixed-EOL handling, compact saved/pending format status, verified staged output, malformed-byte preservation/blocking rules, strict unrepresentable-character failures, and separate in-place Save versus export-copy identity.

Save As now owns filename/encoding/EOL together, preserves source-tab state for different destinations, opens the verified output in a new tab, blocks dirty open targets, double-confirms clean open-target replacement, warns separately for exact encoding changes, reuses target tabs, and rejects destinations changed after preflight confirmation.

Fresh completion evidence:

```text
552 passed, 4 skipped in 14.40s
deep self-check: pass, including text-integrity
offscreen combined smoke: core/gui pass; qt_platform=offscreen
native combined smoke: core/gui pass; qt_platform=cocoa; shown/closed=true
eight-format non-pytest dogfood: open/search/edit/Save/Save As/SHA-256/reopen pass
git diff --check: pass before documentation closure
```

The skips are one xattr capability case and three Windows-only launcher checks unavailable on macOS. Dogfood covered UTF-8 no BOM/CRLF, UTF-8 BOM/LF, Windows-1252/CRLF, UTF-16 LE no BOM, UTF-16 BE BOM, UTF-32 LE BOM, mixed EOL, and malformed UTF-8. No known data-loss, silent encoding/EOL, malformed-byte, document-identity, or save-state defect remains.

## Active and queued work

`v0.001a18` Large-File Alpha is active. `v0.001a19` Regex Intelligence, `v0.001a20` Recovery & Session, `v0.001a21` Cross-Platform, `v0.001a22` Dogfood/Performance, and `v0.001a23` Beta Candidate remain queued in that order.

Extension-sensed file-type profiles and syntax highlighting remain parked with no target version. They are not a18 scope unless explicitly re-evaluated and promoted through the roadmap process.

## Next safe action

Review the a17 verification and documentation closure, then—only with explicit user confirmation—perform a normal non-force push of `main`. After integration, turn the approved a18 scope into an evidence-based design and test-first executable implementation plan before changing large-file behavior. Do not tag a17 unless separately requested.
