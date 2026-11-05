# TXT (plain text)

TXT is the default editor environment. Any extension no other environment owns opens here, as does any file opened with **Open as Plain Text**. See the [overview](README.md).

- **Extensions:** everything not assigned to another environment (`.txt`, `.log`, `.sty`, `.vrs`, …). Files you open as plain text are pinned here too.
- **Features:** the editor itself, with no extended features: no highlighting, environment commands, views or checks. Find/Replace, regex, encodings, line endings, whitespace markers, splits, Compare and the Character Inspector all work as usual; they belong to the editor, not to an environment.
- **Menu:** "No environment tools for plain text", **Move to Environment Window** (a "TXT/1" window), **Configuration Files…**, **Environment Settings…** (TXT has none; the dialog says so), **Assign Environment** (pin this file to another environment) and **Assign by File Type…**
- **Configuration:** only your configuration folder (`…/Environments/Plain Text/`, the folder's name on disk), which holds TXT's `groups.json`.

To give a file opened as plain text its features back, choose **Assign Environment → By Extension**.
