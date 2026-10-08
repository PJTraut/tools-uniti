# UNITI Ordered Roadmap

Date: 2026-09-20

B4 Compare, Character Inspector & Per-View Settings Beta is the active source-development milestone. The user-directed version move is recorded in [ADR-0012](../05_decisions/ADR-0012-b4-version-and-qualification.md), continuing [ADR-0008](../05_decisions/ADR-0008-b3-version-and-qualification.md)'s B2→B3 pattern. All reviewed BF-019, BF-070, BF-072, BF-073, and BF-075 source changes are integrated; the version is `v0.001b4` / `0.1b4`. See the [B4 milestone plan](v0.001b4-compare-character-inspector-and-per-view-settings-beta.md) for the full item-by-item table and the specific items still excluded from scope.

## Active development and outstanding qualification

| Order | Milestone | Status | Remaining purpose |
|---|---|---|---|
| 1 | [`v0.001b4` — Compare, Character Inspector & Per-View Settings Beta](v0.001b4-compare-character-inspector-and-per-view-settings-beta.md) | **active** | Validate the integrated beta source and close native input, affected-host, and hosted checks. |
| — | [`v0.001b3` — Find/Replace Rework & Editor Refinement Beta](v0.001b3-find-replace-and-editor-refinement-beta.md) | superseded as active; own evidence queued | BF-017, BF-019 (pre-B4 re-confirmation), BF-025, and every carried-forward B2 item's native-host and hosted-CI confirmation remains open, tracked per item in the feedback log. |
| — | [`v0.001b2` — Feedback Refinement Beta](v0.001b2-feedback-refinement-beta.md) | superseded as active; own evidence queued | BF-001–BF-010 native-host and hosted-CI confirmation remains open, tracked per item in the feedback log. |
| 2 | [`v0.001a22` — Dogfood / Performance Alpha](v0.001a22-dogfood-performance-alpha.md) | queued qualification | Record the seven required distinct real-use days; implemented performance infrastructure remains in use. |
| 3 | [`v0.001a23` — Executable Health & Recovery Alpha](v0.001a23-executable-health-recovery-alpha.md) | queued | Deliver and qualify native executable startup, health, and recovery. |
| 4 | [`v0.001a24` — Beta Candidate](v0.001a24-beta-candidate.md) | queued | Satisfy the complete executable stabilization gate. |
| 5 | [`v0.001b1` — Real-World Feedback Beta](v0.001b1-real-world-feedback-beta.md) | queued qualification | Complete qualified private executable feedback over fourteen calendar days with three independent testers covering macOS, Windows, and Linux. |

The historical milestone names remain stable links to their acceptance requirements. They are not future version downgrades. Outstanding qualification follows rows 2–5 (plus B2's and B3's own carried-forward evidence) before qualified executable release; advancing the source label does not mark any of them passed.

## Current work

The [feedback transition plan](2026-09-08-b1-feedback-b2-transition-plan.md) records the B1→B2 implementation and remaining work; later promotions have no separate transition plan document beyond their ADR ([ADR-0008](../05_decisions/ADR-0008-b3-version-and-qualification.md) for B2→B3, [ADR-0012](../05_decisions/ADR-0012-b4-version-and-qualification.md) for B3→B4) and their milestone plan itself. The [feedback log](../BETA_FEEDBACK.md) tracks each BF item; the [outstanding work pools](2026-09-16-outstanding-work-pools.md) document clusters what's still open into batches for planning the next pass. The [current status](../01_current/STATUS.md) separates local tests, hosted results, physical input checks, and release evidence.

