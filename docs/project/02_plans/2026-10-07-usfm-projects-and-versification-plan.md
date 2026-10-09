# USFM Projects, Single Files, and Versification — Plan

Date: 2026-10-07
Status: **Implemented**: P1–P3 on 2026-10-07, P4–P5 on 2026-10-08. Hand checks with a real Paratext project are still open (see Verification plan).
Builds on: [ADR-0017](../05_decisions/ADR-0017-environment-windows-in-place-views-reference-sync.md): environment windows, the Book/Chapter/Verse selector, and reference sync within a group.
Origin: user, 2026-10-07: "single file vs 'working folder' for USFM; plan this... should we need to 'open folder' for 'project' view and 'open file' for single files outside of projects? how would we compare BK:CH:VS for 'files' only".

## Decisions (user, 2026-10-07)

| Question | Decision |
|---|---|
| What counts as a project? | A folder with a Paratext `Settings.xml`. Nothing else. |
| Remember projects across restarts? | Yes: a Recent Projects list. |
| Versification for single files | English by default. Other versifications come from `.vrs` files in a user folder. |
| A synced split lacks the book being synced to | Open that book's file, one file at a time. |

## Model

- **Project = which text.** A Paratext folder: name, book file naming, stylesheet, encoding, versification.
- **File = a project of one book.** A file with no `Settings.xml` next to it. Its book comes from its `\id`.
- **Group = which splits move together.** This is Paratext's scroll-group idea, and the document groups A/B/C already work this way: sync stays within one group (ADR-0017 decision 4).
  - Comparing two translations means putting both texts in the same group, side by side.
  - A project is not a group. Making it one would force sync across groups, which was ruled out.
- **A file inside a project folder is a project file.** Opening `41MATNIV.SFM` with **Open File** recognizes the NIV project from the `Settings.xml` beside it, so both ways in lead to the same thing. Only files with no `Settings.xml` next to them are "single files outside projects".

## Comparing BK:CH:VS

- **The reference key is the same everywhere:** the book from `\id`, plus the chapter and verse from `\c`/`\v` (`sfm/references.py`, already built). Verse bridges (`10-12`) and part-verses (`11a`) already match. Single files in one group compare today.
- **New: versification.** A reference is mapped from the source text's versification through Original into the target's. For example, English Ps 51:1 is Original 51:3, Mal 4:1 is 3:19, and Joel 2:28 is 3:1.
  - A project takes its versification from `Settings.xml` `<Versification>`: 1 Original, 2 Septuagint, 3 Vulgate, 4 English, 5 Russian Protestant, 6 Russian Orthodox. A `custom.vrs` in the project folder layers on top.
  - A single file uses English unless overridden.
- **New: across books.**
  - A project split showing another book opens that project's book file and then syncs.
  - A single-file split only follows references in its own book. Otherwise it stays put and shows "GEN isn't in this file".

## Phases

### P1: Paratext project model (core, Qt-free)

New `sfm/paratext_project.py`, with `ParatextProject.load(folder) -> ParatextProject | None`:
- It reads `Settings.xml`: `<ScriptureText>`, with `Name`, `FullName`, `LanguageIsoCode`, `Encoding`, `Versification`, `StyleSheet`, `Naming PrePart/PostPart/BookNameForm`, and `BooksPresent`.
- It caps the file at 1 MiB, never raises, and uses the stdlib parser, which doesn't fetch external entities.
- It returns `None` for any folder whose `Settings.xml` is missing or invalid.

It provides:
- `book_path(code)`, built from the naming pattern and the Paratext book numbers (MAT = 41, …, FRT = A0, …);
- `books()`: the books that are both present and whose files exist, in canonical order;
- `project_for_file(path)`: the project whose folder holds `path`, if any.

Tests: fixture projects, including PrePart/PostPart variants, `41MAT` vs. `MAT` forms, a missing book file, and a broken `Settings.xml`.

