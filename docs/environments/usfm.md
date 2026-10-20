# USFM

Scripture text in USFM (Unified Standard Format Markers) and its older SFM form, in Paratext projects. See the [overview](README.md) for what all environments share.

**USFM assumes a Paratext project:** a folder with a `Settings.xml`. A `.usfm` or `.sfm` file outside one opens as plain text, without the "Open in USFM Environment?" question, and the status bar says why ("GEN.usfm isn't in a Paratext project: opened as plain text"). **Environment for This Document** doesn't offer USFM for such a file. Working with USFM files outside a project is planned for later.

- **Extensions:** `.usfm`, `.sfm` (any case). The separate "SFM" environment was folded into USFM on 2026-10-08. A setting saved under the old name is read as USFM.
- **Highlighting:** every marker is colored as a keyword: `\v`, `\wj*`, nested `\+it`, milestones `\qt-s … \*`, table cells `\th1-2`. The text is uncolored.

## Views

A USFM tab has three modes. Switch with the environment toolbar, the menu's **View As** block, or the mode list at the top of the view. Each tab keeps its own mode, and it's restored with the session.

| Mode | What it shows | Editing |
|---|---|---|
| **Plain Text** | the source, exactly as written | yes |
| **Standard** | formatted from the stylesheets, with every marker shown as a small tag | yes: typing goes into the text, markers are protected; Bold (Ctrl+B), Italic (Ctrl+I), Character Style…, Remove Character Style, Paragraph Style… and Insert Verse… on the right-click menu; Enter starts a paragraph of the same kind |
| **Preview** | a print-like rendering: no markers, book metadata left out | read-only |

What Standard and Preview show:
- **Styling.** Every look comes from the stylesheets: paragraph, character and note styles, by marker. Chapter numbers use `\c`'s style, verse numbers `\v`'s.
- **Nested markers.** A nested marker (`\nd Lord \+it God\+it*\nd*`) is styled by its own marker (`\it`) on top of its parent's.
- **Attributes.** Preview hides `|attributes` (`\w king|lemma="king"\w*` shows "king") and milestones.
- **Notes frame (Preview).** Footnotes, cross references and other notes leave the text and are stacked below it, one section per kind. The text keeps the caller: `+` becomes a, b, c… (restarting each chapter), `-` shows none, anything else is shown as written.
  - Clicking a note moves the caret to it.
  - Putting the caret on a caller highlights its note.
  - A note's category (`\cat People\cat*`) shows as "[People]".
- **Justification and hyphenation.** A paragraph's `\Justification` (including `Both` for justified text) applies in Standard and Preview. As in PTXprint, `Left`, `Right` and the margins follow the paragraph's reading direction, so a right-to-left project's `\qr` sits on the left and a hanging `\q1` hangs from the right. Preview can also break words at the end of a line: see [Hyphenating Preview](#hyphenating-preview). Both are set in the stylesheets; see [USFM Stylesheet Rules](../usfm-stylesheet-rules.md#justification).

**Find and Replace always search the source text**, in every mode. A pattern like `\\v (\d+)` finds verse markers even in Preview. The current match is shown as the selection.

## Undefined markers

When you open a USFM file that uses markers no loaded stylesheet defines, a report pops up. Those are markers Standard and Preview can only show as tags, such as `\esb`, or a project's own `\zfoo`. It lists each marker with how often it's used; expand a marker to see each use, and double-click one to jump there.
- **Copy Report** and **Save Report…** give you the whole report as text.
- **Edit Stylesheet…** opens the file where the definitions belong: the project's `custom.sty`. It creates the file from its template if needed.
- **Add Definitions** adds a starter definition for the selected markers (or all of them) to that file and opens it. Complete each `\Name` and style, then save: the stylesheets reload and the report updates.

**Check Undefined Markers** in the USFM menu runs the same check at any time. Milestones (`\qt-s … \*`) are never reported; they mark positions, not text. Files restored at startup aren't checked automatically.

## Project tabs

