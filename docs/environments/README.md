# Environments

Every file UNITI opens lives in an **environment**: a set of tools, views, checks and configuration for one kind of file. A JSON file gets Format and Check Brackets. A USFM file gets Standard and Preview, a Book/Chapter/Verse selector and stylesheets. A plain text file gets the plain editor and nothing else.

| Environment | Extensions (default) | Page |
|---|---|---|
| Plain Text | anything not listed below | [plain-text.md](plain-text.md) |
| Markdown | `.md`, `.markdown` | [markdown.md](markdown.md) |
| XML | `.xml` | [xml.md](xml.md) |
| JSON | `.json` | [json.md](json.md) |
| YAML | `.yaml`, `.yml` | [yaml.md](yaml.md) |
| USFM | `.usfm`, `.sfm` | [usfm.md](usfm.md) |
| CSV | `.csv` | [csv.md](csv.md) |
| TSV | `.tsv` | [tsv.md](tsv.md) |

Extensions are matched without regard to case: `.SFM`, `.sfm` and `.Sfm` are the same.

## Opening a file

When you open a file whose extension belongs to an environment other than Plain Text, UNITI asks how to open it:

- **Open in <Environment> Environment** (the default): the file goes to that environment's window, with all its tools.
- **Open as Plain Text**: the file stays in the window you opened it from, in the Plain Text environment. That means **no extended features** while you work on it: no environment commands, views, checks or sync. Choose **Environment for This Document → By Extension** to give it its environment back.
- **Cancel**: nothing opens.

Some opens don't ask:
- **Open Folder by Type…** asks once for the whole batch.
- **Already open:** a file that's already open is simply brought to the front.
- **Environment windows:** inside an environment window (File → Open, Recent Files, the Book selector, Open USFM Project…), files open in that environment, as described next.
- **Session restore:** files restored at startup come back where they were.

## Environment windows

An environment window is an ordinary UNITI window for **one environment and one document group**, for example "USFM — A". It has tabs, splits, Find/Replace and saving like any window, plus a toolbar across the top. The toolbar holds the environment and group, the view-mode buttons (for USFM: Plain Text / Standard / Preview) and the environment's own controls (for USFM: Book, Chapter, Verse and Sync).

Ways a file gets there:
- **Opening:** "Open in <Environment> Environment" in the dialog above.
- **Moving:** **Move to Environment Window** in the environment menu. **Dock** (on the tab) takes the file back where it came from.
- **Pinning:** choosing an environment in **Environment for This Document**. The file moves to that environment's window.
- **Opening inside the window:** a file opened inside an environment window lives there.
  - It's pinned to that environment and joins the window's group.
  - If its extension isn't assigned to that environment, UNITI asks "Open as <Environment>?" first.
  - A file that's already open somewhere else moves in.

Environment windows come back when UNITI restarts.

A file in an environment window belongs to that window's group.
- **One file:** give it another group (right-click its tab or its text → **Document Group**) and it moves to that group's environment window. **Dock** still takes it back where it came from.
- **The whole window:** use the **Group** dropdown on the toolbar. Choosing a group regroups every file in the window.
  - If that group has no window of this environment yet, this window becomes it (e.g. "USFM — A").
  - Otherwise the files join that window and this one closes.
  - The dropdown also has **New Group…** and **Manage Groups…**. This is the quick way to put texts side by side for sync.

## Undefined markup

Where an environment knows its vocabulary, opening a file checks it. Today that's USFM: markers no loaded stylesheet defines pop up a report, which you can copy, save, or use to add the missing definitions. See [usfm.md](usfm.md#undefined-markers).

## The environment menu

The menu between **View** and **Tools** is named after the active tab's environment (e.g. **USFM**, or **JSON (Plain Text)**). It holds:
- that environment's commands (see each page);
- **View As:** the view modes, when the environment has any;
- **Move to Environment Window**;
- **Configuration Files…**;
- **Plain Text Mode**;
- **Environment for This Document**;
- **File Type Environments…**

Commands shared by several environments keep one shortcut, and you can rebind them under **Hotkeys**. On macOS, Ctrl means Cmd and Alt means Option.

| Slot | Default shortcut | What it does |
|---|---|---|
| Format Document | Ctrl+Alt+Shift+F | the environment's formatter (JSON, XML, Markdown) |
| Minify Document | — | the environment's minifier (JSON, XML) |
| Validate | Ctrl+Alt+V | the environment's main check |
| Go To | Ctrl+Alt+G | Go to Chapter:Verse… (USFM) |
| Preview | Ctrl+Alt+P | Markdown Preview |
| Plain Text Mode | Ctrl+Alt+T | this tab without environment features, until turned off |
| Inspect | Ctrl+Alt+S | Inspect Marker at Cursor (USFM) |

**Plain Text Mode vs. Open as Plain Text.** Both work in the plain editor:
- **Plain Text Mode** is a per-tab switch that keeps the file's environment. The menu says e.g. "USFM (Plain Text)", and one click turns it back on.
- **Open as Plain Text** puts the file in the Plain Text environment itself.

## Assigning extensions

**View → File Type Environments…** shows one row per environment, with every extension it owns. Type extensions to move them, e.g. `.ptx` onto USFM. UNITI saves only your changes from the defaults. Open files switch environment straight away.

## Configuration

Each environment has configuration files. **Configuration Files…** in the environment menu lists every one that applies to the current file, in the order they apply (later rows win). From there you can:
- **Open** a file to edit it in UNITI;
- **Create** one that doesn't exist yet, from a commented template;
- **Copy to My Configuration and Open** a built-in file, to read it (built-in files can't be changed);
- **Show in Folder**;
- open this documentation.

Saving a stylesheet (`.sty`), a versification file (`.vrs`), `Settings.xml` or `BookNames.xml` reloads the environment's configuration everywhere, so Standard and Preview update straight away.

**Your configuration folder** holds your own files for each environment, next to UNITI's settings:

| System | Folder |
|---|---|
| macOS | `~/Library/Application Support/UNITI/Environments/<Environment>/` |
| Windows | `%LOCALAPPDATA%\UNITI\Environments\<Environment>\` |
| Linux | `$XDG_CONFIG_HOME/uniti/Environments/<Environment>/` (usually `~/.config/uniti/…`) |

Today only USFM reads files from it: your `uniti.sty` and your `Versification/*.vrs` files. See [usfm.md](usfm.md#configuration-files).

UNITI writes into a project's folder only when you ask it to: **Create** in Configuration Files…, or saving a file you opened. It never writes there by itself (ADR-0018).
