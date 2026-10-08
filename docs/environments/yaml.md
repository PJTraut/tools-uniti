# YAML

YAML documents. See the [overview](README.md).

- **Extensions:** `.yaml`, `.yml`.
- **Highlighting:** keys, strings, numbers, comments, and block scalars (`|`, `>`) across lines.

## Commands

| Command | Shortcut | What it does |
|---|---|---|
| Check Indentation | Ctrl+Alt+V | reports lines whose indentation contains a tab, which YAML forbids |

UNITI doesn't parse YAML or validate it against a schema. Check Indentation catches the most common cause of a file that won't load.

## Configuration

Your configuration folder is `…/Environments/YAML/`; nothing reads from it yet.
