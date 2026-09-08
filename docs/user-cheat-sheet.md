# UNITI User Cheat Sheet

**v0.001b2** · [User Manual](user-manual.md) · [Regex Flags Guide](regex-flags.md)

## Everyday actions

Common defaults below use **Ctrl on Windows/Linux** and **Cmd on macOS**. Check **Hotkeys** or the menu for your current bindings.

| Action | Shortcut / location |
|---|---|
| Open | Ctrl/Cmd+O · File → Open… |
| Save | Ctrl/Cmd+S · File → Save |
| Save a copy with format options | Ctrl/Cmd+Shift+S · File → Save As… |
| Undo | Ctrl/Cmd+Z · Edit → Undo |
| Cut / Copy / Paste | Ctrl/Cmd+X / C / V |
| Select All | Ctrl/Cmd+A |
| Find | Ctrl/Cmd+F · Find → Find |
| Replace / Next / Previous | Find menu; hover over panel icons for action names |
| Go to Line | Edit → Navigation → Go to Line… |
| Wrap / Zoom / Split | View → Editor View |
| Attach or detach Find/Replace | View → F/R View |
| Exit | Quit; on macOS, check the UNITI application menu |

**Remember:** Closing the last window keeps an empty editor available; Quit exits. Save As to another path creates a copy and keeps the original's editing state. Undo acts on the focused document or Find/Replace field.

## Find and replace

1. **Regex off:** literal text; Case and Whole word apply.
2. **Regex on:** raw expression; use inline flags. Case/Whole word are disabled.
3. Run **Find All**, inspect matches, then **Replace Current Match** or **Replace All**.
4. Click the document and Undo to reverse Replace All in one step. Save when ready.

**View → F/R View → Toggle Match Report** shows capture groups. Next/Previous also work before Find All. After editing text or changing the pattern, search again.

## Regex essentials

| Syntax | Meaning |
|---|---|
| `(?i)` | Ignore case |
| `(?m)` | Make `^` and `$` recognize line boundaries |
| `(?s)` | Let `.` include newlines |
| `(?x)` | Free-spacing and `#` comments; escape literal spaces/hashes outside `[...]` |
| `(?im)` | Combine ignore-case and multiline |
| `(?i:apple)` / `(?-i:ID)` | Enable / disable case-insensitivity for one group |
| `\A` / `\Z` | Strict document start / end |
| `\1` / `\g<name>` | Insert a captured group in replacement text |

**Without `(?m)`, `^` means document start.** `$` can also match before a final LF. `m` affects anchors; `s` affects the dot. See the guide for ASCII/Unicode flags and CR-only line endings.

Numbered lines → labelled entries:

```text
Find:    (?m)^(\d+)\.[ \t]+([^\r\n]+)
Replace: Item \1: \2
```

`1. Train staff` becomes `Item 1: Train staff`. Enter expressions directly, without quotes or slash delimiters.

## Text format and inspection

| Need | Action |
|---|---|
| Correct a wrong decoding | Format → Encoding → Reinterpret As |
| Write another encoding | Format → Encoding → Convert on Save |
| Preserve / convert EOLs | Format → Line Endings → Keep Source / LF / CRLF / CR |
| Show hidden characters | View → Editor View → Whitespace |
| Temporary Unicode details | Hold Cmd+Option (Mac) / Ctrl+Alt (Windows/Linux) |
| Inspect one code point | Tools → Character Inspector… |
| Theme / contrast / colors | View → Theme → select profile / High Contrast / Edit Themes… |

**“On save” is pending.** Format conversion takes effect on Save; wrap and whitespace markers only change the display.

## When something looks wrong

- Zero regex matches: check `(?m)`, case, and actual EOLs.
- “Text changed”: run the search again.
- Recovery choice unclear: **Skip** keeps evidence; **Discard** removes it.
- External-change warning: inspect before Reload or Save As.
- A bug report: include version, OS, steps, exact error, and a small reproducing sample. Use **Tools → Diagnostics…** for environment details.
