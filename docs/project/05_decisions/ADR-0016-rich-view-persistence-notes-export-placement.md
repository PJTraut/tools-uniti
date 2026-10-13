# ADR-0016: Per-Tab Rich Views, Notes and Tables, `.sty` Export, Marker Placement, Group Detach

Date: 2026-10-03
Status: accepted (implemented — see the [implementation record](../03_implemented/milestones/2026-10-02-rich-views-and-grouped-tabs-plan.md#follow-up-2026-10-03-adr-0016))

## Context

ADR-0015 listed what it left undone: remembering a rich view across sessions, notes and tables in Formatted View, `.sty` export/migration, `OccursUnder`-driven validation, and (from BF-082) detaching a whole group from the grouped tab bar. The user asked to continue development.

## Decision

1. **The rich-view choice belongs to the tab.** `UNITITextView.rich_view_key` is saved in `ViewRecord.extra["rich_view"]`.
   - Switching tabs shows the new tab's own rich view, or hides the pane.
   - Choosing **Source Only**, or the pane's ×, clears the choice.
   - Plain Text Mode, or an environment that no longer offers the view, hides the pane without clearing the choice, so it comes back when the view is available again.
   - On session restore the pane reopens beside its tab.

   This replaces ADR-0015 decision 5's "follow to the next tab of the same type" behaviour. A per-tab choice can be saved and restored; a follow-me pane can't.
2. **Formatted View renders notes and tables.**
   - Notes (`StyleType Note` with an end marker: `\f`, `\fe`, `\x`, …) show their caller as superscript. The note text is muted and smaller, between generated, protected brackets. The note text itself stays editable.
   - `\tr` rows get tab stops. Cell markers (`\th1`, `\tcr2`, `\tc1-2`, … — recognized by name, since `usfm.sty` doesn't type all of them) are hidden, with a generated tab between cells, and header cells are bold.
3. **`.sty` export** (spec §39) has two Qt-free serializers in `sfm/sty_export.py`, both keeping the original key spellings and stripping comments:
   - **Export Resolved Stylesheet…** writes every marker with its effective properties. Re-importing it reproduces each effective style exactly.
   - **Export Stylesheet Overrides…** writes only what the non-baseline layers change.

   Environments still never write files. They return a new `SaveTextFile` command result, and the host asks for a path and writes it atomically.
4. **Marker placement from the loaded stylesheets** (spec §41/§46) is a separate **Check Marker Placement** command (`sfm/placement.py`).
   - It checks each marker's `OccursUnder` against a deliberately lenient context. A paragraph marker may sit under the book level (`id` before the first `\c`, `c` after it) or under the previous paragraph. Any other marker may sit under the current paragraph, the book level, or any open note/character span. `NEST` allows a marker inside a character style.
   - E6 decision 5 still holds for USFM grammar (`usfmtc`). This check covers what `usfmtc` can't: generic SFM projects whose rules exist only in project stylesheets.
   - Because it's a separate command, USFM validation never reports a problem twice.
   - With no stylesheet loaded, it says there are no rules to check against.
5. **Group detach (BF-082 refinement 5).** Dragging a group slot off the grouped tab bar moves that group's files in the split into one new window (`UNITIService.undock_views`). Each file keeps its own dock-return location. A plain click still opens the group's dropdown.

## Consequences

- No settings or session schema change: both new persisted values ride in the existing `extra` blobs.
- Still not done:
  - importing or migrating a project's stylesheet into a UNITI-managed layer (spec §39 "Import"/"Update existing");
  - a session-override style layer;
  - native/hosted confirmation of all of the above.

Update 2026-10-07: [ADR-0017](ADR-0017-environment-windows-in-place-views-reference-sync.md) changes two decisions:
- Decision 1: the per-tab choice still holds, but each tab now gets its own pane, in place of its Source editor.
- Decision 2: Preview moves notes into a frame below the text, and styles cells and notes from the stylesheet only.
