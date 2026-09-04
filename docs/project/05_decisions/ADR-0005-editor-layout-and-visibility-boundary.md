# ADR-0005: Editor Layout and Visibility Boundary

Date: 2026-09-05
Status: accepted

## Context

A20 established one process-lifetime service, multiple editor windows, binary split-pane tab groups, independent views of authoritative documents, durable layout recovery, and one global floating Find/Replace surface. Those capabilities need direct controls, reversible docking, attached Find/Replace presentation, whitespace visualization, and explicit high-contrast themes.

Whitespace visualization was parked until the document/session architecture and a bounded display grammar existed. That re-evaluation condition is now satisfied. Implementing these features through per-document Qt text stores, per-document dock widgets, multiple Find/Replace panels, or whole-document marker indexes would conflict with the established ownership and large-file boundaries.

## Decision

1. Extend the existing binary pane tree with per-pane title-row controls. Splits create independent views over the same authoritative `Document`; assignment creates or selects views without replacing document authority.
2. Treat document undocking as a transactional view transfer. Persist an optional source window/pane/tab return anchor per undocked view and use deterministic fallbacks when that source no longer exists.
3. Keep one service-owned Find/Replace controller and content surface. Present it through one bottom-only dock that follows the active editor window while attached and acts as a floating topmost tool while detached.
4. Implement whitespace visualization as bounded, transient viewport overlays over committed document text. Modes are Off, EOL, Spaces & Tabs, Invisible Unicode, and All. Markers never change text or coordinates.
5. Keep theme appearance and contrast independent. Theme specifications own both the Qt palette and editor overlay colors, with measurable high-contrast requirements.
6. Migrate existing settings and schema-1 sessions forward without discarding compatible state. Preserve current count, byte, recovery, history, and low-space safety budgets.

## Consequences

- `UNITIService`, `DocumentRegistry`, `WindowManager`, `EditorPaneTree`, and `UNITITextView` remain the application, document, layout, and rendering authorities established by A20 and ADR-0002.
- A view can move between panes/windows without changing document identity or history; its cursor and presentation state move with it.
- Find/Replace placement changes never create competing panels or histories.
- Whitespace markers require explicit theme tokens and bounded paint admission, but no document-sized cache or new persistence pack.
- Session and settings schemas gain compatibility migrations and retain strict validation per source schema.
- Whitespace visualization leaves the parked catalog and becomes planned A21 work. General syntax highlighting, workspace/project state, user-authored themes, and elaborate preferences remain parked.

## Affected records

- [A21 Editor Layout and Visibility design](../02_plans/v0.001a21-editor-layout-visibility-design.md)
- [A21 Cross-Platform Alpha](../02_plans/v0.001a21-cross-platform-alpha.md)
- [Parked Capability Catalog](../04_parked/CATALOG.md)
- [ADR-0002: UNITI Document Authority and Qt Boundary](ADR-0002-document-authority-boundary.md)
- [ADR-0004: a16 Usability Boundary and Command Ownership](ADR-0004-a16-usability-boundary.md)

