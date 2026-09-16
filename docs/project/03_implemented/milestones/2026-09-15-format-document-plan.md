# Format Document / Minify Document — Implementation Plan

Date: 2026-09-15
Status: implemented, integrated on `main`. See [BF-061](../BETA_FEEDBACK.md#bf-061--format-document--minify-document-for-json-xml-and-markdown) for the final implementation summary and verification; this document is retained for the design rationale (particularly the XML mixed-content fidelity risk, confirmed real during implementation and fixed as described below).

## Scope (confirmed with the user)

- **Pretty-print ("Format Document")** for JSON, XML, and Markdown.
- **Minify ("Minify Document")** for JSON and XML only. Markdown has no compact-form concept.
- Text/whitespace reformatting only — re-indentation and spacing normalization. No AST-aware structural refactors (sort JSON keys, rename an XML tag everywhere, promote a Markdown heading level, etc.). That is a materially larger effort (real parsers producing an edit-preserving tree, plus a refactor-command UI) and is explicitly out of scope here; it would need its own decision if wanted later.
- **Validate first.** JSON must parse as valid JSON; XML must be well-formed. An invalid document is refused with the parser's reported line/column and the document is left untouched. Markdown has no strict grammar, so Format Document always proceeds for it.

## Why this needs a size cap

Every other bulk-rewrite operation in UNITI (BF-023 EOL conversion, tabs-to-spaces) works as a streaming regex `replace_all` over the document without ever materializing the whole text as one Python object. Structural reformatting cannot work that way: JSON/XML must be parsed into a tree before re-serializing, which requires the complete document text in memory, and a naive line-based Markdown normalizer at least needs whole-document context for blank-line collapsing between blocks. This conflicts with UNITI's bounded/streaming design philosophy for large files.

Mitigation: read the document's full text through `document.iter_text` up to a hard cap (proposed: 16 MiB, matching the general "structural documents are not typically huge" assumption for JSON/XML/Markdown — config files, API payloads, docs — as opposed to UNITI's giant-log-file use case). Above the cap, refuse with a clear message ("document too large to format: relies on parsing the whole file into memory") rather than attempting it. This cap is a new, explicit constant — not inherited from any existing bound — and should be documented next to [Current Status](../01_current/STATUS.md)'s "Storage and safety policy" table once implemented.

## Architecture

New module `src/uniti/core/reformatters.py`, parallel in spirit to `syntax_profiles.py`'s extension→behavior mapping:

```python
@dataclass(frozen=True, slots=True)
class ReformatError:
    message: str
    line: int | None   # 1-based, None if the parser gave no position
    column: int | None  # 1-based

@dataclass(frozen=True, slots=True)
class Reformatter:
    key: str  # matches SyntaxProfile.key ("json", "xml", "markdown")
    can_minify: bool
    format: Callable[[str], str]   # raises ReformatFailure(ReformatError) on invalid input
    minify: Callable[[str], str] | None  # None when can_minify is False

REFORMATTERS_BY_KEY: dict[str, Reformatter] = {...}
```

`UNITIMainWindow` looks up `self.current_view.syntax_profile.key` (the same property BF-027/041 already populates per view via `profile_for_extension`) to decide which reformatter applies, and to enable/disable the two new menu actions — exactly the existing pattern for the current document's detected type, no new detection mechanism needed.

### JSON

Use the standard-library `json` module — no new dependency, and it already gives everything needed:

- Validate + parse: `json.loads(text)`. On `json.JSONDecodeError`, its `.lineno`/`.colno`/`.msg` map directly to `ReformatError`.
- Format: `json.dumps(value, indent=2, ensure_ascii=False) + "\n"`. Key order is preserved (`json.loads` returns a regular `dict`, insertion-ordered since Python 3.7) — this is not "sort keys," it's "don't reorder," consistent with the text-only-reformatting scope above.
- Minify: `json.dumps(value, separators=(",", ":"), ensure_ascii=False)`.
- Fidelity note: round-tripping through `json.loads`/`json.dumps` normalizes number formatting in edge cases (e.g. `1.0` stays `1.0`, but `1e10` may re-render as `10000000000.0` depending on the parsed float) and drops any comments (JSON has none in the standard) — this is expected and matches "format," not "preserve byte-identical structure."

### XML

Use `xml.dom.minidom` (standard library, no new dependency) rather than `xml.etree.ElementTree`: ElementTree silently drops comments and processing instructions on parse, which would corrupt real documents on format — an unacceptable fidelity loss for a "reformat my file" feature. `minidom` preserves comments, CDATA sections, and processing instructions in its DOM tree.

