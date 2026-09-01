# ADR-0004: a16 Usability Boundary and Command Ownership

Date: 2026-09-01
Status: accepted

## Context

UNITI's text engine and startup lifecycle exist, but the desktop shell is not yet sufficient for sustained daily editing. Adding basic usability must not transfer authoritative text ownership to Qt, mix literal and regex semantics, create competing command handlers, or expand the product toward an IDE.

## Decision

1. a16 is an implementation-led Usable Test Alpha. Its purpose is routine dogfooding, not new product architecture.
2. The `Document` remains authoritative for editor text and owns a maximum of 50 undo transactions.
3. Find and Replace fields each own a separate maximum of 50 input undo steps. Keyboard focus decides which of the three histories receives Undo/Redo.
4. Find/Replace is a floating modeless utility. Its zoom and persisted geometry are independent from the editor.
5. Literal mode alone owns Case Sensitive and Whole Word options. Regex mode passes raw pattern syntax and inline switches to `regex==2026.5.9` without GUI modifiers.
6. Match Report displays capture groups `1..N`, never group `0`, and preserves authoritative group numbers.
7. Menus and shortcuts share one command registry with `WINDOW`, `EDITOR`, and `FIND_REPLACE` scopes. Shortcut overrides are persisted; no toolbar is added.
8. Soft wrap is display-only, default off, remembered, and remains lazy rather than constructing a whole-document Qt layout.
9. Only blocking/basic editor omissions discovered by dogfooding may enter a16 without a separate roadmap decision.
10. CotEditor's native, minimal, accurate-text design principles and main-menu organization are UI references, not dependencies. UNITI's application-owned menu bar is `File | Edit | Format | View | Find | Tools | Hotkeys`; Navigation, Encoding, Line Endings, Editor View, and F/R View are submenus rather than competing top-level artifacts.
11. Shortcut display uses native platform notation while persistence remains portable. Keyboard and primary-modifier wheel zoom belong to the focused editor or F/R surface and never change the other surface.
12. Double-click selects a word, triple-click selects a visual line, and quadruple-click selects a complete logical line through its terminating line break.
13. Find/Replace uses an explicit `Literal | Regex` selector. Its window and capture splitter are mouse-resizable, the capture child is collapsible, batch and match actions occupy separate groups, and one configurable `Ctrl+Alt+R` command cycles `Hidden → Bottom → Right → Hidden` report placement.
14. The Find and Replace input editors divide the available controls-frame height equally. Every non-input control remains in one compact stack anchored to the bottom; field zoom changes readable font/minimum sizing without reinstating fixed-height inputs.
15. Find All installs the complete revision-bound result index on the editor. Every visible match receives a clear theme-derived background while the current match remains the stronger selection; painting remains limited to visible intersections and stale results clear on text or pattern changes.

## Consequences

- Replace All must remain one document transaction and one Undo step.
- Identical zoom keys may be assigned in editor and Find/Replace scopes because focus disambiguates them.
- Editor zoom, F/R zoom, wrap, F/R geometry, report location, and hotkey overrides extend the existing settings schema through explicit migration-compatible defaults.
- Current architecture documents are updated only as these planned behaviors become implemented and verified.
- One registry-backed action remains reachable from its canonical menu location; the compact hierarchy does not duplicate command handlers.
- Regex case behavior comes only from raw inline switches such as `(?i)`; hidden literal controls never influence regex compilation.
- CJK specialization, elaborate preferences, IDE/workspace features, and unrelated expansion remain parked.

## Affected records

- [implemented a16 Usable Test Alpha](../03_implemented/milestones/2026-09-01-uniti-v0.001a16-usable-test-alpha.md)
- [implemented a16 implementation plan](../03_implemented/milestones/2026-09-01-uniti-v0.001a16-usable-test-alpha-implementation.md)
- [Current Architecture](../01_current/ARCHITECTURE.md)
- [Project Grammar](../00_governance/GRAMMAR.md)