**Implemented 2026-10-07** in `sfm/paratext_project.py`:
- `ParatextProject.load`, with `books()`, `book_for()`, `book_path()`, `book_names()` (from `BookNames.xml`) and `owns()`;
- `BookNaming`, `book_file_number`, `PARATEXT_BOOKS`, `VERSIFICATIONS` (default English);
- `project_for_file`, cached until `Settings.xml` changes.

Both naming styles are read: Paratext 8+ `<Naming>` and the older `FileName*` elements. A book whose file doesn't follow the naming pattern is found by its `\id` among files with the pattern's prefix and suffix (at most 400 files read).

Tests: `tests/test_paratext_project.py` (11).

### P2: Open USFM Project… and Recent Projects (UI)

- **File → Open USFM Project…** shows a folder picker and refuses a folder without a valid `Settings.xml`. It opens one book, the last used or else the first present, in that project's USFM environment window. The other books open on demand from the Book selector.
- **File → Recent Projects**: a new `RecentProjectsStore`, JSON next to `recent-files.json`. Per project it keeps the folder, name, last book, last reference and last group. It's bounded to 20 entries, and missing folders show as unavailable rather than vanishing.
- **Group on first open:** the active USFM window's group, otherwise Ungrouped. After that, the remembered group is used.
- **ADR-0018** narrowly un-parks "project/workspace concepts", the way ADR-0009 did for Open Folder by Type:
  - UNITI stores only the Recent Projects list and per-project last position.
  - Project folders are read-only to it: nothing is written into them, there's no watching and no recursion.
  - There's no project manifest, and no project-wide commands beyond the existing Find/Replace scopes.

**Implemented 2026-10-07** ([ADR-0018](../05_decisions/ADR-0018-usfm-projects-and-recent-projects.md)):
- `app/recent_projects.py` (`RecentProjectsStore`, `SettingsStore.recent_projects`);
- `ui/usfm_projects.py` (`UsfmProjectController`);
- the registered `file.open_usfm_project` command, with no default shortcut.

A project's books open pinned to USFM without the "Open as USFM?" prompt. Opening a project book as a plain file records its project. The position is saved 1.5 s after the caret settles.

Tests: `tests/app/test_usfm_projects.py` (8).

### P3: Project-aware USFM environment

- **Stylesheet:** in a project, the `Settings.xml` `<StyleSheet>` replaces the fixed `usfm.sty` candidate. The order becomes the named stylesheet, then `custom.sty`, then PTXprint mods, then `uniti.sty`.
- **Encoding:** `<Encoding>` sets how book files open (65001 → UTF-8, 1252 → Windows-1252, …). A book whose content disagrees triggers the existing reinterpretation prompt.
- **Book selector:**
  - In a project: `books()`, labelled with the code and the project's book name where available.
  - For single files: the open files of the window's group. This replaces today's folder scan, so an unrelated folder never lists stray USFM.
- **Window title and toolbar** show the project's short name, e.g. "USFM — A — NIV".

**Implemented 2026-10-07**:
- `style_layers.project_stylesheet_candidates`. A named stylesheet containing a path separator is ignored.
- `paratext_project.project_encoding_profile`. The project's declared encoding, with the file's own BOM, is used only when the start of the file decodes cleanly in it. Otherwise ordinary detection, with its prompt, decides.
- The Book selector (`EnvironmentBar._book_entries`) lists the project's books, labelled "GEN — Genesis", or else the group's open files. It re-reads the list each time it opens.
- The project name appears in the toolbar and the window title. Both follow environment changes.

Tests: +3 in `tests/test_paratext_project.py`, +1 in `tests/app/test_usfm_projects.py`; `tests/app/test_environment_window.py` now covers the single-file and project Book lists.

### P4: Versification (core + UI)

- **New `sfm/versification.py`**, wrapping `usfmtc.versification.Versification`:
  - It always has the built-in English and Original (shipped with `usfmtc`).
  - Septuagint, Vulgate and the Russian versifications come from the USFM user configuration folder, `<UNITI user data>/Environments/USFM/Versification/` (`lxx.vrs`, `vul.vrs`, `rso.vrs`, `rsc.vrs`, copied from a Paratext installation by the user). The folder is set up by round-2 R8 and listed in Configuration Files…. UNITI doesn't bundle them.
  - A project's `custom.vrs` is read on top of its base.
  - When a needed file is missing, UNITI falls back to English and says so in the status bar.
