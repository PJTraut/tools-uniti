# ADR-0019: Named Environment Windows, Groups per Environment, Project Tabs

Date: 2026-10-08
Status: accepted (implemented: [round 3 plan](../03_implemented/milestones/2026-10-08-usfm-field-test-round-3-plan.md) T1–T7)

## Context

USFM field-test feedback, round 3 (2026-10-08, `@externalresources/field_test_feedback`):
- "environmental windows shares groups; groups are per environment, and each environment has its own set of groups."
- A USFM tab is the project: titled with its short name; changing the book changes it in the tab; projects are assigned to groups, whose colour colours the tab.
- A tab's right-click menu splits (up to four panels) and moves it between windows: "name environmental windows: e.g. USFM A; USFM B; USFM C; etc."

The user's answers, the same day:
- Groups "bind" projects across the windows of an environment. A window no longer stands for a group.
- Each environment has its own groups, starting from A, B, C.
- USFM assumes a Paratext project. A file outside one is plain text for now.
- Only the project's short name is shown, everywhere.
- D1–D5 (the plan's decisions) as recommended. Window names can be reconfigured by the user per environment, as groups are.

## Decision

1. **USFM needs a project** (T1). An environment can require a project (`catalog.PROJECT_ENVIRONMENTS`, today `{"usfm"}`). A file assigned to it whose folder has no valid `Settings.xml` resolves to Plain Text wherever a window gives a file its environment, and USFM isn't offered for it.
2. **Each environment has its own groups** (T2). They're stored as `groups.json` in the environment's user configuration folder (`EnvironmentGroups`). Plain Text keeps the groups saved before this decision; the others start from A, B, C. A file's group id is read in its environment, and choosing another environment for a file clears its group.
3. **Environment windows are named per environment, not per group** (T3). This supersedes [ADR-0017](ADR-0017-environment-windows-in-place-views-reference-sync.md) decision 2's "one per environment and document group".
   - A window is (environment, slot). Slot 0 is "USFM A", slot 1 "USFM B" …; a new window takes the lowest free slot.
   - The user can rename a slot (**Rename Window…**, the toolbar's name, or **Manage Groups…**). Names are stored as `windows.json` next to the environment's groups.
   - A file opened into an environment goes to the window that already shows its project, else the environment's most recent window, else a new one.
   - Groups no longer move files between windows. The toolbar's Group dropdown is the current file's group (the project's from T5).
   - The identity rides in `ViewRecord.extra["environment_window"]` as `{environment, window}`. A record saved by group restores into the lowest free slot.
4. **One tab per project** (T4). In a USFM window each split shows one tab per Paratext project, titled with its short name only. Every open book stays its own view and tab, so its state is kept; the others are hidden. Changing the book shows it in the same tab, asking before leaving unsaved changes: Yes saves, No keeps them in memory (D1). Closing the tab closes its books. The same project in two windows is two tabs, and both can show the same book: a book already open in another window of the environment opens here as a second view (enforced 2026-10-13, after the spec check). This narrows ADR-0017 decision 2's "if it's already open elsewhere, it moves in" to files coming from an ordinary window.
5. **A group belongs to a project, and binds projects across windows** (T5). In a project environment a book's group is its project's, stored as `projects.json` per environment (never in the project). The project tab is tinted with the group's colour. Reference sync covers the shown texts of a group in every window, changing a project tab's book when needed, without asking about unsaved changes (D2). This supersedes ADR-0017 decision 4's "within one window".
6. **The tab's menu splits and moves whole tabs** (T6). In an environment window a tab's right-click menu has Group, Split (new split right/down, another split, Unsplit) and Window (new window, another window of the environment, Dock). A USFM tab moves with all its books; moved between windows, they share one dock home. An environment window has at most four splits.
7. **Read-only folders** (T7). The user's list of folders (in settings) whose files open read-only: the `Document` refuses edits, undo/redo and saving in place, while recovery replay and Save As stay allowed. UNITI writes nothing into those folders.

## Consequences

- No settings or session schema change. Groups and window names are new files in the per-environment folders; the window identity is a new value in an existing `extra` blob.
- ADR-0017 decision 3's Book list for files outside a project is gone (decision 1).
- ADR-0017 decision 4 (sync within one window, by document group) now works across windows, by project group (decision 5).
- [ADR-0018](ADR-0018-usfm-projects-and-recent-projects.md)'s consequence "a document group is still which splits move together" stands; Open USFM Project… now opens into the project's window, else the most recent USFM window, and gives the book its remembered group.

## Affected records

- [ADR-0017](ADR-0017-environment-windows-in-place-views-reference-sync.md) decision 2 is superseded where noted (including its "moves in" for a book open in another window of the environment, decision 4); decision 3's single-file Book list is removed.
- [ADR-0018](ADR-0018-usfm-projects-and-recent-projects.md) decision 2's "the USFM environment window of the project's document group" becomes decision 3's window choice.
