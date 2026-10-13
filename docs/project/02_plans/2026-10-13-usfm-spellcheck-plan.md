# USFM Spellcheck from Paratext's Word Lists — Plan

Date: 2026-10-13
Status: **Planned**, not started: S1–S5. Reviewed for render speed 2026-10-13 (see [Performance](#performance)).
Origin: field test feedback item 8, 2026-10-08 ("toggle spellchecking using hyphenatedwords.txt data; plan this"). The first sketch is in the [round 3 plan](../03_implemented/milestones/2026-10-08-usfm-field-test-round-3-plan.md#spellcheck-from-hyphenatedwordstxt-item-8--plan-only-not-queued). This plan replaces it and answers its open questions.

## The user's answers, 2026-10-13

- **Word source:** both files, `SpellingStatus.xml` first. Its R and W decide; a word found only in `hyphenatedWords.txt` counts as correct.
- **What's underlined:** wrong words and unknown words, in two colours.
- **Toggle:** per project tab.
- **Adding words:** not in this plan. UNITI only reads Paratext's lists.

## What Paratext keeps

Read, read-only, in the local copies of `usNIVv3` and `rnBKCv1` (`~/Library/Application Support/paratextlite/Paratext8Projects`):

- **`SpellingStatus.xml`** is Paratext's spelling record.
  - `<Status Word="…" State="R"/>` means correct and `State="W"` means wrong. `Word` is always lowercase.
  - `<SpecificCase>Paul</SpecificCase>` gives the only accepted capitalizations: 3,616 of `usNIVv3`'s entries have one.
  - `<Correction>…</Correction>` on a W entry gives the right spelling. `rnBKCv1` has 1,012 of them, for example `ay'ifyufyu` → `ayʼifyufyu` (ASCII apostrophe → U+02BC) and `kubwʼigikorwa` → `ku bwʼigikorwa` (one word → two).
  - A word can contain a hyphen (328 entries in `usNIVv3`), U+02BC (461; 9,865 in `rnBKCv1`), an ASCII apostrophe (128 in `rnBKCv1`) or a space (210 and 1,037: Paratext's records of word pairs, such as `go at` R and `grain field` W).
  - `usNIVv3`: 15,522 entries, 2 W. `rnBKCv1`: 79,086 entries, 1,074 W, 3.8 MB, parsed in 63 ms.
- **`hyphenatedWords.txt`** is Publishing Assistant's hyphenation list: UTF-8 with a BOM, `#` comment lines, settings lines (`HardHyphen = "-"`, `SoftHyphen = "="`, `SoftHyphenOut`, `HyphenatedMarkers`), then one word per line with `=` at its break points and `*` in front of a line the user fixed. `usNIVv3`'s 102 starred lines look damaged (`*a =ro=se`, `*a sin`), which is why it only adds words and never decides against `SpellingStatus.xml`.
- **The stylesheet** says which text is the translation. `usfm.sty` marks `\id`, `\usfm`, `\ide`, `\rem`, `\sts`, `\restore`, `\tl` and `\pubinfo` `nonvernacular`; `\c` and `\v` have `\TextType ChapterNumber` and `VerseNumber`.

## Design

**A word's status**, in this order:
1. In `SpellingStatus.xml` as W: **wrong**, with its Correction if there is one.
2. In it as R with SpecificCase forms: correct in one of those forms or in all capitals (`\nd LORD`, titles); otherwise **wrong case**, which shows as wrong with the accepted forms.
3. In it as R: correct, in any case.
4. In `hyphenatedWords.txt` (with `=` removed and `*` ignored): correct, in any case.
5. A hyphenated word found in neither: correct if each part on its own is correct, by rules 1–4, splitting at the file's `HardHyphen`. Otherwise the word's status is the worst of its parts'.
6. Otherwise: **unknown**.

Words are compared after NFC normalization and case folding. Entries containing a space are read but not used for matching in this plan (see Later).

**A word** is a run of letters and combining marks (Unicode L* and M*), joined by an ASCII apostrophe, U+2019, U+02BC, a hyphen or ZWJ/ZWNJ only when the run continues with a letter on both sides. Digits and punctuation split words. So `donʼt`, `ay'ifyufyu` and `well-watered` are each one word, and a closing quote after a word isn't part of it.

**What's checked:** the text of every marker whose style isn't `nonvernacular`: verse text, headings, `\h`/`\toc`, notes and cross-reference text. Not checked:
- markers themselves, and `\c`/`\v` numbers (and `\ca`, `\va`, `\vp`);
- attributes (after `|` in a character marker, and `\fig`'s);
- text of `nonvernacular` markers, from the project's layered stylesheet, so a project's `custom.sty` counts.

**The checker works a line at a time, and remembers every line.** A line's words depend only on its text and its start state: the paragraph marker in effect and any character markers still open. A paragraph marker closes character markers in USFM, so the start state is found by walking back to the nearest line that starts with a paragraph marker, usually the line itself or one or two before it. Nothing is threaded from the top of the book.
- **One cache per document**, keyed by (start state, line text), holds each line's flagged spans. Every view of the document uses it: Plain Text, Standard, Preview, and second views in other splits and windows. It's dropped when the word list changes.
- **After an edit only the changed lines are checked again.** Re-checking a whole book through the cache is a dictionary lookup per line.
- **Plain Text** checks only the lines it paints.
- **Standard and Preview** check the book through the cache after each render, then underline only what's on screen (S4).

**The lists are loaded off the UI thread.** They're loaded on a worker (`task_bridge`) the first time a tab turns checking on, and the underlines appear when they're ready. They're cached per project folder and re-read the same way when their modification time changes, checked when the window is activated or a tab turns checking on (Paratext's Send/Receive can change them). `SpecificCase` and `Correction` are read only for the entries that have them. UNITI never writes the lists (ADR-0018).

## Decisions

- **D1:** `SpellingStatus.xml` decides; `hyphenatedWords.txt` only adds correct words (answer 1).
- **D2:** two colours: **wrong** (W, or wrong case) and **unknown** (answer 2). They are two new editor theme roles, `spelling_wrong` and `spelling_unknown`, set in every built-in theme and checked for contrast like the others.
- **D3:** **Check Spelling** is per project tab, off by default (answer 3). It's on the tab's menu (T6) and in the USFM menu, where it acts on the current tab. It's saved with the session in each book's view `extra` (no schema change). A book opened into the tab, or changed to by the Book selector or sync, takes the tab's setting. Moving a tab to another split or window keeps it. Merging into a tab of the same project takes the receiving tab's setting.
- **D4:** a project with neither file shows Check Spelling disabled, with the tooltip "NIV has no spelling list (SpellingStatus.xml or hyphenatedWords.txt)".
- **D5:** no suggestions beyond Paratext's own Correction, and no adding or rejecting words (answer 4).
- **D6:** a wavy underline drawn under the text, in all three modes, so it doesn't change syntax or style colours. Hovering a flagged word shows its status: "Paratext marks this wrong: use ayʼifyufyu", "Paratext spells it: Paul", "Not in NIV's spelling list".
- **D7:** only the active window is live (the user, 2026-10-13: "only 'active' pane and all split windows inside it should be 'live', other panes can be 'frozen'"). Spelling is worked out only for the active window and its splits. Other windows keep the underlines they had; their Standard and Preview underlines are updated when the window is activated, with the re-render that the frozen window already catches up on (`RichViewPane.stale`, `RichViewController.catch_up`). A frozen window's Plain Text paints from the document's shared cache, so it costs nothing extra. Turning Check Spelling on or off in a frozen window's tab takes effect when that window is activated.

## Phases

### S1: The word lists (core, Qt-free)
`sfm/spelling.py`:
- `SpellingStatus.load(path)`: R/W, SpecificCase forms and Correction per word.
- `HyphenatedWords.load(path)`: the words, without `=` and `*`, and the `HardHyphen` setting.
- `SpellingList.for_project(project)`: both files, cached per folder and modification time; `status(word) -> Spelling` (correct, wrong with its correction, wrong case with its forms, unknown), following rules 1–6. A plain `dict` from the normalized word to its entry; a word's own status is cached too, since a book repeats its words.
- Loading is a plain function, so S5 can run it on a worker.

Tests: every rule; a BOM, CRLF and comment lines; a damaged or missing file (it's ignored, and the other still works); the cache re-reading a changed file. Measured: the load time for `usNIVv3` and `rnBKCv1`.

### S2: Finding words in USFM (core, Qt-free)
`sfm/spelling.py`:
- `check_line(line, state, context) -> spans`. `context` holds the list and the stylesheet's checked markers; each span is (start, end, status) in the line's columns. It uses the tokenizer's marker and text tokens and one precompiled word pattern, and skips markers, numbers, attributes and `nonvernacular` text.
- `line_start_state(document, line)`: the walk back to the paragraph's first line.
- `SpellingCache` (per document): `spans_for(line_number)` through the (start state, line text) cache; `book_spans()` for every line, in source offsets, sorted.

Tests: word boundaries (apostrophes, U+02BC, hyphens, ZWJ, quotes, digits); `\id`, `\rem`, `\v 3`, `\w word|lemma="x"\w*`, `\fig …|src="…"\fig*`; a character marker continuing onto the next line; a project `custom.sty` making a marker `nonvernacular`; the cache re-checking only an edited line.

Measurement on `usNIVv3` Genesis and `rnBKCv1`: unknown words per book (NIV, whose list approves its words, should have few: each is listed in the results and explained), and the time to check a whole book.

### S3: Plain Text (`UNITITextView`)
- `set_spelling(cache | None)`: each painted line's spans come from the document's `SpellingCache`.
- The wavy underline is a small tiled pixmap per theme colour, filled under each flagged span from `_span_rects` (`fillRect` with a texture brush), not a path drawn per word: 0.6 ms against 4.8 ms for a screen of 600 flagged words. The two pixmaps are made once per theme and zoom. Wrapped rows, horizontal scroll, bidi and Show One Chapter work as they do for search matches.
- Tooltip on hover (D6).
- Theme roles `spelling_wrong` and `spelling_unknown` in every built-in theme, with the contrast test covering them.

Tests: spans painted for a line; the cache after an edit (only the changed lines are checked again); the tooltip; theme contrast.

### S4: Standard and Preview (`RichViewPane`)
- **Spelling isn't part of the render.** The projection and its render stay as they are, so turning checking on or off never re-renders.
- **Only the live window works (D7).** A pane in a frozen window does nothing for spelling until its window is activated; then it catches up once.
- **Only what's on screen is underlined.** After each render, scroll or resize (coalesced to once per event-loop turn), the pane takes the source range of the visible text (`view_to_source` at the viewport's top and bottom, with one screen's margin each way), finds that range's spans in `book_spans()` by bisection, maps each with `source_to_view` and sets them as extra selections with `SpellCheckUnderline` in the role's colour, alongside the sync highlight in `_apply_highlights`. A screen holds at most a few hundred words, so this stays under 5 ms even when every word is flagged.
- A semantic edit re-renders as today; the cache re-checks only the edited lines.
- Show One Chapter's hidden blocks get no underlines, since they're never on screen.
- Tooltip on hover (D6).

Tests: a wrong word underlined in Standard and Preview, not in a note's `\fr`; only on-screen spans set as extra selections, and scrolling updating them; an edit in Standard updating the underline.

### S5: The toggle (D3, D4)
- **Check Spelling** on the project tab's menu and in the USFM menu, checkable, for the current project tab; `ProjectTabs` applies it to every book of the tab, and to books that join it.
- Session save and restore; disabled for a project with no list (D4); lists re-read on window activation when their time changed.

Tests drive the real window: turning it on for a tab and not another tab of another project; the Book selector and sync keeping it on; a tab moved to another window keeping it; merging into a tab with checking off; the session round trip; a project without lists; a list changed on disk being re-read.

## Order

S1 → S2 → S3 → S4 → S5. S3 and S4 are independent once S2 lands. Documentation when S5 lands: the [USFM](../../environments/usfm.md) page, the user manual, the [roadmap](ROADMAP.md)'s environment track queue and [Current Status](../01_current/STATUS.md), and the wishlist entry removed.

## Performance

Measured 2026-10-13 with a prototype of S1/S2 (pure Python, on the UNITI tokenizer) and offscreen Qt, on `usNIVv3` Psalms (281 KB, 9,463 lines, 43,639 words) and Genesis, and `rnBKCv1` Psalms:

| What | Measured | How the plan keeps it small |
|---|---|---|
| Loading the lists | `usNIVv3` 20 ms; `rnBKCv1` 106 ms (67 parsing the XML, 15 building the lookup, 24 for `hyphenatedWords.txt`) | on a worker thread, once per project and change |
| Checking a whole book, cold | 27–49 ms | once per document; then the cache |
| Checking again after a one-line edit, through the cache | 0.4 ms, plus 0.5 ms to split the lines | the per-document line cache |
| Checking 60 visible lines, cold (Plain Text) | 0.4 ms | only painted lines |
| Flagged words in a real book | 17 (NIV Genesis), 30 (NIV Psalms), 0 (`rnBKCv1` Psalms) | |
| Preview render, for comparison | 148 ms; a paint 0.9 ms | unchanged: spelling isn't rendered |
| Underlining in Preview, every flagged word as an extra selection | 30 spans: nothing measurable; 2,000: 21 ms, paint 3.0 ms; 43,639 (a draft where every word is unknown): 472 ms, paint 9.6 ms | only on-screen words: a few hundred at most, under 5 ms, paint near 1 ms |
| The same, built into the render's formats instead | 2,000: 11 ms; 43,639: 269 ms, and a re-render on every toggle | not used |
| Wavy underlines in Plain Text, a screen of 600 flagged words | a path per word 4.8 ms; a tiled pixmap 0.6 ms | the tiled pixmap |

Budgets, checked with the real code when each phase lands:
- typing in Plain Text stays at today's 16 ms a keystroke on that Psalms, plus under 1 ms;
- a Standard/Preview refresh grows by under 5%, even with every word unknown;
- scrolling Preview with checking on paints within 2 ms;
- turning checking on never blocks the UI for more than one cold check of the shown book (under 50 ms).
- windows other than the active one cost nothing while you type (D7): with the same 281 KB Psalms in Preview in a second window, a keystroke used to re-render that Preview too (148 ms); since 2026-10-13 it waits until that window is activated.

## Later (not in this plan)

- Approving or rejecting a word, into a UNITI-side list in `Environments/USFM/` (writing `SpellingStatus.xml` needs an ADR change).
- Word-pair entries (`grain field` W): flag the pair.
- Next/Previous spelling issue, and a count in the status bar.
- Suggestions beyond Paratext's Correction.
- Hyphenation in Preview from the same `hyphenatedWords.txt` break points ([wishlist](../FEATURE_WISHLIST.md#hyphenation-in-preview)): S1's loader should keep them rather than discard them.
- `WordPrefixes`/`WordSuffixes` from `Settings.xml` (`usNIVv3` lists `ʼs` and `ing`) for words that are only listed without them.
