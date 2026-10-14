# USFM Book Lock — Plan

Date: 2026-10-14
Status: **Implemented** (2026-10-14): L1–L5. Decisions D1–D7 taken 2026-10-14 (D1 revised the same day). See [As built](#as-built) for where the code differs from the plan.
Origin: the user, 2026-10-13/14 ("all paratext folders should start in READONLY mode" and the answers below); the [wishlist](../../FEATURE_WISHLIST.md) entry, which this plan replaced.

## The user's answers, 2026-10-13/14

- **The lock is on the book, not the folder.** The USFM environment lists a project folder's SFM books to open in the active panel. The folder isn't read-only; a book's content editing is disabled until the user unlocks it.
- **The lock belongs to the book's file, not to a view.** It's a USFM environment setting on the open document: every view of the book (other splits, other windows, Plain Text/Standard/Preview) is locked or unlocked together.
- **Every time a book is opened, it's locked.** Unlocking is never remembered; it lasts until the file is closed.
- **Unlocking** is per open book: right-click the **Book** selector on the toolbar › Unlock; also beside Show One Chapter (the USFM menu and the toolbar), and on the tab's and the text's right-click menus.
- **Find/Replace across a group or all open files** first lists the files it would change, for explicit opt-in.
- **Replace in a locked book** asks **Skip** or **Unlock and Replace**.
- **A locked book must be unlocked to save.** As Find/Replace steps through books it opens and closes them in the pane; a book leaving with changes asks "changes will be lost": unlock and save, or discard. No file is ever saved without changes; discarding drops the unsaved edits and their undo history.
- **A USFM book is UTF-8 with CRLF line endings.** One that isn't is a clear error to correct: the user is asked **Close** or **Update**.
- **In USFM, the group is the project.** The project is open, and all of its SFM files are part of Find/Replace, opened or not.
- **USFM only** (except D5). A file/folder lock for the other environments is a separate [wishlist](../../FEATURE_WISHLIST.md#lock-a-file-or-folder-plain-text-and-the-other-basic-environments) entry.

## Today

- Round 3 T7 (read-only folders): `Document.set_read_only` makes `insert`, `delete`, `replace`, `replace_many`, `apply_replacement_plan`, `undo`, `redo` and `save` raise `DocumentReadOnlyError` (one `_ensure_writable`); `UNITIMainWindow._apply_read_only` sets it from `Settings.read_only_folders` and calls `view.set_read_only` and the Standard editor's `setReadOnly`; `set_read_only_folders` refreshes every view in every window; `_refuse_read_only` gives the message, and guards Save (`start_save_current`, `save_current`), Undo/Redo and USFM commands (`EnvironmentController._apply`); `RichViewPane.editable` blocks Standard; the tab's 🔒 (`_tab_label`, `ProjectTabs.label`) and the title's "(read-only)".
- Find/Replace: Replace in the current document checks `read_only` before `document.replace` (`find_replace.py`, "is read-only"); Replace All in a group or all open documents skips read-only files ("; 1 read-only") and counts other failures as skipped. **Current Group** is Replace All only, over the group's *open* documents (`service._documents_in_same_group`); Find Next and Replace stay in the current document.
- Changing book in a project tab (`EnvironmentBar.open_book`): a book with unsaved changes asks Yes (save) / No (keep the changes, the book hidden in the tab) — `project_tabs.ask_save_before_switch`.
- Save writes even when nothing changed: `save_current` doesn't check `Document.modified` (which already counts a changed output format).
- A file with mixed line endings shows `LineEndingReportDialog` on open, which converts the live text (`_convert_and_set_output_eol`); so do the Line Endings menu and the encoding choices.
- Nothing locks a book by default.

## Design

**A second, lighter state on the document: locked.** `Document.locked` blocks the same edit paths as `read_only`, save included: one `_ensure_writable`, two reasons. `DocumentLockedError` is a `DocumentReadOnlyError`, so existing handlers catch it; `_safe_operation_error` says "the book is locked" for it. Recovery replay isn't an edit and stays allowed. Read-only folders stay as they are and are stronger: a book in one is read-only and can't be unlocked (the Unlock entries are disabled, with the folder named in the tooltip). Changing the lock notifies the document's metadata listeners, and every view of it in every window refreshes: the text view's `set_read_only`, the Standard editor, the tab's 🔒, the title and the Unlock action's check.

**Who sets it.** The window locks a project book's `Document` when its first USFM view is added (`_add_document`, for a path `is_project_book` accepts, opened into USFM): one place, so every open path (Open, Book selector, sync, Recent Files, Open USFM Project…, session restore, Open in USFM Environment, pinning, Find/Replace stepping) goes through it. A second view of an open book (another split or window) shares the document, so it shares the lock. Reopening the file after it's closed locks it again. A file opened as Plain Text, or in another environment, isn't locked; if a Plain Text tab shares the document of a locked book, it shows the lock too, since the lock is the file's. A Plain Text document that already has unsaved changes when its first USFM view opens stays unlocked, with a status message.

**Unlocked is per open document, never saved.** Session restore opens books locked, unsaved edits recovered from a crash included.

**Saving.**
- **A locked book is unlocked to save.** Save on a locked book with changes asks "GEN (NIV) is locked." with **Unlock and Save** and **Cancel**. Save All asks once for all of them: "3 locked books have changes." with **Unlock and Save Them** and **Skip Them**. The save prompt on closing a window or quitting shows **Unlock and Save** for a locked book instead of **Save**.
- **No file is written without changes (all of UNITI, D5).** Save on a document that isn't `modified` does nothing and says "GEN.SFM has no changes: nothing saved"; the file isn't touched. Save As to another path still writes the copy.
- **A book with changes leaving the pane asks Save or Discard (D4)**, locked or not: when another book replaces it in its tab (Book selector, Find/Replace stepping) or its tab or window closes. "Changes to GEN (NIV) will be lost." with **Save** (**Unlock and Save** for a locked book) and **Discard**. Discard closes the book without saving: its edits and their undo history are dropped, and reopening it reads the file. The prompt comes only when this is the book's last view; another split or window still showing it keeps the changes. This replaces today's "No keeps the changes, the book hidden in the tab" in project tabs.
- How a locked book gets changes: unlocked, edited and locked again; crash recovery; or **Update** (below).

**UTF-8 with CRLF.** When a project book opens into USFM and isn't UTF-8 with CRLF line endings (LF, CR or mixed lines, or another encoding), it asks "GEN (NIV) isn't UTF-8 with CRLF line endings (found: LF / mixed / Windows-1252)." with **Close** and **Update**. Close closes it; nothing is written. Update converts the text to CRLF and the output format to UTF-8 CRLF, as one change Undo can take back; the book stays locked, so the change is saved only with Unlock and Save (D6). A BOM is kept as found. For project books this replaces the mixed-line-ending dialog. While a book is locked, the Line Endings and Encoding menu choices are disabled.

**What the user sees.**
- A lock on the project tab ("🔒 NIV", as read-only folders do) and "(locked)" in the title while the shown book is locked.
- Typing, paste, Standard edits, Undo/Redo, USFM commands and Replace on a locked book are refused with "GEN (NIV) is locked: right-click the Book list › Unlock to edit" in the status bar (`_refuse_locked`, a sibling of `_refuse_read_only`; Save has its own prompt above).
- **Unlock Book / Lock Book** (checkable): the Book selector's right-click menu; the USFM menu and the toolbar beside **Chapter**; the project tab's and the text's right-click menus. It acts on the shown book. Locking a book with unsaved changes is allowed; saving them then asks to unlock.

**Find/Replace.**
- **In USFM, Current Group is the project (D3):** every SFM book of the current project, opened or not. Other environments keep today's group (its open documents).
- **Replace / Replace All in the current document**, when it's a locked book: "GEN (NIV) is locked." with **Unlock and Replace** and **Skip**. Unlock and Replace unlocks the book (as the toggle does) and replaces. Skip changes nothing; the next Replace asks again.
- **Replace All in a group or all open documents (D2):** before changing anything, a dialog lists every file with matches (name, project, match count, and 🔒 for locked books), each with a checkbox, all unticked. Only ticked files are changed; a ticked locked book is unlocked first, and the dialog says so ("2 locked books will be unlocked"). Cancel changes nothing. Read-only-folder files are listed disabled, as today's skip. A project book that wasn't open is read for the search and closed again if it isn't ticked; a ticked one stays open in the project tab, changed and unsaved.
- **Find Next / Replace step through the project's books** (USFM, Current Group): past the last match in a book, the next book with a match is shown in the pane, as the Book selector shows it, and the book left behind follows the Save or Discard rule. Wrapping past the last book asks, as wrapping past the end of a document does.

## Phases

### L1: The lock and saving (core)
- `Document.locked` / `set_locked`; `_ensure_writable` refuses with `DocumentLockedError` for every edit path and `save`; recovery replay allowed; lock changes notify the metadata listeners.
- **No write without changes**, all of UNITI: Save and Save All skip a document that isn't `modified`, with the status message.
- `_safe_operation_error` names the locked case.
- Tests: each edit path and save refused while locked; replay allowed; unlocking allows edits and saving; read-only and locked together; Save on an unmodified document leaves the file's bytes and modification time alone, in every environment; Save after only an encoding or line-ending change still writes.

### L2: Locked on open (USFM environment)
- `_add_document` locks a project book's document on its first USFM view; second views share it; Plain Text and other environments never lock it; a modified Plain Text document stays unlocked.
- Every view follows the lock: the text view, Standard (`RichViewPane.editable` false while locked), the tab's 🔒, the title's "(locked)"; `_refuse_locked` for typing, Undo/Redo and USFM commands.
- Saving a locked book: Unlock and Save / Cancel; Save All's one prompt; the close/quit prompt's Unlock and Save.
- Leaving the pane with changes: Save (Unlock and Save) / Discard, for every project book, replacing `ask_save_before_switch`'s Yes/No; only for a book's last view.
- UTF-8 with CRLF on open: Close / Update; Line Endings and Encoding disabled while locked.
- Find/Replace until L4 (D7): Replace and Replace All in a locked current book ask Skip / Unlock and Replace; Replace All across files skips locked books and reports them ("; 3 locked"), as read-only files are.
- Tests: every open path locks; reopening after close locks again; a second view in another window shares the state and refreshes when it changes; Plain Text doesn't lock; the session restore locks, recovered edits included; Unlock and Save saves and unlocks, Cancel writes nothing; Discard closes without writing and reopening shows the file's text with no undo history; no prompt while another view shows the book; Update converts LF, mixed and Windows-1252 books, stays locked, and Undo takes it back; Close writes nothing; Skip / Unlock and Replace in the current book; Replace All's locked count.

### L3: Unlock / Lock Book
- The checkable action in the Book selector's context menu, the USFM menu, the toolbar beside **Chapter**, and the tab's and text's right-click menus; disabled (with the folder in the tooltip) for a book in a read-only folder.
- Tests drive the real window: unlocking from each place; Standard edits after unlocking; locking again with unsaved changes; the action disabled in a read-only folder; the toolbar fits within the 1,000 px limit (`fd7bbe2`).

### L4: The opt-in list and the project as the group
- In USFM, Current Group's documents are the project's SFM books, opened or not (the service's group provider).
- Replace All across a group or all documents: the opt-in file list, all unticked, locked books marked; ticked locked books unlocked first; unticked books that weren't open closed again; replaces L2's locked skip.
- Tests: the list shows only files with matches, books not open included; unticked files unchanged and never written; Cancel changes nothing; read-only-folder files disabled; ticked locked books unlocked and left open, unsaved; all open documents covers every environment.

### L5: Stepping through the project's books
- Find Next / Replace with Current Group in USFM move to the next book with a match in the pane; the book left behind asks Save or Discard; wrapping past the last book asks.
- Tests: Find Next crosses into a book that wasn't open; a book with no match is passed over; leaving a changed book asks, and Discard drops its changes; Replace in a locked book reached by stepping asks Skip / Unlock and Replace.

## Order

L1 → L2 → L3 → L4 → L5. Each is useful alone (D7: L2 brings the single-book Find/Replace dialog, so only multi-file Replace All waits). Documentation when L5 landed: the [USFM](../../../environments/usfm.md) page, the user manual, the [live-app checklist](../../LIVE_APP_CHECKLIST.md), [Current Status](../../01_current/STATUS.md), the roadmap, and the wishlist entry removed. D5's "no write without changes" goes into the user manual with L1.

## Decisions

Decided 2026-10-14:
- **D1 (revised): a locked book is unlocked to save.** Save, Save All and the close prompt offer Unlock and Save. (First decided the other way: save allowed on a locked book.)
- **D2: the opt-in list covers every multi-file Replace All.** Groups are per environment, so Replace All in a group lists that environment's files; Replace All in all open documents covers all open files, in every environment, not only USFM books.
- **D3: in USFM, the group is the project.** All its SFM files are part of Find/Replace, opened or not; Find Next and Replace step through them in the pane (L5).
- **D4: a book with changes leaving the pane asks Save or Discard,** locked or not; Discard drops the edits and their undo history. It replaces "No keeps the changes" in project tabs.
- **D5: no file is written without changes, in all of UNITI.**
- **D6: Update leaves the book locked.** Its conversion is saved only with Unlock and Save.
- **D7: before L4, the single-book dialog ships with L2;** multi-file Replace All skips locked books with a count until the opt-in list replaces it.

## As built

Implemented 2026-10-14, L1–L5 in order. Where the code differs from the plan above:
- **Unlock Book / Lock Book isn't a checkable action.** Its text swaps ("Unlock Book" while locked, "Lock Book" while not). On the toolbar the lock (🔒/🔓) takes the place of the word "Book" before the Book list, because a separate button pushed the toolbar past its 1,000 px limit; its tooltip carries the full name.
- **There is no Save All in UNITI,** so the "3 locked books have changes" prompt isn't built. Save, closing a tab or window, and Quit each offer Unlock and Save.
- **Update's Undo takes back the text only.** Converting LF or mixed lines is one undoable edit; the output-encoding change (Windows-1252 → UTF-8) isn't part of the text history, so a book that needs only the encoding change has nothing to undo.
- **A book that was closed lately** (the registry keeps it for a while) is locked again when its view is added: the lock is applied on a document's first view, not on a first-ever open.
- **Find Next / Replace stepping** searches the project's other books in a background job, then shows the book through the Book list's own path (`EnvironmentBar.open_book`), so its Save / Discard question is the one the Book list asks. Wrapping asks only when the next match is in another book; if this book holds the only matches, Find wraps within it as before.
- **Tests:** a test of the lock is marked `book_lock`. The other tests run with books opening unlocked, unchecked for format, and leaving their tab keeping their changes (`tests/conftest.py`), and with a multi-file Replace All ticking every file its list allows.
