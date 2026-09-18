# UNITI Feature Wishlist

Started: 2026-09-12

A running list of future feature ideas raised in passing, not yet scoped, designed, or committed to any plan. An entry here is not a request disposition, an implementation commitment, or a roadmap position. Concrete, actively-tracked feedback with a disposition belongs in the [Beta Feedback Log](BETA_FEEDBACK.md); a formally considered and deliberately shelved capability belongs in the [Parked Capability Catalog](04_parked/CATALOG.md). This list sits between the two: ideas worth remembering, not yet worth a full entry in either.

An idea moves out of this list when it is either promoted to a dated `BF-NNN` entry in the feedback log (once someone wants to actually scope it) or written up in the parked catalog (once it's evaluated and deliberately deferred with rationale).

## Multi-cursor / Select All Occurrences

- Noted: 2026-09-13, from an architecture review.
- Idea: select all occurrences of a match (or manually placed cursors) and edit at multiple positions simultaneously, as in VS Code/Sublime.
- Deliberately kept long-term only, per explicit direction (2026-09-13) — not prioritized alongside the escalated architecture findings in the [Beta Feedback Log](BETA_FEEDBACK.md).
- Why this is a bigger lift than it looks: `EditorState` (`src/uniti/app/editor_state.py`) holds exactly one `cursor`/`anchor` pair per view today. Multi-cursor isn't a UI toggle on top of that — it's a data-model change (a list of cursor/anchor pairs, not one) that ripples through `text_view.py`'s paint loop, hit-testing, and Undo/Redo transaction grouping.

## SFM highlighting informed by Paratext .sty stylesheets

- Noted: 2026-09-18 ("note that paratext ships with .sty files -- terrible hybrid dtd and stylesheet").
- Current state: the [SFM syntax profile](../syntax-highlighting.md#sfm) (`_SFM_RULES`, `src/uniti/core/syntax_profiles.py`) recognizes only the generic `\marker`/`\marker*` shape — a single `keyword` category for every marker, with no notion of which markers are valid, or of a marker's kind (paragraph/character/note/milestone) or nesting.
- Idea: Paratext ships `.sty` stylesheet files (per the user, "a terrible hybrid DTD and stylesheet" format) that define the actual set of valid SFM markers and per-marker properties, including style type and formatting. These could inform a richer SFM profile — validating markers against a real stylesheet and coloring by marker kind rather than one flat `keyword` category for everything.
- Not yet scoped at all: whether UNITI would parse a user-supplied `.sty` file directly, bundle a default/standard one, or something else; the `.sty` format itself (described only qualitatively so far, not yet inspected against a real file); and how this would interact with the existing extension→profile mapping model.
- Reference, provided by the user 2026-09-18: [USFM 3.1 documentation](https://docs.usfm.bible/usfm/3.1/index.html), which also covers USJ (the JSON-serialized form of USFM — relevant to the existing JSON profile too, not just SFM). Not yet read/incorporated into this entry's scoping.
