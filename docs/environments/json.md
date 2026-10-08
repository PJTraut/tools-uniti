# JSON

JSON documents (USJ, configuration files, data). See the [overview](README.md).

- **Extensions:** `.json`. A different extension, such as `.usj`, can be added under **File Type Environments…**
- **Highlighting:** strings, numbers, keywords and punctuation.

## Commands

| Command | Shortcut | What it does |
|---|---|---|
| Format Document | Ctrl+Alt+Shift+F | re-indents with two spaces; the document must parse as JSON |
| Minify Document | — | removes all optional whitespace |
| Check Brackets | Ctrl+Alt+V | reports unmatched `{}` / `[]`, ignoring brackets inside strings |

Check Brackets is a bracket check, not a full JSON parser: it doesn't report missing commas, bad numbers or duplicate keys. Formatting does parse the document, and says so when it can't. Format and Minify work on files up to 16 MiB.

## Configuration

Your configuration folder is `…/Environments/JSON/`; nothing reads from it yet.
