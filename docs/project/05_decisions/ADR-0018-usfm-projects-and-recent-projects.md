# ADR-0018: USFM Projects — Open USFM Project… and Recent Projects

Date: 2026-10-07
Status: accepted (implemented: [plan](../02_plans/2026-10-07-usfm-projects-and-versification-plan.md) phases P1–P2)

## Context

USFM work happens in Paratext projects: a folder of book files with a `Settings.xml`. The user asked for "open folder" for projects alongside "open file" for single files, and decided on 2026-10-07:
- a project is a folder with a Paratext `Settings.xml`, and nothing else;
- UNITI remembers projects across restarts.

That re-enters the parked ["Project and workspace concepts"](../04_parked/CATALOG.md#project-and-workspace-concepts) capability. [ADR-0009](ADR-0009-bounded-open-folder-by-type.md) un-parked only a one-shot batch open that retains no folder state.

## Decision

Un-park a second narrow slice: **Paratext USFM projects, read-only, remembered by folder.**

1. **A project is a folder with a valid Paratext `Settings.xml`** (`sfm/paratext_project.py`). UNITI reads only a few fields: name, file naming, encoding, versification, stylesheet and books present. A file directly inside a project folder is that project's book, however it was opened.
2. **File → Open USFM Project…** picks a folder and refuses one without a valid `Settings.xml`.
   - It opens one book, never the whole project: the book the project was left at, otherwise its first.
   - The book opens in the USFM environment window of the project's document group. That's the remembered group, otherwise the active USFM window's group, otherwise Ungrouped.
   - A project's books are USFM whatever their extension, so `.SFM` books open pinned to USFM without the "Open as USFM?" question.
3. **File → Recent Projects** (`recent-projects.json` next to `recent-files.json`, at most 20 entries) is the only project state UNITI keeps.
   - Per project it stores the folder, the name, and where the project was left: the book, chapter:verse and group.
   - The position is saved 1.5 s after the caret settles, and only for projects already in the list. Opening a project book as a plain file adds its project to the list.
   - A folder that has gone is shown as unavailable, not dropped silently.
4. **Still parked:**
   - writing anything into a project folder (no manifest, no settings edits);
   - watching folders, or recursing into them;
   - opening a project whole;
   - project-wide commands beyond the existing Find/Replace scopes;
   - any project concept for other environments.

## Consequences

- A project is "which text"; a document group is still "which splits move together" ([ADR-0017](ADR-0017-environment-windows-in-place-views-reference-sync.md) decision 4). Comparing two projects means putting both in one group.
- The rest of the plan builds on this:
  - P3: the project's stylesheet and encoding, and a Book selector that lists the project's books;
  - P4: versification;
  - P5: sync that opens a project's missing book.

## Affected records

- [Parked Capability Catalog](../04_parked/CATALOG.md): the "Project and workspace concepts" entry gains this second narrow exception.
- [ADR-0009](ADR-0009-bounded-open-folder-by-type.md): unchanged; Open Folder by Type still retains nothing.

Update 2026-10-08 ([field test round 2](../02_plans/2026-10-08-usfm-field-test-round-2-plan.md) R8): **Configuration Files…** can create a project's `custom.sty` or `uniti.sty` from a template, and open project files to edit. Those are writes you ask for, like saving any file you opened. UNITI still never writes into a project folder by itself.
