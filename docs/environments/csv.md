# CSV

Comma-separated values. See the [overview](README.md) and [TSV](tsv.md).

- **Extensions:** `.csv`.
- **Highlighting:** quoted fields and separators.

## Commands

| Command | Shortcut | What it does |
|---|---|---|
| Check Column Counts | Ctrl+Alt+V | reports each row whose number of fields differs from the first row's |

Fields are counted with Python's `csv` module, so quoted commas and quoted line breaks are handled correctly. At most 500 findings are listed.

## Configuration

Your configuration folder is `…/Environments/CSV/`; nothing reads from it yet.
