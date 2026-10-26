# Mac Field-Test Feedback (2026-10-26) — Plan

Date: 2026-10-26
Status: **every N-item is built (2026-10-26) except N15, which is parked.** Q1–Q3 answered, Q4 parked.
Origin: `@externalresources/field_test_feedback`, notes from the Mac users. Items are the testers' words, tidied; none is yet a confirmed decision.

## Items

| ID | Area | Feedback | Status |
|---|---|---|---|
| N1 | Environments | Windows are named `[ENV][x]`, x a number 1–9, never 0; at most nine windows | **built** |
| N2 | Environments | Harmonize the UI layout across environments | **built**: every environment's toolbar has the same left side: window name, Group button, project, Text / Preview switch; the Book/Chapter/Verse and Sync block is shown only where the environment has references |
| N3 | Environments | Compact environment names (USFM → SFM, Markdown → MD …), as short labels only | **built**: window names use short labels (`SHORT_LABELS` in `catalog.py`): SFM (USFM), MD, TXT, XML, JSON, YAML, CSV, TSV; menus and tooltips keep the full names |
| N4 | Environments | One menu tree per environment | **already so**: the Environment menu is rebuilt for the active document's environment (Plain Text gets only the assignment entries); its two assignment entries are now **Assign Environment** (submenu) and **Assign by File Type…** |
| N5 | Environments | Rollers step to previous/next in the list (Book GEN + → EXO, Chapter 3 − → 2) | **built**: "−" and "+" buttons around Book, Chapter and Verse (`EnvironmentBar.step`), disabled at the ends of the list |
| N6 | Environments | Clicking inside a roller opens a truncated dropdown (current plus a few options, scrollbar); Psalms' 1–150 list is the bad case | **built**: the list pop-up shows 12 rows and scrolls (`combobox-popup: 0` replaces the native full-height Mac pop-up) |
| N7 | USFM | Roller labels Book → BK, Chapter → CH, Verse → VS | **built** (the toolbar's Chapter toggle reads CH, a BK label precedes the lock, VS labels Verse; full names stay in tooltips and menus) |
| N8 | Markdown | Remove the Bold/Italic/Code/Heading banner in Rendered view; keep the hotkeys | **banner removed** (Cmd+B, Cmd+I stay; commands on the right-click menu); **N8b built**: Cmd/Ctrl+B and +I in a Markdown file's text view wrap the selection in `**`/`*` (an empty pair with the caret between when nothing is selected); other environments and Plain Text Mode leave the keys alone |
| N9 | Markdown | Text/Preview switch always in the menu bar (the template behaviour every environment shares) | **built**: every environment shows Text then its views; Markdown's Rendered view is now called Preview, and an environment without a rich view shows Preview greyed out |
| N10 | Menus | Fewer top-level menus; Help last; Environment menu second to last (the plain-text menu gets "Assign Env"); fold menus into submenus, drop redundant ones | **built**: File, Edit, View, Environment, Help (was File, Edit, Format, View, Environment, Tools, Hotkeys). Format → File › Encoding & Line Endings; Compare… → File; Character Inspector and Whitespace/Unicode Legend → View; Find panel items (attach, zoom, Match Report) → View › Find Panel; Hotkeys, Diagnostics and dogfood evidence → Help; View's duplicate File Type Environments… removed |
| N11 | Groups | Replace the tab's dot with a horizontal bar or something smaller | **built**: a 12×3 px rounded bar on tabs and the grouped-tab buttons; menus keep the round swatch |
| N12 | Groups | Use the same button as Environment in the display panel | **built**: the toolbar's Group is a flat button (like the window name) showing the group's swatch and name; clicking lists the groups, New Group… and Manage Groups… |
| N13 | Find/Replace | Attach/detach to the main environment frame, not a "project panel" | **built**: Find/Replace attaches below the whole pane tree (`EditorPaneTree.split_root`), across the window frame, not under one pane |
| N14 | Find/Replace | The match/preview result line doesn't always show the capture-group colour | **built**: a replacement line too long for the Match Report is elided and keeps its group colours up to the ellipsis (it used to lose them all) |
| N15 | Find/Replace | Clicking in the text clears the match display | parked (Q4) |

## N1 — numbered window names (built)

`default_window_name` (`app/environment_window_names.py`) gives 1 … 9 for slots 0 … 8 (slots past nine are never used, but stay zero-free as 11, 12 …). Windows read "SFM-1", "SFM-2", "TXT-1". Renamed slots in `windows.json` are untouched. Only slots left at their default change name. **Hard cap of nine** (Q1): `MAX_ENV_WINDOWS`; a tenth request returns the environment's most recently used window, and the tab menu's "Move to New Window" is disabled with a tooltip. Group names (A, B, C) are a separate thing and stay.

## Answered, 2026-10-26

- **Q1:** a hard cap of nine windows per environment (built).
- **Q2:** "SFM" is a short label for USFM; the generic SFM environment does not come back (N3).
- **Q3:** Markdown's Rendered view loses its Bold/Italic/Code/Heading button banner (built, as Standard did on 2026-10-09). The hotkeys stay, plus the right-click menu. **N8b, hotkeys in the text view:** yes, possible — the same `**`/`*` wrap as a text-view shortcut for Markdown files, Cmd+B and Cmd+I (neither is taken elsewhere in the app); with no selection it would insert an empty pair and put the caret between.
- **Q4 (parked):** whether clicking in the text should clear the match highlight.

## Order

N1, then the contained Find/Replace bugs (N14, N15), the roller items (N5–N7, one change in the environment bar), the tab bar/button items (N11, N12), then the menu restructuring (N4, N10) with N2, N9 and N13, which share the environment-frame layout.

## N4 and N10 — the menu bar (built)

Top menus: **File, Edit, View, Environment, Help.** Not flattened further: View still holds Whitespace, Text Direction, Tab Width, Editor Theme and Syntax Profile as pickers beside Font…, Convert Tabs to Spaces and Pause Background Work. A further "Editor" submenu would put pickers two levels deep; say if you want it.
