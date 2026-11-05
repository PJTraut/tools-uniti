# Markdown

Markdown documents. See the [overview](README.md). Short label: MD.

- **Extensions:** `.md`, `.markdown`.
- **Highlighting:** headings, emphasis, code, links and list markers.

## Views

| Mode | What it shows | Editing |
|---|---|---|
| Text | the Markdown source | yes |
| Preview (the Rendered view) | headings sized, emphasis, code and quotes formatted; the syntax characters hidden; list bullets as "•"; numbered items keep their number; pipe tables as an aligned monospace block with their pipes; lines match the source's lines | yes: the right-click commands below; Enter continues a bulleted, numbered or task list (a new task is unchecked) |

What Preview recognises follows the **Flavour** setting:

| Form | Extended | GitHub | CommonMark |
|---|---|---|---|
| `**bold**`, `*italic*`, `` `code` ``, links, headings, quotes, lists, code fences | yes | yes | yes |
| `<sup>x</sup>`, `<sub>x</sub>`, `<del>x</del>` | yes | yes | yes |
| `~~strikethrough~~`, pipe tables | yes | yes | no |
| `^super^`, `~sub~`, `==highlight==` | yes | no | no |
| task lists (`- [ ]`, `- [x]`, shown as ☐ and ☑) | yes | yes | no |
| footnotes (`[^1]` as a superscript; `[^1]: text` shows its label, then the text) | yes | yes | no |
| definition lists (a term line, then `: definition` lines; the term bold, the definition indented) | yes | no | no |
| YAML front matter at the start (`---` … `---` or `...`), shown as written, muted and monospace | yes | yes | yes |

Anything Preview doesn't recognise stays visible as text. The read-only Markdown Preview side pane (Ctrl+Alt+P) was retired on 2026-11-05: Preview replaces it.

## Preview's right-click menu

After Cut, Copy and Paste, the commands come in three blocks:

| Block | Commands |
|---|---|
| Character | Bold (Ctrl+B), Italic (Ctrl+I), Strikethrough, Superscript, Subscript, Code, Remove Formatting |
| Paragraph | Headings ▸ (Body Text, H1–H6; the caret's level is ticked), Quote, Bullet List, Numbered List, Task List, Check or Uncheck Task, Code Block |
| Insert | Insert Table… |

- A **character** command wraps the selection (each selected line separately, never the spaces around it). Inside text that already has it, it removes it. **Remove Formatting** removes every bold, italic, strikethrough, highlight, superscript, subscript and code delimiter in the selection, or around the caret; links stay.
- The syntax written follows the Flavour: Extended writes `^x^`, `~x~` and `~~x~~`; GitHub writes `<sup>`, `<sub>` and `~~x~~`; CommonMark writes `<sup>`, `<sub>` and `<del>`.
- A **paragraph** command replaces the line's prefix (`# `, `> `, `- `, `1. `, `- [ ] `). Quote, Bullet List, Numbered List and Task List on lines that already have that form turn them back into body text. **Check or Uncheck Task** checks the selected task items, or unchecks them when they're all checked. CommonMark has no task lists. Code Block fences the selected lines with ```, or, inside a fenced block, removes its fences.
- **Insert Table…** asks for columns × rows (for example `3 × 2`) and inserts a pipe table with a header row. CommonMark has no tables.

## Commands

| Command | Shortcut | What it does |
|---|---|---|
| Format Document | Ctrl+Alt+Shift+F | tidies the whole document in one undo step (details below) |
| Load Stylesheet… | | layers one more `.css` file on Preview until UNITI closes |
| Configuration Files… | | the stylesheets and settings that apply to the document |
| Environment Settings… | | MD's settings (below) |

What Format Document changes (the settings in brackets):
- one space after a heading's `#`s;
- the same bullet for every list item (Bullet; `-` by default);
- italic and bold delimiters (Emphasis, Bold; as written by default);
- numbered lists renumbered, or all `1.` (Numbered lists; as written by default);
- at most so many blank lines in a row (Most blank lines in a row; 1);
- pipe-table columns padded to line up (Align table columns; on);
- no trailing whitespace;
- code fences and YAML front matter left exactly as written; `* * *` stays a rule.

There's no Validate: Markdown has no strict grammar to check against.

## Settings

**Environment Settings…** in the MD menu. Saved in `…/Environments/Markdown/settings.json`, only the values that differ from the defaults; **Restore Defaults** resets them. A change applies at once.

| Setting | Values | Default |
|---|---|---|
| Flavour | Extended (the [Markdown Guide cheat sheet](https://www.markdownguide.org/cheat-sheet/)), GitHub, CommonMark | Extended |
| Opens in | Text, Preview | Text |
| Bullet | `-`, `*`, `+` | `-` |
| Emphasis | as written, `*italic*`, `_italic_` | as written |
| Bold | as written, `**bold**`, `__bold__` | as written |
| Numbered lists | as written, renumber 1, 2, 3 …, all `1.` | as written |
| Most blank lines in a row | 1–9 | 1 |
| Align table columns | on, off | on |

## Stylesheets

Preview takes its look from CSS. The layers, lowest first (later ones win, property by property):

1. **Built in:** `markdown.css`, read-only. Open it from Configuration Files… to see every element and property Preview reads.
2. **Yours:** `…/Environments/Markdown/uniti.css`, for every Markdown file. Configuration Files… creates it from a template.
3. **The document's:** the files its front matter names, relative to the document:

   ```markdown
   ---
   stylesheet: [notes.css, print.css]
   ---
   ```

   Without a `stylesheet:` entry, a `uniti.css` in the document's folder.
4. **Loaded:** Load Stylesheet…, until UNITI closes.

Preview isn't a browser, so it reads a subset of CSS:
- **Selectors:** element names only: `h1`–`h6`, `p`, `strong`, `em`, `del`, `mark`, `sup`, `sub`, `code`, `pre`, `blockquote`, `a`, `ul`, `ol`, `li`, `table`, `th`, `td`, `hr`, `dt`, `dd`. A footnote reference takes `sup` and `a`, a footnote's text `li`, a task item `ul`/`ol` and `li`; front matter's look is fixed. Commas list several.
- **Properties:** `font-family`, `font-size` (em, %, px, pt or a keyword), `font-weight`, `font-style`, `text-decoration`, `color` (`GrayText` is the theme's muted text), `background-color`, `margin-left`, `margin-top`, `text-align`.

Anything else (classes, ids, combinators, `@media`, other properties) is ignored and listed once in Preview's status line. Saving a stylesheet in UNITI updates Preview at once; a change made elsewhere shows at the next refresh.

## Configuration

Your configuration folder is `…/Environments/Markdown/`. It holds `settings.json`, `uniti.css` and `groups.json`.
