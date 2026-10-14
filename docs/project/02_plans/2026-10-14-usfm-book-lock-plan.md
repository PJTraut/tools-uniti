# USFM Book Lock — Plan

Date: 2026-10-14
Status: **Planned**, not started: L1–L4. Decisions D1–D2 taken 2026-10-14.
Origin: the user, 2026-10-13/14 ("all paratext folders should start in READONLY mode" and the answers below); the [wishlist](../FEATURE_WISHLIST.md#paratext-books-open-locked) entry, which this plan replaces.

## The user's answers, 2026-10-13/14

- **The lock is on the book, not the folder.** The USFM environment lists a project folder's SFM books to open in the active panel. The folder isn't read-only; a book's content editing is disabled until the user unlocks it.
- **The lock belongs to the book's file, not to a view.** It's a USFM environment setting on the open document: every view of the book (other splits, other windows, Plain Text/Standard/Preview) is locked or unlocked together.
- **Every time a book is opened, it's locked.** Unlocking is never remembered; it lasts until the file is closed.
- **Unlocking** is per open book: right-click the **Book** selector on the toolbar › Unlock; also beside Show One Chapter (the USFM menu and the toolbar), and on the tab's and the text's right-click menus.
- **Find/Replace across a group or all open files** first lists the files it would change, for explicit opt-in.
- **Replace in a locked book** asks **Skip** or **Unlock and Replace**.
- **USFM only.** A file/folder lock for the other environments is a separate [wishlist](../FEATURE_WISHLIST.md#lock-a-file-or-folder-plain-text-and-the-other-basic-environments) entry.

## Today

- Round 3 T7 (read-only folders): `Document.set_read_only` makes `insert`, `delete`, `replace`, `replace_many`, `apply_replacement_plan`, `undo`, `redo` and `save` raise `DocumentReadOnlyError`; `UNITIMainWindow._apply_read_only` sets it from `Settings.read_only_folders`; `_refuse_read_only` gives the message; `RichViewPane.editable` blocks Standard; Find/Replace's Replace All in all documents skips read-only files (`find_replace.py`, "; 1 read-only").
- Nothing locks a book by default.

## Design

**A second, lighter state on the document: locked.** `Document.locked` blocks the same edit paths as `read_only` (one `_ensure_writable` check, two reasons), but not `save`: a locked book has no unsaved edits of its own, and a book unlocked, edited and locked again can still be saved. Read-only folders stay as they are and are stronger: a book in one is read-only and can't be unlocked (the Unlock entries are disabled, with the folder named in the tooltip).

**Who sets it.** The USFM environment, when a project book's `Document` is opened (created), sets `locked = True`. A second view of an already open book (another split or window, fix #1 of 2026-10-13) shares the document, so it shares the lock. Reopening the file after it's closed locks it again. Plain Text tabs ("Open as Plain Text") and other environments never lock.

**Unlocked is per open document, never saved.** Session restore opens books locked, unsaved edits recovered from a crash included (recovery replay isn't an edit, as for read-only).

**What the user sees.**
- A lock on the project tab ("🔒 NIV", as read-only folders do) and "(locked)" in the title while the shown book is locked.
- Typing, paste, Standard edits, Undo/Redo and Replace on a locked book are refused with "GEN (NIV) is locked: right-click the Book list › Unlock to edit" in the status bar. That also answers the open question for Standard: the same status message.
- **Unlock Book / Lock Book** (checkable): the Book selector's right-click menu; the USFM menu and the toolbar beside **Chapter**; the project tab's and the text's right-click menus. It acts on the shown book.

**Find/Replace.**
- **Replace / Replace All in the current document**, when it's a locked book: a dialog, "GEN (NIV) is locked." with **Unlock and Replace** and **Skip**. Unlock and Replace unlocks the book (as the toggle does) and replaces.
- **Replace All in a group or all open documents:** before changing anything, a dialog lists every file with matches (name, project, match count, and 🔒 for locked books), each with a checkbox, all unticked. Only ticked files are changed; a ticked locked book is unlocked first, and the dialog says so ("2 locked books will be unlocked"). Cancel changes nothing. Read-only-folder files are listed disabled, as today's skip.

## Phases

### L1: The lock (core)
- `Document.locked` / `set_locked`; `_ensure_writable` refuses with `DocumentLockedError` (a `DocumentReadOnlyError`, so existing handlers catch it) for every edit path except `save` and recovery replay.
- Tests: each edit path refused while locked; save and replay allowed; unlocking allows edits; read-only and locked together.

### L2: Locked on open (USFM environment)
- The environment controller locks a project book's document when it's opened into USFM, through every open path (Open, Book selector, sync, Recent Files, Open USFM Project…, session restore, Open in USFM Environment, pinning).
- Second views share it; Plain Text tabs and other environments never lock.
- The tab's 🔒 and the title's "(locked)"; the refusal message (`_refuse_read_only` gains the locked case).
- Tests: every open path locks; reopening after close locks again; a second view in another window shares the state; Plain Text doesn't lock; the session restore locks.

### L3: Unlock / Lock Book
- The checkable action in the Book selector's context menu, the USFM menu, the toolbar beside **Chapter**, and the tab's and text's right-click menus; disabled (with the folder in the tooltip) for a book in a read-only folder.
- Standard: `RichViewPane.editable` false while locked; Preview is read-only anyway.
- Tests drive the real window: unlocking from each place; Standard edits after unlocking; the action disabled in a read-only folder; the toolbar fits within the 1,000 px limit (`fd7bbe2`).

### L4: Find/Replace
- Replace / Replace All in a locked current book: the Skip / Unlock and Replace dialog.
- Replace All across a group or all documents: the opt-in file list, all unticked, locked books marked; ticked locked books unlocked first.
- Tests: Skip leaves the book unchanged; Unlock and Replace unlocks and replaces; the list shows only files with matches; unticked files unchanged; Cancel changes nothing; read-only-folder files disabled.

## Order

L1 → L2 → L3 → L4. L1–L3 are useful alone; L4 completes the user's rules for Find/Replace. Documentation when L4 lands: the [USFM](../../environments/usfm.md) page, the user manual, the [live-app checklist](../LIVE_APP_CHECKLIST.md), [Current Status](../01_current/STATUS.md), the roadmap, and the wishlist entry removed.

## Decisions

Decided 2026-10-14:
- **D1: Save is allowed on a locked book.** With no edits it does nothing; a book unlocked, edited and locked again can still be saved.
- **D2: the opt-in list covers every multi-file Replace All.** Groups are per environment, so Replace All in a group lists that environment's files; Replace All in all open documents covers all open files, in every environment, not only USFM books.
