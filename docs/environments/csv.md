# CSV

Comma-separated values. See the [overview](README.md) and [TSV](tsv.md).

- **Extensions:** `.csv`.
- **Highlighting:** quoted fields and separators.

## Commands

| Command | Shortcut | What it does |
|---|---|---|
| Check Column Counts | Ctrl+Alt+V | reports each row whose number of fields differs from the first row's |

Fields are counted with Python's `csv` module, so quoted commas and quoted line breaks are handled correctly. At most 500 findings are listed.

## Settings

**Environment Settings…** (saved in `settings.json`), used by Check Column Counts:

| Setting | Values | Default |
|---|---|---|
| Delimiter | `,` `;` `\|` or Tab | `,` |
| Quote character | `"` or `'` | `"` |
| First row is a header | on: the report names the header as the row the others must match | on |

## Configuration

Your configuration folder is `…/Environments/CSV/`. It holds `settings.json` and `groups.json`.
