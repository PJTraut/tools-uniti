# Markdown

Markdown documents. See the [overview](README.md).

- **Extensions:** `.md`, `.markdown`.
- **Highlighting:** headings, emphasis, code, links and list markers.

## Views

| Mode | What it shows | Editing |
|---|---|---|
| Plain Text | the Markdown source | yes |
| Preview (the Rendered view) | headings sized, emphasis, code and quotes formatted; the syntax characters hidden; list bullets as "•"; lines match the source's lines | yes: Bold, Italic, Code, Heading…; Enter continues a list |

The rendering covers a CommonMark subset. Anything it doesn't recognise stays visible as text.

## Commands

| Command | Shortcut | What it does |
|---|---|---|
| Markdown Preview | Ctrl+Alt+P | a read-only rendered preview beside the editor, updating as you type |
| Format Document | Ctrl+Alt+Shift+F | tidies the whole document in one undo step (details below) |

What Format Document changes:
- one space after a heading's `#`s;
- `-` for every list bullet;
- at most one blank line in a row;
- no trailing whitespace;
- code fences left exactly as written.

There's no Validate: Markdown has no strict grammar to check against.

## Configuration

Your configuration folder is `…/Environments/Markdown/`; nothing reads from it yet.
