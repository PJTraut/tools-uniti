# USFM Hyphenation, Justification and Spelling Follow-ups — Plan

Date: 2026-10-15
Status: **Implemented** (2026-10-15): H1–H3, J1, F1–F5 and the documentation sweep, each phase committed on its own. See [As built](#as-built) for where the code differs and what was measured.
Origin: the user, 2026-10-15: "start with the spellcheck follow-ups and hyphenation in preview; also add justification options for UNITI .sty extension; document all USFM 'css' extension features". Builds on the [spellcheck plan](2026-10-13-usfm-spellcheck-plan.md) (its "Later" list) and the [wishlist](../../FEATURE_WISHLIST.md) entry for hyphenation.

## What was checked first

- **Qt breaks at U+00AD and prints the hyphen only at a line end.** Measured 2026-10-15 in a `QTextEdit` with a justified block: `pre­tended` and `un­der­stand` broke as "under-" / "stand", with a hyphen drawn there and nowhere else, and `toPlainText()` kept the U+00AD characters. So Preview needs no layout code of its own: its projection puts U+00AD at the break points.
- **S1's loader already keeps the break points** (`HyphenatedWordsData.words` maps a word to its `=`-marked line) and the settings (`HardHyphen`, `SoftHyphen`, `SoftHyphenOut`, `HyphenatedMarkers`), so hyphenation needs no new parsing except `HyphenatedMarkers`' list.
- **`\Justification` already works** in the stylesheets (`Left`, `Center`, `Right`, `Both`, with `Justify` as an alias), for markers and for rules, in Standard and Preview. What's missing is direction-aware values and a way to turn hyphenation on and off per marker, which is where justified text needs it.
- **The "css" extension is the `uniti.sty` rules**: `a+b` and `marker::caller` selectors, comma lists, the level-1 equivalence, `-` to turn a flag off, ordinary marker records in a `uniti.sty`, and the five layers. [USFM Stylesheet Rules](../../../usfm-stylesheet-rules.md) documents part of it; this plan's last phase makes it complete.

## Decisions

- **H-D1: Preview only.** Standard and Plain Text show the source you edit; a U+00AD there would be text the source doesn't have. The notes frame is not hyphenated either.
- **H-D2: per project tab, off by default, like Check Spelling and the footnote filter.** **Hyphenate Preview** is on the tab's right-click menu and in the USFM menu. It is greyed out for a project with no `hyphenatedWords.txt` ("NIV has no hyphenation list (hyphenatedWords.txt)"). It's saved in each book's view `extra` as `hyphenate_preview`.
- **H-D3: which paragraphs (answers the wishlist question).** In order: a stylesheet's `\Hyphenate` field for the marker (`Yes`/`No`, any layer, so `uniti.sty` can decide); otherwise the file's `HyphenatedMarkers` list; otherwise every paragraph whose `\TextType` is `VerseText`. Headings, poetry and titles aren't in `usNIVv3`'s list, so they stay unhyphenated.
- **H-D4: which words.** Only words in the file break, at the file's `=` points. A hyphenated word (`well-watered`) is looked up whole, then each part (Qt already breaks after the hyphen). Starred lines are used like any other, unless they hold a space (they're damaged, as the spellcheck plan found, and are skipped by the loader already). A word not in the file never breaks: no automatic rule.
- **H-D5: copy and selection.** The U+00AD characters are generated segments, so the source map skips them: the caret, sync, Find and spelling underlines keep their source offsets. Copying from Preview takes the source text of the selection, never a U+00AD.
- **J-D1: justification values.** `\Justification` takes `Left`, `Center`, `Right`, `Both` (and `Justify`), and the new `Start` and `End`, which follow the paragraph's reading direction (a right-to-left paragraph's `Start` is its right edge). `Left` and `Right` are the physical edges (see [As built](#as-built)). Anything else is ignored, as before.
- **J-D2: a `\Hyphenate` field** (H-D3), the only new UNITI stylesheet field. Paratext and PTXprint ignore unknown fields, so it's safe in a `custom.sty`, but the rules belong in `uniti.sty`.
- **F-D1: approving and rejecting words** go into UNITI's own list, never `SpellingStatus.xml` (ADR-0018 stands). One file per project, `…/Environments/USFM/Spelling/<project short name>.json`: `{"approved": [...], "rejected": [...]}`, words as typed. It sits above the Paratext lists: an approved word is correct, a rejected one wrong, whatever they say.
- **F-D2: suggestions** come from the word lists: the words within edit distance 1 (2 for words of 8+ letters) of the flagged word, case-matched, by frequency-free alphabetical order after Paratext's Correction. No new dictionary and nothing fetched.
- **F-D3: word pairs** (`go at` R, `grain field` W): a `W` pair flags both words (wrong), found where two checked words are separated by exactly one space or a line break inside a paragraph. An `R` pair has no effect (its words are judged singly).
- **F-D4: Next/Previous issue** walk the document's flagged spans in source order from the caret, wrap with a status-bar note, and move the caret (so every mode and sync follows). The status bar shows the book's count of wrong / unknown words while checking is on.
- **F-D5: `WordPrefixes`/`WordSuffixes`** from the project's `Settings.xml`: a word unknown by itself is correct when stripping one listed prefix or suffix leaves a word that is correct (`Paul` + `ʼs`).

## Phases

### H1: Break points (core, Qt-free)
`sfm/hyphenation.py`: `HyphenationRules` (the file's data, the markers set, `soft_hyphen_out`), `break_points(word) -> tuple[int, ...]` (offsets in the word as typed, after checking NFC length so offsets line up), `rules_for(project_folder)`, `marker_hyphenates(marker, styles, rules)` (H-D3). Tests: the `=` points, case, a hyphenated word, a word not listed, a damaged line, the marker order of precedence.

### H2: The Preview projection
`layout_projection(..., hyphenation=rules)` splits each paragraph's text at break points with `builder.generated("­")`, only inside hyphenating paragraphs and outside notes. `SfmPreviewView.project_with(source, hidden, hyphenation)`; `ProjectionCache` keys the variant. Tests: the view text has U+00AD, the source map round-trips every offset, notes aren't touched, a paragraph with `\Hyphenate No` isn't.

### H3: The toggle
`UNITITextView.hyphenate_preview` (saved), `ProjectTabs.set_hyphenation`, `RichViewPane.set_hyphenation`, the menu entries, D4-style disabled state, copy strips U+00AD. Tests drive the window like the spelling toggle's.

### J1: Justification
`\Justification Start|End`, resolved against the block's direction in `block_format`; `\Hyphenate` registered as a known presentation field (Style Inspector shows it). Tests, and the template/docs.

### F1: Approve and reject
The UNITI list (F-D1), loaded with the Paratext lists; right-click a flagged word in all three modes: **Approve "word"**, **Mark "word" Wrong**, **Use "correction"** and suggestions (F2). Underlines refresh.

### F2: Suggestions (F-D2) · F3: Word pairs (F-D3) · F4: Next/Previous and the count (F-D4) · F5: Affixes (F-D5)

### D1: Documentation
Complete [USFM Stylesheet Rules](../../../usfm-stylesheet-rules.md) (every selector, field, layer, the flag syntax, `\Hyphenate` and `\Justification`), the template inside `uniti.sty`, [USFM](../../../environments/usfm.md), the roadmap, [Current Status](../../01_current/STATUS.md), the wishlist (hyphenation entry removed, spellcheck's "Later" updated) and the live-app checklist.

## Order

H1 → H2 → H3 → J1 → F1 → F2 → F3 → F4 → F5 → D1. Documentation for a phase lands with it; D1 is the sweep.

## As built

Implemented 2026-10-15. Core: `sfm/hyphenation.py`, `sfm/user_words.py`, and additions to `sfm/spelling.py`, `sfm/spellcheck.py`, `sfm/views.py` and `sfm/paratext_project.py`; UI: `ui/hyphenation.py`, `ui/spelling.py`, `rich_view.py`, `text_view.py`. Tests: `tests/test_sfm_hyphenation.py`, `tests/test_spelling_followups.py`, `tests/ui/test_rich_view_alignment.py`, `tests/app/test_hyphenation_toggle.py`, `tests/app/test_spelling_followups_ui.py`.

**Where the code differs from the plan:**
- **`Left` and `Right` are now physical.** Qt turns a plain left or right around in a right-to-left paragraph unless the alignment carries `AlignAbsolute`: measured, `Right` put Hebrew text against the left edge. `Left` and `Right` now set `AlignAbsolute`, so they mean what they say, and `Start` and `End` use the plain flags, which Qt mirrors by direction. The built-in `usfm.sty` has no `Left` or `Right`, so only a user's own stylesheet in a right-to-left book changes. An unset `\Justification` is unchanged.
- **`\Hyphenate` reaches the projection as a paragraph attribute** (`hyphenate: yes|no`), so the same field works in a rule (`p+q1`) as in a marker record.
- **The hyphenation rules are read synchronously.** `hyphenatedWords.txt` alone is 24 ms for `rnBKCv1`, so no worker is used; the rules are cached per folder and file stamp and replaced when it changes.
- **The status bar's count** is a message (on turning Check Spelling on, and when a book of the tab is shown), not a permanent widget.
- **Word pairs** are found only inside one line, between two words separated by exactly one space.
- **The user list's file** is named after the project's short name, so two projects with the same short name share one list.
- **Suggestions are filtered by a letter mask** before the edit distance is computed: 18 ms (usNIVv3) and 108 ms (rnBKCv1) for the first request, which builds the vocabulary, then 3–15 ms; without the mask 69 and 337 ms each time.
- **`SpellingList.derive`** makes the list the checker uses (Paratext's files, the user's words, the project's affixes); `effective_spelling_list(project)` hands back one object until the files, the user's list or the affixes change, so every document's cache is shared across windows.

**Measured with the real code** (usNIVv3 and rnBKCv1, Genesis and Exodus, offscreen):
- Checking a whole book cold, with word pairs and affixes: 86–112 ms (97 ms before), once per document, then the line cache.
- `rnBKCv1` pairs found in Genesis and Exodus: `ata wuzoba`, `intege nke`, `ku bwʼubuzima`.
- Qt's soft hyphen needs no layout code: a justified `QTextEdit` broke `understand` as "under-" / "stand" and drew the hyphen only there.

**Left for later:** approving or rejecting a word pair; suggestions ranked by frequency; a shortcut for Next/Previous Spelling Issue; hyphenating Preview's notes frame; an automatic hyphenation rule for words not in the list.
