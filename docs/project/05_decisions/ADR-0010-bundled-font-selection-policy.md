# ADR-0010: Bundled Font Selection Policy

Date: 2026-09-16
Status: accepted

## Context

BF-006 bundled 13 pinned Noto faces (nine Indic scripts, Simplified/Traditional Chinese, Korean, and Latin/Cyrillic monospace) as an application-only fallback, alongside the platform-resolved primary monospace font. That process — pin an exact upstream release, verify archive and extracted-file hashes, capture the license notice, register the result in a schema-versioned manifest read by `register_bundled_fonts()` (`src/uniti/ui/bundled_fonts.py`) — has never been written down as a repeatable procedure; it exists only as tribal knowledge encoded implicitly in `manifest.json`'s fields and `register_bundled_fonts()`'s validation logic. [BF-064](../BETA_FEEDBACK.md#bf-064--rtlbidi-content-support-arabic--hebrew) (RTL/bidi content support) now needs two more faces (Arabic, Hebrew), confirming this will recur, and the current code hardcodes the exact count `13` in three places (`BundledFontCapability.complete`, `register_bundled_fonts`'s entry-count check, and `tests/ui/test_font_policy.py`) rather than deriving it from the manifest — every addition requires remembering to update all three by hand.

## Decision

1. **Trigger for bundling a new script/face:** a demonstrated, real need — an implemented feature or explicit user request that requires rendering/editing that script, not speculative future-proofing. BF-006's nine Indic scripts came from an explicit request; Arabic/Hebrew come from BF-064 actually implementing RTL support. A script with no such trigger stays unbundled (falls back to whatever the host OS substitutes, unverified) until one exists.
2. **Sourcing process**, formalizing what BF-006 already did:
   - Find the face's canonical repository under the `notofonts` GitHub organization, matching the lowercase generic script-name pattern already used by every existing entry (e.g. `notofonts/devanagari`, `notofonts/bengali`) — not a differently-cased or differently-named repo that happens to also exist, which may be an unreleased or legacy variant (confirmed during BF-064's research: `notofonts/NotoSansArabic` exists but has zero published releases, while `notofonts/arabic` — the repo matching the established pattern — has a proper release pipeline and is canonically "Noto Naskh Arabic," not "Noto Sans Arabic," for that script).
   - Use that repository's latest tagged GitHub release (not a branch tip or arbitrary commit) and its release archive (`.zip`) asset.
   - Record, in the manifest: `sourceRepository`, `sourceTag`, `sourceRevision` (the tag's target commit), `sourceArchiveURL`, `sourceArchivePath` (the exact path inside the archive, conventionally `<Family>/unhinted/otf/<Family>-Regular.otf`), `sourceArchiveSha256`, the extracted file's own `bytes` and `sha256`, and the license (`license`, `licenseURL`, `noticePath`, `noticeSha256`).
   - Bundle only the `Regular` weight, matching every existing entry — no bold/italic/other-weight variants unless a future need is demonstrated for those specifically.
   - Verify the license is OFL-1.1 (as every existing entry is) before proceeding; a different license would need its own review, not an assumed pass-through.
3. **Registration code contract:** `register_bundled_fonts()`'s hardcoded expected-count checks (`BundledFontCapability.complete`, the manifest entry-count validation) must be derived from the manifest's actual entry count rather than a hardcoded literal, so adding a face only requires adding its manifest entry, asset file, and license notice — not hunting down every place a magic number needs to change in lockstep. `tests/ui/test_font_policy.py`'s equivalent assertion should read the manifest the same way rather than hardcode the count too.
4. **Verification before landing:** the full existing font test suite (`tests/ui/test_font_policy.py` and any font-capability tests) must pass with the new entries, confirming the registered family is actually usable (`QFontDatabase.addApplicationFont` succeeds and reports the expected family name) — not merely that the file exists and hashes match.

## Consequences

Future font additions (this ADR's immediate motivating case is Arabic + Hebrew for BF-064) follow a written, reproducible process instead of re-deriving it from reading `bundled_fonts.py`'s validation logic backwards. The manifest remains the single source of truth for "how many fonts are bundled," removing the three-places-in-lockstep hazard. This does not change the existing 13 fonts, their hashes, or their registration; it only changes how the *count* is derived and documents the process for the next addition.

## Affected records

- [BF-064](../BETA_FEEDBACK.md#bf-064--rtlbidi-content-support-arabic--hebrew)
- [Arabic/Hebrew font bundling plan](../02_plans/2026-09-16-arabic-hebrew-font-bundling-plan.md) — the first application of this policy
- `src/uniti/ui/bundled_fonts.py`, `src/uniti/ui/assets/fonts/manifest.json`, `tests/ui/test_font_policy.py`