The [isolated file-type environment framework plan](2026-09-29-environment-framework-e1-e4-plan.md) (Phases E1–E4 implemented 2026-09-29, full suite green at 2,212 passed/6 platform skips; see [ADR-0013](../05_decisions/ADR-0013-environment-framework-ownership-boundary.md)) is a separate engineering-track initiative running alongside B4 — it does not gate B4's qualification and is not itself a version-qualification milestone. Phase E5 (generic SFM foundation, [plan](2026-09-29-environment-framework-e5-sfm-foundation-plan.md)) and Phase E6 (USFM layer: vendored baseline `usfm.sty`, `.usfm` as its own environment, chapter/verse index, `usfmtc` reference validation, [plan](2026-09-30-environment-framework-e6-usfm-layer-plan.md)) are implemented, full suite green at 2,280 passed/6 platform skips (2026-10-02). The [environment workbench](2026-10-02-environment-workbench-plan.md) ([ADR-0014](../05_decisions/ADR-0014-environment-workbench-and-extension-assignment.md), 2026-10-02) then gave every file type an environment with its own menu, commands and findings list, per-environment extension assignment (View > File Type Environments…), and a per-view Plain Text Mode fallback. [ADR-0015](../05_decisions/ADR-0015-stylesheet-layers-and-rich-views.md) ([record](2026-10-02-rich-views-and-grouped-tabs-plan.md), 2026-10-02) completed E6 (layered project `.sty` files with provenance, Style Inspector) and implemented E7–E10: the rich-view/source-map framework, SFM Standard and Formatted views, and the Markdown Rendered view, each editable beside Source through semantic edits. USFM field-test feedback ([ADR-0017](../05_decisions/ADR-0017-environment-windows-in-place-views-reference-sync.md), [record](2026-10-07-usfm-field-test-plan.md), 2026-10-07) moved those views into the tab itself and added environment windows with a Book/Chapter/Verse selector, side-by-side reference sync within a document group, stylesheet-only styling, `uniti.sty` presentation rules, and Preview's notes frame. [USFM projects, single files and versification](2026-10-07-usfm-projects-and-versification-plan.md) phases P1–P3 followed: Paratext `Settings.xml` projects, Open USFM Project… and Recent Projects ([ADR-0018](../05_decisions/ADR-0018-usfm-projects-and-recent-projects.md)), and the project's stylesheet, encoding and Book list.

### Environment track queue

Ordered, alongside B4. This track doesn't gate B4's qualification.

| Order | Item | Status | Plan |
|---|---|---|---|
| 1 | R1 — Standard/Preview mode switch speed: render once, render off-screen, cache the projection (41 s → 0.86 s for a 220 KB book) | implemented 2026-10-08 | [Field test round 2](2026-10-08-usfm-field-test-round-2-plan.md) |
| 2 | R2 — Nested `\+` markers (and milestones, column ranges, attributes) in the tokenizer, parser and style lookup; `\nd` small caps | implemented 2026-10-08 | [Field test round 2](2026-10-08-usfm-field-test-round-2-plan.md) |
| 3 | R3 — `\cat` shown as `[category]` in Preview notes | implemented 2026-10-08 | [Field test round 2](2026-10-08-usfm-field-test-round-2-plan.md) |
| 4 | R4 — Highlight the verse on Book/Chapter/Verse and Go to Chapter:Verse, in every mode | implemented 2026-10-08 | [Field test round 2](2026-10-08-usfm-field-test-round-2-plan.md) |
| 5 | R5 — One USFM environment: `.sfm`/`.usfm` both belong to USFM; generic SFM environment removed, saved `sfm` keys read as `usfm` | implemented 2026-10-08 | [Field test round 2](2026-10-08-usfm-field-test-round-2-plan.md) |
| 6 | R6 — "Open in <Environment> / Open as Plain Text" on open; Plain Text means no extended features | next (D2 decided) | [Field test round 2](2026-10-08-usfm-field-test-round-2-plan.md) |
| 7 | R8 — Environment documentation and editable configuration: user configuration folder per environment, Configuration Files…, reload on save, `docs/environments/` | queued (D3 decided) | [Field test round 2](2026-10-08-usfm-field-test-round-2-plan.md) |
| 8 | R7 — Report undefined markup when a file is opened: popup with copy/save report and edit/add definitions to configuration files (SFM/USFM, through a hook any environment can implement) | queued (D4 decided) | [Field test round 2](2026-10-08-usfm-field-test-round-2-plan.md) |
| 9 | P4 — Versification (built-in English and Original; others from `.vrs` files in a user folder; project `custom.vrs`) | queued | [Projects plan](2026-10-07-usfm-projects-and-versification-plan.md) |
| 10 | P5 — Sync across books and versifications (opens a project's missing book) | queued | [Projects plan](2026-10-07-usfm-projects-and-versification-plan.md) |

Wishlist, not queued: the USFM per-chapter view, and choosing which footnote categories Preview shows ([wishlist](../FEATURE_WISHLIST.md)).

A21 Cross-Platform Alpha and earlier completed milestones remain in [Implemented](../03_implemented/README.md). A22 source infrastructure and the beta feedback code are implemented, but unfinished milestone acceptance records remain here.

## Queue rules

- B4 is the one active development milestone. Earlier unfinished milestone requirements, including B2's and B3's own outstanding evidence, remain queued for release qualification under ADR-0007, ADR-0008, and ADR-0012.
- Source identity and qualified release readiness are recorded separately; missing evidence remains `NOT RUN` or pending.
- A milestone moves to implemented history only after its complete acceptance gate passes with evidence.
- Parked capabilities remain outside the queue. Scope changes require an explicit roadmap and decision update.

See [Project Grammar](../00_governance/GRAMMAR.md) and the [Parked Capability Catalog](../04_parked/CATALOG.md).
