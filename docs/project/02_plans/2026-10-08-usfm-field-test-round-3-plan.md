# USFM Field Test, Round 3 — Plan

Date: 2026-10-08
Status: **Accepted** (2026-10-08, decisions D1–D5 settled). In progress.
Origin: `@externalresources/field_test_feedback` (2026-10-08, the day's second round) and the user's answers the same day.
Changes: [ADR-0017](../05_decisions/ADR-0017-environment-windows-in-place-views-reference-sync.md) decisions 2–4 (an environment window per group, the Book selector, sync within one window) and [ADR-0018](../05_decisions/ADR-0018-usfm-projects-and-recent-projects.md)'s consequence that "a document group is still which splits move together". A new ADR-0019 records the replacement when T3 lands.

## Feedback

Environments:
1. "environmental windows shares groups; groups are per environment, and each environment has its own set of groups."

USFM:
2. "as soon as a "text document" moves to USFM envronment, the "tab" it lives in is for the PROJECT it belongs to."
3. "the tab just assumes the project shortcode name as the title of the tab (currently in top bar), and the project name is displayed in the tab header.(setting.xml)"
4. "changing BOOK does not open new text document, it just changes the book in the current tab."
5. "opening new document in USFM environment opens a new tab for the project it belongs to, and the tab title is the project shortcode name."
6. "projects are assigmned to groups, and group colors are used to color the tab header for the project."
7. "right clicking the folder name on the tab header:
   - SPLIT: unsplit / move to split view panel; allow up to 4 concurrent split panels, each with its own set of tabs/project in individual groups when requested
   - DOC/UNDOC/MOVE DOC: move to new floating window, or move back to other window; name environmentatal windows: e.g. USFM A; USFM B; USFM C; etc."
8. Wishlist: "toggle spellchecking using hyphenatedwords.txt data; plan this"

The user's answers, 2026-10-08:
- **Windows and groups:** "groups can "bind" projects accross windows in envronment". A window no longer stands for a group.
- **Groups:** each environment has its own groups, starting from the default A, B, C.
- **Changing the book with unsaved edits:** "never autosave, alway request (y/n)". Every other piece of editor state stays with its file, undo history included. A read-only option for some folders should be considered.
- **USFM outside a project:** the USFM environment assumes a project. A USFM file outside one is plain text only for now; planning it is left for later.
- **Names:** "Only use SHORTNAME everywhere".

## Today (at `18736cb`)

- **Groups** are one list for the whole app (`document-groups.json`, defaults A, B, C, at most 32). A group belongs to a file (`DocumentEntry.group_id`).
- **An environment window is one environment plus one group.**
  - It's found by `UNITIService.environment_window_for(key, group)` and saved as `ViewRecord.extra["environment_window"] = {environment, group}`.
  - Its title is "USFM — A — NIV".
  - The toolbar's Group dropdown regroups every file in the window and merges it into that group's window (`18736cb`). Regrouping a file moves it to its group's window (`3fad1fb`). Recent Files opens a file into its remembered group's window (R6).
- **One tab per book file.** The project's short name (`Settings.xml` `<Name>`, `ParatextProject.name`) appears only on the toolbar and in the window title. The full name is in the toolbar's tooltip.
- **The Book selector** shows the book's tab, or opens the book as a new tab (`EnvironmentBar.open_book`).
- **Sync** moves the other splits of the same window whose shown file is in the same document group (`ReferenceSync._targets`). Across books, it opens the project's book as a new tab in that split (P5).
- **Splits:** Split Right / Split Down buttons on each split's control bar, with no limit. **Undock/Dock** work per tab, and `UNITIService.undock_views` already moves several tabs into one new window (Grouped Tabs uses it).
- **Hidden tabs:** Grouped Tabs (BF-082) hides tabs with `setTabVisible(False)`. Every tab still exists, so session capture, Find/Replace, splits and transfer keep working. Project tabs reuse this.
- **Read-only:** `UNITITextView.set_read_only` exists. Nothing sets it from a folder.
- **Unsaved changes** are asked about only on close (Save / Don't Save / Cancel).

## Changes

### T1 — USFM needs a project (answer 4)
- A file assigned to USFM (`.usfm`, `.sfm`) whose folder has no valid `Settings.xml` opens as Plain Text, pinned to the Plain Text environment, without R6's question.
  - The status bar says why: "GEN.usfm isn't in a Paratext project: opened as plain text".
  - The same applies to Open Folder by Type, Recent Files and a restored pin to USFM.
  - **Environment for This Document** doesn't offer USFM for such a file.
- **The gate is where a window gives a file its environment.** The USFM parser, views, validation and checks don't change, so the core tests are unaffected. UI tests that open a single `.usfm` file get a minimal `Settings.xml` fixture.
- Planning USFM outside a project is in the [wishlist](../FEATURE_WISHLIST.md#usfm-files-outside-a-project).
- **Tests:**
  - a file outside a project opens as plain text, with the message;
  - a project book still opens in USFM;
  - Environment for This Document doesn't offer USFM for a file outside a project.

**Implemented 2026-10-08.**
- **`catalog.PROJECT_ENVIRONMENTS = {"usfm"}`**, `environment_available(key, path)` and `environment_key_for_path(path, overrides)`: a file assigned to a project environment resolves to Plain Text unless `project_for_file` finds its project. `FileEnvironmentManager.resolve_path_key` wraps it.
- **Every place a window gives a file its environment uses it:**
  - `EnvironmentController.environment_key_for`, which also ignores a USFM pin on a file outside a project (a session saved before T1);
  - adopting and replacing a document;
  - `open_path`'s R6 question, which isn't asked for such a file, plus the status message;
  - Open Folder by Type, which asks only about the files that have an environment and reports the rest: "2 files aren't in a Paratext project: opened as plain text";
  - opening inside a USFM window, which opens such a file in an ordinary window instead of pinning it.
- **Environment for This Document** shows "USFM (needs a Paratext project)", disabled. `set_document_environment("usfm")` refuses with "notes.txt isn't in a Paratext project, so it can't be USFM".
- **Unchanged:** the USFM parser, views, validation and checks.
- **Docs:** the [USFM page](../../environments/usfm.md) says USFM assumes a project, and drops the single-file Book list, the single-file sync case and `uniti.sty` as the target for a file outside a project.

Tests:
- `tests/usfm_project_fixture.py`: `ensure_project` / `in_project` give the UI tests' USFM files a minimal `Settings.xml`;
- `tests/app/test_environment_window.py` +6: a file outside a project opens as plain text with the message; a USFM window opens one elsewhere; USFM isn't offered; a restored pin is ignored; Open Folder by Type; a project's file of any extension opens in USFM without a question;
- the single-file Book list test is now the project's Book list; the "unknown extension asks" test uses a Markdown window, since a USFM window no longer asks.

### T2 — Each environment has its own groups (item 1, answer 2)
- **Storage:** `<user data>/Environments/<Environment>/groups.json` (R8's per-environment folder), in the schema of `document-groups.json`. A missing file starts from A, B, C.
- **Migration (D3):** the existing `document-groups.json` becomes the Plain Text environment's groups, so nothing saved is lost. Every other environment starts from A, B, C. The old file stays where it is and is no longer written.
- **A group id now means a group of the file's environment.** `DocumentEntry.group_id` stays as it is, looked up in the groups of the file's environment. Choosing another environment for a file (Environment for This Document) clears its group.
- **Everywhere groups appear:**
  - tab swatches;
  - the Document Group menus and the toolbar dropdown;
  - Grouped Tabs slots, keyed by environment and group, since ordinary windows can mix environments;
  - Save Group / Open Saved Group;
  - Manage Groups…, with the environment chosen at the top (the current window's or file's environment by default).
- A group created or edited reaches every window of that environment at once (today's `_publish_groups`, per environment).
- **Tests:**
  - lists and defaults per environment;
  - the migration;
  - the same id in two environments is two groups;
  - Manage Groups… edits one environment's groups.

**Implemented 2026-10-08.**
- **`document_groups.EnvironmentGroups`**: one `DocumentGroupStore` per environment at `<settings folder>/Environments/<Environment>/groups.json`. It's cached, and shared by a service's windows (`UNITIService._environment_groups`). A missing file gives A, B, C; Plain Text's falls back to the old `document-groups.json` (D3), which is never written again.
- **The window:** `groups_for(key)`, `_set_groups(key, groups)`, `_group_by_id(group_id, key)` and `group_environment_key()` (an environment window's environment, else the current file's) replace `_groups` and `_group_store`.
- **Per environment:** the group menus, New Group…, Save / Close / Open Saved Group (which act only on files of that environment), the toolbar's Group dropdown, Recent Files' swatches (by the environment the path resolves to), recent projects' remembered group (USFM), and Grouped Tabs, whose slots are `(environment, group)` and are labelled "A · USFM" when a split mixes environments.
- **Manage Groups…** (`DocumentGroupEditor(…, environments=…, environment=…)`) has an environment chooser and returns every environment's groups. Removing a group clears it only from that environment's files.
- **Open Folder by Type** asks R6's question first, then offers the groups of the environment the files will be in.
- **Environment for This Document** clears the file's group when its environment changes.
- **Docs:** a [Groups](../../environments/README.md#groups) section and the user manual.

Tests:
- `tests/app/test_document_groups.py` +4: defaults per environment; Plain Text's migration; a file per environment and the same id as two groups; groups in memory without a folder;
- `tests/ui/test_document_group_editor.py` +1: editing each environment's groups;
- `tests/app/test_group_menus.py` +2: each file offers its own environment's groups; Manage Groups… starts at the file's environment;
- updated: service and environment-window tests now name the environment of the groups they use.

### T3 — Environment windows are lettered, not per group (items 1 and 7, answer 1)
- **Identity:** an environment window is (environment, letter): "USFM A", "USFM B", "USFM C" …
  - A new window takes the lowest free letter.
  - It's saved as `{environment, window}` in the same `extra` blob. An old `{environment, group}` record is read as a lettered window, in restore order.
- **Names (D4):** each environment has its own list of window names, A, B, C … by default.
  - **Rename Window…** (environment menu, and the toolbar's window label) renames the window; the new name is that environment's name for the window's slot from then on.
  - **Manage Groups…** also edits the environment's window names, next to its groups.
  - The names are stored with the environment's groups, in its folder.
- **Title:** "USFM A — NIV": the window's name and the current project's short name.
- **Opening into the environment:** "Open in USFM Environment" (R6), Open USFM Project…, Recent Projects, Recent Files and Move to Environment Window go:
  1. to the project's existing tab (T4);
  2. otherwise, to the environment's most recently active window;
  3. otherwise, to a new "USFM A".
- **Groups no longer move files between windows.**
  - The toolbar's Group dropdown (`18736cb`) sets the current project's group (T5). It no longer merges or closes windows.
  - Regrouping a file in an environment window no longer moves it (the move added in `3fad1fb` goes).
- **Plain Text environment windows** are lettered the same way ("Plain Text A"). Their files keep per-file groups.
- **Tests:**
  - letters are assigned and reused;
  - renaming a window, and the name surviving a restart;
  - old and new saved records restore;
  - opening goes to the project's tab, otherwise to the active window;
  - regrouping doesn't move a tab.

**Implemented 2026-10-08.** Recorded in [ADR-0019](../05_decisions/ADR-0019-named-environment-windows-groups-and-project-tabs.md).
- **Identity:** `UNITIMainWindow.environment_window` is `(environment key, slot)`. `UNITIService` gained `environment_window_for(key, slot)`, `environment_windows(key)` (most recent first), `free_environment_slot`, `new_environment_window` and `environment_window_target(key, path)`: the window showing the path's project, else the most recent. `move_to_environment_window(view_id, key, slot=None)` uses them.
- **Names:** `app/environment_window_names.py` (`EnvironmentWindowNames`, `default_window_name`: A … Z, AA …) stores renamed slots in `windows.json` per environment, shared by the service's windows. Names are validated (1–32 printable characters) and must differ from every other slot's, defaults included.
  - **Rename Window…** in the environment menu, and the toolbar's name (now a button) rename the window.
  - **Manage Groups…** has a "Window names" line per environment.
- **Titles:** "UNITI — USFM A — NIV — 01GEN.usfm". The toolbar's project label shows the short name, with the folder as its tooltip.
- **Groups don't move files:** `set_environment_window_group` is gone; `_document_group_changed` only refreshes the toolbar; a file opened inside an environment window keeps its group; the toolbar's Group dropdown sets the current file's group; a book chosen in the Book list takes the current book's group.
- **Opening:** `open_path` lost its `group_id`; R6's "Open in USFM Environment", Open USFM Project…, Recent Projects (which re-applies the remembered group to the book) and Move to Environment Window use `environment_window_target`.
- **Session:** `{environment, window: slot}`. An old `{environment, group}` record restores into the lowest free slot, as does a slot another window already has.
- **Removed:** the Book list's open-files fallback for files outside a project (unreachable since T1).

Tests:
- `tests/app/test_environment_window_names.py` (4): default letters, renaming per environment and its file, validation and uniqueness, a damaged file;
- `tests/app/test_environment_window.py`: windows named per environment, not per group (and a project's book going to its project's window); session identity, old and new; renaming and keeping a name; a closed window's slot reused; the Group dropdown setting only the current file's group; updated window, title and group expectations;
- `tests/app/test_session_orchestration.py` +1: a restored window keeps its slot;
- `tests/app/test_group_menus.py`: regrouping keeps a file in its window; Manage Groups… renames windows;
- `tests/ui/test_document_group_editor.py` +1: window names per environment.

### T4 — One tab per project (items 2–5, answers 3 and 5)
- **In a USFM window, each split shows one tab per project.**
  - Every open book of the project is still its own `UNITITextView` in that split.
  - Only the project's current book has a visible tab. The others are hidden with `setTabVisible(False)`, as Grouped Tabs does.
  - Undo history, caret, scroll, view mode and zoom stay with each book.
- **The tab's title is the project's short name** (`<Name>`), and nothing else.
  - The full name isn't shown anywhere (answer 5): not on the toolbar, in the title, in Recent Projects or in messages.
  - The book is on the toolbar's Book selector. The tab's tooltip gives the book and its path.
- **Changing the book changes the book in the tab.** The Book selector shows that book in the same tab:
  - its hidden tab, if the book is already open in this split;
  - otherwise the book opens hidden in this split, in the current mode, and becomes the tab's current book.
- **Unsaved changes (answer 3, D1).** When the current book has unsaved changes, changing the book asks "Save changes to GEN (NIV)?":
  - **Yes** saves, then changes the book.
  - **No** changes the book without saving. The book stays open in the tab with its changes and its undo history. The Book list marks it modified (•), and it's asked about again when the tab or window closes.
  - Nothing is ever saved without asking.
- **Opening a book** (Open, Recent Files, Open USFM Project…, Recent Projects, sync) goes into its project's tab in the target split, if there is one. Otherwise it starts a new project tab there.
- **Closing a project tab** closes all its books. Each modified one asks, as closing does today.
- **The same project in two splits or windows** is two project tabs, each with its own current book. Both can show the same book: two views of one document, as today.
- **Grouped Tabs** (BF-082) doesn't apply in USFM windows. It keeps working in ordinary windows.
- **Session:** hidden books are captured and restored as part of their project tab, and the shown one is the current book. Project membership comes from `project_for_file`, so there's no schema change.
- **Find/Replace:** the current document is the current book. "All open documents" includes the hidden books, as it does with Grouped Tabs.
- **Tests:**
  - two books of a project give one tab, titled with the short name;
  - changing the book reuses the tab, and each book keeps its undo history and caret;
  - the Yes/No question and both outcomes;
  - opening a book of a project that's already in the split;
  - closing asks once per modified book;
  - a session round trip;
  - the short name only, everywhere.

### T5 — Projects belong to groups, and groups bind projects across windows (items 1 and 6, answer 1)
- **A project has a group** in the USFM environment.
  - It's stored in `Environments/USFM/groups.json` next to the groups, by project folder. UNITI still writes nothing into a project folder.
  - Every book of the project takes that group. There's no per-book group in USFM.
- **Setting it:** the project tab's right-click menu (T6), the toolbar's Group dropdown and the text's right-click Group submenu all set the project's group.
- **The group's colour colours the project's tab**, in every window and split.
  - The tab is tinted with the colour, with its text contrast checked as for other group colours, and keeps the swatch.
- **Sync across windows:**
  - A caret move in a project tab moves every other shown project tab of the same group, in any split of any USFM window, mapped by versification as today.
  - A tab showing another book changes its book (T4). That's P5, but in the tab instead of a new tab.
  - Activation stays where it was.
- **Sync never asks about unsaved changes (D2).** It saves and discards nothing: a modified book stays open in its tab with its changes.
- **Ungrouped projects don't sync**, as today.
- **Tests:**
  - a project's group persists and colours every tab of the project;
  - sync across two windows;
  - a target tab changes book without asking, and keeps its edits;
  - an ungrouped project doesn't sync.

### T6 — The project tab's menu: splits and windows (item 7)
Right-clicking a tab in an environment window gives:
- **Group ▸**: No Group, each of the environment's groups with its swatch, New Group…, Manage Groups….
- **Split ▸**
  - **Move to New Split Right / Move to New Split Down**: makes a split and moves the tab, with all its books, into it. Disabled when the window has four splits.
  - **Move to Split 1 … 4**: each other split of the window, numbered in reading order.
  - **Unsplit**: the tab's split closes, and its tabs join the neighbouring split.
- **Window ▸**
  - **Move to New Window**: a new lettered window of the environment ("USFM D").
  - **Move to USFM A / USFM B / …**: each other window of the environment.
  - **Dock**: back to where it was undocked from, as today.

Also:
- In environment windows, the Split Right / Split Down buttons on a split's control bar respect the same limit of four. Ordinary windows don't change.
- Each split has its own project tabs. Projects in different splits can be in different groups.
- Moving a project tab moves all its books (`UNITIService.undock_views` / `_transfer_view`), and each book keeps its state. Moving it into a split or window that already has a tab of that project merges the books into that tab.
- **Tests:**
  - the menu's entries;
  - the four-split limit;
  - Unsplit merges into the neighbour;
  - moving to a new window and to another window;
  - Dock back;
  - merging into an existing project tab.

### T7 — Read-only folders (answer 3: "consider"; D5)
- **A list of read-only folders:** View > Read-Only Folders… adds and removes them. The project tab's menu gets **Read Only** for its project's folder.
- **A file in a read-only folder, or below one, opens read-only:**
  - no typing, no Replace, and no semantic edits in Standard;
  - Save is disabled; Save As… to somewhere else still works;
  - a lock on its tab and "(read-only)" in the title;
  - Configuration Files… and Add Definitions don't create or edit files there, and offer your own `uniti.sty` instead.
- **What it's for:** the Paratext projects that Paratext itself owns and synchronizes (Send/Receive), so UNITI can't change them by accident.
- It's stored in `settings.json`. Nothing is written into the folder.
- **Tests:**
  - a file opens read-only;
  - every edit path is blocked;
  - Save is blocked;
  - turning it on for a project that's open.

## Spellcheck from `hyphenatedWords.txt` (item 8) — plan only, not queued

Also in the [wishlist](../FEATURE_WISHLIST.md#spellcheck-from-paratext-word-lists).

**What Paratext keeps.** Read, read-only, in `usNIVv3` and `ruCARSv3`:
- **`hyphenatedWords.txt`**: UTF-8 with a BOM and CRLF line ends.
  - A `#Hyphenated Word List v2.0` header and comment lines.
  - Settings lines: `HardHyphen = "-"`, `SoftHyphen = "="`, `SoftHyphenOut = "­"`, `HyphenatedMarkers = "cd iex im … p p1 …"`.
  - Then one word per line, with `=` at its soft-hyphen points, and `*` in front of a line the user has fixed: `*a =ro=se`.
  - `usNIVv3` has 15,351 lines, 102 of them starred. `ruCARSv3` has 55,363 lines, almost all starred.
- **`SpellingStatus.xml`**: Paratext's own spelling decisions.
  - `<Status Word="…" State="R"/>` means correct and `State="W"` means wrong, sometimes with `<SpecificCase>` forms.
  - `usNIVv3` has 15,520 R and 2 W. `ruCARSv3` has 50,638 R and 71 W.

**Proposed:**
- **Toggle:** **Check Spelling** in the USFM menu, per project tab, off by default.
- **Word list:** the project's `hyphenatedWords.txt`, with `=` removed and `*` ignored.
  - It's read when the project opens, and again when the file changes (R8's reload on save).
  - Words are compared after Unicode normalization (NFC), ignoring case, since Paratext's lists are lowercase.
- **What's checked:** words in the text: verse text, headings and note text. Not markers, attributes, or `\id`/`\rem` lines.
  - Word boundaries follow Unicode: letters and marks, with an apostrophe or hyphen inside a word.
  - The file's `HardHyphen` splits compounds.
- **How it shows:** a wavy underline in Plain Text, Standard and Preview.
- **Not in a first step:** suggestions, and adding a word. Adding one would write into the project folder, and ADR-0018 says UNITI doesn't.
- **Speed:** check visible text first and the rest incrementally, so a 220 KB book still switches mode in about a second.

**Open questions:**
- Should `SpellingStatus.xml` be used, instead of or as well as `hyphenatedWords.txt`? It's Paratext's actual record of approved (R) and rejected (W) words. `hyphenatedWords.txt` lists words for hyphenation, so a correct word can be missing from it, and the W words are explicitly wrong.
- Is the toggle per tab, per project or for everything?
- Adding a word: never, or into a UNITI-side list in `Environments/USFM/`?

## Decisions

Decided 2026-10-08 ("all good"):
- **D1 (T4):** **No** on the book-change question keeps the unsaved changes in memory. The book stays open, hidden in the tab, marked modified, and is asked about again when it closes.
- **D2 (T5):** a book change made by sync doesn't ask. It saves and discards nothing.
- **D3 (T2):** the existing groups become Plain Text's groups. Every other environment starts from A, B, C.
- **D4 (T3):** windows are lettered "USFM A, B, C" by default, and the user can rename them per environment, as groups are named per environment ("#4 can be re-configured by user per env and groups").
- **D5 (T7):** read-only folders are in this round, last.

## Order

T1 → T2 → T3 → T4 → T5 → T6 → T7.
- T1 comes first: project tabs (T4) assume every USFM file belongs to a project.
- T2 before T3: windows stop standing for groups only once groups are per environment.
- T3 before T4: a project tab lives in a lettered window.
- T5 needs T4's tabs to colour and sync. T6 needs T4's tabs to move.
- T7 is independent and goes last, if D5 keeps it in this round.

Documentation, as each phase lands: ADR-0019 (at T3), the [Environments](../../environments/README.md) overview and [USFM](../../environments/usfm.md) pages, the user manual, [Current Status](../01_current/STATUS.md) and the [roadmap](ROADMAP.md)'s environment track queue.
