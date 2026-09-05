# UNITI Parked Capability Catalog

Last reviewed: 2026-09-05

These capabilities are intentionally outside the lean editor boundary described by [Current Scope](../01_current/SCOPE.md). They are recorded for later re-evaluation, not promised delivery.

## Project and workspace concepts

- **Why parked:** Multi-file project state, discovery, persistence, and project-level commands would shift UNITI from a focused editor toward an IDE/workspace platform.
- **Known dependencies/risks:** workspace schema, file watching at directory scale, trust boundaries, session persistence, and interaction with large-file resource priorities.
- **Re-evaluation trigger:** sustained workflows that cannot be served safely by opening independent files and tabs.

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

- **Future capability:** UNITI senses a file's presentation profile from its extension and applies a predefined syntax highlighter. Illustrative profiles include `.txt` as Plain Text, `.md` as Markdown, and `.xml` as XML; unknown extensions fall back to Plain Text. These are file-type profiles, not document-content templates. Highlighting is presentation-only and must never mutate text, encoding, BOM, or line endings. Manual override behavior and the final supported-profile catalog remain future design decisions.
- **Why parked:** Extension mapping, incremental parsing, and language grammars would create new profile, cache, worker, invalidation, and grammar-maintenance responsibilities beyond regex-field highlighting. This capability is explicitly outside `v0.001a17` and has no roadmap position or target version.
- **Known dependencies/risks:** profile ownership, extension aliases, parser choice, grammar distribution, multiline incremental state, huge-file degradation, manual override semantics, and memory-pressure integration.
- **Re-evaluation trigger:** stable rendering/cache interfaces and approval of a bounded file-type and syntax-highlighting subset.

## CJK typography specialization

- **Why parked:** a16 guarantees Western/Latin and Cyrillic fixed-pitch coverage only; specialized CJK shaping, fallback, column-width, and typography policy needs a dedicated evidence base.
- **Known dependencies/risks:** font discovery, fallback chains, ambiguous-width characters, shaping, vertical metrics, platform differences, and large-file rendering cost.
- **Re-evaluation trigger:** tested CJK workflows demonstrate requirements that the general Unicode text engine and installed fonts cannot meet.

## Elaborate preferences UI

- **Why parked:** a16 needs persisted operational state and hotkey control, not a broad preferences architecture or large settings surface.
- **Known dependencies/risks:** schema ownership, discoverability, reset behavior, migration, platform conventions, and premature commitment to unstable options.
- **Re-evaluation trigger:** repeated stable settings accumulate beyond focused menus and controls.

## Large multi-document and session architecture

- **Why parked:** tabs needed for current testing already exist, but automatic restoration and complex session/workspace ownership would expand scope before document scale and recovery are proven.
- **Known dependencies/risks:** resource prioritization, recovery identity, external-file changes, window topology, and startup latency.
- **Re-evaluation trigger:** a18-a20 evidence shows a bounded multi-document/session design is required for normal use.

## Polished installers, signing, and update delivery

- **Why parked:** A23 now owns unsigned standalone application bundles with embedded runtime and guided offline health/repair. Installer UX, privileged installation, publisher signing, macOS notarization, update delivery, and distribution-channel trust are separate security/release systems.
- **Known dependencies/risks:** code signing and certificate custody, notarization, Windows signing, platform installers, update metadata and rollback, secure transport, release hosting, licensing, and incident response.
- **Re-evaluation trigger:** A23 executable evidence and A24 beta stability justify a separate distribution/trust architecture decision.
