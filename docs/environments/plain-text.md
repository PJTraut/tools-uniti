# Plain Text

The default editor environment. Any extension no other environment owns opens here, as does any file opened with **Open as Plain Text**. See the [overview](README.md).

- **Extensions:** everything not assigned to another environment (`.txt`, `.log`, `.sty`, `.vrs`, …). Files you open as plain text are pinned here too.
- **Features:** the editor itself, with no extended features: no highlighting, environment commands, views or checks. Find/Replace, regex, encodings, line endings, whitespace markers, splits, Compare and the Character Inspector all work as usual; they belong to the editor, not to an environment.
- **Menu:** "No environment tools for plain text", **Move to Environment Window** (a "Plain Text — <group>" window), **Configuration Files…**, **Environment for This Document** (pin this file to another environment) and **File Type Environments…**
- **Configuration:** only your configuration folder (`…/Environments/Plain Text/`); nothing reads from it yet.

To give a file opened as plain text its features back, choose **Environment for This Document → By Extension**.
