# ADR-0017: Environment Windows, In-Place Rich Views, Stylesheet-Only Styling, Presentation Rules, Reference Sync

Date: 2026-10-07
Status: accepted (implemented — see the [implementation record](../03_implemented/milestones/2026-10-07-usfm-field-test-plan.md)); decision 2's one window per environment and group is superseded by [ADR-0019](ADR-0019-named-environment-windows-groups-and-project-tabs.md) (2026-10-08)

## Context

USFM field-test feedback (2026-10-07, `@externalresources/field_test_feedback`):

- General: "undock from MAIN panel, create 'environment panel', move text file to the 'environment panel'".
- USFM:
  - "display plain text/standard/preview in 'same' window; current standard/preview opens in sidepanel - DO NOT DO this";
  - "preview: add extra frame for footnotes (\f) and crossreferences (\x) stacked per class below text";
  - "add conditional styling for STY extension implementation for PREVIEW: e.g.: \p followed by \q, separate with blank line like CSS 'Immediate Sibling'", and "how are we extending the STY to PREVIEW?";
  - "have BOOK/CHAPTER/VERSE selector in USFM ENVIRONMENT frame";
  - "have option to view per chapter or per book";
  - "all USFM files in GROUP syncs when in Side-by-side display: klick in GEN 10:11 on text in LHS, moves RHS to GEN 10:11; highligh matched lines";
  - "all styling is done by PAR or CHAR styles using tagging".

The user's answers to the open questions, the same day:

- The environment panel is a separate window, one per environment and document group.
- The book list is every file of the environment in the document's project folder.
- Sync is between files of the same document group only.
- The per-chapter view is paused; it's in the [wishlist](../FEATURE_WISHLIST.md#usfm-per-chapter-view).

## Decision

1. **Rich views are shown in place of the tab's Source editor.** This supersedes ADR-0015 decision 5's side-by-side pane and the one-pane-per-window part of ADR-0016 decision 1.
   - Plain Text / Standard / Preview are modes of one tab. A tab in a rich mode gets its own `RichViewPane`, a child widget of its `UNITITextView` that covers it and follows its size.
   - The tab still holds the `UNITITextView`, so Find/Replace, save, recovery, splits, transfer and session capture keep working on it unchanged. The pane mirrors its caret both ways, and the editor's focus is proxied to the pane.
   - Each tab has its own pane, so split views can show different modes side by side. A pane in a background tab re-projects only when it's shown.
   - Edit-menu Undo/Redo/Cut/Copy/Paste/Select All act on the pane, so a read-only Preview can't be edited through the menu. The pane also claims its own navigation and zoom keys ahead of the Source editor's shortcuts.
   - The per-tab choice is still `UNITITextView.rich_view_key` in `ViewRecord.extra["rich_view"]`. The pane's × button is gone: Plain Text is the first mode.
2. **Environment windows** ("environment panel").
   - **Move to Environment Window** (environment menu, every environment including Plain Text: a plain text file gets a "Plain Text — A" window, with no rich modes and no selector) moves a tab into the window for its environment and document group, e.g. "USFM — A". The window is created on first use (`UNITIService.move_to_environment_window`). Like undock, the tab remembers its home, so Dock takes it back.
   - A file lives in its environment (follow-up, 2026-10-07):
     - A file opened inside an environment window (File > Open, Recent Files, Book) is pinned to the window's environment and joins its group. If it's already open elsewhere, it moves in.
     - When the file's extension isn't assigned to that environment, an "Open as <environment>?" confirmation comes first; Cancel doesn't open it.
     - Choosing an environment in **Environment for This Document** moves the file into that environment's window, and a file whose environment no longer matches its environment window moves out to the right one.
     - Opening a file in an ordinary window asks first (round 2 R6): open it in its environment's window, or as Plain Text (pinned to the Plain Text environment, no extended features).
   - An environment window is an ordinary UNITI window plus an environment frame: an `EnvironmentBar` toolbar with the environment and group, the Plain Text / Standard / Preview switch, and for USFM/SFM a Book / Chapter / Verse selector and the sync toggle.
   - This narrows ADR-0004 decision 7 ("no toolbar is added"): ordinary windows still have no toolbar, and only environment windows carry this frame.
   - Its identity is saved in each of its views' `ViewRecord.extra["environment_window"]`, so there is no window-schema change. `restore_shell` rebuilds the frame before any document loads.
3. **Book / Chapter / Verse selector.**
   - Books are every file in the document's folder whose extension is assigned to the environment and that has an `\id` line. They're listed in canonical USFM order (`sfm/references.py`).
   - Choosing a book shows its tab if it's open in the window. Otherwise it opens the book there, puts it in the window's group and gives it the current tab's mode.
   - Chapter and Verse move the caret, and they follow the caret as it moves.
