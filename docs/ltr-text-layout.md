# LTR text layout and editing

Current implementation: `v0.001b3` / `0.1b3`. This LTR layout work itself landed unchanged since reviewed feedback source candidate `3e20214`, integrated on `main`. See [current status](project/01_current/STATUS.md) for verification and remaining native input qualification.

UNITI registers its pinned Noto fonts inside the application. It does not install
fonts into the operating system or download fonts at runtime. The primary face's
fixed-pitch and Latin/Cyrillic facts remain separate from bundled fallback
capability. Missing assets are reported by `register_bundled_fonts()` rather than
counted as available coverage. The manifest records each source revision, exact
font and notice hash, license and sample. Han regional preference follows the
system locale: plain text has no per-range language metadata for distinguishing
Simplified and Traditional regional forms of the same code point.

Document positions and explicit selections count Unicode code points. User
left/right movement and ordinary deletion use the pinned `regex` library's
Unicode extended grapheme boundaries. Explicit single-code-point selection and
Unicode inspection remain available. A plain deletion from an explicit cursor
inside a cluster removes the containing cluster. The Unicode grapheme definition
can put a boundary between dead consonants and following consonants in scripts
such as Tamil and Kannada; it is not a universal syllable boundary rule.

One Qt layout supplies text, selection and match geometry, hit testing, caret
positions, tabs and UTF-16 conversions for each bounded window. All fallback
families contribute to a common row baseline and height. Soft wrapping follows
Qt's cluster-safe WrapAnywhere policy; Qt can include trailing whitespace in the
preceding row, with no visible text ink beyond the wrap edge.

Public document windows remain at most 8192 code points. Grapheme navigation
reads at most its 8192-code-point budget, including contextual retries. If a
cluster cannot be resolved inside that budget, ordinary navigation/deletion does
not change the document. Horizontal checkpoints accumulate actual shaped widths;
unknown variable-width prefixes remain pending. A horizontal advance reads at
most one 8192-code-point window. Shaped wrap advances read at most 8192 returned
code points and add at most 512 rows per request. Row blocks retain at most 2048
rows, with resumable positions for rebuilding evicted blocks. A cold distant
request may need several event-loop advances. Pending positions do not produce
an approximate caret rectangle. The inherited document line index can still
perform additional indexing while discovering logical lines; these bounds on
layout materialization do not assert a new bound on all core indexing work.

IME surrounding text and selection queries are bounded. Replacements and
selection attributes convert from UTF-16 through that snapshot, including
supplementary characters and deletion-only commits. Preedit text is a bounded
virtual projection and never enters document history; its cursor and formatting
are painted through the same Qt layout. Commit, cancellation and undo are
covered by synthetic events. Preedit remains associated with its current row. A temporary pan of that row
keeps the composition caret visible in narrow viewports without changing saved
scroll or wrap settings; cancellation and commit restore ordinary geometry.

The bundled coverage and synthetic tests cover nine Indic scripts, Simplified
and Traditional Chinese, Korean, Latin/Cyrillic, tabs and representative emoji.
Emoji glyphs may use host fonts. RTL and mixed-direction editing are outside this
qualification. Native Chinese/Korean IME behavior on Windows, macOS and Linux
still requires qualification on those hosts; offscreen event tests do not provide
that evidence.

Run `python -m benchmarks.multilingual` for the representative 72-interaction
mixed-script scenario at three zoom levels with and without wrapping. It uses
the existing interaction latency gates, without changing their thresholds.