- **`map_reference(ref, source_versification, target_versification)`** works through Original. It's tested against known pairs (Ps 51:1 ↔ 51:3, Mal 4:1 ↔ 3:19, Joel 2:28 ↔ 3:1) and the identity case. If `usfmtc`'s `remap` misbehaves on those, UNITI maps through its `toorg`/`fromorg` tables directly.
- **Single-file override:** an Environment menu **Versification** picker (an exclusive submenu), saved in `DocumentRecord.extra["versification"]` with no schema change.

**Implemented 2026-10-08.**
- **`sfm/versification.py`:**
  - `load_versification(stem, custom)` uses your folder first, then the built-in `eng`/`org` files, and falls back to English when a file is missing.
  - `versification_for(path, override)`: the text's own choice, else its project's, else English.
  - `map_reference(book, chapter, verse, source, target)` goes through Original using `usfmtc`'s tables. It's checked against Ps 51:1 ↔ 51:3, Mal 4:1 ↔ 3:19, Joel 2:28 ↔ 3:1 and the identity case, with bridges and parts mapped by their first verse.
  - A project's `custom.vrs` is overlaid the way Paratext does: its mappings replace the base's for the verses it names. `usfmtc`'s `readFile` would merge them into ranges.
- **Per-file choice:** `DocumentEntry.versification`, saved in `DocumentRecord.extra["versification"]` and restored with the pin.
- **The USFM menu's Versification picker:** "Project (…)" or "Default (English)", each available versification (a missing file says so), and Your Versification Files…, which opens Configuration Files at the versification folder.

Tests: `tests/test_sfm_versification.py` (9) and `tests/app/test_environment_window.py` +1 (the picker, and saving and restoring the choice).

**Checked against real projects, 2026-10-08:** `usNIVv3` (English + `Custom.vrs`) against `ruCARSv3` (Russian Protestant + `custom.vrs`), in `/Volumes/Win11Arm64/Paratext Projects`, at the user's request. It found and fixed three problems:
- **`.vrs` lookup:** Paratext keeps `rsc.vrs` and the others in its projects folder, so `versification_path` now looks there for a project book, after your folder.
- **Case:** NIV's `Custom.vrs` wasn't found on the case-sensitive volume. `paratext_project.find_file` now matches without regard to case.
- **Romans:** ruCARS's `custom.vrs` keeps the Russian "ROM 14:24-26 = ROM 16:25-27" while giving ROM 14 only 23 verses. `map_reference` now ignores a mapping onto a verse the target's own counts say doesn't exist, and sync falls back to the same reference when the text lacks the mapped verse.

Results (NIV → ruCARS, the verse text compared):

| NIV | ruCARS |
|---|---|
| Ps 3:1 | 3:2 |
| Ps 23:1 | 22:1 |
| Ps 51:1 | 50:3 |
| Ps 51:19 | 50:21 |
| Ps 90:1 | 89:2 |
| Ps 119:176 | 118:176 |
| Ps 150:6 | 150:6 |
| Joel 2:28 | 2:28 |
| Mal 4:1 | 4:1 |
| Rom 14:23 | 14:23 |
| Rom 16:25 | 16:25 |
| Num 16:36 | 16:36 |

Side-by-side sync in an offscreen window moved and highlighted ruCARS correctly for each Psalm reference. Book-file naming resolved every present book in both projects (68 and 74 books).

### P5: Sync across books and versifications

`ReferenceSync` (ADR-0017 decision 4) gains three things:
- versification mapping per target;
- for a project target in another book: open the project's book file in that split, then sync. This opens at most one file per split per sync and never steals focus;
- for a single-file target in another book: no move, and a "BOOK isn't in this file" notice.

Choosing a book in one split's Book selector moves every split of the group to that book: project texts open it, single files stay.

