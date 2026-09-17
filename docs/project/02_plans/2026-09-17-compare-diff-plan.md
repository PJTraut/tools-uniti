# Compare/Diff — Implementation Plan

Date: 2026-09-17
Status: **Phase 1 (plain view, two open documents) implemented and integrated on `main`.** Phases 2 (merge-style editing) and 3 (doc-vs-disk mode) are not yet started. This document exists to turn the [Feature Wishlist](../FEATURE_WISHLIST.md)'s unscoped "Compare files" idea into a concrete task breakdown before any code is written; see "Progress" below for what actually landed.
Feedback: [BF-070](../BETA_FEEDBACK.md#bf-070--comparediff-between-two-documents)
Milestone: a new workstream inside the active [B3 milestone](v0.001b3-find-replace-and-editor-refinement-beta.md), following the same "planned before implementation" pattern the [RTL/bidi plan](../03_implemented/milestones/2026-09-15-rtl-bidi-support-plan.md) used.

## Progress

**Phase 1 implemented 2026-09-17**, matching the draft task breakdown below with two deliberate, documented deviations:

- `uniti.core.text_diff` (new, Qt-free): `HunkKind`, `Hunk`, `diff_lines`, `changed_hunks`, `align_left_to_right`/`align_right_to_left` — exactly as planned. `tests/core/test_text_diff.py` (10 tests).
- `ComparePane` (`src/uniti/ui/compare_pane.py`): two read-only, non-wrapping `QPlainTextEdit` panes with a hunk-colored gutter (`_HunkGutter`, following Qt's standard line-number-area pattern) and full-row `ExtraSelection` highlighting, opened via a new **Tools → Compare…** menu entry and a `CompareDocumentPickerDialog`. Scroll sync and hunk navigation (Previous/Next buttons) both use the line-alignment mapping. Staleness recompute mirrors `UNITITextView`'s own pattern exactly: `document.add_history_listener` with a `weakref`-held callback, marshaled onto the GUI thread through a queued Qt signal. A 4 MiB provisional size cap (`MAX_COMPARE_CHARS`) guards both sides before any read. `tests/ui/test_compare_pane.py` (8 tests) and 3 menu-integration tests in `tests/ui/test_main_window_contract.py`. Full suite green: 2,012 passed (21 new), 6 platform skips, no regressions.
- **Deviation 1 — document picker scope.** The plan named `DocumentRegistry.entries` (service-wide, across every window) as the candidate source; the picker actually built reuses `show_diagnostics`'s existing pattern instead (`dict.fromkeys(view.document for view in self.views)` — the *current window's* open tabs only). Simpler, requires no `_service` wiring, and works identically in the common one-window case; a user with documents split across two windows can't yet compare across them. Worth widening to `DocumentRegistry.entries` in a follow-up if that turns out to matter in practice.
- **Deviation 2 — no line-padding for visual row alignment.** Not called out as an open question originally, but a real design choice made during implementation: the two panes do **not** insert blank placeholder lines to keep row *N* on the left visually beside its counterpart on the right (the way most side-by-side diff tools do). They scroll in sync via the alignment mapping instead, but within an unequal-length hunk the two panes' visible rows are not pixel-aligned line-for-line. Full padding is a real follow-up, not attempted here — it would also change how the gutter's line numbers and the `_HunkGutter` painting work.
- Open question 3 (size bound) has a real number now, not just a recommendation: **4 MiB per side**, chosen precautionarily (Compare reads two buffers plus a diff pass, vs. Format Document's one buffer for its 16 MiB cap) and explicitly marked provisional in code — still not empirically tuned against a real large-file prototype.
- Not yet done: Phase 2 (apply/reject hunks, `Document.replace_many`) and Phase 3 (doc-vs-disk mode) are both unimplemented, exactly as planned — see the task breakdown below, unchanged for those phases.

## Scope (confirmed with the user)

- **Comparison sources, both in scope:** (a) two currently open documents, chosen by the user; (b) one open document against its saved-on-disk content (for reviewing unsaved edits).
- **Presentation:** a side-by-side view (two panes shown next to each other, changes highlighted per line).
- **Editing model:** both a plain non-interactive view (side-by-side, highlighted, no apply/reject controls — pure review) and a merge-style editable mode (apply or reject individual changed hunks between the two sides) are in scope. Whether these are two explicit modes the user switches between, or one surface where merge controls are simply absent for a source pairing that can't sensibly be edited (see open question 2, doc-vs-disk), is an implementation-time decision — not yet settled.

## Why this is tractable: reusable pieces already in the codebase

Nothing here needs a new architectural boundary; this is a presentation- and command-layer feature built on primitives that already exist for other reasons.

- **Atomic multi-range apply:** `Document.replace_many(replacements: list[tuple[int, int, str]])` (`src/uniti/core/document.py:649`) applies any number of non-overlapping original-coordinate replacements as **one** history transaction. This is exactly the primitive "apply this hunk" and "apply all remaining hunks" need — no new document-level edit API is required.
- **Enumerating open documents:** `DocumentRegistry.entries` (`src/uniti/app/document_registry.py`) already gives every live `DocumentEntry` (canonical path, the authoritative `Document`) process-wide — the natural source for a "pick a second open document" picker in comparison mode (a).
- **Whole-buffer read, bounded:** Format Document (`UNITIMainWindow._reformat_current_document`, `main_window.py:2519`) and the Markdown preview (`_refresh_markdown_preview_now`) both already read an entire document into memory synchronously (`document.read(0, document.total_chars())`), gated by a size cap (`MAX_REFORMAT_CHARS`, 16 MiB, `core/reformatters.py:31`) before doing so. Compare should follow this exact "bounded synchronous whole-buffer read" pattern rather than inventing a background-task pipeline on day one — see open question 4.
- **Staleness key:** `document.revision` is already the standard invalidation key for every derived/cached view of document content (search, the wrapped/horizontal layout caches, BF-064's per-line direction cache). A computed diff must key off **both** sides' revisions the same way, so an edit made elsewhere to either open document is never silently shown as an already-stale comparison.
- **No existing diff engine.** `difflib`/`SequenceMatcher` is not used anywhere in the codebase today (confirmed by search). Python's stdlib `difflib.SequenceMatcher.get_opcodes()` run over each side's line list is the natural fit — `DocumentLineIndex` already indexes documents by line, so line-granularity diffing aligns with a unit the app already navigates by, rather than introducing a new document-shape concept.
- **Highlight-painting precedent:** BF-064's `UNITITextView._span_rect` and the existing selection/search-match highlight painting are the closest existing overlay mechanism for drawing a hunk's changed-region background. Per the current architecture, "Markers are transient overlays over committed text" (whitespace markers, search matches) — hunk highlighting should follow that same model rather than a new one.
- **What does *not* already exist:** synchronized scrolling between two panes, and a shared hunk gutter with next/previous navigation and per-hunk apply/reject controls. Today's pane splitter (`panes.py`) gives independent views with independent scroll positions — real, new UI work, not a reuse of existing split behavior.

## Resolved design decisions

Settled by reading the existing codebase for direct precedent, not guessed.

- **Compare surface: non-modal, attached beside the pane tree — not a dialog, not an ordinary tab.** Two existing patterns were compared directly: `CharacterInspectorDialog`/`DiagnosticsDialog` (`main_window.py:2957`/`:2985`) are shown with `dialog.exec()` — **modal**, blocking interaction with the rest of the window. `MarkdownPreviewPane` (`main_window.py:2485`) instead attaches directly into `self._central_splitter` alongside `self._panes` (`self._central_splitter.addWidget(self._markdown_preview)`, then `setSizes([1, 1])` for an even split) — **non-modal**, coexisting with ongoing editing. Compare must be non-modal: applying a hunk mutates a live `Document` that may simultaneously be open in an ordinary tab, and the user needs to keep working while comparing. Recommendation: a new `ComparePane` widget attached into `_central_splitter` the same way, but — unlike Markdown preview, which is a single read-only render tied to one source tab and auto-closes when that tab closes — Compare owns its own internal splitter with two independent text panes and has its own explicit close action, since it isn't "attached to" any single tab (its two sides can be two arbitrary open documents, or one open document plus disk content that isn't a tab at all).
- **Menu placement: Tools → Compare…**, alongside the existing auxiliary-tool entries in that menu (Character Inspector…, Diagnostics…, `main_window.py:1176`) — Compare is an auxiliary tool opened on demand, not a File-menu document-lifecycle action (Open/Save/Recent) or a View-menu display-preference toggle.
- **Synchronized scrolling needs a line-alignment mapping, not a raw scrollbar link.** The two sides generally have different line counts after insertions/deletions, so linking the two `QScrollBar`s by raw value (or even by proportional position) will drift out of alignment inside any hunk of unequal length. The diff engine's hunk list is already exactly the alignment table needed: for a source-side line `L`, find the enclosing hunk `(kind, i1, i2, j1, j2)`, compute `L`'s fractional position within `[i1, i2)`, and map to the same fractional position within the other side's `[j1, j2)` (clamping into the target range for an `insert`/`delete` hunk, which has zero length on one side). This mapping is pure data (over the already-computed hunk list) — cheap to recompute whenever the diff itself recomputes (task 6), so it does not need any separate caching of its own.

## Genuinely open design questions

Flagged explicitly rather than guessed silently, following this project's convention (see the RTL/bidi plan's own "needs a decision once implementation starts" notes). Each has a recommendation, not a final answer.

1. **The disk side of doc-vs-disk mode.** On-disk content has no file identity of its own to save independent edits back to — it isn't a real open document. *Recommendation:* the disk side is read-only reference text; the only merge action available there is "revert this hunk in the live document to match disk," not free editing of the disk-side pane. A user who wants to edit that content as its own document already can, via ordinary Open, and would then use two-open-documents mode instead.
2. **Recompute strategy when a compared document changes elsewhere.** A document open in Compare mode (a) may be the very same `Document` a user is actively editing in an ordinary tab. *Recommendation:* recompute the whole diff on any relevant revision change (mirrors Format Document's whole-buffer-at-once simplicity) rather than building an incremental hunk-patching engine now; revisit only if real large-file testing shows recompute is too slow.
3. **Size bound.** Format Document's 16 MiB cap gates one buffer read plus one formatter pass; Compare needs two full buffer reads plus a diff pass — likely a different, probably smaller, bound. *Recommendation:* needs empirical numbers from a real prototype rather than a guessed constant now.
4. **Intra-line highlighting.** Whole-changed-line (hunk-level) highlighting is the achievable first cut. Character-level "exactly which words changed within a line" highlighting is a materially separate, harder pass (its own `SequenceMatcher` per changed line, plus per-line overlay geometry). *Recommendation:* defer to a follow-up, the same way BF-064 deferred embedding-level caret affinity out of its own first pass, rather than blocking the first landing on it.

## Draft task breakdown, in delivery order

Subject to change once the remaining open questions above are resolved at implementation time. Ordered so each phase is independently useful rather than landing as one large all-or-nothing change — the same incremental-workstream pattern BF-064 (RTL/bidi) and BF-063 (syntax color editing) both used.

**Phase 1 — plain view, two open documents only:**

1. **`uniti.core.text_diff`** (new, Qt-free, mirrors `uniti.core.bidi`'s shape) — line-level diff between two text buffers via `difflib.SequenceMatcher`, returning a sequence of typed hunks (equal / insert / delete / replace) with original-coordinate line ranges on each side. Also exposes the line-alignment lookup described above, since both the gutter and scroll-sync need it.
2. **`ComparePane` widget** — attached into `_central_splitter` as resolved above; two read-only synchronized text panes (scroll-linked via the line-alignment mapping), a shared hunk-highlighted gutter, and next/previous-hunk navigation. Opened from the new **Tools → Compare…** entry, which first prompts for two open documents (via `DocumentRegistry.entries`).
3. **Hunk highlight painting** — a background color per hunk kind (added/removed/changed), following the existing transient-overlay painting model (`_span_rect` and friends).
4. **Staleness handling** — recompute (or clearly mark stale and require a manual refresh) when either side's `document.revision` changes from an edit made outside the Compare surface.
5. **Tests** — a Qt-free `tests/core/test_text_diff.py` for the diff engine and its line-alignment mapping (mirroring `tests/core/test_bidi.py`'s structure), plus UI tests for the pane, its scroll sync, hunk painting, and staleness recompute.

**Phase 2 — merge-style editing:**

6. **Apply/reject actions** — per-hunk controls calling `Document.replace_many` with that hunk's original-coordinate range and the other side's text, as one undoable transaction; "apply all remaining" mirrors Format Document's single whole-buffer `replace` call.
7. **Tests** — apply/reject/apply-all, each confirmed as one `Undo` step, including the interleaving case where the same document is also open in an ordinary tab.

**Phase 3 — doc-vs-disk mode:**

8. **Comparison-source resolution for disk content** — reads on-disk bytes independent of the live in-memory document, reusing the existing verified-read path already trusted for save/hash reconciliation; feeds `text_diff` the same way an open document does, but marked read-only per open question 1.
9. **Tests** — an open document with unsaved edits compared against its own saved bytes; confirms the disk side rejects apply/reject controls.

## Out of scope (first pass)

- Three-way merge / conflict resolution.
- Comparing content across a transformation (e.g., a live document against a Format-Document-reformatted version of itself).
- A persisted "compare session" surviving an app restart.
- Character-level intra-line highlighting (see open question 5).
