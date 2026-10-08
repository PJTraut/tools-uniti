# USFM Field Test, Round 2 — Plan

Date: 2026-10-08
Status: **Proposed**. All items are ready to implement (D1–D4 decided 2026-10-08).
Origin: `@externalresources/field_test_feedback` (2026-10-08).
Builds on: [ADR-0017](../05_decisions/ADR-0017-environment-windows-in-place-views-reference-sync.md) and [ADR-0018](../05_decisions/ADR-0018-usfm-projects-and-recent-projects.md). It's ordered on the [roadmap](ROADMAP.md) ahead of the remaining [projects plan](2026-10-07-usfm-projects-and-versification-plan.md) phases P4–P5.

## Feedback

General (environments):
1. "every environment needs to have its own file extensions associated: SFM & USFM all belong to the same environment (and sfm/usfm)"
2. "files from defined environments must open with dialog 'open as plain text or in XXX Environment'"

USFM:
3. "PREVIEW - footnotes (and possibly other nested styles) are not displaying correctly: `\+xt` should be parsed as `\xt` etc. the '+' indicates nesting. so `\nd xx \+it yy\+it*\nd*` must render 'yy' as SMALLCAP ITALIC"
4. "`\cat` in footnotes needs to be displayed in [] for now; later feature select category/ies of footnotes to display in preview"
5. "when selecting BK:CH:VS from menu, jump to location and highlight the verse for all view modes"
6. "optimize speed of view mode switch; text to standard/preview is very slow"

General, added the same day:

7. "report undefined tags/markup for all environments where applicable when file opened"

## Findings (measured 2026-10-08)

- **Speed (item 6).** On a 220 KB book (50 chapters, 1,550 verses, a footnote per verse), switching Plain Text → Standard took **41 s** in a window.
  - **The pane renders twice.** `_ensure_pane` sets the focus proxy before the pane is bound. The resulting focus-in re-activates the tab, and `sync()` doesn't yet see a key, so it calls `show()` again.
  - **Each render takes about 20 s.** `render_projection` applies about 51,000 `mergeCharFormat` calls to the editor's *live* `QTextDocument`, and each one triggers a re-layout. The same rendering into a detached document takes **0.6 s**.
  - **The projection itself is not the bottleneck:** 0.24 s for Standard and 0.55 s for Preview, which walks the notes too.
- **Nested markers (item 3).** The tokenizer's marker pattern `\\[A-Za-z][A-Za-z0-9]*\*?` doesn't accept `+`, so `\+it`, `\+it*` and `\+xt` stay literal text, and Preview shows `\+it yy\+it*`.
  - The same pattern also misreads milestones (`\qt-s`, `\qt-e`, `\*`) and column-range cells (`\th1-2`).
  - In the bundled official `usfm.sty`, `\nd` is **Underline**, not small caps. With `+` fixed, `\nd xx \+it yy\+it*\nd*` renders "yy" as underlined italic unless a stylesheet says otherwise (decision D3).
- **`\cat` (item 4)** isn't in the bundled `usfm.sty`, so it's an unknown marker and shows as a raw `\cat` tag in the note.
- **Highlight on navigation (item 5).** The Book/Chapter/Verse selector and **Go to Chapter:Verse…** move the caret but highlight nothing. The verse highlight exists only for side-by-side sync (`ReferenceSync._highlight`).
- **Undefined markup (item 7).**
  - **Validate USFM** (`usfmtc`) reports unknown tags against the official USFM grammar, e.g. "Unknown tag 'zfoo' in 'p'". It runs only on demand. It ignores the project's stylesheets, so a `\zfoo` defined in `custom.sty` is still reported, and `\cat`, which the grammar knows, isn't reported even though no loaded stylesheet styles it.
  - Generic SFM has no such check.
  - No other environment defines a vocabulary UNITI could check against today. XML has no schema validation, and JSON, YAML, CSV and Markdown have no "undefined tag" concept.
- **Extensions (item 1).** By default `.sfm` belongs to the generic **SFM** environment and `.usfm` to **USFM** (`DEFAULT_EXTENSION_PROFILES`). Extensions are already matched case-insensitively, and View > File Type Environments… can already reassign them.

## Changes

### R1 — Mode switch speed (item 6)
- **Bind first, then focus.** `RichViewController._ensure_pane` sets the focus proxy, and the pane takes focus, only after `bind()`. `sync()` and `show()` also ignore a re-entrant call for the same tab and key. The pane then renders once.
- **Render off-screen.** `render_projection` fills a detached `QTextDocument` and hands it to the editor in one step, keeping the editor's document settings. It inserts text in runs that each carry their final format, so there's no full-text insert followed by thousands of `mergeCharFormat` calls.
- **Cache the projection** per (document revision, provider, stylesheet generation). Switching Standard ↔ Preview ↔ Plain Text and back without editing doesn't re-project.
- **Target:** under 1 s for the 220 KB book, from Plain Text to Standard or Preview, measured in a window. A benchmark scenario (`benchmarks/`) and a UI test keep it there. Re-projecting only the edited paragraph after an edit is a separate, later step.