**Implemented 2026-10-08.**
- **`ReferenceSync.sync_from`:**
  - maps the reference from the source's versification into each target's (`map_reference`);
  - lands on the verse when found;
  - follows the chapter or book start when the caret is in a heading.
- **`_targets`:** per other split of the group,
  - its shown tab with the book;
  - otherwise another tab of that split with the book (then shown);
  - otherwise, for a Paratext project text, the project's file of the book. `_open_in_split` opens it in that split, in the split's view mode and the group, without the undefined-markup popup (`_quiet_open`) or the open dialog, and hands activation back to the source.
  - A single file without the book stays, and the status bar says "GEN isn't in 02EXO.usfm".
- **The Book selector** syncs after opening a book, so every split of the group follows to it.

Tests: `tests/app/test_environment_window.py` +4:
- versification-mapped sync (English Ps 51:1 → Original 51:3);
- a project split opening its own book quietly, keeping its mode;
- a single file staying with a notice;
- the Book selector carrying a project split from GEN to EXO.

**Found in the field test, 2026-10-09** (`ruCARSv3` against `usNIVv2`; the 2026-10-08 check above only went NIV → ruCARS): ruCARS Ps 11:1 synced to NIV Ps 11:1, a psalm off. Russian numbers a psalm's title as verse 1 (sometimes 1–2), English as verse 0 (`eng.vrs`: "PSA 12:0-8 = PSA 12:1-9"), so the mapping gave NIV 12:0. `map_reference` took verse 0 for a verse that doesn't exist and kept the same numbers, and sync, finding no `\v 0`, did the same. A sweep of both projects found 67 ruCARS Psalm verses affected: 59 landed in the wrong psalm (every numbered title from Ps 11 to 139), 8 on verse 1 instead of the title (Ps 3–9, 89). A caret in a heading also followed the chapter number unmapped, so every Psalm heading from 10 to 147 went a psalm off, both ways.
- **`map_reference`:** every chapter has a verse 0, its title.
- **`ReferenceMap.heading_range`:** a chapter's heading, from `\c` to its first verse.
- **`ReferenceSync._landing`:**
  - a verse mapped to verse 0 lands on the target's heading and highlights it;
  - a caret in a heading is that chapter's verse 0: it lands on the target's heading, or on the verse the target numbers the title as (NIV Ps 12's title → ruCARS 11:1, both highlighted). That holds only while it agrees with where verse 1 lands; otherwise it lands where verse 1 does (NIV Ps 10 → ruCARS 9:22), so a `.vrs` without title mappings can't put a heading a psalm off.
- **Unchanged:** the same-reference fallback (Mal 4:1, Rom 16:25–27).

After the fix, a sweep of both projects (31,167 NIV and 31,130 ruCARS verses, every chapter heading) puts each Psalm title and heading in its own psalm, including ruCARS Ps 147's heading on NIV 147:12. Tests: `tests/test_sfm_versification.py` +7 (Russian titles both ways, a two-verse title), `tests/test_sfm_references.py` +1, `tests/app/test_environment_window.py` +2 (a title syncing to the English title; English headings syncing to the Russian title verse, Russian Ps 10's heading, and 9:22).

## Verification plan

- **Core:** `Settings.xml` parsing and naming, `books()`, `project_for_file`, versification mapping pairs, and the custom `.vrs` layer.
- **UI/service:** Open USFM Project and refusal without `Settings.xml`; Recent Projects persistence and an unavailable folder; Book selector contents (project vs. single file); project sync opening a missing book in the other split; single-file "not in this file"; the versification picker saved and restored.
- **Hand check:** a real Paratext project folder plus a reference text side by side.

## Risks and limits

- `Settings.xml` varies between Paratext 7, 8 and 9. Read only the fields above and ignore the rest.
- `BooksPresent` and the naming forms need checking against real projects.
- Only English and Original versification ship with UNITI. The others depend on files the user supplies.
- A project is never opened whole. The Book selector reads `Settings.xml` plus at most about 120 file-existence checks.
