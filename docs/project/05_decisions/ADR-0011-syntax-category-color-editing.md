# ADR-0011: Un-park Syntax Category Color Editing

Date: 2026-09-17
Status: accepted

## Context

[BF-063](../BETA_FEEDBACK.md#bf-063--theme--text-type-profile-editor) asked for an editor covering both theme colors and text-type (syntax) profiles. Its extension→profile mapping half was implemented directly; its color half — making the eight syntax-highlighting categories (keyword, string, number, tag, attribute, heading, comment, punctuation) user-editable — squarely overlaps the parked ["File-type profiles and syntax highlighting"](../04_parked/CATALOG.md#file-type-profiles-and-syntax-highlighting) capability, whose stated re-evaluation trigger is "demonstrated need for… user-customizable syntax colors." That trigger is exactly BF-063's own request, so it needs the same kind of explicit un-parking decision [ADR-0009](ADR-0009-bounded-open-folder-by-type.md) recorded for BF-029, confirmed with the user before implementation.

Today, `uniti.ui.syntax_theme.syntax_category_palette(base)` derives every category color algorithmically from the active theme's base color, with a built-in loop that nudges lightness until each color clears a 4.5:1 contrast ratio against that base. There is no per-category override anywhere, and `ThemeProfile.colors` (`src/uniti/app/theme_profiles.py`) validates that a profile's colors dict contains *exactly* its fixed `COLOR_ROLES` set — un-parking this needs extending that fixed set, and a decision for what happens to every existing saved custom profile that predates it.

## Decision

Un-park syntax category colors as full per-category editable colors, not a narrower hue-only override:

1. **Full manual color per category**, all eight (not only the six hued ones — comment and punctuation become editable too, for consistency), stored as new `syntax.*` roles extending `ThemeProfile.COLOR_ROLES`, alongside the existing `palette.*`/`editor.*` roles.
2. **Contrast is a warning, not a gate.** A user can pick a syntax color with poor contrast against the editor background under Standard contrast — the existing theme editor already only hard-blocks a color choice under High Contrast (`ThemeEditor.set_color`), never under Standard; syntax colors follow that same existing asymmetry rather than inventing a new, inconsistent rule just for them. Under High Contrast, syntax colors are held to the same 4.5:1 bar already used for the editor's other markers (space/tab/EOL markers, invalid-byte, current-match) rather than the stricter 7:1 body-text bar — syntax highlighting is secondary color-coding, not primary text, and `syntax_category_palette`'s own derivation loop only ever targets 4.5:1 regardless of mode.
3. **Migration freezes in today's algorithmic colors.** A profile saved before this change (schema 1) has no `syntax.*` roles at all — not merely unset optional fields. On load, `ThemeProfileStore` computes what `syntax_category_palette` would already have shown for that profile's own background and saves the result as that profile's explicit starting colors (schema bumped to 2). The profile looks identical immediately after upgrade; the user edits from there. If PySide6 isn't installed (this module is otherwise deliberately Qt-free), the migration is skipped and the profile fails validation exactly like any other damaged file — a graceful degradation, not a crash, and an acceptable one since a syntax-color feature has no meaning without the UI it colors.
4. **The UI is new rows in the existing theme editor**, not a separate dialog. `ThemeEditor`'s "Color role" dropdown already iterates `COLOR_ROLES` generically (`role.split('.')` → "Category: Label"), so extending `COLOR_ROLES` makes "Syntax: Keyword" etc. appear automatically with the existing color-edit/color-picker/contrast-feedback/Clone/Reset/Delete machinery — no new dialog, no new editing code path.

## Consequences

`EditorThemeTokens` (`src/uniti/ui/theme.py`) gains a `syntax: Mapping[str, QColor]` field, populated by `_editor_tokens()` (via the existing algorithmic `syntax_category_palette`, for System/Light/Dark/High-Contrast, which have no stored `ThemeProfile`) or by `build_profile_theme()` (from a resolved profile's stored `syntax.*` colors, for Paper/Slate and custom profiles). `UNITITextView` now reads `theme_tokens.syntax` directly instead of calling `syntax_category_palette` itself, so a syntax color, once customized, renders identically to any other theme-driven editor color. `contrast_feedback()` gains one row per syntax category so the theme editor's existing warning summary covers them.

The packaged Paper and Slate theme assets are updated with their own frozen syntax colors (computed once, identically to what a live user would have seen before this change), so `test_packaged_complete_immutable_and_round_trip`-style completeness checks hold without a separate migration step for the two built-in custom-style profiles.

## Affected records

- [BF-063](../BETA_FEEDBACK.md#bf-063--theme--text-type-profile-editor), updated to reflect this decision and its implementation.
- [Parked Capability Catalog](../04_parked/CATALOG.md) — the "File-type profiles and syntax highlighting" entry's color-editing scope note is resolved; its other remaining scope-cut (non-incremental, non-multiline-aware highlighting) stays parked and unaffected.
- [Current Scope](../01_current/SCOPE.md).
