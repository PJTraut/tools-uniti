# Live-App Checklist — USFM Environment

Started: 2026-10-13, for `main` at `f3fe859`. Tick each line, and note anything that's wrong under it. Use two Paratext projects (for example `usNIVv3` and `ruCARSv3`). Add their folder to **View › Read-Only Folders…** only in section 7, or work on copies, so nothing is changed by accident.

## 1. Project tabs (round 3 T4)
- [ ] Open a book with **File › Open USFM Project…**: it opens in "SFM-1", in a tab titled with the project's short name only (e.g. "NIV").
- [ ] Pick another book in the **Book** list: the same tab now shows it; no new tab.
- [ ] Type in a book, then pick another book: "Save changes to GEN (NIV)?" appears.
  - [ ] **No**: the book changes; the edited book is marked "•" in the Book list and the tab reads "NIV*".
  - [ ] **Yes**: it saves, then changes the book.
- [ ] Open a book of the second project: it gets its own tab ("CARS").
- [ ] Close a project tab with unsaved books: you're asked once per modified book.
- [ ] The full project name (`<FullName>` in `Settings.xml`) appears nowhere: tab, title, toolbar, menus.

## 2. Windows (T3)
- [ ] The title reads "UNITI — USFM A — NIV — 01GEN.usfm".
- [ ] Open a second USFM window: it's "SFM-2".
- [ ] Rename a window (click its name on the toolbar, or **Rename Window…**). Restart UNITI: the name is kept.

