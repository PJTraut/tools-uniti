# ADR-0009: Un-park a Bounded "Open Folder by Type" Capability

Date: 2026-09-15
Status: accepted

## Context

[BF-029](../BETA_FEEDBACK.md#bf-029--open-all-files-of-a-type-in-a-folder-grouped) asked to open every file of a chosen type in a folder as separate documents, assigned to one document group. That request squarely overlaps the parked ["Project and workspace concepts"](../04_parked/CATALOG.md#project-and-workspace-concepts) capability, whose stated re-evaluation trigger is "sustained workflows that cannot be served safely by opening independent files and tabs." [BF-044](../BETA_FEEDBACK.md#bf-044-p6--document-groups-vs-the-parked-projectworkspace-boundary) escalated this as a decision dependency rather than implementation work, and BF-029 itself recorded a concrete, non-hypothetical motivating workflow: a "bible project" of SFM text for 66 books plus a handful of meta files, no more than ~80 files total, opened together as one document group.

## Decision

Un-park a narrow, bounded slice of this request: a one-shot command that lets the user pick a folder, pick one file type present in that folder (by extension, non-recursive, top-level files only), open every matching file as an independent document exactly as `File → Open…` would, and optionally assign all of them to one document group (existing or newly named) in the same action.

This explicitly does **not** un-park the general project/workspace concept. The following remain parked and out of scope for this decision:

- Any persistent "project" file, manifest, or on-disk representation of "this folder is a project."
- Recursive folder traversal or nested-directory discovery.
- File-system watching of the folder for added/removed/changed files after the one-shot open.
- Any session/restore behavior tied to "the folder" as a first-class object — restoring the resulting documents on relaunch uses the existing per-document session mechanism, identical to any other individually-opened file.
- Any workspace-level command surface (build, search-across-project, project-wide replace beyond the existing "current group" and "all open documents" Find/Replace scopes).

The folder picker is used exactly once, as a convenience for selecting a batch of files to open; UNITI does not retain the folder path as project state afterward.

## Consequences

`File → Open Folder by Type…` becomes a new command. It reuses the existing per-file open pipeline (`UNITIMainWindow.open_path`) unchanged, so every existing open-time behavior (encoding detection, mixed-EOL prompts, duplicate-open focus-instead-of-reopen) applies identically to each file in the batch. It reuses the existing document-group model (BF-016) for the optional group assignment; a newly named group is created through the same `DocumentGroup`/`DocumentGroupStore` validation already used by the group editor, not a separate code path.

Because [BF-030](../BETA_FEEDBACK.md#bf-030--no-benchmark-coverage-for-many-concurrently-open-documents) and [BF-040](../BETA_FEEDBACK.md#bf-040-p2--per-document-task-pool-fairness-and-multi-document-benchmark-foundation) record that concurrent-document behavior at meaningful scale is not yet benchmarked, this command warns (but does not block) before opening an unusually large batch, and does not add benchmark coverage itself — that remains BF-030/BF-040's own work.

## Affected records

- [BF-029](../BETA_FEEDBACK.md#bf-029--open-all-files-of-a-type-in-a-folder-grouped) and [BF-044](../BETA_FEEDBACK.md#bf-044-p6--document-groups-vs-the-parked-projectworkspace-boundary), updated to reflect this decision and its implementation.
- [Parked Capability Catalog](../04_parked/CATALOG.md) — the "Project and workspace concepts" entry is annotated with this narrow exception; the entry itself remains otherwise parked.
- [Current Scope](../01_current/SCOPE.md).
