# UNITI Parked Capability Catalog

Last reviewed: 2026-09-03

These capabilities are intentionally outside the lean editor boundary described by [Current Scope](../01_current/SCOPE.md). They are recorded for later re-evaluation, not promised delivery.

## Editor whitespace visualization and Unicode inspection

- **Future capability:** Treat spaces, tabs, line endings, non-breaking spaces, zero-width characters, and related invisibles as optional editor-display overlays without inserting or changing document text. Add a keyboard command that reports the Unicode code point, name, category, and encoded representation for the selection or, when there is no selection, the preceding character or grapheme-aware unit.
- **Why parked:** The feature needs an explicit display grammar, selection/preceding-character rule, grapheme-versus-code-point decision, shortcut ownership, accessibility behavior, and bounded rendering contract. It is intentionally excluded from a19 and is not part of a20 Recovery & Session scope.
- **Known dependencies/risks:** visible-only viewport painting, tabs and mixed EOL presentation, combining sequences, surrogate-free Python/Qt coordinates, ambiguous zero-width markers, IME interaction, shortcut collisions, large-file performance, screen readers, and copy/paste remaining byte-for-byte unaffected.
- **Re-evaluation trigger:** approve a focused editor-display milestone or incorporate the bounded behavior into a later usability milestone after a20 recovery ownership is stable.

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

## Polished installers and embedded runtimes

- **Why parked:** a23 requires reproducible executable packaging, but the current startup direction still excludes embedded Python, signed polished `.app`/`.exe` installers, notarized distribution, shortcuts, and update delivery.
- **Known dependencies/risks:** runtime bundling, code signing, notarization, Windows signing, update delivery, platform packaging, licensing, and release infrastructure.
- **Re-evaluation trigger:** cross-platform and beta-candidate evidence supports a separate distribution architecture decision beyond reproducible packaging.