## 3. Groups (T2, T5)
- [ ] **Manage Groups…** has an environment chooser; USFM's groups are separate from Plain Text's.
- [ ] Put a project in group A (tab right-click › Group, or the toolbar's Group list): its tab is tinted in A's colour, in every split and window.
- [ ] Changing a group never moves a tab to another window.

## 4. Sync (T5, P4, P5)
- [ ] NIV and CARS both in group A, in two windows: moving the caret in NIV moves CARS to the matching verse, mapped by versification (try Ps 51:1 → 50:3, Ps 23:1 → 22:1).
- [ ] Move to another book: the other project's tab changes to that book, without asking about unsaved changes.
- [ ] An ungrouped project doesn't follow.
- [ ] **New 2026-10-13:** with NIV and ESV tabs in one split and NIV showing, sync changes NIV's book, never switching to the ESV tab.

## 5. The tab menu (T6)
- [ ] Right-click a tab: **Group**, **Split**, **Window**, **Read Only**.
- [ ] **Split › Move to New Split Right**: the tab moves with its book.
- [ ] At most four splits. **New 2026-10-13:** with Find/Replace attached you still get four splits, and **Move to Split** never lists the Find pane.
- [ ] **Unsplit**: the split's tabs join the neighbouring split.
- [ ] **Window › Move to New Window**, then **Dock**: the tab goes back where it was.

## 6. The same book in two windows (new 2026-10-13)
- [ ] Open NIV GEN in USFM A and USFM B (Book list or File › Open in B): both windows keep it; neither loses its tab.
- [ ] Type in A: A's views update as you type.
- [ ] With GEN in **Preview** in B, type in A: B's Preview doesn't change yet. Click into B: it catches up at once.
- [ ] Typing in A stays fast while B shows the book in Preview.

## 7. Read-only folders (T7)
- [ ] Add the projects' folder in **View › Read-Only Folders…**: the tab shows 🔒 and the title "(read-only)".
- [ ] Typing, Replace, Undo and Save are refused with a message.
- [ ] **New 2026-10-13:** **Save As** into that folder is refused; Save As elsewhere works.
- [ ] **New 2026-10-13:** edit a book, then turn **Read Only** on from its tab menu and close it: you're offered Discard or Cancel, not Save.

## 8. Show One Chapter (C1–C4)
- [ ] Turn on **Chapter** (toolbar) or **Show One Chapter** (USFM menu): only the caret's chapter shows, in Plain Text, Standard and Preview.
- [ ] Arrow keys, clicks and scrolling stop at the chapter's edges; Select All selects the chapter.
- [ ] The Chapter selector, Go to Chapter:Verse, sync and Find change the chapter.
- [ ] Preview's notes list only that chapter's notes.

## 9. USFM book lock (L1–L5)
- [ ] Open a project book: the tab shows 🔒 and the title "(locked)"; typing, paste, Undo and Replace say it's locked in the status bar.
- [ ] Unlock Book from the toolbar's lock, the USFM menu, the Book list's right-click menu, and a tab's and the text's right-click menus; Lock Book locks again.
- [ ] Open the same book in a second split or window: both show the lock and follow it.
- [ ] Edit an unlocked book, lock it, then Save: asked Unlock and Save or Cancel. Save with no changes: "has no changes: nothing saved".
- [ ] Change the book with unsaved changes: Save / Discard / Cancel. Discard, then reopen: the file's text, no Undo history.
- [ ] Open a book that's LF, mixed or not UTF-8: Close / Update. Update leaves it locked and unsaved.
- [ ] Replace in a locked book: Unlock and Replace / Skip.
- [ ] Project **Replace All**: the list shows files with matches, all unticked, locked ones marked; only ticked files change; Cancel changes nothing; books that weren't open and weren't ticked close again.
- [ ] Find Next with Project steps into the next book with a match (one that wasn't open too) and asks at the end of the project.
- [ ] Scopes follow the tab: a USFM tab offers Book, Cursor to End, Project, Group; a text or JSON tab offers Whole Document, Cursor to End, Current Group, All Open Documents (only that environment's files). Group with two projects in one group searches both, books that weren't open too, and Find Next steps into the other project's book.
- [ ] One book per project: changing the book (Book list, Find stepping, File → Open) closes the previous one and asks about unsaved changes; Replace All over a Project writes the ticked books that aren't open to disk and says so in the list.
- [ ] A book in a read-only folder can't be unlocked.

## 10. Check Spelling (S1–S5)
- [ ] Open a project with `SpellingStatus.xml` (usNIVv3, rnBKCv1): **USFM → Check Spelling** is on offer; for a project with neither list it's greyed with the reason.
- [ ] Turn it on from the USFM menu and from a tab's right-click menu: wrong words and unknown words get different wavy underlines in Plain Text, Standard and Preview; hover shows the reason (and Paratext's correction).
- [ ] Footnote text isn't underlined in Preview's notes frame; `\id`, `\rem` and verse numbers aren't underlined anywhere.
- [ ] Change the book from the Book list and with sync: the new book is checked too. Another project's tab isn't. Quit and restore the session: it's still on.
- [ ] Type in Plain Text and Standard: no lag, the underline of an edited word updates.
- [ ] Change `SpellingStatus.xml` in Paratext (or by hand) and activate the window: the underlines follow.
- [ ] Dark and light themes: both underline colours are easy to see.

## 11. Footnote categories
- [ ] On a book whose notes have `\cat` (`usNIVv3`): **USFM → Footnote Categories** lists the categories and **None**, all checked.
- [ ] Uncheck one in Preview: its notes' callers and bodies go, and the remaining callers are a, b, c… Standard still shows every note.
- [ ] Uncheck **None**: notes without `\cat` go. **Show All** brings everything back.
- [ ] Change the book from the Book list: the filter stays on for the tab; another project's tab is unaffected. Restart: it's restored.

## 12. Hyphenate Preview (H1–H3)
- [ ] On a project with `hyphenatedWords.txt` (`usNIVv3`): **USFM → Hyphenate Preview** is on offer; for a project without one it's greyed with the reason.
- [ ] Turn it on from the USFM menu and from a tab's right-click menu; in Preview, long listed words break at a line end with a hyphen, and nowhere else. Standard and Plain Text are unchanged.
- [ ] Narrow and widen the window: the breaks move; with `\Justification Both` on `\p` (project `uniti.sty`) the lines fill the width.
- [ ] Click and select across a broken word; Find a word that Preview breaks; copy from Preview and paste: no stray hyphens. Sync and Check Spelling underlines still land on the right words.
- [ ] `\Hyphenate -` on `\p` stops it for that style; change the book, restart: the setting stays.
- [ ] Preview's notes frame breaks listed words in footnotes too (`\Hyphenate -` on `\Marker f` stops it); copy from the notes: no stray hyphens.
- [ ] Right-click a misspelt word that has several equally near suggestions: the one the book uses most is first.

## 13. Justification and text direction (J1, W1–W6, W8)
- [ ] `\Justification Start`, `End`, `Left`, `Right`, `Center` and `Both` on a paragraph style: each sits where the stylesheet reference says. In a right-to-left book `Start` and `Left` are the right edge.
- [ ] An Arabic or Hebrew project (`arNAV12`), Standard and Preview, with the stock stylesheet: `\qr` lines sit on the left, `\s3`/`\sp` headings on the right, and a `\q1` passage hangs from the right (first line ¼" in, the rest ¾"). View → Text Direction → Left-to-Right turns all of it round.
- [ ] The status bar's direction: `RTL` in Standard and Preview of an `arNAV12` book (hover: the project named), `LTR (project RTL)` after View → Text Direction → Left-to-Right, in Plain Text only the tab's own choice (`Auto` once Text Direction is back on Auto), and it follows a switch to another tab.
- [ ] In `arNAV12`, a `\p` that starts with a Latin word or a digit still lays out right to left (its lines sit on the right), and the chapter heading `\c 1` sits on the right. A Hebrew or Arabic `.sfm` opened outside any project, with Text Direction Auto, takes each paragraph's direction from its first letter.
- [ ] Standard in `arNAV12`: tags read `\p`, `\v 1`, `\f +` (not `p\`), from the right. Arrow keys move through a tag without a dead press, typing just after a tag goes into the text after it, Backspace there steps into the tag, and a copied passage pastes into Plain Text without invisible characters (Character Inspector shows no U+2066/U+2069).
- [ ] `\Direction LTR` on `\ip` in the project's `uniti.sty`: the introduction paragraphs read left to right in that project, everything else stays right to left, and the Style Inspector shows the field under `\ip` with its layer. Reload Project Stylesheets after saving.
- [ ] `\Marker tl` with `\Direction LTR` in `arNAV12`'s `uniti.sty`, and `\tl Paul,\tl*` typed between Arabic words: in Standard and Preview the name reads `Paul,` (comma on its right), the Arabic around it stays right to left, the arrow keys cross the name without a dead press, Check Spelling's underline (if any) covers the word alone, and a copy pastes without U+2066/U+2069. The HTML export shows the same in a browser.
- [ ] **USFM → Export Preview as HTML…** on an `arNAV12` book with Show One Chapter on: the save dialog offers `<book>.html` next to the book; the page opens in a browser right to left in the project's font, with every chapter, `\qr` on the left and `\q1` hanging from the right as in Preview; a caller jumps to its note and back; hidden footnote categories stay out. The same entry is on Preview's right-click menu, not Standard's.
- [ ] Optional, against PTXprint: a PDF from one of `arNAV12`'s right-to-left configurations (`Mark`, `John`) shows the same `\q1` and `\qr` geometry.

## 14. Spelling follow-ups (F1–F5)
- [ ] Right-click a flagged word in Plain Text, Standard and Preview: the suggestions and Paratext's correction (editable modes only), **Approve**, **Mark Wrong**.
- [ ] Choose a suggestion: the word is replaced, Undo takes it back; in a locked book the status bar says it's locked.
- [ ] Approve a word: it stops being underlined in every split and window of the project; quit and restart: still approved. Mark a correct word wrong: it's underlined, and **Remove … from Your Spelling List** undoes it. `SpellingStatus.xml` is untouched.
- [ ] A project with `WordSuffixes` in `Settings.xml` (`usNIVv3`): `Paulʼs`-style words aren't flagged when `Paul` is correct.
- [ ] `rnBKCv1`: a word pair Paratext marks wrong (`ata wuzoba`) is underlined as one.
- [ ] **Next / Previous Spelling Issue** walk the book, wrap round, and the status bar counts them; Ctrl+Alt+. and Ctrl+Alt+, do the same, and both can be rebound in Hotkeys.
- [ ] Right-click a pair Paratext marks wrong (`ata wuzoba` in `rnBKCv1`): **Approve** stops it being underlined. In Plain Text, then in Standard and Preview, select two words and choose **Mark … Wrong Together**: the pair is underlined wherever it stands; **Remove … from Your Spelling List** undoes it.

## 15. Grouped Tabs (BF-082, ordinary windows)
- [ ] **View › Grouped Tabs** on, in an ordinary window: files stack per group in each split; it feels right to use.

## 16. Floating windows across screen changes (P1–P2)
Needs a laptop and an external monitor. [Plan](02_plans/2026-10-20-window-layouts-per-screen-configuration-plan.md).
- [ ] Open Find (detached), Character Inspector and Compare on the external monitor and maximize the main window there. Quit, unplug the monitor, launch: every window is on the laptop, the main window is scaled, and un-maximizing gives a laptop-sized window, not a screen-sized one.
- [ ] Windows that were large on the external monitor (Compare, Whitespace Legend at a high zoom) come back smaller than the laptop screen, proportions kept, with their title bars visible.
- [ ] Replug with UNITI running: the windows jump back to where they were on the external monitor.
- [ ] Change the external monitor's scaled resolution: the windows adapt (the main window scales with the screen, tool windows keep their size); change it back: the first layout returns exactly.
- [ ] Sleep and wake with the monitor attached: no window moves.
- [ ] Unplug the monitor while a toggle window is open on it: it moves onto the laptop, and its hotkey still closes it.
- [ ] `window-layouts.json` appears next to `settings.json`; it keeps at most eight layouts.
- [ ] Keyboard zoom ([BF-097](BETA_FEEDBACK.md#bf-097--floating-windows-keyboard-font-zoom-acts-on-the-editor-not-the-floating-window)): with Compare, the Character Inspector, the Whitespace Legend and a detached Find/Replace open in turn, Cmd++, Cmd+=, Cmd+- and Cmd+0 zoom that window and leave the editor behind it alone; back in the editor they zoom the editor.
- [ ] Character Inspector with a word selected (Opt+Cmd+I): opens at a sensible size, on the screen the main window is on ([BF-098](BETA_FEEDBACK.md#bf-098--character-inspector-opened-full-screen-and-did-not-resize)).

## Results

Report anything wrong here, or tell Claude; each failure becomes a fix or a BF entry.
