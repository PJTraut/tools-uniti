# Arabic + Hebrew Font Bundling — Implementation Plan

Date: 2026-09-16
Status: implemented (2026-09-16). Both faces registered and verified; full suite green (1,888 passed, 6 platform skips).
Feedback: [BF-064](../BETA_FEEDBACK.md#bf-064--rtlbidi-content-support-arabic--hebrew) (RTL/bidi content support), task 7
Policy: [ADR-0010](../05_decisions/ADR-0010-bundled-font-selection-policy.md)

## Why

BF-064's RTL content work has no font behind it: the bundled Noto fallback set covers nine Indic scripts, Simplified/Traditional Chinese, Korean, and Latin/Cyrillic — no Arabic, no Hebrew. Without a bundled face, Arabic/Hebrew text depends entirely on whatever the host OS substitutes, unverified and untested, undermining the shaping/layout correctness work already landed.

## Sourced and verified faces

Following [ADR-0010](../05_decisions/ADR-0010-bundled-font-selection-policy.md)'s process — the `notofonts` GitHub org's lowercase generic per-script repo (matching every existing entry's pattern), latest tagged release, `Regular` weight only:

| | Arabic | Hebrew |
|---|---|---|
| Repository | `https://github.com/notofonts/arabic` | `https://github.com/notofonts/hebrew` |
| Family | **Noto Naskh Arabic** (not "Sans" — see note below) | Noto Sans Hebrew |
| Release tag | `NotoNaskhArabic-v2.021` | `NotoSansHebrew-v3.001` |
| Tag commit | `59f5a3fd985bf24858915c3dddfc51a537640965` | `036f3206f67caac235cf8546a7751d3440771a7e` |
| Archive URL | `https://github.com/notofonts/arabic/releases/download/NotoNaskhArabic-v2.021/NotoNaskhArabic-v2.021.zip` | `https://github.com/notofonts/hebrew/releases/download/NotoSansHebrew-v3.001/NotoSansHebrew-v3.001.zip` |
| Archive SHA-256 | `6c050ab9bd087d69b733c505a7576e60c528c2f33cd7b91005a5bd7da4514032` | `df0a71814b4e63644cf40fcc4529111b61266b7a2dafbe95068b29a7520cc3cb` |
| Path in archive | `NotoNaskhArabic/unhinted/otf/NotoNaskhArabic-Regular.otf` | `NotoSansHebrew/unhinted/otf/NotoSansHebrew-Regular.otf` |
| Extracted file bytes | 129,440 | 13,840 |
| Extracted file SHA-256 | `06f5e69cffb92bb0e08564718cd7ac2353a6c9305782f41b07b9e6ee3e3f4583` | `2551f8af9ede3cf55c4c975eec5fd743fed0722067a6b36494ec12c508ae103c` |
| License | OFL-1.1 (verified: both archives' `OFL.txt` state "licensed under the SIL Open Font License, Version 1.1") | OFL-1.1 |
| Notice file SHA-256 | `a7a5a25eb188bf1cd96982030d53e23c33485c69b1044a562254226857ee13af` (`arabic/OFL.txt`) | `9b9fe028b5ba74d231659a1bbaf0ed09b11e759d1ca6a070999e16d151616b47` (`hebrew/OFL.txt`) |
| Sample | `مثال` (or similar short representative word) | `שלום` (or similar) |

**Naming note:** every other bundled face is "Noto Sans `<Script>`," but Arabic's canonical repository under the established `notofonts/<lowercase-script>` pattern — the same pattern used to source all 13 existing fonts — publishes "Noto Naskh Arabic," not "Noto Sans Arabic." A separate `notofonts/NotoSansArabic` repository exists but has **zero published GitHub releases** (confirmed directly), so it has no verifiable, hash-pinnable archive to source from — it cannot be used under this project's sourcing process as written. Naskh is also the conventional default style for Arabic body text (the rough equivalent of why Latin defaults to a sans/serif body face, not a stylistic afterthought), so this is not a downgrade — but the resulting bundled family name will read "Noto Naskh Arabic," which is a deliberate, documented deviation from the "Sans" naming pattern, not an inconsistency to silently paper over.

Sourcing was verified directly, not assumed: both archives were downloaded, unzipped, hash-checked, and confirmed as valid OpenType font data (`file` reported "OpenType font data" for both extracted `.otf` files) — not just trusted because their GitHub metadata looked right.

## Code changes required

1. **Manifest** (`src/uniti/ui/assets/fonts/manifest.json`): append two entries (Arabic, Hebrew) following the exact schema of the existing 13, using the verified fields in the table above.
2. **Assets**: add `NotoNaskhArabic-Regular.otf` and `NotoSansHebrew-Regular.otf` to `src/uniti/ui/assets/fonts/`; add `NotoNaskhArabic-OFL.txt` and `NotoSansHebrew-OFL.txt` to `src/uniti/ui/assets/fonts/licenses/`, matching the `NotoSans<Script>-OFL.txt` naming convention (adapted to `NotoNaskhArabic-OFL.txt` for the one that isn't a "Sans" family).
3. **`src/uniti/ui/bundled_fonts.py`** (per [ADR-0010](../05_decisions/ADR-0010-bundled-font-selection-policy.md)'s registration-code contract, done *before* adding the new entries so the count-derivation change is tested against the current 13 first, then verified again after adding 15):
   - `BundledFontCapability.complete`: replace `len(self.families) == 13` with a count derived from the manifest (e.g. store the manifest's expected entry count on the capability, or compare `len(self.families) + len(self.failures)` against `len(entries)` read at registration time) rather than a hardcoded literal.
   - `register_bundled_fonts()`: replace `if len(entries) != 13` similarly — the real invariant worth checking is "the manifest is well-formed and non-empty," not an exact hardcoded count.
4. **`tests/ui/test_font_policy.py`**: replace the hardcoded `assert len(manifest['fonts']) == 13` with an assertion appropriate to the new contract (e.g. asserting the manifest's count matches whatever `bundled_fonts.py` now derives, plus updating any test that constructs a `BundledFontCapability` expecting exactly 13 families).
5. **`ordered_families()`** (`bundled_fonts.py`): no change needed — its Han-locale regional reordering is specific to `Noto Sans SC/TC/KR` and doesn't need to know about Arabic/Hebrew.
6. **Font-count references in prose docs**: `docs/ltr-text-layout.md`'s "13 pinned official Noto faces... totaling 19,683,928 bytes" (and any similar count/byte-total mention in `docs/project/01_current/STATUS.md`/`ARCHITECTURE.md`) will need updating to 15 faces and the new byte total once the assets actually land — historical evidence entries citing "13 fonts" for a *specific past candidate* (e.g. BF-006's own verification paragraph) are point-in-time records and must stay as they are.

## Testing plan

- Extend `tests/ui/test_font_policy.py` (or add a focused test) verifying `register_bundled_fonts()` successfully registers both new families and that `QFontDatabase.applicationFontFamilies()` reports "Noto Naskh Arabic" and "Noto Sans Hebrew" after registration — mirroring the existing per-font assertions, not just a count check.
- A representative glyph/shaping/rendering smoke test for both scripts, matching BF-006's own per-script coverage pattern (`tests/ui/test_multilingual_text.py` already has synthetic Arabic/Hebrew content from BF-064's caret and IME tests — those can be extended to assert the *bundled* font is actually the one resolved for that text, not a host fallback, once the fonts are registered).
- Full suite must stay green; the manifest-driven count change (item 3 above) should be verified to still pass with the *current* 13-entry manifest before the two new entries are added, isolating "count-derivation refactor" risk from "new font addition" risk.

## Open items before implementation starts

- Confirm sample strings for the manifest's `sample` field (a short representative word per face, matching the style of existing entries like Devanagari's `"क्षि"`).
- Decide whether to also verify glyph coverage (e.g. presence of key Arabic/Hebrew code points) via a script before accepting the extracted files, beyond the `file`-command sanity check already done.
- This plan does not touch IME, caret, or layout code — those are BF-064's already-completed content-level bidi work; this is purely the font-asset addition those features currently lack.

## Implementation notes (2026-09-16)

All steps above executed as planned, with every asset hash re-verified against the table above after copying into the repository:

- Assets landed at `src/uniti/ui/assets/fonts/{NotoNaskhArabic-Regular.otf, NotoSansHebrew-Regular.otf}` and `src/uniti/ui/assets/fonts/licenses/{NotoNaskhArabic-OFL.txt, NotoSansHebrew-OFL.txt}`; sample fields set to `"مرحبا"` (Arabic) and `"שלום"` (Hebrew).
- `manifest.json` now declares 15 entries; `register_bundled_fonts()` and `BundledFontCapability.complete` (`src/uniti/ui/bundled_fonts.py`) no longer hardcode a face count — `BundledFontCapability` gained an `expected: int` field set to `len(entries)` at registration time, so `complete` compares `len(self.families) == self.expected` instead of a literal `13`. The manifest-well-formedness check changed from `len(entries) != 13` to `not entries or not isinstance(entries, list)`, per ADR-0010.
- `tests/ui/test_font_policy.py`'s `test_bundled_faces_cover_each_declared_sample_without_system_fallback` needed only its hardcoded count (`13` → `15`) updated — being written generically over `manifest['fonts']`, it automatically extended its hash/size/notice-hash/glyph-coverage checks to both new faces and passed unmodified otherwise, including `QRawFont(...).supportsCharacter()` glyph coverage for both sample strings.
- `docs/project/01_current/ARCHITECTURE.md`'s "registers 13 pinned Noto faces" updated to 15 (naming Arabic/Hebrew explicitly); point-in-time evidence entries elsewhere (STATUS.md, BF-006, milestone docs) citing "13" for a specific past candidate were left untouched, as planned.
- **Noted, not a change**: upstream Noto Naskh Arabic and Noto Sans Hebrew are published as variable fonts spanning a weight axis (Thin 100 – ExtraBold 800). The files bundled here are the release archives' static `unhinted/otf/<Family>-Regular.otf` instances, not the variable font — confirmed directly (no `fvar` table in either file; `QRawFont.weight()` reports 400/normal for both), matching every one of the other 13 bundled faces and ADR-0010's "Regular weight only" policy. No action needed unless a future bold/italic styling feature is added, at which point the variable font's other instances would need separate sourcing/verification.
- **Finding during verification, not anticipated in the plan**: with the real bundled Noto Naskh Arabic font now resolved for Arabic text (previously the RTL caret-advance test exercised whatever font the host substituted), `tests/ui/test_text_view_contract.py::test_typing_into_an_rtl_line_advances_the_caret_visually` failed its strict per-keystroke monotonic-caret-position assertion. Root cause confirmed directly with a standalone `QTextLayout` probe: shaping `"مرحب"` (4 letters) with Noto Naskh Arabic produces a natural text width of 55.9px, but shaping `"مرحبا"` (5 letters) produces only 49.3px — the `ب` glyph's isolated/final terminal-tail form shrinks to a narrower medial-joining form once `ا` follows it. This is genuine Arabic contextual shaping from a real Arabic-specific font, not a caret regression. The test was corrected to keep its actual regression guard (no two consecutive positions equal — what the original caret-freeze bug produced) while relaxing the per-step ordering to a net-movement check (`positions[-1] < positions[0]`), with the reshaping behavior documented inline. Full suite reconfirmed green after the fix (1,888 passed, 6 platform skips).
