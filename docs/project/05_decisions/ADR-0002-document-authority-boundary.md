# ADR-0002: UNITI Document Authority and Qt Boundary

Date: 2026-08-31
Status: accepted

## Context

UNITI targets text correctness and bounded editing for files of at least 1 GiB. Allowing a Qt text widget or `QTextDocument` to mirror and own file contents would make opening/rendering proportional to document size, blur byte/character fidelity, and bypass the piece-table, encoding, EOL, invalid-byte, save, and recovery invariants.

## Decision

The UNITI `Document`, piece table, immutable byte source, edit store, line indexes, and history remain the authoritative text model. PySide6 owns application windows, native input/clipboard/IME integration, and viewport painting only.

The editor view remains a custom virtual `QAbstractScrollArea`. UI commands mutate text through `EditorState` and `Document`; `QPlainTextEdit`, `QTextEdit`, and `QTextDocument` must not become document storage.

## Consequences

- Rendering and input integrations must request bounded spans and coordinate translations from the UNITI engine.
- Qt conveniences that assume an internal text document require custom implementations.
- The core stays PySide6-free and headless-testable.
- Large-file, encoding, EOL, invalid-byte, history, save, and recovery ownership remains coherent.

## Affected records

- [Current Architecture](../01_current/ARCHITECTURE.md)
- [Current Scope](../01_current/SCOPE.md)
- [Implemented Phase 1B Design](../03_implemented/designs/2026-08-31-uniti-phase1b-document-model-design.md)
- [Implemented Alpha Completion Design](../03_implemented/designs/2026-08-31-uniti-v0.001-alpha-completion-design.md)
