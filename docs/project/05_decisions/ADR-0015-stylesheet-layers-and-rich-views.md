# ADR-0015: Layered Stylesheets, Style Inspector, and Editable Rich Views (E6 completion, E7–E10)

Date: 2026-10-02
Status: accepted (implemented — see the [implementation record](../02_plans/2026-10-02-rich-views-and-grouped-tabs-plan.md))

## Context

E6 shipped the vendored `usfm.sty` baseline but left four items for later: loading a project's own `.sty`, a marker/style inspector, the rich-view/source-map framework (spec Phase E7), and the SFM/Markdown rich views built on it (E8 Standard, E9 Formatted, E10 Markdown). On 2026-10-02 the user asked for all remaining work to be implemented.

## Decision

1. **Stylesheets stay as separate layers, with provenance** (spec §37–38). `sfm/style_layers.py`: `LayeredStyleRegistry` over ordered `StyleLayer`s:
   - the official baseline (USFM only);
   - project stylesheets discovered next to the document (`usfm.sty`, `custom.sty`, `shared/ptxprint/ptxprint-mods.sty`, in that precedence);
   - stylesheets imported explicitly (**Load Stylesheet…**).

   Every effective property can report the layer it came from and the base value it overrides. Discovery never raises and skips files over 2 MiB. Trailing `# comments` in values are stripped. Generic SFM gets the same project layers, just with no baseline.
2. **Environments learn the document's path and the caret, read-only.** `EnvironmentContext` gains `document_path`, `caret` and `anchor`. Commands still cannot write anything themselves (ADR-0013 decision 6). Discovery only reads sibling files.
3. **Style Inspector** (spec §47). The commands are **Inspect Marker at Cursor** (`environment.inspect`, Ctrl+Alt+S), **Style Inspector…**, **Load Stylesheet…** and **Reload Project Stylesheets**. They open a non-modal window with a filterable marker list and Identity / Structure / Semantics / Presentation / Definition sections. Each row shows the property's value, the layer it came from, and its base value. The model is Qt-free (`sfm/inspection.py`). `marker_at` resolves the caret to:
   - the marker token under it;
   - else the innermost paired character span;
   - else the nearest still-open preceding marker.
4. **Rich views are projections with a bidirectional source map** (spec §31, Phase E7). The Qt-free `core/rich_views/` package covers four pieces:
   - **Source map:** a gap-free `SourceMap` of `TEXT` / `MARKER` / `HIDDEN` / `GENERATED` segments.
   - **Projection:** backend-neutral `Projection` presentation (block and span attribute maps, spec §50).
   - **Planner:** `plan_view_edit`, which maps a view-range replacement to source replacements. Protected syntax is never deleted by character-level editing, and typing at the end of a styled word stays inside the style.
   - **Provider protocol:** `EditorViewProvider` / `ViewCommand`, for semantic commands in source offsets.

   Every edit lands through `Document.replace_many`, so it is one undo step. The canonical document is never rewritten from view text (spec §32).
5. **The rich view sits beside Source, not in place of it.** The environment menu's **View As** block (Source Only / Standard View / Formatted View / Rendered View) is the view switcher. It opens an editable pane in the central splitter, next to the tab's ordinary source editor, the same way the BF-062 preview is mounted. Every window path assumes a tab holds a `UNITITextView`: Find/Replace, save, recovery, splits, session capture. Keeping Source in the tab leaves all of those untouched, and shows exactly what source each formatted edit produces.
   - Caret and selection sync both ways.
   - Edits made anywhere re-project the view.
   - Switching tabs retargets the pane, or closes it if the new document's environment has no such view.
   - Plain Text Mode closes it.
   - Documents above 1 MiB get a read-only "too large" notice instead of a view.
6. **SFM Standard View (E8)** shows every marker as a protected token and applies character styles; its lines match the source's lines. **SFM Formatted View (E9)** works as follows:
   - It hides markers and the one separator character after them.
   - Each paragraph marker starts a block, with that marker's effective STY formatting (alignment, margins, indents, spacing, size, weight, colour). Non-publishable paragraphs are muted.
   - Chapter numbers are large and verse numbers superscript.
   - A paragraph marker in the middle of a line gets a generated, protected line break.
   - **A marker no stylesheet defines stays visible as a protected token**, so content never silently disappears.

   Both views share these commands: Bold (`\bd`), Italic (`\it`), Character Style…, Remove Character Style, Paragraph Style…, Insert Verse…. Enter starts a new paragraph of the current kind. This is an editing renderer, not a typesetter: PTXprint-grade layout stays out of scope (spec Phase E9).
7. **Markdown Rendered View (E10)** works on the same infrastructure:
   - It hides heading, emphasis, code, quote, link and fence syntax, and shows list bullets as a protected `•`.
   - Lines map 1:1 to source lines.
   - Its commands are Bold / Italic / Code / Heading…, and Enter continues a list.
   - It supports a CommonMark subset only; anything it doesn't recognize stays visible as text.

## Consequences

- `EnvironmentFinding`, the chapter/verse index and the style registry all now have UI consumers.
- Standard View uses the editor's monospace font so markers line up with the source. Formatted and Rendered views use the proportional UI font.
- Not done:
  - nesting validation from `OccursUnder` (still left to `usfmtc`, per E6 decision 5);
  - exporting or migrating `.sty` files (spec §39);
  - a session-override style layer;
  - remembering an open rich view across sessions;
  - tables and footnote-caller rendering in Formatted View.

Update 2026-10-03: [ADR-0016](ADR-0016-rich-view-persistence-notes-export-placement.md) implemented several of these:
- remembering an open rich view across sessions (now a per-tab choice);
- notes and tables in Formatted View;
- `.sty` export;
- an `OccursUnder` placement check.

## Affected records

- [ADR-0013](ADR-0013-environment-framework-ownership-boundary.md) and [ADR-0014](ADR-0014-environment-workbench-and-extension-assignment.md) — extended; decision 6 of ADR-0013 holds unchanged.
- [E6 plan](../02_plans/2026-09-30-environment-framework-e6-usfm-layer-plan.md) — its "later phases" list is resolved here.
