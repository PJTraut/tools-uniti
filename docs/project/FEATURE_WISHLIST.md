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

## USFM per-chapter view

- Noted: 2026-10-07, from USFM field-test feedback ("have option to view per chapter or per book"). Paused by the user the same day, pending the environment window work.
- Idea: an option to show a USFM document one chapter at a time instead of the whole book. The chapter would come from the environment window's Book/Chapter/Verse selector.
- Current state: Standard and Preview project the whole document (up to 1 MiB) through `layout_projection` (`src/uniti/core/environments/sfm/views.py`). Plain Text shows the whole file.
- Open questions: does narrowing apply to Plain Text too? That would need a narrowed or folded `UNITITextView`, which doesn't exist. For Standard and Preview, the projection could cover only the chapter's source range, with the rest of the source hidden. How do Find/Replace and the caret behave outside the visible chapter?

## Footnote category filter in Preview

- Noted: 2026-10-08, from USFM field-test feedback ("`\cat` in footnotes needs to be displayed in [] for now; later feature select category/ies of footnotes to display in preview").
- Idea: choose which footnote categories (`\cat …\cat*`) Preview's notes frame shows, so a reader can, for example, hide textual notes and keep study notes.
- Current state: per the [round 2 plan](02_plans/2026-10-08-usfm-field-test-round-2-plan.md) R3, Preview shows each note's category in brackets and shows every note.
- Open questions: is the filter per tab, per project or global? Are uncategorized notes shown? Should Standard follow the filter too?

