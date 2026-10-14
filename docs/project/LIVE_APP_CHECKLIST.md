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

## 9. Grouped Tabs (BF-082, ordinary windows)
- [ ] **View › Grouped Tabs** on, in an ordinary window: files stack per group in each split; it feels right to use.

## Results

Report anything wrong here, or tell Claude; each failure becomes a fix or a BF entry.
