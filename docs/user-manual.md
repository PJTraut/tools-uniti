# UNITI User Manual

For **v0.001b3 — Find/Replace Rework & Editor Refinement Beta** · Updated 2026-09-15

UNITI is a text editor for Unicode, explicit encoding and line-ending control, large files, and regex search/replace. This manual describes the current source beta. Native executable distribution and some platform/input qualification remain pending; see [current release status](project/01_current/STATUS.md).

**Quick references:** [User Cheat Sheet](user-cheat-sheet.md) · [Regex Flags Guide](regex-flags.md)

## Contents

1. [Start and update UNITI](#start-and-update-uniti)
2. [Open, edit, save, and quit](#open-edit-save-and-quit)
3. [Find and replace](#find-and-replace)
4. [Encoding and line endings](#encoding-and-line-endings)
5. [Read and inspect text](#read-and-inspect-text)
6. [Arrange your workspace](#arrange-your-workspace)
7. [Appearance and shortcuts](#appearance-and-shortcuts)
8. [Sessions and recovery](#sessions-and-recovery)
9. [Large files and troubleshooting](#large-files-and-troubleshooting)

## Start and update UNITI

The current beta runs from a source checkout with **Python 3.12 or newer** installed. Use the complete UNITI folder; keep its scripts and resources together.

| Platform | Launch |
|---|---|
| macOS | Double-click `uniti.command`. |
| Windows | Double-click `uniti.bat`. |
| Linux | From a terminal in the UNITI folder, run `./uniti.command`. |

First use prepares a private Python environment and installs the required dependencies; this can take time and needs network access for dependency downloads. The terminal reports `// prepping UNITI for first use` and the setup stages. Subsequent healthy launches stay quiet. Keep the launching terminal open while UNITI is running.

For updates, save your work and use **Quit**. Update the source checkout through your normal distribution process, then launch with the same launcher so it can refresh the managed installation when required. For a Git checkout without local changes, `git pull --ff-only` downloads the latest branch updates; if it reports a conflict, stop and resolve the checkout rather than discarding changes. Development setup and explicit repair commands are in [Development](project/01_current/DEVELOPMENT.md).

## Open, edit, save, and quit

1. Choose **File → Open…** and select a text file.
2. If an encoding confirmation appears, inspect its preview and choose the encoding that represents the file correctly.
3. Edit the document. The status bar shows line/column, encoding and line-ending state, zoom, wrap mode, file size, and work/resource status.
4. Choose **File → Save** to write changes to the current file.
5. Choose **Quit** when finished. On macOS, Quit can appear in the native UNITI application menu.

Use **File → Open Folder by Type…** to open every file of one chosen extension from a folder at once (top-level files only, not subfolders) — for example, every `.sfm` file in a translation project. A follow-up prompt lets you assign all of them to no group, an existing group, or a newly named group, in the same step. UNITI does not remember the folder afterward; it is a one-time batch convenience, not a project or workspace.

### Saving choices

| Action | What it does |
|---|---|
| **Save** | Writes edits and any pending output-format conversion to the current file. |
| **Save As…** | Choose a folder, filename, encoding, and line endings. Saving to a different path creates a copy and opens that copy; the original document keeps its own path, edits, and save state. |
| **Reload/Revert from Disk** | Reopens the disk version, with confirmation when necessary. Use it when you intend to replace the current editing state with the saved file. |
| **Close** | Closes the current tab, with unsaved-change choices when applicable. |
| **Quit** | Resolves unsaved changes across documents and exits UNITI. |

**Save As is not a rename.** After exporting to a new path, the original document may still have unsaved changes. Save, discard, or retain those separately.

Closing the last window leaves an empty editor available. It does not exit UNITI or release the launching terminal. Use **Quit** to finish the session.

### Editing and navigation

Use **Edit** for Undo, Redo, Cut, Copy, Paste, and Select All. Undo/Redo applies to the focused editor, Find field, or Replace field. Click the document before undoing document changes.

Use **Edit** for Go to Line, document start/end, word movement, and page movement. Double-click selects a word; triple-click selects a visual row; quadruple-click selects a logical line including its line ending. A wrapped visual row may be only part of one logical line.

## Find and replace

Choose **Edit → Find** (toggles the panel open/closed) or **Edit → Replace**. The panel belongs to the application and follows the active document/view. Hover over an icon to see its action name.

### Literal search

Leave **Regex** unchecked. Enter the text to find. Enable **Case** for case-sensitive matching or **Whole word** to restrict matches to word boundaries. Regex-looking text such as `.` or `\d` is ordinary text in this mode.

Choose **Find All** to populate results and highlight visible matches. **Next Match** and **Previous Match** also work without first running Find All; they navigate relative to the cursor and wrap around the document.

### Regex search and flags

Enable **Regex** and enter the expression directly, without surrounding quotes or slash delimiters. **Case** and **Whole word** become disabled; the pattern and its inline flags now determine behavior.

UNITI uses raw engine defaults. Matching is case-sensitive, and `^` anchors the **start of the entire document**. It does not automatically mean the beginning of each line.

| Flag | Use |
|---|---|
| `(?i)` | Ignore case: `(?i)apple` matches `Apple`. |
| `(?m)` | Match line boundaries with `^` and `$`. |
| `(?s)` | Let `.` match newline characters. |
| `(?x)` | Allow readable spacing and `#` comments in the pattern. Escaped characters and character classes retain literal spaces/hashes. |

For numbered entries beneath a heading, use:

```regex
(?m)^(\d+)\D([^\r\n]+)
```

Without `(?m)`, this anchored expression finds nothing if the document begins with a heading rather than a digit. A pattern can be valid and still have no matches.

Combine flags as `(?im)`. See the [Regex Flags Guide](regex-flags.md) for scoping, disabling flags, ASCII/Unicode options, strict `\A`/`\Z` anchors, and CR/LF details. Multiline affects anchors; dot-all affects `.`. Neither implies the other.

### Captures and replacement

1. Enter the Find expression and wait for the valid-pattern status.
2. Run Find All and inspect the matches.
3. Open **View → Toggle Match Report** to inspect capture groups. The right-hand report's `\1 :`, `\2 :`, and similar labels identify capture groups, not match numbers.
4. Enter replacement text. In Regex mode, use `\1` or `\g<name>` to insert captured text.
5. Use **Replace Current Match** for the selected result, or **Replace All** for every match.
6. Inspect the result, then Save when satisfied. Replace All is one document Undo operation.

Example:

```text
Find:    (?m)^(\d+)\.[ \t]+([^\r\n]+)
Replace: Item \1: \2
```

This changes `1. Train staff` to `Item 1: Train staff`. Parentheses create captures; a flag prefix such as `(?m)` does not. With Regex unchecked, backslash references in replacement text remain literal.

Use **Cancel** to stop ongoing search or replacement planning. Editing the document or changing the pattern invalidates old results; search again before replacing. After replacing one match, use Next Match or Find All to establish fresh results.

## Encoding and line endings

These are separate settings. Changing how bytes are interpreted is different from choosing the format to write on Save.

| Menu | Use it when… |
|---|---|
| **Format → Reinterpret As** | Existing text was decoded using the wrong encoding. This rereads the source bytes under the chosen interpretation; handle any unsaved-change prompt first. |
| **Format → Convert on Save** | Text already reads correctly, but the output file needs another encoding. |
| **Format → Keep Source** | Preserve existing line-ending choices, including mixed endings. |
| **Format → LF / CRLF / CR** | Convert line endings when the file is saved. |

Supported profiles include UTF-8, Windows-1252, UTF-16 LE/BE, and UTF-32 LE/BE, with explicit BOM choices where available. Read the complete profile label: byte order and BOM presence matter.

The status bar distinguishes the current format from **on save** changes. Selecting an output conversion does not immediately rewrite the file or change the visible committed EOL markers. After a successful Save, the views and markers reflect the written format.

For mixed line endings, the dialog offers **Keep** or conversion to LF, CRLF, or CR. Choose deliberately; opening a mixed file does not silently normalize it. If output characters cannot be represented in the chosen encoding, address the reported problem or select an appropriate Unicode profile.

### Format Document and Minify Document

For JSON, XML, and Markdown files (detected by extension), **Format → Format Document** re-indents and normalizes whitespace as one Undo step — pretty-printing JSON and XML, and lightly normalizing Markdown heading spacing, list bullets, blank lines, and trailing whitespace. **Format → Minify Document** (JSON and XML only) collapses the document to a compact form. Both are disabled for file types without a formatter.

This is text reformatting only, not a structural refactor: it never reorders JSON keys, renames XML tags, or reflows Markdown paragraphs. JSON must parse and XML must be well-formed first; an invalid document is refused with the reported line and column, left completely unchanged. XML comments, CDATA sections, and any element containing mixed text-and-element content are preserved exactly as written — only purely structural (element-only) nesting gets re-indented. Markdown code fences are left untouched. Very large documents (above roughly 16 million characters) are declined, since formatting needs the whole document in memory rather than UNITI's usual streaming approach for large files.

## Read and inspect text

Use **View → Whitespace** to choose **Off**, **EOL**, **Spaces & Tabs**, **Invisible Unicode**, or **All**. Markers are display aids; they do not insert characters or change file bytes.

For temporary details, hold **Cmd+Option** on macOS or **Ctrl+Alt** on Windows/Linux. This reveals details for the selected whitespace mode; selecting one Unicode code point also gives its inspection readout. Release the modifiers to hide the details. Customize the hold under **Hotkeys → Editor View → Hold to inspect Unicode**.

For a dedicated readout, place the cursor at the character or select it and choose **Tools → Character Inspector…**. A visible character may contain several Unicode code points; the inspector describes one code point at a time.

**View → Soft Line Wrap** wraps the display without inserting line endings. The editor's own zoom controls (also in **View**) are independent of the Find/Replace panel's zoom, which lives in the panel's own controls and affects only that panel.

## Arrange your workspace

Use **File → New Window** for another window. Use **View → Split Right / Split Down** to create another view, or **Close Split** to remove one. Pane controls also provide **Assign Document**, **Dock/Undock**, and splitting. **Move Tab to New Window** moves the active tab.

Views of the same file share edits and Undo/Redo history, while keeping independent cursor and scroll positions. A split is another view, not a copy of the file.

Use **View → Attach/Detach Find & Replace** to switch between the full-width bottom panel and a detached tool window. There is one shared Find/Replace panel; its state follows you across editor windows.

## Appearance and shortcuts

Choose **View → Theme** for System, Light, Dark, Paper, Slate, or a saved custom theme. **High Contrast** is a separate option.

To customize colors, open **Edit Themes…**, select a starting profile, and **Clone** it. Edit the name and colors, inspect the preview, then **Apply**. Built-in themes are read-only. **Cancel** restores the pre-preview appearance; **Reset** restores the draft's last applied or initial clone colors. Custom changes preview across windows.

Open the top-level **Hotkeys** panel, select a category and command, enter a shortcut, then choose **Assign / Change**. Use **Clear**, **Reset Selected**, **Reset Category**, or **Reset All** as needed. Conflicts in overlapping command scopes are reported. The current menu and Hotkeys display are authoritative for your platform and saved overrides; not every command has a default shortcut.

## Sessions and recovery

UNITI restores eligible documents, window/view layout, and Find/Replace state on startup. Saved-file history can also be restored when the file still matches the saved state; retention is bounded, so it is not a backup archive.

When startup presents the **UNITI Recovery Center**, select each entry and inspect the available action:

| Choice | Result |
|---|---|
| **Recover** | Restore available UNITI state into the editor. |
| **Open Disk** | Open the current disk file with fresh history when it changed externally. |
| **Locate Matching File** | Locate the exact file associated with saved state. |
| **Skip** | Keep the evidence for a later decision. |
| **Discard** | Permanently remove that UNITI recovery/session evidence, not the original source file. |

Choose **Continue** after making the decisions. Available choices depend on the entry. Inspect recovered text and Save explicitly when ready.

## Large files and troubleshooting

Large-file indexing, analysis, and navigation can complete progressively. The status bar shows active work. **View → Pause Background Work** pauses background work; Save remains available. Resume it when background analysis is wanted again.

| What you see | What to check or do |
|---|---|
| Valid regex, zero matches | Check Regex mode, case flags, and anchors. Use `(?m)` for line starts; inspect actual line endings. |
| “checking pattern…” | Wait for analysis to complete before starting the search. |
| “text changed — search again” | Re-run the search; previous results belong to older text. |
| Regex timeout or context-limit message | Narrow the expression or reduce expensive/unbounded matching; the operation stopped at its safety limit. |
| Text looks garbled | Inspect the encoding preview and consider Reinterpret As; conversion alone does not repair a wrong decoding. |
| Save reports an external change | Inspect the disk file and your edits before deciding whether to Reload or Save As to another path. |
| Terminal stays occupied | Closing the last window retains an empty editor. Use Quit to exit. If explicit Quit still hangs, report it. |
| Startup fails | Keep the exact error and phase. Follow the targeted guidance or [development repair instructions](project/01_current/DEVELOPMENT.md); avoid deleting session/recovery files as a first step. |

For a report, include the UNITI version and OS, steps, expected/actual behavior, exact error, and a small sample that reproduces the issue. **Tools → Diagnostics…** helps inspect the current environment; review any paths or document details before sharing. **Export Dogfood Evidence…** and **Clear Dogfood Evidence…** support the current testing program when enabled.

The current beta includes bundled Indic/Chinese/Korean fallback and LTR editing; physical Chinese/Korean IME qualification is still open. Advanced full Unicode case-folding searches have an open boundary qualification issue ([BF-012](project/BETA_FEEDBACK.md#bf-012--full-unicode-case-folding-misses-a-match-with-one-character-search-windows)). RTL/mixed-direction editing, syntax highlighting, integrated Git, plugins, and polished installers are outside the current delivered scope. [Current Status](project/01_current/STATUS.md) tracks remaining qualification.
