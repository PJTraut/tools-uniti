# XML

XML documents (USX, project settings, and any other XML). See the [overview](README.md).

- **Extensions:** `.xml`.
- **Highlighting:** tags, attributes, values, comments and CDATA, including ones that span lines.

## Commands

| Command | Shortcut | What it does |
|---|---|---|
| Format Document | Ctrl+Alt+Shift+F | re-indents the document, one undo step |
| Minify Document | — | removes the whitespace between elements |
| Check Well-Formedness | Ctrl+Alt+V | parses the document with Python's standard XML parser and reports the first error with its line and column |

Check Well-Formedness needs the whole document in memory, so files above 1 MiB aren't checked. UNITI doesn't validate against a DTD or schema.

## Configuration

Your configuration folder is `…/Environments/XML/`; nothing reads from it yet. A future schema-aware check would read declared schemas from here.