- Validate + parse: `xml.dom.minidom.parseString(text)`. On `xml.parsers.expat.ExpatError`, its `.lineno`/`.offset` map to `ReformatError`.
- Format: `dom.toprettyxml(indent="  ")`, then a cleanup pass collapsing `toprettyxml`'s well-known artifact of extra blank lines around text-only nodes (a documented quirk: `"\n".join(line for line in pretty.splitlines() if line.strip())`, joined back with the original trailing newline convention). This needs a real fidelity test against a document with mixed text/element content, not just an empty-element sample, since that's exactly where `toprettyxml` misbehaves.
- Minify: parse the same way, then serialize with `dom.toxml()` and collapse purely-whitespace text nodes between tags via a targeted `re.sub(r">\s+<", "><", xml_text)` — deliberately not touching whitespace inside any text content that isn't purely-whitespace-only, since XML whitespace inside text can be significant (`xml:space="preserve"` and ordinary mixed content). This is a "safe minify," not a byte-minimal one; document that boundary clearly in the command's tooltip/help text so it isn't mistaken for guaranteeing minimum byte size.

### Markdown

No parser dependency — a modest, explicitly bounded line-based normalizer, not a CommonMark-aware reformatter:

- Normalize ATX heading spacing (`#Heading` → `# Heading`; strip trailing `#` runs some styles use to close a heading).
- Normalize unordered list bullets to one consistent marker (`*`/`+` → `-`) at each existing indentation level — indentation level itself is not changed.
- Collapse 3+ blank lines between blocks to exactly 1.
- Strip trailing whitespace from every line.
- Ensure exactly one trailing newline at end of file.
- Explicitly NOT attempted: paragraph reflow/line-wrapping, table column alignment, link reference normalization, front-matter awareness. These would need a real Markdown grammar to do safely and are out of scope for this pass — call this out in the command's tooltip so it isn't mistaken for a full formatter.

## Wiring

- Checked: every existing `Format` menu action (encoding Reinterpret As/Convert on Save, Line Endings) is a plain `self._action(label, None, handler)` `QAction`, not routed through the `_command_action`/`CommandRegistry`/Hotkeys system at all — `Format` has no `CommandCategory` today. Follow the same convention: plain `self._action("Format Document", None, self.format_current_document)` / `self._action("Minify Document", None, self.minify_current_document)`, no new `CommandCategory`, no default shortcut. This avoids touching `tests/ui/test_hotkeys.py`'s asserted category list.
- Menu placement: `Format` menu, as a new block after the existing Line Endings block (both already flattened per BF-057, so this stays consistent with "prefer blocks over submenus"). `Format Document` is enabled whenever the current view's `syntax_profile.key` has a registered reformatter; `Minify Document` additionally requires `can_minify`. Since plain `QAction`s aren't auto-updated like `_command_action` ones, enablement needs an explicit refresh hook wherever the active view/document changes (the existing `_on_current_changed`/`_on_pane_active` path already refreshes other per-document menu/status state and is the natural place to add it).
- Apply as one `document.replace(0, document.total_chars(), formatted_text)` (or the existing whole-document-replace helper used by `convert_document_eol`/`convert_document_tabs_to_spaces` in `regex/replace.py`, generalized to accept an arbitrary replacement rather than a regex match) — one undo step, matching every other bulk document mutation in the app. If the formatted text is identical to the current text, make it a no-op (no history entry), matching `convert_document_eol`'s existing "already-conforming" behavior.
- On a `ReformatError`, show a dialog with the message and line/column (when available) and make no change — mirrors the existing encoding/EOL error-reporting dialogs' style.
- On success past the size cap check but before parsing, no special UI; the cap rejection itself needs a clear dialog ("This document is larger than the Xd MiB Format Document supports").

## Testing plan

- `tests/core/test_reformatters.py`: one file per format covering valid pretty-print round-trip, minify round-trip (JSON/XML), invalid-input error with correct line/column, and — for XML — a document with a comment, CDATA section, and mixed text/element content to catch the `toprettyxml` fidelity risk directly.
- `tests/ui/test_main_window_contract.py` or a new file: menu action enabled/disabled per `syntax_profile.key`, one-step Undo/Redo through the real `Document`, the size-cap rejection path, and the already-formatted no-op-history case.

## Resolved during implementation

- Size cap: `MAX_REFORMAT_CHARS = 16 * 1024 * 1024` (16 Mi characters, not bytes — counted this way for simplicity, documented in `reformatters.py`'s module docstring rather than [Current Status](../01_current/STATUS.md)'s storage-policy table, since it's specific to this one feature rather than a document-wide bound).
- JSON indent width: fixed at 2 spaces, not detected from the document's own style, as recommended.
- `CommandCategory`/Hotkeys placement: resolved by following the existing convention — every other `Format` menu action (Encoding, Line Endings) is a plain `QAction` outside the command-registry/Hotkeys system entirely, so Format Document/Minify Document follow suit. No new `CommandCategory` was added, and `tests/ui/test_hotkeys.py`'s asserted category list is unaffected.
- The XML mixed-content fidelity risk flagged above was real: `dom.toprettyxml()` alone splits mixed text/element content (e.g. `<a>text <b/> more</a>`) across separate indented lines, corrupting it. Fixed with a custom recursive serializer that leaves any element containing significant text completely untouched internally (see BF-061's implementation note for detail); confirmed idempotent on a mixed-content fixture in `tests/core/test_reformatters.py`.
- The original XML declaration (including `encoding=`/`standalone=`) is preserved verbatim from the source text rather than reusing minidom's regenerated one, which always emits a bare `version="1.0"` and would otherwise silently drop those attributes.
