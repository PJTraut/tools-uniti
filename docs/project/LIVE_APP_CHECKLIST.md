# Live-App Checklist — USFM Environment

Started: 2026-10-13, for `main` at `f3fe859`. Tick each line, and note anything that's wrong under it. Use two Paratext projects (for example `usNIVv3` and `ruCARSv3`). Add their folder to **View › Read-Only Folders…** only in section 7, or work on copies, so nothing is changed by accident.

## 1. Project tabs (round 3 T4)
- [ ] Open a book with **File › Open USFM Project…**: it opens in "USFM A", in a tab titled with the project's short name only (e.g. "NIV").
- [ ] Pick another book in the **Book** list: the same tab now shows it; no new tab.
- [ ] Type in a book, then pick another book: "Save changes to GEN (NIV)?" appears.
  - [ ] **No**: the book changes; the edited book is marked "•" in the Book list and the tab reads "NIV*".
  - [ ] **Yes**: it saves, then changes the book.
- [ ] Open a book of the second project: it gets its own tab ("CARS").
- [ ] Close a project tab with unsaved books: you're asked once per modified book.
- [ ] The full project name (`<FullName>` in `Settings.xml`) appears nowhere: tab, title, toolbar, menus.

## 2. Windows (T3)
- [ ] The title reads "UNITI — USFM A — NIV — 01GEN.usfm".
- [ ] Open a second USFM window: it's "USFM B".
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
- [ ] **Split › Move to New Split Right**: the tab moves with all its books.
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
- [ ] Current Group **Replace All**: the list shows files with matches, all unticked, locked ones marked; only ticked files change; Cancel changes nothing; books that weren't open and weren't ticked close again.
- [ ] Find Next with Current Group steps into the next book with a match (one that wasn't open too) and asks at the end of the project.
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

## 13. Justification (J1)
- [ ] `\Justification Start`, `End`, `Left`, `Right`, `Center` and `Both` on a paragraph style: each sits where the stylesheet reference says. In a right-to-left book `Start` is the right edge and `Left` stays left.

## 14. Spelling follow-ups (F1–F5)
- [ ] Right-click a flagged word in Plain Text, Standard and Preview: the suggestions and Paratext's correction (editable modes only), **Approve**, **Mark Wrong**.
- [ ] Choose a suggestion: the word is replaced, Undo takes it back; in a locked book the status bar says it's locked.
- [ ] Approve a word: it stops being underlined in every split and window of the project; quit and restart: still approved. Mark a correct word wrong: it's underlined, and **Remove … from Your Spelling List** undoes it. `SpellingStatus.xml` is untouched.
- [ ] A project with `WordSuffixes` in `Settings.xml` (`usNIVv3`): `Paulʼs`-style words aren't flagged when `Paul` is correct.
- [ ] `rnBKCv1`: a word pair Paratext marks wrong (`ata wuzoba`) is underlined as one.
- [ ] **Next / Previous Spelling Issue** walk the book, wrap round, and the status bar counts them.

## 15. Grouped Tabs (BF-082, ordinary windows)
- [ ] **View › Grouped Tabs** on, in an ordinary window: files stack per group in each split; it feels right to use.

## Results

Report anything wrong here, or tell Claude; each failure becomes a fix or a BF entry.
