# UNITI Feature Wishlist

Started: 2026-09-12

A running list of future feature ideas raised in passing, not yet scoped, designed, or committed to any plan. An entry here is not a request disposition, an implementation commitment, or a roadmap position. Concrete, actively-tracked feedback with a disposition belongs in the [Beta Feedback Log](BETA_FEEDBACK.md); a formally considered and deliberately shelved capability belongs in the [Parked Capability Catalog](04_parked/CATALOG.md). This list sits between the two: ideas worth remembering, not yet worth a full entry in either.

An idea moves out of this list when it is either promoted to a dated `BF-NNN` entry in the feedback log (once someone wants to actually scope it) or written up in the parked catalog (once it's evaluated and deliberately deferred with rationale).

## Multi-cursor / Select All Occurrences

- Noted: 2026-09-13, from an architecture review.
- Idea: select all occurrences of a match (or manually placed cursors) and edit at multiple positions simultaneously, as in VS Code/Sublime.
- Deliberately kept long-term only, per explicit direction (2026-09-13) — not prioritized alongside the escalated architecture findings in the [Beta Feedback Log](BETA_FEEDBACK.md).
- Why this is a bigger lift than it looks: `EditorState` (`src/uniti/app/editor_state.py`) holds exactly one `cursor`/`anchor` pair per view today. Multi-cursor isn't a UI toggle on top of that — it's a data-model change (a list of cursor/anchor pairs, not one) that ripples through `text_view.py`'s paint loop, hit-testing, and Undo/Redo transaction grouping.
