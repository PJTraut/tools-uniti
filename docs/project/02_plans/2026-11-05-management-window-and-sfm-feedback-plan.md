# Management Window, MD and SFM Feedback (2026-11-05) — Plan

Date: 2026-11-05
Status: **proposed; N34, N35, N36, N38, N37 and N39–N43 built, the rest not started.** Items are the testers' words, tidied; none is yet a confirmed decision.
Origin: `@externalresources/field_test_feedback` (second 2026-11-05 round, after the MD.ENV items N27–N31 were built). IDs continue from [N27–N31](2026-11-05-markdown-environment-feedback-plan.md).

## Items

| ID | Area | Feedback | Proposal / notes | Status |
|---|---|---|---|---|
| N32 | Management window | A "management" window as the default; it opens when all environment panels are closed. Everything opens in an environment, even if only TXT | A default window shown when no environment window is open. Opening any file lands in an environment (TXT at least) | proposed |
| N33 | Management window | The window shows stats of the UNITI ecosystem: open files/projects, memory usage, cache sizes, etc. | Read-only stats panel; the list of stats needs agreeing | proposed |
| N34 | MD | The Group dropdown is still on the text panel; redundant, since the group shows next to the environment | Remove it from the text panel (the right-click entry went in N30; this is the remaining dropdown). Group hotkeys are good, keep them | **built 2026-11-05:** the control was the grouped-tabs dropdown at the left of the tab row; it is no longer shown in any environment window (the toolbar's group button stays). No automated test; Mac-checked by the user 2026-11-05 |
| N35 | MD | How do you indent list levels / nesting? | Question first: Tab / Shift+Tab (and a command) to indent and outdent list items in Preview; check what exists | **built 2026-11-05:** nothing existed (Tab typed a tab). With lines selected, **Tab** / **Shift+Tab** move every selected list item in or out one level together, in Preview and the Text view; two spaces under a bullet or task, three under a number; non-list lines, rules and code fences are left alone, and with no list item Tab types a tab as before. Commands **Indent List Item** / **Outdent List Item** in the Preview menu. Tests in `test_markdown_indent.py`; Mac check |
| N36 | MD | Environment Settings needs a link to manage the custom CSS extensions/mods | A button in Environment Settings… opening the CSS layers (as Configuration Files… does for SFM) | **built 2026-11-05:** MD's Environment Settings has **Manage Stylesheets…**, which opens Configuration Files… (built-in, user and project CSS layers); other environments don't show it (Mac check) |
| N37 | SFM | Remove the lock icon next to "BK" | Removed the toolbar lock button; Lock/Unlock Project stays in the USFM menu, the tab and text menus and the unlock banner | **built 2026-11-05** (offscreen tests pass; Mac check to do) |
| N38 | SFM / all | The status line is only used for the lock. Always display it, even when blank; use it for every environment, future functions and warnings | A permanent status line in every environment window with a reserved slot | **built 2026-11-05:** the unlock banner is now a permanent row in every environment window: blank and neutral normally, red with the Lock Project button while a project is unlocked; `UnlockBanner.set_message(text)` is the slot for later warnings and function messages. Windows that aren't environment windows still show it only while unlocked. Mac check |
| N39 | SFM, Persian | "Auto" direction did not sense right-to-left | Cause, Standard and Preview: Auto used only the project's `LeftToRight`; a Persian book with none (or `T`) got no direction, so no tag isolates. Auto now reads the text (`core/bidi.dominant_direction`, first 20,000 characters, markers skipped): mostly right-to-left letters give RTL, and the status bar says so. Documented in the stylesheet rules. Cause, Text view (where the Mac test was): a line's direction is its first strong letter, and every SFM line starts with a Latin marker, so Persian lines read left to right; markers are now skipped when judging a line (`is_rtl_paragraph`) | **built 2026-11-05, reworked the same day** (the first fix covered Standard and Preview only; the Mac test was in the Text view) |
| N40 | SFM, Persian | `\c` and `\v` tags show the number next to the backslash: `c 1\` | Standard and Preview: the tags are isolated (W4) once the direction is known. Text view: the raw `\c 1` in a right-to-left line reordered to `c 1\`; `ShapedWindow` now puts a zero-width left-to-right mark before each marker in the layout's text only (no text or caret position changes; not while composing) | **built 2026-11-05** (Mac check in the Text view) |
| N41 | SFM, Persian | `\id` and `\rem` tags display wrongly: `id ...text...\` | Same fix as N40 | **built 2026-11-05** with N40 (Mac check) |
| N42 | SFM, Persian | The EOL "CRLF" marker overlaps `\ie` and `\b`; add a phantom space so it doesn't cover the tag | Cause: the EOL marker sat at the logical end of the line, which for a Latin tag in a right-to-left row is the text's right edge, so it drew over the tag. It now sits past the text's own left edge (right edge in a left-to-right row). Regression test in `test_whitespace_markers.py` | **built 2026-11-05** (Mac check) |
| N43 | SFM, Persian | Second Persian test, right to left: tag-only lines (`\ie`, `\rem`, `\b` …) not working; `\c` and `\v` must show the number or range to the left of the tag; number ranges in general, especially in `\xt`, display wrongly | **Text view built 2026-11-05:** a line with no letters takes the book's direction (`first_strong_direction`; the book's from its first 20,000 characters). Each marker and each number range (`1-3`, `2:3–5`, Persian digits) gets a zero-width left-to-right mark before and a right-to-left one after, in the layout only, so the tag reads `\c` with its number on its left and a range keeps its order (isolates drew the same but gave the caret wrong positions). The `*` of a closing marker read to the left of its tag (`(\xt 12:15\xt*)` showed as `.(*15\xt:12 \xt)`): a second left-to-right mark after each run keeps it in. The real Persian project (`faTMN`, `(\xt ۲تواریخ ۷‏:۱۴\xt*)`, Persian digits and a right-to-left mark before the colon) then showed the closer between `۷:` and `۱۴`: a number just before a closer joins its left-to-right run, so each run also starts with a right-to-left mark. Checked by rendering the layout to an image. Standard and Preview: tags are isolated, but a dash between digits in text is not; to do if the next test shows it | Text view built (Mac check); Preview ranges open. **Direction is a state (2026-11-05):** in a right-to-left book (predominant script, markers skipped) every line takes the book's direction, so the Latin-only `\id` and `\rem` lines no longer read left to right (`direction_for_text`); a left-to-right book still reads each line by its first strong letter |

N39–N42 came from one Persian test. N39–N41 share a cause (direction not detected, so no tag isolates); N42 is a separate marker-placement bug. N39–N41 were first fixed for Standard and Preview only; the Mac test showed they were in the Text view (the EOL marker only exists there), so they were fixed again there. No Persian project here: checked by layout tests, not by eye.

## Decisions (2026-11-05, Q&A)

- **Q1 (N32):** the management window is a window of its own, shown at start-up and again whenever the last environment window closes.
- **Q2 (N33):** stats: open files; open projects per environment; memory usage; cache and recovery sizes; undo caches and when they expire.
- **Q3 (N38):** the status line is a new row in every environment window, always visible even when blank (not the bottom status bar).

## Order (proposed)

1. N37 (done), N34 (waiting on which control).
2. N39–N42 (Persian bugs, done).
3. N38, N36, N35.
4. N32, N33 (after Q1–Q2 answered).

## Tests and checks

To be written when approved. The Persian bugs need a regression test each; the rest need Mac checks.