In a USFM window, **a tab is a project**, titled with the project's short name (`<Name>` in `Settings.xml`), e.g. "NIV". Each split has one tab per project.
- **Changing the book** (the toolbar's **Book**) shows that book in the same tab. Every book you've opened stays open in the tab with its own caret, undo history and view mode, so going back to it picks up where you were.
- **Unsaved changes:** when the book you're leaving has unsaved changes, UNITI asks "Save changes to GEN (NIV)?". **Yes** saves it; **No** keeps the changes in the book, open but not shown. Nothing is ever saved without asking. The Book list marks a book with unsaved changes "•", and the tab's name gets a "*" while any of its books has them.
- **Opening a book** of a project that already has a tab in the split (File → Open, Recent Files, Open USFM Project…) shows it in that tab; a book of another project gets a tab of its own.
- **Closing the tab** closes all its books, asking about each one with unsaved changes.
- The same project can have a tab in two splits or windows, each showing its own book.
- **Right-click the tab** to put it in a group, move it to another split (up to four) or window, or dock it back; it moves with all its books (see [Environment windows](README.md#environment-windows)). **Read Only** there makes the project's folder read-only (see [Read-only folders](README.md#read-only-folders)).
- The tab's tooltip names the current book and its file. Only the project's short name is shown, anywhere in UNITI.

## Book, chapter and verse

The environment window's toolbar has **Book**, **Chapter** and **Verse** at its right end.
- **Book** lists the project's books.

  Each book shows its `\id` code and its `\h` line, e.g. "GEN Genesis". UNITI looks for `\h` in the book's first 10 lines; a book without one shows just its code. Choosing a book shows it in the current tab (see [Project tabs](#project-tabs)), in the current book's mode and group.
- **Chapter** and **Verse** jump to that place and follow the caret as it moves.

Jumping, here or with **Go to Chapter:Verse…** (Ctrl+Alt+G), puts the verse a third of the way down and highlights it in every mode. The highlight clears when the caret leaves the verse.

### One chapter at a time

Click **Chapter** (the word before the Chapter selector), or choose **USFM → Show One Chapter**, to show only the chapter the caret is in. It works in Plain Text, Standard and Preview, and is set per window: every tab and split of the window shows its own chapter. It's saved with the session.
- **A chapter** runs from its `\c` line to the line before the next `\c`. The book's identification, headers and introduction (everything before `\c 1`) show with the first chapter.
- **The edges hold.** Arrow keys, Page Up/Down, Ctrl+Home/End, clicks and scrolling stay in the chapter, and Select All selects it. Backspace at its first character and Delete after its last do nothing, so a chapter is never joined to the next by accident.
- **Changing chapter:** the Chapter and Verse selectors, Go to Chapter:Verse…, side-by-side sync, Find (which still searches the whole book) and Undo all move the caret, and the view shows the chapter it lands in.
- **Preview's notes frame** lists only the chapter's notes; a kind of note with none in the chapter is hidden.
- A tab opened as Plain Text (no USFM features), a book without `\c`, and a file above 1 MiB always show whole.

## Locked books

**Every book opens locked.** A project's book can't be edited until you unlock it; the tab shows 🔒 ("🔒 NIV") and the title says "(locked)". The lock belongs to the open file, not to a view: every split, window and mode (Plain Text, Standard, Preview) showing the book is locked or unlocked together. It's never remembered: closing the book and opening it again (or restoring the session) locks it again, and unsaved edits recovered after a crash open locked too. A file opened as Plain Text isn't locked.

- **Unlock Book / Lock Book:** the lock button before the Book list on the toolbar, **USFM → Unlock Book**, right-click the Book list, and right-click a tab or the text. It acts on the shown book. Locking a book with unsaved changes is allowed.
- **Typing, paste, Undo/Redo, Format and Replace** are refused with "GEN (NIV) is locked: right-click the Book list › Unlock to edit". **Reload** keeps the lock.
- **A book in a read-only folder** (**View → Read-Only Folders…**) can't be unlocked: that setting is stronger, and the Unlock entries are off.

### Saving a locked book

A locked book is unlocked to save. **Save** asks "GEN (NIV) is locked" with **Unlock and Save** or **Cancel**; closing the tab or window, or quitting, offers **Unlock and Save**, **Discard** or **Cancel**. No file is written without changes, in any environment.

### Leaving a book with changes

When another book replaces a book that has unsaved changes in its tab (the Book list, Find/Replace stepping), UNITI asks "Changes to GEN (NIV) will be lost." with **Save** (**Unlock and Save** when locked), **Discard** (the book closes without saving; reopening reads the file) or **Cancel**. It asks only when that tab is the book's last view: another split or window still showing it keeps the changes.

### UTF-8 with CRLF

A USFM book is UTF-8 with CRLF line endings. A book that isn't (LF, CR or mixed lines, or another encoding such as Windows-1252) asks "GEN (NIV) isn't UTF-8 with CRLF line endings (found: LF)" with **Update** or **Close**. **Close** closes the book and writes nothing. **Update** converts the text and the output encoding as one change (Undo takes the text back once the book is unlocked); the book stays locked, so the change is saved only with **Unlock and Save**. A BOM is kept as found. While a book is locked, the Format menu's encoding and line-ending choices are off.

## Footnote categories

A note's categories are the words inside its `\cat … \cat*` (`\cat People Places\cat*` is in two); a note with none is in **None**. **USFM → Footnote Categories** (also on the tab's right-click menu) lists the book's categories and **None**, all checked. Unchecking one leaves the notes out of **Preview**, caller and body, when all of a note's categories are unchecked; the callers that remain number from a. **Show All** checks everything again.
- **Per project tab,** like Check Spelling: it applies to every book of the tab and the books you open into it, and is saved with the session.
- **Preview only.** Standard and Plain Text keep every note, since they show the source you edit.

## Hyphenating Preview

**Hyphenate Preview** breaks long words at the end of a line, at the points in the project's `hyphenatedWords.txt`, the list Paratext's Publishing Assistant keeps (`a=ro=se`: break after `a` or after `aro`). It's **per project tab** and off by default, like Check Spelling: turn it on from **USFM → Hyphenate Preview** or the tab's right-click menu. It then applies to every book of the tab, including books you open into it later, and is saved with the session. A project with no `hyphenatedWords.txt` shows it greyed out ("NIV has no hyphenation list (hyphenatedWords.txt)").

- **Preview only.** Standard and Plain Text show the source you edit, so they never hyphenate; Preview's notes frame doesn't either.
- **Only listed words break,** and only where the list says. A hyphenated word (`well-watered`) breaks at its hyphen and inside any part the list has. A word not in the list never breaks: there is no automatic rule for your language.
- **Which paragraphs:** a stylesheet's `\Hyphenate` field on the paragraph's style decides first (`\Hyphenate -` turns it off for poetry, `\Hyphenate` turns it on for a heading); otherwise the list's own `HyphenatedMarkers` line (`p m pi1 …`); otherwise every paragraph of verse text. See [USFM Stylesheet Rules](../usfm-stylesheet-rules.md#hyphenation).
- **Justified text** (`\Justification Both`) shows the point best: the space between words is spread, and the hyphen appears only where a word is split at a line end.
- **Nothing else changes.** The caret, Find, sync and spelling underlines keep their source offsets, and copying from Preview gives the text without the break points.
- **A list changed on disk** (Paratext's Send/Receive) is read again when you switch back to the window.

## Check Spelling

**Check Spelling** underlines wrong and unknown words, from the project's Paratext word lists. It is **per project tab** and off by default: turn it on from **USFM → Check Spelling** or the tab's right-click menu. It then applies to every book of the tab, including books you open into it later (the Book list, sync), and is saved with the session. A tab moved to another split or window keeps it; a book merged into a tab that has checking off takes that tab's setting. A project with neither list shows it greyed out ("NIV has no spelling list (SpellingStatus.xml or hyphenatedWords.txt)").

- **The lists:** `SpellingStatus.xml` decides (`R` correct, `W` wrong; a `W` entry's correction is shown; an `R` entry with a specific capitalization, like `Paul`, is wrong in other cases unless written in capitals). `hyphenatedWords.txt` only adds correct words. A hyphenated word found in neither is correct when each part is. UNITI only reads the lists, and never writes them. Lists are read on a background thread the first time a tab turns checking on, and again when their files change (checked when the window is activated, since Paratext's Send/Receive can change them).
- **Two colours:** a wavy underline in **wrong** (Paratext marks it wrong, or its capitalization) and **unknown** (in neither list). Both are editor theme colours (`spelling_wrong`, `spelling_unknown`) in every built-in theme; older saved themes get them by their background. Hover a flagged word: "Paratext marks this wrong: use ayʼifyufyu", "Paratext spells it: Paul", or "Not in NIV's spelling list".
- **What is checked:** the text of every marker except `nonvernacular` ones in the project's stylesheets (`\id`, `\rem`, `\ide`, … and any your `custom.sty` marks), and not markers, `\c`/`\v` numbers, `\ca`/`\va`/`\vp`, or attributes after `|`. A word is letters and combining marks, joined by an apostrophe, U+02BC, a hyphen or a zero-width joiner only when a letter follows.
- **All three modes.** Plain Text underlines the lines it paints; Standard and Preview underline the words on screen. Preview's notes frame isn't underlined. Only the active window and its splits update their Standard and Preview underlines as you type; the others catch up when activated.
- **Word pairs.** Paratext keeps two-word entries too (`grain field` marked wrong). Two words separated by a single space on one line are underlined together as a wrong pair, with Paratext's correction when it has one. A pair is only found within a line.
- **Word endings and beginnings.** A word that isn't listed is correct when it's a listed word plus one of the project's `WordPrefixes` or `WordSuffixes` (`Settings.xml`): `Paul` with `ʼs`, `walk` with `ing`.

### Fixing a word: the right-click menu

Right-click a flagged word, in Plain Text, Standard or Preview. At the top of the menu:
- **Use “correction”**, when Paratext gives one, and **Change to “word”** for the nearest correct words in the project's lists (up to five: one edit away for a word of up to seven letters, two for longer ones; keeps the word's capitals). They replace the word as one edit that Undo takes back, in Plain Text and Standard. A locked or read-only book refuses, as for any edit. Preview, which can't be edited, offers none.
- **Approve “word”** counts the word as correct from now on. **Mark “word” Wrong** counts it as wrong. **Remove “word” from Your Spelling List** undoes either.
- **A word pair.** On a pair Paratext marks wrong together (`grain field`, underlined as one), **Approve “grain field”** counts the two words as correct together, and their words are judged singly again. To flag a pair yourself, select exactly two words separated by one space in Plain Text and choose **Mark “go at” Wrong Together**; the pair is underlined in the "wrong" colour wherever the two words stand together. **Remove “go at” from Your Spelling List** undoes either.

Approved and rejected words are kept in **your own spelling list**, never in Paratext's: `…/Environments/USFM/Spelling/<project short name>.json`, with `approved` and `rejected` words (and pairs, written `go at`) as you typed them. It sits above Paratext's lists, applies to every book and window of the project at once, and is read again when you switch back to the window. UNITI never writes `SpellingStatus.xml`, so Paratext's Send/Receive can't be disturbed. A word you reject is underlined in the "wrong" colour; hovering says "Marked wrong in your spelling list".

### Next and previous issue

**USFM → Next Spelling Issue** (Ctrl+Alt+.) and **Previous Spelling Issue** (Ctrl+Alt+,), on while Check Spelling is on, select the next or previous flagged word from the caret, wrapping round the book, in every mode; sync follows. The status bar says "Spelling issue 3 of 18: wrong “word”". Turning Check Spelling on, or showing another book of the tab, shows the book's count in the status bar: "GEN: 2 wrong, 14 unknown words".

## Find and Replace across a project

With **Current Group** as the Replace scope, **the group is the project**: every SFM book of the current project, open or not.
- **Replace All** first lists every file with matches (name, folder, match count, 🔒 for locked books), each with a checkbox, **all unticked**. Only the ticked files change; a ticked locked book is unlocked first (the dialog says "2 locked books will be unlocked"), and one that wasn't open opens, changed and unsaved, in the project's tab. Unticked books that weren't open are closed again. Cancel changes nothing. Files in read-only folders are listed greyed out and never changed. **All Open Documents** uses the same list, across every environment.
- **Find Next / Replace** step through the project's books: past the last match in a book, the next book with a match is shown in the pane (as the Book list shows it, with the Save or Discard question for the book you leave). A book with no match is passed over. Wrapping past the last book asks before carrying on from the first.
- **Replace in a locked book** (the current one, or one reached by stepping) asks **Unlock and Replace** or **Skip**; Skip changes nothing and the next Replace asks again.

## Groups and side-by-side sync

**A project belongs to a group**, not each book: give any of its books a group (the toolbar's **Group**, or right-click the tab or the text → **Project Group**) and every book of the project is in it, including books you open later. The project's tab is tinted with the group's colour. UNITI keeps the assignment in `projects.json` in your USFM configuration folder; it writes nothing into the project.

**A group binds its projects across windows.** When splits, in any USFM window, show texts of the same group, moving the caret in one moves the others to the same chapter and verse, and highlights the verse in all of them.
- **Versification:** the reference is mapped into each text's own versification, so English Ps 51:1 lands on 51:3 in a text numbered like the original.
  - **Psalm titles:** Russian numbers a psalm's title as verse 1, English doesn't number it (verse 0). Russian Ps 11:1 lands on the title of English Ps 12, and the caret in English Ps 12's title lands on Russian 11:1.
  - **Headings:** the caret in a chapter's heading, before its first verse, lands on the matching heading or title in the other texts, or where their chapter begins (English Ps 10 begins at Russian 9:22).
- **Different book:** a project tab showing another book changes its book: to that book if it's open in the tab, otherwise it opens the project's file of that book, in the same view mode. You stay where you were.
  - Sync never asks about unsaved changes: the book it leaves stays open in the tab, with its changes.
  - A project without the book stays put, and the status bar says so ("GEN isn't in 02EXO.usfm").
- **Book selector:** choosing a book in the Book selector carries the group's other texts to that book the same way.
- **Bridges and parts:** verse bridges (`\v 10-12`) and parts (`\v 11a`) are matched.
- Ungrouped projects don't sync.
- Turn sync on or off with **Sync Side-by-Side by Reference** (toolbar or menu).

## Versification

Translations number some verses differently: English Ps 51:1 is the original-text 51:3, Mal 4:1 is 3:19, Joel 2:28 is 3:1. Each text has a versification:
- the one you choose in **USFM → Versification**;
- otherwise its Paratext project's (`Settings.xml`, plus the project's `custom.vrs` if there is one);
- otherwise English.

English and Original are built in. For a project book, UNITI also uses the `.vrs` files Paratext keeps in its projects folder, the folder the project sits in (`rsc.vrs`, `lxx.vrs`, …), so Russian or Septuagint projects work with nothing to copy. For other files, copy `lxx.vrs`, `vul.vrs`, `rsc.vrs` or `rso.vrs` into your versification folder; **Versification → Your Versification Files…** shows it. A copy in your folder wins over Paratext's. A project's `custom.vrs` is found whatever its capitalisation (`Custom.vrs`). When a text asks for one that isn't there, UNITI uses English and the menu says the file is missing. Your choice for a file is saved with the session.

When a mapping lands on a verse the text doesn't have, sync uses the same reference instead. That covers a mapping onto a verse its own `custom.vrs` says doesn't exist, as in ruCARS's Romans 16:25–27.

## Projects

**File → Open USFM Project…** opens a Paratext project folder: one with a `Settings.xml`.
- **Book:** UNITI opens one book, the one you were last in (otherwise the first), and the Book list opens the rest.
- **Window and group:** the book opens in the USFM window that already shows the project, otherwise the most recently used USFM window, otherwise a new "USFM A". It gets the group the project was left in.
- **Recent Projects:** **File → Recent Projects** remembers each project's book, chapter:verse and group.
- **From `Settings.xml`,** UNITI reads the name, the book-file naming, the encoding (books open in it), the versification, and the stylesheet to use in place of `usfm.sty`.
- **Books opened as files:** a file opened with Open File inside a project folder counts as that project's book, whatever its extension. A file outside any project opens as plain text.

## Commands

| Command | Shortcut | What it does |
|---|---|---|
| Go to Chapter:Verse… | Ctrl+Alt+G | jump to e.g. `3:16` or `3` |
| Validate USFM | Ctrl+Alt+V | unmatched end markers, plus the `usfmtc` reference grammar check |
| Check Marker Placement | — | each marker's `OccursUnder` against the loaded stylesheets |
| Check Undefined Markers | — | markers no loaded stylesheet defines (see [Undefined markers](#undefined-markers)) |
| Next / Previous Spelling Issue | Ctrl+Alt+. / Ctrl+Alt+, | select the next or previous flagged word (see [Check Spelling](#check-spelling)) |
| Hyphenate Preview | — | break words at their listed points in Preview (see [Hyphenating Preview](#hyphenating-preview)) |
| Inspect Marker at Cursor | Ctrl+Alt+S | the Style Inspector at the marker under the caret |
| Style Inspector… | — | every marker's effective style, with the layer each value comes from |
| Load Stylesheet… | — | layer another `.sty` on top, for this session |
| Reload Project Stylesheets | — | re-read the stylesheets next to the file |
| Export Resolved Stylesheet… / Export Stylesheet Overrides… | — | write the effective styles, or just what's changed from the built-in ones, as a `.sty` |

Findings from Validate and Check Marker Placement open in a list. Activating a row moves the caret there. Files above 1 MiB aren't checked.

## Configuration files

These apply from top to bottom, later ones winning. **Configuration Files…** lists the ones for the current file.

| # | File | Where | Edit |
|---|---|---|---|
| 1 | Official `usfm.sty` | built in | read-only (copy to read) |
| 2 | UNITI built-in rules, `uniti.sty` | built in | read-only (copy to read) |
| 3 | **Your rules**, `uniti.sty` | your configuration folder: `…/Environments/USFM/uniti.sty` | yes; applies to every USFM file |
| 4 | Project stylesheet: `usfm.sty`, or the one `Settings.xml` names | project folder | yes |
| 5 | Project `custom.sty` | project folder | yes; Paratext and PTXprint read it too |
| 6 | PTXprint changes, `shared/ptxprint/ptxprint-mods.sty` | project folder | yes |
| 7 | Project rules, `uniti.sty` | project folder | yes; UNITI only |
| 8 | Loaded stylesheets | wherever you loaded them from | yes |

Other files:
- `Settings.xml`, `BookNames.xml` and `custom.vrs` in the project folder.
- `SpellingStatus.xml` and `hyphenatedWords.txt` in the project folder: Paratext's word lists, read-only (see [Check Spelling](#check-spelling) and [Hyphenating Preview](#hyphenating-preview)).
- **Your spelling lists**, `…/Environments/USFM/Spelling/<project>.json`: the words you approved or marked wrong.
- **Your versification files**, `…/Environments/USFM/Versification/*.vrs`. Copy Septuagint, Vulgate or Russian versification files there from a Paratext installation; English and Original are built in.

The two `uniti.sty` files can hold **rules** that a plain `.sty` can't express:
- a paragraph straight after another, e.g. a blank line between prose and poetry (`\Marker p+q1`);
- a note's caller (`\Marker f::caller`).

They can also hold ordinary marker records, such as the built-in `\Marker nd` with `\SmallCaps`, and every presentation field, including `\Justification` (`Left`, `Center`, `Right`, `Both`, `Start`, `End`) and `\Hyphenate`. [USFM Stylesheet Rules](../usfm-stylesheet-rules.md) is the full reference: the file format, every field, selectors, justification, hyphenation, the built-in rules and recipes.

Creating your rules or a project `uniti.sty` starts from a template that explains the syntax and lists UNITI's built-in rules, commented out, to copy and change. Saving any of these files reloads the stylesheets, and Standard and Preview update straight away.
