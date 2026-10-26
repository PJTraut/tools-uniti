# Find/Replace Scopes per Environment — Plan

Date: 2026-10-22
Status: **S1, S2 and S3 built 2026-10-22**; S4 (documentation) done as it went; the live-app checks are the user's. Q1 is answered.
Origin: the user, 2026-10-22: "we need to redesign 'All open documents' per environment, and environments like USFM will include a project folder 'hidden' books."

## Today

- **All Open Documents** is every entry in `DocumentManager.entries` (`app/service.py:559`), across every environment. It never reaches a project book that isn't open.
- **Current Group** is `_documents_in_same_group` (`app/service.py:442`). In USFM the group is the project (book-lock plan D3): every SFM book of the document's project, open or not, built by `_project_documents` (books not open are opened as transient documents and dropped by `release_group_document`).
- Find Next/Previous stepping through books (`find_book`, `_step_into_another_book`) is wired only to Current Group, and only in USFM.
- Replace All over several files asks first which files to change (book-lock plan D2); it is fed by the same two providers.

## The user's answers, 2026-10-22

1. **Remove the cross-environment "All Open Documents".** A scope never mixes environments.
2. **USFM has three scopes: 1) book, 2) project, 3) group.**
3. **The project and group scopes are about open projects:** "open projects or open group of projects". A group in USFM is a group of projects (round 3, T5: a project belongs to a group, and the group binds projects for sync across windows).

## Decisions (from the answers; to confirm when built)

- **D1: the scope list belongs to the environment.** The Find/Replace window asks the current view's environment for its scopes and for each scope's documents, through a hook any environment can implement (like the undefined-markup hook). `find_replace.py` and `service.py` keep no USFM-specific scope code beyond the hook's registration.
- **D2: USFM scopes** (each also offers **Cursor to End** as today):
  - **Book** — the current book. Replaces *Whole Document* in USFM.
  - **Project** — every book in the current project's folder, open or not. Today's *Current Group* in USFM, renamed.
  - **Group** — every book of every open project in the current project's group, hidden books included. A project that has no group is a group of one, so Group then equals Project.
- **D3: books that aren't open are searched, not opened for editing.** They are transient documents as today: a Find Next that lands in one shows it in the project tab (the Book selector's way, with its Save/Discard question); anything not chosen is dropped.
- **D4: stepping and Replace All treat all three scopes alike.** Find Next/Previous step through the scope's books in the project's book order, project by project in tab order for Group. Replace All keeps D2 of the book-lock plan: the opt-in list shows only files with matches, locked books marked, none ticked.
- **D5: other environments** keep *Whole Document*, *Cursor to End* and *Current Group* (their own groups, as today). *All Open Documents* stays, limited to the current document's environment (answer 1, Q1); it is never a pool across environments.
- **D6: the chosen scope is not saved** (neither the settings nor the recipes hold it), so there is nothing to migrate. When the environment changes, the combo keeps the chosen scope if the new environment offers it and falls back to the first (Whole Document) if not.

## Answered

- **Q1: non-project environments keep "All Open Documents", limited to their own environment** (the user, 2026-10-22).

## The one-book rule (the user, 2026-10-22)

"USFM environment: only ONE BOOK open at a time per project." Answers the same day: ticked books other than the shown one are written to disk by Replace All; the rule is per project tab (each split or window shows its own book, and the same book can be a second view elsewhere); an old session with several books keeps the shown one.

- **D7: changing the book closes the old one** (`EnvironmentBar.keep_one_book`, hooked into `_add_document` and `accept_transferred_view`, so Book list, Find stepping, File → Open, sync, moving a tab between windows and Open Folder by Type all follow it). A book with unsaved changes asks Save / Discard / Cancel first; Cancel leaves it open, hidden. A read-only book with changes asks Discard or Cancel.
- **D8: Replace All writes the ticked books that aren't open** (`save_group_document`, the opt-in list says "N files that aren't open will be saved to disk"); open books change in their tab, unsaved, as before. Nothing is adopted into a tab any more.
- **D9: sync never replaces a book with unsaved changes** (it can't ask): that split stays and the status bar says so.
- **D10: Open Folder by Type opens the first book of each project only.** An old session's extra books are closed when everything is restored, except any with unsaved changes (`settle_restored_books`).
- Tests: `tests/app/test_project_tabs.py`, the S2 tests in `tests/app/test_book_lock.py`, `test_project_groups.py`, `test_tab_menu.py`, `test_hyphenation_toggle.py`, `test_environment_window.py`.

## Risks

- **Group in USFM can be many books** (a project is up to 66, a group several projects). Handled by S3: books are opened one at a time inside the search job. Replace All still keeps every book with matches open until the list is answered.
- **Hidden books** no longer exist: with one book per project tab, everything but the shown book is a file on disk, so Project and Group scopes read them as transient documents. "Open projects" (answer 3) means projects with a tab.
- **Book-lock plan D2/D3 and the Find/Replace tests** assume the scope names and provider shape; they change with D1.

## Steps

1. **S1 — the hook and the scope list. Built 2026-10-22.** `app/find_scopes.py` (`register_scopes`, `scopes_for_environment`: USFM registers its own in S2, everything else gets the four defaults); the Find window takes a `scope_provider(view)` and rebuilds the combo when the view's environment offers a different list; `document_provider` now takes the current document and `UNITIService._documents_in_same_environment` returns only that environment's open documents. Tests: `tests/app/test_find_scopes.py`, the scope-combo test in `tests/ui/test_find_replace_contract.py`, and the two All Open Documents tests in `tests/app/test_book_lock.py`.
2. **S2 — USFM scopes. Built 2026-10-22.** `ReplaceScope.BOOK`, `PROJECT`, `PROJECT_GROUP` (labels Book, Project, Group), registered for USFM in `app/find_scopes.py`; Project reuses the group provider (`_documents_in_same_group`), Group is the new `project_group_provider` (`UNITIService._documents_in_project_group`: the current project first, then the group's other open projects in the order opened, each with every book). Find Next/Previous and Replace All's list work over all three. While a view has no document entry (opening or closing) or there is no view, the combo keeps the chosen scope. Tests: the S2 section of `tests/app/test_book_lock.py`.
3. **S3 — lazy opening. Built 2026-10-22.** The provider hands a `PendingBook` (`app/pending_book.py`) for each book that isn't open; the search job opens it just in time and closes it again unless it has a match (Find stepping: the first match's book stays open until the step is applied; Replace All: books with matches stay until applied). At most one book is open for nothing at a time. The wrap-past-the-end question names the group in Group scope (`ask_wrap_project(group=True)`).
4. **S4 — documentation:** the [USFM](../../environments/usfm.md) page, the user manual, the live-app checklist, Current Status, the roadmap.

## Tests

- A non-USFM environment never lists another environment's documents.
- USFM Book, Project and Group return the expected books: unopened books included; a project that isn't open excluded; a project without a group equals Project.
- Stepping crosses books and projects in order and wraps; Replace All lists only files with matches and writes no file without changes.
- The combo keeps a still-offered scope and falls back otherwise (D6).
