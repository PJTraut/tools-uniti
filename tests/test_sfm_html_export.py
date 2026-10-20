"""Export Preview as HTML (text direction plan W8)."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest

from uniti.core.environments.sfm.html_export import export_preview_html
from uniti.core.environments.sfm.hyphenation import SOFT_HYPHEN, HyphenationRules
from uniti.core.environments.sfm.sty import parse_raw_stylesheet
from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry, StyleLayer, StyleOrigin, build_layers
from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline
from uniti.core.environments.sfm.views import SfmPreviewView, body_font_size

STYLES = LayeredStyleRegistry(build_layers(load_usfm_baseline(), None))
GOLDEN = Path(__file__).parent / "fixtures" / "html_export"
RTL_BOOK = (
    "\\id JHN\n\\c 1\n\\s3 כותרת\n\\p\n\\v 1 שלום \\nd יהוה\\nd* עולם\\f + \\ft הערה\\f*\n"
    "\\q1 \\v 2 אור מים אור מים\n\\qr סוף\n"
)
LTR_BOOK = (
    "\\id JHN\n\\c 1\n\\s3 Heading\n\\p\n\\v 1 Peace to the \\nd Lord\\nd* world\\f + \\ft A note\\f*\n"
    "\\q1 \\v 2 light water light water\n\\qr End\n"
)


def _export(source: str, *, styles=STYLES, hidden=frozenset(), hyphenation=None, direction=None, **kwargs) -> str:
    projection = SfmPreviewView(lambda: styles).project_with(source, hidden, hyphenation, direction)
    kwargs.setdefault("title", "JHN")
    return export_preview_html(projection, base_size=body_font_size(styles), direction=direction, **kwargs)


class _Text(HTMLParser):
    """The text inside <main>'s paragraphs and cells, and every start tag."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.in_main = False
        self.text: list[str] = []
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == "main":
            self.in_main = True
        if self.in_main and tag in ("p", "td", "th"):
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == "main":
            self.in_main = False
        if self.in_main and tag in ("p", "td", "th"):
            self.depth -= 1

    def handle_data(self, data):
        if self.in_main and self.depth:
            self.text.append(data)


def _parse(page: str) -> _Text:
    parser = _Text()
    parser.feed(page)
    parser.close()
    return parser


@pytest.mark.parametrize(
    ("name", "source", "direction", "language", "font"),
    [("rtl", RTL_BOOK, "rtl", "he", "SBL Hebrew"), ("ltr", LTR_BOOK, None, "en", None)],
)
def test_golden_pages(name, source, direction, language, font):
    page = _export(source, direction=direction, language=language, font=font)

    assert page == (GOLDEN / f"{name}.html").read_text(encoding="utf-8")


def test_a_right_to_left_book_keeps_the_stylesheet_logical():
    page = _export(RTL_BOOK, direction="rtl", language="he")

    assert '<html lang="he" dir="rtl">' in page
    assert "margin-inline-start: 0.75in; text-indent: -0.5in" in page  # \q1, start side
    tags = _parse(page).tags
    qr = next(attrs for tag, attrs in tags if attrs.get("data-marker") == "qr")
    assert qr["dir"] == "rtl" and f".{qr['class']} {{ text-align: end;" in page
    s3 = next(attrs for tag, attrs in tags if attrs.get("data-marker") == "s3")
    assert f".{s3['class']} {{ text-align: start;" in page
    assert "left" not in page.split("<style>")[1].split("</style>")[0]  # no physical edges


def test_without_a_direction_paragraphs_decide_for_themselves():
    page = _export(LTR_BOOK)

    assert "<html lang" not in page and "<html>" in page
    assert all(attrs.get("dir") == "auto" for tag, attrs in _parse(page).tags if tag == "p")


def test_the_text_content_is_the_projections():
    source = RTL_BOOK + "\\p a < b & c \"d\" ‎Latin‏\n"
    projection = SfmPreviewView(lambda: STYLES).project_with(source, direction="rtl")
    page = export_preview_html(projection, title="t")

    assert "".join(_parse(page).text) == projection.text.replace("\n", "")
    assert "a &lt; b &amp; c \"d\"" in page
    assert "&#x200E;Latin&#x200F;" in page and "‎" not in page


def test_the_title_and_font_are_escaped():
    page = _export(LTR_BOOK, title="A <b> & c", font='Evil"; } body { x')

    assert "<title>A &lt;b&gt; &amp; c</title>" in page
    assert 'font-family: "Evil  body  x", serif' in page


def test_soft_hyphens_are_written_as_entities():
    rules = HyphenationRules({"understand": (5,)}, None)
    page = _export("\\c 1\n\\p\n\\v 1 They understand completely.\n", hyphenation=rules)

    assert "under&shy;stand" in page and SOFT_HYPHEN not in page


def test_a_hidden_category_leaves_neither_caller_nor_note():
    source = "\\c 1\n\\p\n\\v 1 Text\\f + \\cat People\\cat* \\ft hidden\\f* more\\f + \\ft shown\\f*\n"
    page = _export(source, hidden=frozenset({"People"}))

    assert "hidden" not in page and "shown" in page
    # The remaining note is the first one: caller "a", linked both ways.
    assert '<a class="caller" href="#f-1" id="f-1-ref">' in page
    assert '<p id="f-1"' in page and 'href="#f-1-ref"' in page


def test_callers_link_to_their_own_notes_across_kinds():
    source = (
        "\\c 1\n\\p\n\\v 1 One\\f + \\ft first\\f* two\\x - \\xo 1.1 \\xt Gen\\x* three\\f + \\ft second\\f*"
        " four\\x + \\xt Exod\\x*\n"
    )
    page = _export(source)

    for entry, text in (("f-1", "first"), ("f-2", "second"), ("x-2", "Exod")):
        assert f'href="#{entry}"' in page
        assert page.index(f'<p id="{entry}"') < page.index(text)
    # x-1 was written with "-": no caller, so nothing links to it or back.
    assert '<p id="x-1"' in page and 'href="#x-1"' not in page and 'href="#x-1-ref"' not in page


def test_a_table_is_a_table_with_header_cells():
    source = "\\c 1\n\\tr \\th1 Name \\thr2 Age\n\\tr \\tc1 Abram \\tcr2 75\n\\p after\n"
    page = _export(source)

    assert page.count("<table>") == 1
    assert "<th>" in page and "<td>Abram </td>" in page
    assert page.index("</table>") < page.index("after")


def test_colours_are_the_stylesheets_own():
    sheet = "\\Marker nd\n\\Color 255\n"
    styles = LayeredStyleRegistry(
        build_layers(load_usfm_baseline(), None, [StyleLayer("c.sty", StyleOrigin.UNITI_PROJECT, parse_raw_stylesheet(sheet))])
    )
    page = _export("\\c 1\n\\p the \\nd Lord\\nd*\n", styles=styles)

    assert "color: #ff0000" in page


def test_an_undefined_marker_stays_a_visible_tag():
    page = _export("\\c 1\n\\p text \\zz more\n")
    parsed = _parse(page)

    assert "\\zz" in "".join(parsed.text)
    assert "font-family: monospace" in page
