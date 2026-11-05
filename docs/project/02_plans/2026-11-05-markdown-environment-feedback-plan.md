# Markdown Environment Feedback (2026-11-05) — Plan

Date: 2026-11-05
Status: **approved 2026-11-05** (roadmap row 30). **All built 2026-11-05** (N29 and N30 first; then N28, N31 and N27 in the plan's order, steps 2–6), with the read-only side pane retired (Q7); offscreen tests pass; the Mac checks are still to do. Q5–Q12 answered 2026-11-05; N31 added the same day. No questions open.
Origin: `@externalresources/field_test_feedback`, section "MD.ENV". IDs continue the [Mac field-test plan](2026-10-26-mac-field-test-feedback-plan.md) (N1–N26, all closed).

## Items

| ID | Area | Feedback | Proposal |
|---|---|---|---|
| N27 | Markdown | A custom stylesheet: more than one, linked as CSS, for customization (ref. the [Markdown Guide cheat sheet](https://www.markdownguide.org/cheat-sheet/)) | Preview is styled from layered CSS files, like SFM's layered `.sty` files (see N27 below) |
| N28 | Markdown | Preview's right-click menu sorted by type: character styles, then paragraph styles (Headings ▸ H1–H6, other paragraph types), then tables | The view's commands carry a group; the menu draws one block per group, with Headings as a submenu. Adds Strikethrough, Superscript, Subscript, paragraph types and Insert Table… (see N28 below) |
| N29 | Groups | Apply the SFM "group" display to Markdown | A Markdown tab is tinted with its group's colour, as an SFM project tab is (`set_tab_tint`), in place of the 12×3 px bar icon (N11). **Built 2026-11-05, every environment (Q8):** `_refresh_group_indicator` sets `set_tab_tint` and clears the icon; the grouped-tab buttons keep the bar |
| N30 | Groups | Group on the text area's right-click menu is redundant; group by hotkey, as in SFM | Remove the **Document Group** submenu from the text right-click menu (Text and Preview). The tab's right-click menu, the toolbar's `[group]` button and Ctrl+Alt+0…9 stay. **Built 2026-11-05:** `add_group_submenu` removed; Ctrl+Alt+0…9 are window actions on every window (`choose_group_by_position`, groups of `group_environment_key()`), so the toolbar no longer adds its own; the `[group]` pop-up shows each row's key; docs updated, with TXT for the plain-text environment |
| N31 | Environments | Every environment has **Configuration Files…**, but outside SFM nothing reads any settings (2026-11-05, from planning) | A shared settings mechanism: each environment declares its settings, saved in `…/Environments/<Env>/settings.json`, edited in **Environment Settings…**. All environments' settings are in this plan (see N31 below) |

## What exists today

- **Preview** (`core/environments/markdown_views.py`, `MarkdownRenderedView`) is an editable rich-view projection, 1:1 by line. It renders headings, bold, italic, inline code, links, quotes, bullets and code fences, but no tables, strikethrough, sub/superscript or numbered lists. Styles are hard-coded property dicts (`{"bold": "yes", "font_scale": "1.800"}` …).
- **Its commands** are Bold (Ctrl+B), Italic (Ctrl+I), Code and Heading… (a pick-list dialog). `RichViewEditor.context_menu` (`ui/rich_view.py:619`) lists them flat after Cut/Copy/Paste, then the host hook adds Document Group.
- **Markdown Preview** (Ctrl+Alt+P, `ui/markdown_preview.py`) is a separate read-only side pane using Qt's `QTextBrowser.setMarkdown`.
- **Configuration:** `…/Environments/Markdown/` exists, and nothing reads from it.
- **SFM stylesheets** are layered: built-in `usfm.sty` → the user's `uniti.sty` → the project's `custom.sty` → **Load Stylesheet…** (session only). Each layer is listed in the environment's configuration dialog (`core/environments/configuration.py`).
- **Groups:** SFM project tabs get a wash + band in the group colour (`project_tabs.py:159`, `panes.py:55`). Every other tab gets the bar icon. Ctrl+Alt+0…9 are added by the environment bar (`environment_window.py:870`), so they already work in a Markdown window. Ordinary windows don't have the shortcuts. The text right-click entry comes from `add_view_context_entries` (`main_window.py:2033`) through the rich view's `context_menu_hook`.

## N27 — Markdown stylesheets (CSS)

**Answer to "do we have a custom stylesheet?":** no. Preview's look is fixed in code.

**Proposal.** Preview takes its look from CSS. Layers, lowest first, mirroring SFM:

1. **Built in:** `markdown.css`, a read-only resource that reproduces today's look.
2. **User:** `…/Environments/Markdown/uniti.css`. Edit it from the configuration dialog; it's created from a template on first edit.
3. **Document folder:** `*.css` linked from the document. This covers the "more than one" part of the request. *How* they're linked is Q6.
4. **Session:** **Load Stylesheet…** layers one more `.css` file until restart, as in SFM.

**CSS subset.** Preview isn't a browser, so only a subset is read:
- Selectors: element names only (`h1`–`h6`, `p`, `strong`, `em`, `del`, `sup`, `sub`, `code`, `pre`, `blockquote`, `a`, `ul`, `ol`, `li`, `table`, `th`, `td`, `hr`).
- Properties: `font-family`, `font-size` (em / % / px), `font-weight`, `font-style`, `text-decoration`, `color`, `background-color`, `margin-left`, `margin-top`, `text-align`.

Anything else is ignored and listed once in the status bar. A small hand-written parser does this (no new dependency); it maps each rule onto the projection's existing style properties. Later layers win per property, as in the browser cascade by order.

**Explicit non-goals:** classes and ids, combinators, `@media`, and Format Document rewriting the CSS.

**Side pane.** The read-only Markdown Preview side pane (Ctrl+Alt+P) can't take this CSS through `setMarkdown`. Q7 asks whether to retire it now that the Preview mode exists (N9).

## N28 — Preview right-click menu by type

**Menu**, after Cut / Copy / Paste:

```
-----
Bold            Ctrl+B
Italic          Ctrl+I
Strikethrough
Superscript
Subscript
Code
Remove Formatting
-----
Headings      ▸  Body text, H1 … H6   (current level ticked)
Quote
Bullet List
Numbered List
Code Block
-----
Insert Table…
```

**Infrastructure** (generic, so SFM can use it too):
- `ViewCommand` gains `group: str` ("character" / "paragraph" / "insert") and `submenu: bool`. With `submenu`, `choices` become submenu rows instead of the `QInputDialog` pick list.
- `RichViewEditor.context_menu` draws a separator between groups.
- Commands without a group behave as today, so SFM's menu doesn't change unless we opt it in (Q9).

**Markdown commands:**
- **Character** commands wrap or unwrap the selection. Running one inside a run that already has it removes it (a toggle), so **Remove Formatting** strips every inline delimiter in the selection.
  - Syntax for strikethrough is `~~x~~`. Superscript and subscript are Q5.
- **Paragraph** commands rewrite the line's prefix (`# `, `> `, `- `, `1. `), or wrap the selected lines in a ``` fence. They replace each other, as Heading does today.
- **Insert Table…** asks for columns × rows and inserts a GFM pipe table with a header row.

**Rendering.** Preview must render what the menu can make:
- `~~ ~~`, sub/superscript and numbered lists as text styles.
- Pipe tables as a monospaced block with the pipes kept, aligned. This keeps the 1:1 line mapping that editing depends on.

A real grid layout for tables is a larger change to the projection model and is out of this plan.

**Hotkeys** stay Ctrl+B and Ctrl+I. No new shortcuts are proposed (say if you want Strikethrough on one).

## N29 — group colour on Markdown tabs

Give a Markdown tab the same treatment as an SFM project tab: `set_tab_tint(view_id, group.color)` when it's grouped, and no bar icon. The tint is refreshed wherever the bar icon is set today (`document_groups_and_recent_files.py:106`, `grouped_tabs.py:244`). Q8 asks whether every environment (TXT, JSON, …) should get it too, which would finish N2's harmonisation.

## N30 — group off the text right-click menu

- `add_view_context_entries` stops adding the group submenu. The book-lock entry stays. This covers both Text and Preview right-click menus, in every environment, since the hook is shared.
- The tab's right-click **Document Group / Project Group** stays.
- Ctrl+Alt+0…9 already work in every environment window. Show them as shortcut hints on the `[group]` pop-up's rows so they can be discovered.
- **Ordinary (non-environment) windows** have no `[group]` button and no Ctrl+Alt shortcuts, so after this change their only route is the tab menu. Add Ctrl+Alt+0…9 there too (as window actions on `MainWindow`), so the hotkey rule holds everywhere.
- **Docs:** `docs/environments/README.md` lines 56 and 70 and `usfm.md:157` mention "right-click … the text". Line 36 is also stale (window renaming was removed by N21/N26); fix it in the same pass.
- **TXT in the docs** (2026-11-05): the docs name the plain-text environment by its short label, TXT, as they already do SFM and MD. Examples are "Plain Text's groups" (`README.md`) and the stale "Plain Text — <group>" window in `plain-text.md`, which becomes "TXT/1". **Plain Text Mode** (viewing a file without its environment) and the **Plain Text** choice in the open dialog are modes, not the environment, so they keep their names.

## N31 — environment settings

**Today:** every environment's menu has **Configuration Files…**. Outside SFM it lists only the configuration folder, and nothing but `groups.json` is read from it. Format Document's rules and each environment's choices are fixed in code (for example JSON's 2-space indent in `reformatters.py:66`).

**Mechanism** (shared, Qt-free core):
- Each environment declares its settings in code: key, label, type (choice / number / on-off), default and a one-line description.
- Values are saved in `…/Environments/<Env>/settings.json`. Only values that differ from the default are written. An unknown key or a bad value is ignored, with one status-bar note, and never stops the environment loading.
- **Environment Settings…** in the Environment menu sits beside Configuration Files…. It opens a dialog built from the declarations, with **Restore Defaults**.
- `settings.json` is listed as a row in Configuration Files… so it can be opened as text.
- A change applies at once: Preview re-projects, and the next Format Document uses it.

**Settings per environment:**

| Environment | Settings |
|---|---|
| MD | **Flavour:** Extended (the cheat sheet's syntax; default), GitHub, CommonMark. It decides which syntax the N28 commands write and which forms Preview recognises (sub/superscript `^x^ ~x~` or `<sup>`/`<sub>`, tables, strikethrough, task lists, footnotes, highlight, definition lists). **Format Document:** bullet character (`-` `*` `+`), emphasis `*`/`_`, bold `**`/`__`, numbered lists renumbered or all `1.`, most blank lines in a row, align table columns. **Opens in:** Text or Preview |
| JSON | Indent (2), sort keys (off), non-ASCII as `\u` escapes (off) |
| XML | Indent (2), attributes on one line or wrapped |
| YAML | Indent width (2), used by Check Indentation |
| CSV | Delimiter (`,`), quote character (`"`), first row is a header (on) |
| TSV | First row is a header (on) |
| TXT | none; the dialog says so |
| SFM | none new; its stylesheets and rules stay in Configuration Files… |

The Q5 answer is now the Markdown default: the Extended flavour writes `^x^` and `~x~`, and the GitHub flavour writes `<sup>`/`<sub>`.

## Open questions

**Answered 2026-11-05:**
- **Q5:** `^x^` and `~x~`, as in the cheat sheet.
- **Q6:** front matter (`stylesheet: [a.css, b.css]`), with a `uniti.css` in the document's folder as the fallback.
- **Q7:** retire the read-only side pane (Ctrl+Alt+P).
- **Q8:** the group tint applies to every environment's tabs.
- **Q9:** SFM is left as it is. Its markers are handled with tags in Text and Standard, and its Preview stays a read-only text rendering, not an editing mode. The grouped menu is for Markdown only; `ViewCommand.group` stays optional and SFM doesn't set it.

- **Q10:** Preview shows pipe tables as an aligned monospace block, pipes kept.
- **Q11:** Ctrl+Alt+0…9 are added to ordinary windows as well.
- **Q12:** Strikethrough gets no shortcut.

**Future idea (not in this plan):** an SFM "Bible view" pop-up, a print emulation with single or double column and running headers. It belongs to the parked catalog or a later plan.

Original wording:

- **Q5 — superscript/subscript syntax.**
  - Option 1: `^x^` and `~x~`, as in the Markdown Guide cheat sheet. This is Pandoc / markdown-it syntax; GitHub doesn't render it.
  - Option 2: `<sup>x</sup>` and `<sub>x</sub>`, which render on GitHub and everywhere HTML is allowed.
  - *Recommended:* follow the cheat sheet (option 1), since the testers cite it.
- **Q6 — how a document links its CSS files.**
  - Option 1: every `*.css` in the document's folder, in name order.
  - Option 2: a `uniti.css` in the folder only.
  - Option 3: front matter, `stylesheet: [a.css, b.css]`.
  - *Recommended:* option 3 with option 2 as fallback. It's explicit, allows several files, and doesn't surprise anyone who keeps unrelated CSS beside their notes.
- **Q7 — the read-only Markdown Preview side pane (Ctrl+Alt+P).**
  - Option 1: retire it.
  - Option 2: keep it unstyled.
  - *Recommended:* retire it. It predates the Preview mode and now duplicates it.
- **Q8 — N29's scope:** Markdown only, or every environment's tabs? *Recommended:* every environment.
- **Q9 — SFM's right-click menu:** group it the same way (Bold, Italic, Character Style…, Remove | Paragraph Style… | Insert Verse…)? *Recommended:* yes. It costs only the group tags.

## Order

1. N30 and N29. These are small, shared group code, with one Mac check.
2. N28's menu infrastructure: `ViewCommand.group` and submenus.
3. N31's mechanism and Markdown's settings, before N28's commands land, so the flavour decides their syntax from the start.
4. N28's Markdown commands and rendering.
5. N27, which builds on N28's new elements. The built-in `markdown.css` must cover them.
6. N31's settings for JSON, XML, YAML, CSV and TSV.

## As built (2026-11-05)

- **Step 2, menu infrastructure:** `ViewCommand` gained `group`, `submenu` and `current` (`core/rich_views/provider.py`). `RichViewEditor._add_command_entries` draws one block per group; a submenu command's choices are rows, the one `current` names ticked; a command's shortcut shows in the menu's shortcut column. SFM's commands set no group, so its menu is unchanged (Q9).
- **Step 3, N31's mechanism:** `core/environments/settings.py`: declarations (`EnvironmentSetting`), `settings.json` read with notes for what's ignored, written with only the changed values (keys this version doesn't declare are kept), re-read when the file changes, kept for the session when there's no user data folder. **Environment Settings…** (`ui/environment_settings.py`) in every environment menu after Configuration Files…, which lists `settings.json`. Saving the dialog, or `settings.json` as text, re-renders that environment's rich views everywhere. "Opens in" is a generic `opens_in` setting naming a view provider.
- **Step 4, N28's commands and rendering** (`markdown_views.py`): the commands as the menu above; Headings' choices are Body Text and H1–H6. Preview parses inline runs recursively (`**bold *and italic***`), and the commands find runs by the same parse, so a toggle never mistakes bold's stars for italic. Enter continues a numbered list with the next number. Pipe tables are padded with generated spaces (dashes in the delimiter row), so the source isn't touched.
- **Step 5, N27:** `markdown_css.py` and the built-in `assets/markdown.css`, which reproduces the earlier look. The fenced block's marker is now `pre` (its CSS element). `color: GrayText` stands for the theme's muted text. The view's `cache_token` changes when a stylesheet or the flavour does, so the projection cache re-projects. Notes about ignored CSS show once in Preview's status line. **Q7:** the side pane (`ui/markdown_preview.py`, the `environment.preview` command and Ctrl+Alt+P) is removed; a saved override for that shortcut is ignored.
- **Step 6:** JSON (indent, sort keys, escape non-ASCII) and XML (indent, attributes one per line) reach Format Document; YAML's indent width adds warnings to Check Indentation (blank lines, comments and block scalar text skipped); CSV's delimiter and quote character and the header flag (CSV, TSV) reach Check Column Counts. The header flag only changes the report's wording ("the header has 3" or "the first row has 3").
- **Step 7, the Flavour's remaining forms (2026-11-05):** YAML front matter shows as written, muted and monospace, in every flavour, and Format Document leaves it untouched (it was formatted as Markdown). GitHub and Extended: task lists (`- [ ]`/`- [x]` as ☐/☑, Enter continues unchecked, **Task List** and **Check or Uncheck Task** in the paragraph block) and footnotes (`[^1]` a superscript with `sup` and `a`'s look; `[^1]: text` shows its label; Remove Formatting leaves references alone). Extended: definition lists (the plain line above `: definition` is `dt`, bold; each `: ` line is `dd`, indented); `dt` and `dd` are new CSS selectors. Footnote continuation lines and multi-paragraph definitions aren't recognised.

## Tests

- **Projection tests** for each new inline and paragraph form and for the pipe table (`tests/…markdown_views`).
- **Command tests:** wrap, toggle off, Remove Formatting, prefix replacement, Insert Table.
- **Context menu structure:** separators, Headings submenu, no Document Group entry.
- **CSS:** the parser, the cascade order, and unknown properties ignored.
- **Groups:** Markdown tab tint set and cleared with the group; Ctrl+Alt+digit in an ordinary window.
- **Settings (N31):** declarations load with their defaults; only changed values are written; a bad `settings.json` is ignored with a note; the flavour switches which syntax the commands write; JSON indent and CSV delimiter reach Format and Check.
- **Mac check** after N29/N30, after N28 and after N31's dialog.
