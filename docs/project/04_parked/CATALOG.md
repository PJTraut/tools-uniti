# UNITI Parked Capability Catalog

Last reviewed: 2026-09-17

These capabilities are intentionally outside the lean editor boundary described by [Current Scope](../01_current/SCOPE.md). They are recorded for later re-evaluation, not promised delivery.

Current identity is `v0.001b3` / `0.1b3`, with feedback code through BF-068, plus BF-040/042, integrated on `main`. Bounded multi-window/document ownership and durable session restoration were implemented in A20 and are no longer parked. Bundled Indic/CJK/Arabic/Hebrew fallback, shaped bidi-aware editing, focused theme editing, and a bounded file-type syntax-highlighting extension point are also implemented; remaining native input qualification is tracked in [Current Status](../01_current/STATUS.md).

## Project and workspace concepts

- **Why parked:** Multi-file project state, discovery, persistence, and project-level commands would shift UNITI from a focused editor toward an IDE/workspace platform.
- **Known dependencies/risks:** workspace schema, file watching at directory scale, trust boundaries, session persistence, and interaction with large-file resource priorities.
- **Re-evaluation trigger:** sustained workflows that cannot be served safely by opening independent files and tabs.
- **Narrow exception, [ADR-0009](../05_decisions/ADR-0009-bounded-open-folder-by-type.md):** **File → Open Folder by Type…** is implemented — a one-shot, non-recursive batch-open of one file extension from a folder, with optional document-group assignment (BF-029). The folder is not retained as project state; no persistent project file, recursion, file-watching, or workspace session concept exists. Everything else in this entry remains parked.

## Plugin system

- **Why parked:** A plugin API would freeze extension boundaries before the editor core and lifecycle are mature, while adding third-party code execution and compatibility obligations.
- **Known dependencies/risks:** API/version governance, sandboxing or trust policy, dependency conflicts, discovery, updates, diagnostics, and crash isolation.
- **Re-evaluation trigger:** stable public core interfaces plus repeated, well-defined extension needs that cannot be satisfied in the core without product bloat.

## Language Server Protocol

- **Why parked:** LSP process management, project roots, language configuration, and semantic UI move UNITI toward IDE behavior outside its text-correctness focus.
- **Known dependencies/risks:** project/workspace ownership, subprocess lifecycle, protocol state, diagnostics overlays, large-file policy, and per-language configuration.
- **Re-evaluation trigger:** an explicit product decision to support coding intelligence while retaining bounded editor behavior.

## Git UI

- **Why parked:** Repository status, staging, history, and diff workflows are separate from UNITI's document ownership and editing responsibilities.
- **Known dependencies/risks:** project discovery, repository trust, subprocess/library choice, credential handling, and cross-platform Git availability.
- **Re-evaluation trigger:** approval of project/workspace scope and demonstrated need for integrated version-control workflows.

## Integrated terminal

- **Why parked:** Shell process management and terminal emulation add security, resource, accessibility, and cross-platform complexity unrelated to the text engine.
- **Known dependencies/risks:** pseudoterminal APIs, shell discovery, escape-sequence rendering, process trees, input routing, and environment trust.
- **Re-evaluation trigger:** a deliberate expansion from focused editor to development workspace.

## AI and cloud features

- **Why parked:** Networked inference, accounts, remote document transfer, and telemetry conflict with the current local, account-free product boundary.
- **Known dependencies/risks:** privacy, consent, credentials, data retention, connectivity, provider coupling, cost, and nondeterministic behavior.
- **Re-evaluation trigger:** an explicit privacy/security architecture and a user-approved product direction for optional network services.

## Hex editing

- **Why parked:** Arbitrary binary editing requires a different interaction, rendering, mutation, search, and save model from UNITI's decoded-text document semantics.
- **Known dependencies/risks:** byte-oriented cursor/selection APIs, binary history, hex/ascii synchronized views, non-text search, and interaction with encoding reinterpretation.
- **Re-evaluation trigger:** validated binary-editing demand and a design that preserves the existing text engine without conflating byte and character coordinates.

## File-type profiles and syntax highlighting

