# Footnote Category Filter — Plan

Date: 2026-10-14
Status: **Implemented** (2026-10-14).
Origin: field test feedback, 2026-10-08 ("`\cat` in footnotes needs to be displayed in [] for now; later feature select category/ies of footnotes to display in preview"), the [wishlist](../../FEATURE_WISHLIST.md) entry "Footnote category filter in Preview"; started by the user 2026-10-14.

## The user's answer, 2026-10-14

- **The categories to choose from are the items in `\cat aa bb cc\cat*`, and "none".** Every word inside a note's `\cat … \cat*` is a category; a note with no `\cat` is in **None**, which is its own entry.

The rest of the wishlist's open questions were decided with the defaults below (not asked: the user answered only the list question).

## Decisions

- **D1: per project tab,** like Check Spelling: the filter is on the tab, saved in each book's view `extra` (`hidden_note_categories`), applies to every book of the tab and to books that join it. A tab seen first takes the union of its books'.
- **D2: stored as the hidden set,** so a category the user has never seen (a new book's) is shown by default.
- **D3: a note is hidden when all of its categories are hidden.** A note in `aa` and `bb` stays while either is shown; a note with no `\cat` is hidden by unchecking **None**.
- **D4: Preview only.** Standard shows the source with every marker, so hiding a note there would hide text being edited; the Source editor is untouched.
- **D5: a hidden note leaves no caller and no body,** and the callers after it number as if it weren't there (a, b, c over the shown notes).

## What was built

- **Core (`sfm/views.py`):** `note_categories(body)`, `source_note_categories(source)`, `note_is_hidden`, `NO_CATEGORY`; `layout_projection(..., hidden_categories)` drops a filtered note in `move_note_to_frame`; `SfmPreviewView.project_filtered`.
- **Rich view:** `ProjectionCache.project(..., variant)` keeps a filtered projection beside the full one (switching the filter back is a cache hit); `RichViewPane.set_hidden_categories` re-renders on a change.
- **Tab setting:** `UNITITextView.hidden_note_categories`, kept in step across a tab by `ProjectTabs.set_note_filter` and `_sync_note_filter`, like Check Spelling.
- **UI (`ui/note_categories.py`):** **USFM → Footnote Categories** and the tab's right-click menu list the book's categories (in order of first appearance), then **None**, each checkable (checked = shown), and **Show All**. A hidden category the book lacks stays listed so it can be shown again.
- **Tests:** `tests/test_note_category_filter.py` (core) and `tests/app/test_note_category_toggle.py` (window).

## Later

- A count of hidden notes in the notes frame's title.
- Categories from the stylesheet or a project list rather than the book's text.