### R2 — Nested `\+` markers (item 3)
- **Tokenizer:** accept `\+name` and `\+name*`. The token keeps its source text, and the marker name is `name` without the `+`. While here, also accept milestones `\name-s`, `\name-e` and the self-closing `\*`, and column ranges (`\th1-2`), so they stop leaking into text.
- **Parser:** pair `\+name` with `\+name*`.
- **Style lookup:** everywhere a marker's style is looked up — Standard/Preview, semantic commands, placement, inspection, `marker_at` — `+name` means `name`.
- **Nesting:** an inner style applies on top of the outer one. `\nd xx \+it yy\+it*\nd*` gives "yy" both `\nd`'s and `\it`'s formatting. Inside notes, `\+xt …\+xt*` is styled as `\xt`.
- **`\nd` is small caps (D3).** The built-in `uniti.sty` gains `\Marker nd` with `\SmallCaps` and `\Underline -`, so the feedback example renders "yy" as small-caps italic. A project or user `uniti.sty` can change it back.
- **Tests:** the feedback example; `\+xt` inside `\f`; an unclosed `\+it`; and Standard showing `\+it` as its own tag.

### R3 — `\cat` in Preview notes (item 4)
- Preview shows a note's category as generated, protected `[People]` text right after its caller in the notes frame, and hides the `\cat`/`\cat*` markers.
- The brackets are styled by a new built-in rule, `\Marker cat` in `uniti.sty`, so they can be restyled like everything else.
- Standard keeps `\cat` visible as a tag, as it does every marker.
- Choosing which categories Preview shows is in the [wishlist](../FEATURE_WISHLIST.md#footnote-category-filter-in-preview).

### R4 — Highlight the verse when navigating (item 5)
- Choosing a book, chapter or verse in the environment toolbar, and **Go to Chapter:Verse…**, highlight the verse after jumping, in Plain Text, Standard and Preview. They use the same tint as reference sync. A chapter-only jump highlights the `\c` line.
- The highlight clears when the caret leaves that verse or at the next jump.
- The verse lands about a third of the way down the view, as sync does.

### R5 — One USFM environment for `.sfm` and `.usfm` (item 1, D1: group them)
- **The generic SFM environment is removed.** `.sfm` and `.usfm`, in any case, both belong to **USFM**: the official baseline, `usfmtc` validation, projects, views, sync.
- **The SFM syntax profile goes too.** That keeps ADR-0014's one-profile-per-environment catalog.
- **Saved references to `sfm` are read as `usfm`, so nothing a user saved is lost:**
  - extension overrides in `settings.json`;
  - pins (`DocumentRecord.extra["environment_override"]`);
  - per-view syntax choices (`ViewRecord.extra["syntax_choice_key"]`);
  - environment windows.

  The rich-view keys (`sfm.standard`, `sfm.preview`) stay as they are, since they name the shared SFM views.
- **What changes for non-Scripture SFM** (e.g. Toolbox dictionaries): it now gets USFM validation and the official stylesheet. Undefined-marker reports (R7) and Plain Text (R6) are the way to work with those files.
- **Docs:** ADR-0013/ADR-0014's catalogs and the [SFM syntax-highlighting entry](../../syntax-highlighting.md) are updated.

### R6 — "Open as Plain Text or in <Environment>" (item 2) — decision D2
- Opening a file whose extension belongs to an environment other than Plain Text asks:
  - **Open in USFM Environment**: into that environment's window for the file's group;
  - **Open as Plain Text**;
  - **Cancel**.
- **"Plain Text" is the default editor environment (D2).** Opening as plain text pins the file to the **Plain Text environment**, so the file has no extended features while it's being worked on: no environment menu commands, views, validation, sync or environment window. That's different from the per-tab Plain Text Mode toggle, which keeps the file's environment.
- "Don't ask again" isn't part of this; the dialog appears on every such open, unless that's revisited.
- No prompt for:
  - session restore;
  - Open USFM Project… and Recent Projects;
  - the Book selector;
  - opening inside an environment window (already pinned, ADR-0017);
  - files that are already open.
- This settles the question left open on 2026-10-07: files no longer land in the main window by default without asking.

### R7 — Report undefined markup when a file is opened (item 7, D4: popup)
- **Environment hook:** a new optional `undefined_markup(context) -> tuple[EnvironmentFinding, ...]`. An environment implements it where "defined" means something; others don't, so nothing is reported for them.
- **Implemented for SFM and USFM:**
  - Every marker the document uses that no loaded stylesheet layer defines is reported: official, built-in `uniti.sty`, project (`usfm.sty`/named, `custom.sty`, PTXprint mods, `uniti.sty`) or loaded.
  - It uses the same layers Standard and Preview use, so "undefined" means "these views can't style it".
  - Closing markers, the `+` of nested markers (R2), and `-s`/`-e` milestones resolve to their base marker first.
  - Findings are grouped per marker with a count, e.g. "`\zfoo` — 3 uses, not defined in any loaded stylesheet". A `\z…` marker is labelled as a custom marker that needs a definition in `custom.sty`.
- **When it runs:**
  - when a file is opened;
  - again whenever the stylesheets change (Reload Project Stylesheets, Load Stylesheet…, saving a configuration file per R8);
  - on demand with a new **Check Undefined Markers** command in the environment menu, next to Validate and Check Marker Placement.
  - Files above 1 MiB are skipped, as for validation.
  - Files restored at startup aren't checked automatically, so a restart doesn't open a dialog per file; the command still works on them. The user didn't settle this; it's the recommended default.
- **Popup dialog (D4).** When an opened file has undefined markup, a dialog opens:
  - **The list:** one row per undefined marker, with its count, the stylesheet layers it was looked for in, and a `\z` "custom marker" label where it applies. Expanding a row lists its locations (chapter:verse and line); activating one jumps to it.
  - **Copy Report / Save Report…:** the whole report as plain text, with the file, the layers checked, and every marker with its locations. Save Report writes a `.txt` wherever you choose.
  - **Edit / update files:**
    - **Edit Stylesheet…** opens the configuration file that should define the markers, through R8's Configuration Files: by default the project's `custom.sty`, or for a single file the user `uniti.sty`, created from its template if missing.
    - **Add Definitions** appends a stub record for each selected marker to that file, then opens it. Character when the document closes it (`\x …\x*`), Paragraph otherwise; with `\Name`, `\StyleType` and, for character styles, `\Endmarker`. Saving the file reloads the stylesheets (R8) and re-runs the check.
  - **Close.** The dialog is non-modal and belongs to its document.
- **XML** could join later through the same hook, once a declared DTD or schema is read. It's not in this round.
- **Dependencies:** R2 (so `\+it` resolves to `\it`), and R3, which defines `\cat` (StyleType Character, EndMarker `cat*`) in the built-in `uniti.sty` so it isn't reported.

### R8 — Environment documentation and editable configuration (D3)
- **A user configuration folder per environment:** `<UNITI user data>/Environments/<Environment>/`. For USFM it holds:
  - `uniti.sty`: the user's own presentation rules, a new layer between the built-in rules and the project's stylesheets, applying to every USFM file;
  - `Versification/*.vrs`: the user versification files (P4 uses this location).
- **Configuration Files…** in the environment menu lists every configuration file that applies to the current document, in the order they apply. For USFM:
  1. the official `usfm.sty` (built in, read-only);
  2. the built-in `uniti.sty` (read-only);
  3. the user `uniti.sty`;
  4. the project's stylesheet (`usfm.sty` or the one `Settings.xml` names), `custom.sty`, PTXprint mods, and the project's `uniti.sty`;
  5. stylesheets loaded with Load Stylesheet…;
  6. `Settings.xml`, `BookNames.xml`, the project's `custom.vrs` and the user `.vrs` files.

  Each row shows its role, path and whether it exists, with **Open** (edit it in UNITI) and **Show in Folder**. A built-in file offers **Copy to My Configuration and Open**. A missing user or project `uniti.sty` offers **Create**, starting from a commented template of the built-in rules.
- **Saving reloads.** Saving any of these files in UNITI reloads that environment's stylesheets (and versification) for the documents it affects. Standard and Preview update straight away.
- **Documentation**, as `docs/environments/`:
  - an overview: what an environment is; environment windows; Open as Plain Text vs. Plain Text Mode; extension assignment; configuration layers and folders;
  - one page per environment (Plain Text, Markdown, XML, JSON, YAML, CSV, TSV, USFM): extensions, menu commands, views, validation and findings, environment window, and every configuration file with its location, format, precedence and how to edit it, with examples;
  - folded in: the USFM page carries [USFM stylesheet rules](../../usfm-stylesheet-rules.md), `Settings.xml` projects, and versification.

  The pages are linked from the README and the user manual, and each menu's **Configuration Files…** links to its page.
- **Tests:** the layer order with a user `uniti.sty`; creating a file from the template; reload after saving a configuration file; the Configuration Files list for a single file and for a project file.

## Decisions needed

Decided 2026-10-08:
- **D1:** remove the generic SFM environment; `.sfm` and `.usfm` both belong to USFM (R5).
- **D2:** "Plain Text" is the default editor environment, so opening as plain text means no extended features (R6).
- **D3:** yes, the built-in `uniti.sty` makes `\nd` small caps without underline (R2). Also: document every environment and its configuration files in detail, and let users update and edit those files (R8).
- **D4:** undefined markup is reported in a popup dialog, which can copy or save the report, or edit and update the configuration files (R7).

## Order

R1 → R2 → R3 → R4 → R5 → R6 → R8 → R7, then projects P4 (versification) and P5 (sync across books).
- R1 comes first: it's the most visible problem, and its cause is known.
- R2–R4 are independent fixes. R5 (one USFM environment) comes before R6's dialog and R8's per-environment folders and pages, so both are written once for the final set of environments.
- R7 follows R2, R3 and R8: they change what counts as defined, and its Edit/Add Definitions buttons use R8's configuration files.
