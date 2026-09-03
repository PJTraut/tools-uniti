# UNITI Current Handover

Captured: 2026-09-03

This is a continuation snapshot, not a controlling specification. Resolve conflicts using the authority order in the [Documentation System](../00_governance/DOCUMENTATION_SYSTEM.md).

## Canonical repository state

- Repository: `https://github.com/PJTraut/tools-uniti.git`
- Canonical branch: `main`
- Remote baseline: `origin/main` at `84407e3`
- Local a19 implementation sequence: `45d7a20` through `06d644d`, followed by the a19 freeze closure
- Latest implemented milestone: `v0.001a19` — Regex Intelligence Alpha
- Active milestone: `v0.001a20` — Recovery & Session Alpha
- Current display/package metadata: `v0.001a19` / `0.1a19`
- Latest immutable tag: `v0.001a15` at `10f419e`
- a16/a17/a18/a19 tags: none

a19 is implemented and verified on local `main`. `origin/main` is intentionally unchanged until a separate push is authorized; no tag has been created.

## Canonical records

- [Current status and exact a19 evidence](../01_current/STATUS.md)
- [Current scope](../01_current/SCOPE.md)
- [Current architecture](../01_current/ARCHITECTURE.md)
- [Development and performance workflow](../01_current/DEVELOPMENT.md)
- [Ordered roadmap](../02_plans/ROADMAP.md)
- [Active a20 scope](../02_plans/v0.001a20-recovery-session-alpha.md)
- [Implemented a19 milestone](../03_implemented/milestones/2026-09-02-uniti-v0.001a19-regex-intelligence-alpha.md)
- [Implemented a19 design](../03_implemented/designs/2026-09-02-uniti-v0.001a19-regex-intelligence-design.md)
- [Implemented a19 execution plan](../03_implemented/milestones/2026-09-02-uniti-v0.001a19-regex-intelligence-implementation.md)
- [Historical a18 handover](history/2026-09-02-v0.001a18-large-file-alpha.md)
- [Parked capabilities](../04_parked/CATALOG.md)
- [Architecture decisions](../05_decisions/README.md)

## a19 closure

a19 turns regex authoring and results into one generation-sealed intelligence path. Pattern and replacement inputs now receive asynchronous engine-validated analysis, shared group/reference identities, paired delimiters, inline-switch presentation, and structured diagnostics. Search stores zero-width matches as first-class results and applies each exactly once across navigation, wrapping, rendering, Replace, and atomic one-Undo Replace All. A model-backed current/next Match Report resolves captures off-thread within explicit context, preview, and payload bounds.

Task delivery is now generation-monotonic, and analysis/capture latest-request slots serialize work and reject stale publication using expression, document, revision, store, and match-index seals. Superseded work releases owned snapshots and result artifacts. `regex==2026.5.9` remains the only matching, group-numbering, capture, and replacement authority.

Implementation commits:

```text
45d7a20 fix: make task status delivery monotonic
d147d22 feat: define regex analysis diagnostics
ba6c509 feat: reconcile regex group identities
a685717 feat: analyze regex replacement references
13840c8 feat: serialize latest regex task requests
126fe4d feat: debounce regex analysis off the gui thread
986d61c feat: render shared regex group identities
db3699b fix: preserve zero width regex results
0b8991a feat: complete zero width regex behavior
771a179 feat: bound regex capture reports
2d7147f feat: publish async regex match reports
06d644d test: add a19 regex intelligence gates
```

Fresh closure evidence:

```text
focused a19 + inherited suites: 273 passed
complete suite: 779 passed, 4 skipped
compileall and git diff --check: pass
deep self-check: pass, including valid runtime ownership,
  regex-intelligence, text-integrity, and large-file
offscreen and native Cocoa combined smoke: pass
native visual/interaction checklist: pass
controlled quick: 12/12 PASS
controlled 100 MiB routine: 12/12 PASS
native Cocoa 10 MiB quick: 12/12 PASS
```

The documented skips are one unavailable xattr capability and three Windows launcher cases on macOS. Selected schema-1 a19 results are `benchmarks/baselines/v0.001a19-mac15-8-routine.json` and `benchmarks/baselines/v0.001a19-mac15-8-native-quick.json`. Regex-intelligence routine medians were 3.48 ms analysis, 49.11 ms capture reporting, 21.45 ms zero-width planning, 6.33 ms maximum heartbeat, 1.30 ms cancellation, and 25.36 MiB retained RSS. Native quick medians were 3.27 ms, 48.27 ms, 21.60 ms, 6.42 ms, 1.30 ms, and 21.53 MiB respectively. Both complete runs evaluated all twelve scenarios `PASS`.

The native Cocoa checklist additionally drove real widget focus and keyboard input and visually inspected original-resolution captures. It confirmed eight distinct group colors with shared replacement-reference identity, paired groups, scoped switches, diagnostic wave/text, readable current/next report rows, exact navigation and single-result wrapping, visible cancellation state, and zero-width insertion markers at line/document ends. The temporary screenshots are not selected benchmark artifacts.

## Defect and limitation state

The post-a18 task-status race, pre-start cancellation ghosts, worker-future publication race, repeated-empty capture formatting, Qt shutdown callback, whole-document capture measurement, and performance-harness retained-reference defects all have deterministic regression coverage. No known regex correctness, infinite-navigation, GUI-freeze, stale-publication, partial-replacement, data-loss, text-integrity, or runtime-ownership blocker remains.

Interactive expressions longer than 65,536 code points remain editable but unavailable for regex execution. Advanced identity color is conservatively withheld when structural facts cannot be reconciled with successful engine metadata. Capture detail that cannot be completed within the report bounds is explicitly unavailable.

Editor whitespace visualization and a keyboard command to report Unicode values for selected or preceding characters are recorded in the [Parked Capability Catalog](../04_parked/CATALOG.md) as future editor-display work. They are not silently added to a20.

## Active and queued work

`v0.001a20` Recovery & Session Alpha is active at order 1. `v0.001a21` Cross-Platform, `v0.001a22` Dogfood/Performance, and `v0.001a23` Beta Candidate remain queued at orders 2–4.

Extension-sensed file-type profiles and syntax highlighting remain parked with no target version. Promotion of any parked feature requires explicit re-evaluation and a roadmap decision.

## Next safe action

Write and review the a20 Recovery & Session design and its test-first implementation plan against the current recovery/session code before changing product behavior. Preserve the verified a19 gates, remain on `main` unless directed otherwise, and do not tag or push until separately authorized.