- **Status: partially un-parked, 2026-09-15; color editing also un-parked, 2026-09-17.** [BF-027](../BETA_FEEDBACK.md#bf-027--file-type-syntax-highlighting-profiles-xml-yml-json-sfm-md-tsv-csv-)/[BF-041](../BETA_FEEDBACK.md#bf-041-p3--syntax-highlighting-extension-point-does-not-exist) implemented a deliberately bounded first slice: a profile registry (Plain Text/Markdown/XML/JSON/YAML/SFM/CSV/TSV), extension-to-profile mapping with a user override setting, and presentation-only highlighting in the editor. This remains scoped down from the future capability described below in one specific way, kept parked here rather than claimed as resolved:
  - **Not incremental or multiline-aware.** Each profile's tokenizer runs independently per visible row/window, matching the granularity the editor already uses for whitespace markers — bounded and huge-file-safe by construction, but a construct spanning more than one visible row (a multi-line comment, a fenced code block, a value wrapped across visual rows) will not highlight correctly across that boundary. True incremental, cross-row grammar state remains parked.
  - ~~No theme-editor UI for colors.~~ Resolved by [BF-063](../BETA_FEEDBACK.md#bf-063--theme--text-type-profile-editor) and [ADR-0011](../05_decisions/ADR-0011-syntax-category-color-editing.md): all eight syntax categories are now editable per-profile roles (`syntax.*`) in the existing theme editor, with the same contrast-warning behavior as every other theme color.
- **Future capability:** UNITI senses a file's presentation profile from its extension and applies a predefined syntax highlighter. Illustrative profiles include `.txt` as Plain Text, `.md` as Markdown, and `.xml` as XML; unknown extensions fall back to Plain Text. These are file-type profiles, not document-content templates. Highlighting is presentation-only and must never mutate text, encoding, BOM, or line endings. Manual override behavior and the final supported-profile catalog remain future design decisions.
- **Why parked:** Extension mapping, incremental parsing, and language grammars would create new profile, cache, worker, invalidation, and grammar-maintenance responsibilities beyond regex-field highlighting. This capability remains outside the current B2 scope and has no roadmap position or target version.
- **Known dependencies/risks:** profile ownership, extension aliases, parser choice, grammar distribution, multiline incremental state, huge-file degradation, manual override semantics, and memory-pressure integration.
- **Re-evaluation trigger for the remaining scope:** demonstrated need for cross-row-aware highlighting (e.g. multi-line comments/fenced code blocks rendering incorrectly in real use).
- **Re-evaluation trigger:** stable rendering/cache interfaces and approval of a bounded file-type and syntax-highlighting subset.

## CJK typography specialization

- **Why parked:** General bounded LTR shaping and bundled Simplified/Traditional Chinese and Korean fallback are implemented through BF-006. Further script-specific typography beyond the [current LTR contract](../../ltr-text-layout.md) needs a separate scope and evidence base.
- **Known dependencies/risks:** locale-dependent Han forms, ambiguous-width characters, typography policy, platform differences, and large-file rendering cost.
- **Re-evaluation trigger:** tested CJK workflows demonstrate requirements beyond the implemented shaping and fallback contract. Qualifying native IME behavior remains current feedback work, not a parked capability.

## Elaborate preferences UI

- **Why parked:** Focused persisted controls, configurable hotkeys, and custom theme editing are implemented. A broad preferences architecture or larger settings surface remains outside current scope.
- **Known dependencies/risks:** schema ownership, discoverability, reset behavior, migration, platform conventions, and premature commitment to unstable options.
- **Re-evaluation trigger:** repeated stable settings accumulate beyond focused menus and controls.

## Polished installers, signing, and update delivery

- **Why parked:** A23 now owns unsigned standalone application bundles with embedded runtime and guided offline health/repair. Installer UX, privileged installation, publisher signing, macOS notarization, update delivery, and distribution-channel trust are separate security/release systems.
- **Known dependencies/risks:** code signing and certificate custody, notarization, Windows signing, platform installers, update metadata and rollback, secure transport, release hosting, licensing, and incident response.
- **Re-evaluation trigger:** A23 executable evidence and A24 beta stability justify a separate distribution/trust architecture decision.
