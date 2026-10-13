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

## Footnote category filter in Preview

- Noted: 2026-10-08, from USFM field-test feedback ("`\cat` in footnotes needs to be displayed in [] for now; later feature select category/ies of footnotes to display in preview").
- Idea: choose which footnote categories (`\cat …\cat*`) Preview's notes frame shows, so a reader can, for example, hide textual notes and keep study notes.
- Current state: per the [round 2 plan](02_plans/2026-10-08-usfm-field-test-round-2-plan.md) R3, Preview shows each note's category in brackets and shows every note.
- Open questions: is the filter per tab, per project or global? Are uncategorized notes shown? Should Standard follow the filter too?


## USFM files outside a project

- Noted: 2026-10-08, from the user's answers to the round 3 field-test feedback ("USFM environment assumes PROJECT, plain text only for now / add to todo later planning").
- Current state: per the [round 3 plan](02_plans/2026-10-08-usfm-field-test-round-3-plan.md) T1, a USFM file whose folder has no Paratext `Settings.xml` opens as Plain Text. Before T1, such a file got the USFM environment with the official stylesheet and the default versification.
- Open questions: which stylesheet, versification and book naming apply without `Settings.xml`? Is a single file its own "project tab", titled with its file name or its `\id`? Does it get a group of its own, and does it sync?

## Spellcheck from Paratext word lists

- Noted: 2026-10-08, from USFM field-test feedback ("toggle spellchecking using hyphenatedwords.txt data; plan this").
- Plan: the [spellcheck plan](02_plans/2026-10-13-usfm-spellcheck-plan.md) (2026-10-13), queued as row 19 of the [roadmap](02_plans/ROADMAP.md#environment-track-queue): `SpellingStatus.xml` first, then `hyphenatedWords.txt`; wrong and unknown words underlined in two colours; **Check Spelling** per project tab. This entry goes when it lands.

## Hyphenation in Preview

- Noted: 2026-10-13 ("wishlist: use hyphenation in PREVIEw mode").
- Idea: Preview breaks long words at the line end where the project's `hyphenatedWords.txt` allows it, as Paratext's Publishing Assistant does.
- What the file gives (read in `usNIVv3`, see the [spellcheck plan](02_plans/2026-10-13-usfm-spellcheck-plan.md#what-paratext-keeps)): one word per line with `=` at its break points (`a=ro=se`), `SoftHyphenOut = "­"` (U+00AD) as the character to print there, and `HyphenatedMarkers` listing the paragraph markers whose text is hyphenated (`p`, `m`, `pi1`, `ip` …; not poetry or headings).
- Current state: Preview wraps only at spaces. The spellcheck plan's S1 reads `hyphenatedWords.txt` already, so its loader can keep the break points too.
- Open questions:
  - Does Qt's text layout break at a U+00AD in Preview's text and show a hyphen there? If so, Preview's projection would put U+00AD at the break points, and the source map would have to skip them so the caret, sync and editing keep their offsets.
  - Only `HyphenatedMarkers`, or every paragraph?
  - Starred (user-fixed) lines: in `usNIVv3` they look damaged (`*a =ro=se`). Use them, or only unstarred lines?
  - Words not in the file: no breaks, or an automatic hyphenation rule for the language?
  - A toggle (per project tab, like Check Spelling), or always on in Preview?
