# USFM Projects, Single Files, and Versification — Plan

Date: 2026-10-07
Status: **In progress**. P1 is implemented (2026-10-07); P2–P5 are next.
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

### P3: Project-aware USFM environment

- **Stylesheet:** in a project, the `Settings.xml` `<StyleSheet>` replaces the fixed `usfm.sty` candidate. The order becomes the named stylesheet, then `custom.sty`, then PTXprint mods, then `uniti.sty`.
- **Encoding:** `<Encoding>` sets how book files open (65001 → UTF-8, 1252 → Windows-1252, …). A book whose content disagrees triggers the existing reinterpretation prompt.
- **Book selector:**
  - In a project: `books()`, labelled with the code and the project's book name where available.
  - For single files: the open files of the window's group. This replaces today's folder scan, so an unrelated folder never lists stray USFM.
- **Window title and toolbar** show the project's short name, e.g. "USFM — A — NIV".

### P4: Versification (core + UI)

- **New `sfm/versification.py`**, wrapping `usfmtc.versification.Versification`:
  - It always has the built-in English and Original (shipped with `usfmtc`).
  - Septuagint, Vulgate and the Russian versifications come from `<UNITI user data>/Versification/` (`lxx.vrs`, `vul.vrs`, `rso.vrs`, `rsc.vrs`, copied from a Paratext installation by the user). UNITI doesn't bundle them.
  - A project's `custom.vrs` is read on top of its base.
  - When a needed file is missing, UNITI falls back to English and says so in the status bar.
- **`map_reference(ref, source_versification, target_versification)`** works through Original. It's tested against known pairs (Ps 51:1 ↔ 51:3, Mal 4:1 ↔ 3:19, Joel 2:28 ↔ 3:1) and the identity case. If `usfmtc`'s `remap` misbehaves on those, UNITI maps through its `toorg`/`fromorg` tables directly.
- **Single-file override:** an Environment menu **Versification** picker (an exclusive submenu), saved in `DocumentRecord.extra["versification"]` with no schema change.

### P5: Sync across books and versifications

`ReferenceSync` (ADR-0017 decision 4) gains three things:
- versification mapping per target;
- for a project target in another book: open the project's book file in that split, then sync. This opens at most one file per split per sync and never steals focus;
- for a single-file target in another book: no move, and a "BOOK isn't in this file" notice.

Choosing a book in one split's Book selector moves every split of the group to that book: project texts open it, single files stay.

## Verification plan

- **Core:** `Settings.xml` parsing and naming, `books()`, `project_for_file`, versification mapping pairs, and the custom `.vrs` layer.
- **UI/service:** Open USFM Project and refusal without `Settings.xml`; Recent Projects persistence and an unavailable folder; Book selector contents (project vs. single file); project sync opening a missing book in the other split; single-file "not in this file"; the versification picker saved and restored.
- **Hand check:** a real Paratext project folder plus a reference text side by side.

## Risks and limits

- `Settings.xml` varies between Paratext 7, 8 and 9. Read only the fields above and ignore the rest.
- `BooksPresent` and the naming forms need checking against real projects.
- Only English and Original versification ship with UNITI. The others depend on files the user supplies.
- A project is never opened whole. The Book selector reads `Settings.xml` plus at most about 120 file-existence checks.
