# UNITI Parked Capability Catalog

Last reviewed: 2026-09-01

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

## Full programming-language syntax highlighting

- **Why parked:** Incremental parsing and broad language grammars would create new cache, worker, invalidation, and language-maintenance responsibilities beyond regex-field highlighting.
- **Known dependencies/risks:** parser choice, grammar distribution, multiline incremental state, huge-file degradation, and memory-pressure integration.
- **Re-evaluation trigger:** stable rendering/cache interfaces and approval of a bounded language-highlighting subset.

## Polished platform installers and embedded runtimes

- **Why parked:** The current startup direction requires an existing host Python and deliberately excludes embedded Python plus signed `.app`/`.exe` distribution.
- **Known dependencies/risks:** runtime bundling, code signing, notarization, Windows signing, update delivery, platform packaging, licensing, and release infrastructure.
- **Re-evaluation trigger:** the host-Python bootstrap lifecycle is implemented and runtime evidence supports a separate packaging architecture decision.