4. **Reference sync** (`ReferenceSync`, every window, on by default; toggle: **Sync Side-by-Side by Reference**).
   - When the caret moves in a USFM/SFM tab, every other split whose shown tab is a file of the same document group and the same book (`\id`) moves to the same chapter:verse.
   - Verse bridges and parts count, so 10:11 finds `\v 10-12` or `\v 11a`.
   - If the split shows another book, it switches to a tab of that split that has the right book; activation stays where it was.
   - The matched verse is highlighted on every side: tinted lines in the Source editor (`set_line_highlights`) and a tinted range in a rich pane.
   - Ungrouped files don't sync.
5. **All styling comes from the stylesheet.** Standard and Preview no longer hard-code any look. Each piece of text takes the paragraph, character or note style of the marker that tags it:
   - chapter numbers from `\c`;
   - verse numbers from `\v`;
   - note bodies from the note style;
   - the unclosed note-internal markers (`\fr`, `\ft`, `\xo`, `\xt`, …) up to the next marker;
   - table cells from their cell style.

   Nothing is muted any more. The marker-tag look in Standard is editor chrome, not content, and stays.
6. **Presentation rules: how the STY is extended for Preview.** There's no new file format. A rule is an ordinary `.sty` record whose `\Marker` is a CSS-like selector, carrying ordinary STY fields.
   - `\Marker p+q1` is the adjacent-sibling rule: it styles a `\q1` paragraph whose previous paragraph-level marker in the source (paragraph styles and `\c`) is `\p`. Its fields override `\q1`'s own.
   - `\Marker f::caller` is a pseudo-element: a note's caller.
   - Several selectors can share one record, separated by commas.
   - A numberless marker matches its level-1 form (`q` = `q1`).
   - A flag is turned off again with `-`.

   Where rules come from:
   - A built-in `uniti.sty` layer sits directly above the official baseline. It holds note-caller styles (superscript bold for footnotes, superscript italic for cross-references) and the blank line between prose and poetry (`p+q1, p+q2, p+q3, q1+p, q2+p, q3+p` → `\SpaceBefore 12`).
   - A project's own `uniti.sty` next to the book files is the highest-precedence project layer. Paratext and PTXprint never read that file.
   - Rule records are kept out of the structural registry, the Style Inspector's marker list and the marker choices. Export Stylesheet Overrides treats the built-in layer like the baseline.
   - User guide: [USFM stylesheet rules](../../usfm-stylesheet-rules.md).
7. **Preview notes frame.** Preview moves closed notes out of the text. The text keeps only the caller: `+` becomes a, b, c … per note class, restarting at each `\c`; `-` shows none; anything else is shown as written.
   - Below the text, a vertical splitter stacks one section per note class (footnotes, endnotes, cross references …), titled from the STY `\Name`.
   - Each section is its own projection (`Projection.notes`, `NoteSection`), with the whole source mapped, so clicking a note moves the caret to it. A caret on a caller highlights its note.
   - Standard keeps notes inline and editable.
8. **Regex search always matches the underlying plain text** (user, 2026-10-07). Find/Replace runs on the canonical source of the tab's `UNITITextView`, never on a rich view's display text, whatever mode the tab is in.
   - A pattern such as `\\v (\d+)` matches verse markers even where Preview hides them.
   - Match offsets, Find All, Replace and the Match Report are all source spans.
   - The current match is the Source editor's selection, which the rich view mirrors through the source map. Markup-only parts of a match (a hidden `\v`) collapse onto the text they belong to.

## Consequences

- No settings or session schema change. Both new persisted values ride in existing `extra` blobs.
- With every look now taken from the stylesheet, a project's `custom.sty` changes Standard and Preview, and so does a `uniti.sty`.
- Following decision 8, Find/Replace searches the source while a tab is in a rich mode. The current match shows in the rich view as the mirrored selection, but the Find All highlight of every match is only painted in Plain Text.
- Not done:
  - The per-chapter view (wishlist).
  - Sync across windows. Sync works between the splits of one window.
  - Opening a book from disk to satisfy a sync.
  - Showing presentation rules in the Style Inspector.
  - Native-host confirmation of all of the above.

## Affected records

- [ADR-0015](ADR-0015-stylesheet-layers-and-rich-views.md) decision 5 and [ADR-0016](ADR-0016-rich-view-persistence-notes-export-placement.md) decisions 1–2 are superseded where noted above.
- [ADR-0004](ADR-0004-a16-usability-boundary.md) decision 7 is narrowed: there's still no toolbar in ordinary windows.
