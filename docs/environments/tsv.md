# TSV

Tab-separated values. See the [overview](README.md) and [CSV](csv.md).

- **Extensions:** `.tsv`.
- **Highlighting:** tab separators.

## Commands

| Command | Shortcut | What it does |
|---|---|---|
| Check Column Counts | Ctrl+Alt+V | reports each row whose number of fields differs from the first row's |

At most 500 findings are listed.

## Settings

**Environment Settings…** (saved in `settings.json`), used by Check Column Counts:

| Setting | Values | Default |
|---|---|---|
| First row is a header | on: the report names the header as the row the others must match | on |

## Configuration

Your configuration folder is `…/Environments/TSV/`. It holds `settings.json` and `groups.json`.
