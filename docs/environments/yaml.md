# YAML

YAML documents. See the [overview](README.md).

- **Extensions:** `.yaml`, `.yml`.
- **Highlighting:** keys, strings, numbers, comments, and block scalars (`|`, `>`) across lines.

## Commands

| Command | Shortcut | What it does |
|---|---|---|
| Check Indentation | Ctrl+Alt+V | reports lines whose indentation contains a tab, which YAML forbids (errors), and indentation off the Indent width setting (warnings) |

UNITI doesn't parse YAML or validate it against a schema. Check Indentation catches the most common cause of a file that won't load.

## Settings

**Environment Settings…** (saved in `settings.json`):

| Setting | Values | Default |
|---|---|---|
| Indent width | 1–8; Check Indentation warns about a line indented by something other than a multiple of it | 2 |

Blank lines, comments and the text of a block scalar (`|`, `>`) aren't checked. A width of 1 turns the warning off.

## Configuration

Your configuration folder is `…/Environments/YAML/`. It holds `settings.json` and `groups.json`.
