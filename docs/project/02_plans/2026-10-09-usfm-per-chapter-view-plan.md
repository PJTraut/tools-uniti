# USFM Per-Chapter View — Plan

Date: 2026-10-09
Status: **Implemented** (2026-10-09): C1–C4.
Origin: the [wishlist](../FEATURE_WISHLIST.md) entry "USFM per-chapter view" (2026-10-07 field test: "have option to view per chapter or per book"), un-paused by the user 2026-10-09 ("do USFM per chapter view option").

## The user's answers, 2026-10-09

- **Modes:** all three: Plain Text, Standard and Preview.
- **Scope:** per window. One toggle covers every tab and split of an environment window.
- **Chapter edges:** the caret stops at the edge. Arrow keys, clicks and scrolling stay in the chapter. The chapter changes through the Chapter selector, sync, Go to Chapter:Verse and Find; Find still searches the whole book.

## Design

**The shown chapter is the one the caret is in.** Nothing else is stored. A move the user makes in the view (keys, mouse, Select All) is kept inside the chapter it started in; any other move — the Chapter or Verse selector, Go to Chapter:Verse, sync, Find, undo — puts the caret in another chapter, and the view follows it.

**A chapter is whole lines:** from its `\c` line up to the line before the next `\c`. The lines before the first `\c` (the book's identification, headers and introduction) belong to the first chapter. A text without `\c` is shown whole. So is a text above 1 MiB, the limit of the reference map that finds the chapters (the same limit as Standard and Preview).

**Decisions:**
- **D1:** the toggle is **Show One Chapter**, checkable, per window, off by default, in the USFM menu and on the toolbar. It's saved with the session, with the window's identity in each view's `extra` (no schema change). On the toolbar it's the word **Chapter** before the Chapter selector, not a button of its own: a separate "Chapter" button beside Sync took the toolbar to 1,050 px, past the 1,000 px it must stay under since the morning's shortening (`fd7bbe2`).
- **D2:** Select All selects the chapter; Ctrl+Home/End go to its start and end. Backspace at the chapter's start and Delete at its end do nothing: an edit never joins two chapters' lines by itself. Edits that add or remove a `\c` re-divide the chapters, and the view keeps the chapter the caret is in.
- **D3:** a tab opened as Plain Text (the environment's "Open as Plain Text", round 2 R6) isn't narrowed: it has no USFM features.
- **D4:** Preview's notes frame lists only the shown chapter's notes, and a note class with none there is hidden.

## Phases

### C1: Chapter windows (core, Qt-free)
`references.chapter_window(chapter_lines, line, line_count)`: the (first, last) lines of the chapter that `line` is in, given each chapter's `\c` line. `ReferenceMap` counts each chapter's line and the line count from its own text (`\n`, `\r\n` and a lone `\r`, as the document does), so the view never indexes a whole book's lines: asking the document for every chapter's line made each keystroke re-index the book (+70 ms on a 300 KB Psalms). Tests: first chapter with the header, the last chapter, two `\c` on one line, no chapters; the map's lines against the document's for each line ending.

### C2: Plain Text narrowing (`UNITITextView`)
- `line_window_provider`: called with the view, returns its (first, last) lines or None; `line_window()` and `source_window()` read it.
- The vertical scrollbar's range is the window (rows when wrapped); painting stops after its last line.
- `keyPressEvent` and the mouse handlers keep the caret and selection in the window they started in (D2); `_state_changed` re-ranges the scrollbars before scrolling to the caret, so a move into another chapter lands visible.

### C3: Standard and Preview narrowing (`RichViewPane`)
- Blocks outside the target view's `source_window()` are hidden (`QTextBlock.setVisible`), after every render and whenever the window changes.
- A caret the user moves outside the shown blocks is put back (QTextEdit's own Down/Select All walk into hidden blocks); Backspace and Delete stop at the edges (D2).
- The notes frame hides entries outside the window (D4).

### C4: The window toggle
- `ChapterView` (per window): the action, `line_window` as every view's provider (it finds the view's own window, so a tab moved between windows follows that window's toggle), and a refresh of every view and pane when toggled.
- USFM menu and toolbar entries; session save and restore.
- Tests drive the real window: the selector, Go To, sync and Find changing the chapter; keys, clicks and Select All staying in it; the toggle saved and restored.

## Order

C1 → C2 → C3 → C4. Documentation when C4 lands: the [USFM](../../environments/usfm.md) page, the [roadmap](ROADMAP.md)'s environment track queue, and the wishlist entry removed.

## Results

Tests: `tests/test_sfm_references.py` +4 (`chapter_window`, the map's lines with three line endings), `tests/ui/test_line_window.py` (7: the scroll range, keys, Backspace/Delete at the edges, a click below the last line, a move from elsewhere, Select All, wrapped rows), `tests/app/test_chapter_view.py` (7: the toggle; the selector, Go To and Find changing the chapter while keys don't; sync; Preview's text and notes; Standard's caret and edges; a tab opened as Plain Text; the session capture), `tests/app/test_session_orchestration.py` +1 (the restore), and the USFM menu's entries in `tests/ui/test_environment_ui.py`.

On a copy of `usNIVv2`'s Psalms (300 KB, 150 chapters), offscreen: switching chapter took 60–135 ms in Plain Text and 20–135 ms in Preview; turning the view on, 9 ms. Typing cost the same with one chapter shown as with the whole book (176 vs 172 ms a keystroke). That keystroke cost was already there before this work (171 ms).

**Typing speed, the same day.** Of those ~170 ms, about 60 went to re-reading the whole book after each edit for the toolbar's reference map, and most of the rest to the reference map itself and to repainting:
- `decoder.decode_text`: a read that needs only the text (`PieceTable` reads) no longer builds per-character byte boundaries. A non-ASCII span went through a Python loop over every character; valid text in a stable encoding now comes straight from the codec, and anything else still takes `decode_span`. Re-reading the book: 60 ms → under 1 ms.
- `ReferenceMap` looks only at `\c`/`\v` candidates instead of tokenizing the whole book: 20 ms → 4 ms. It finds exactly what the tokenizer did: checked on 3,000 random strings and on every book of `ruCARSv3` and `usNIVv2` (145 books, 64,700 chapters and verses).

A keystroke now takes 16 ms with the whole book and 19 ms with one chapter; switching chapter takes 12–24 ms in Plain Text and 18–65 ms in Preview.

