"""Markdown Preview's forms and right-click commands (N28, 2026-11-05)."""

from __future__ import annotations

import pytest

from uniti.core.environments.markdown_environment import COMMONMARK, EXTENDED, GITHUB
from uniti.core.environments.markdown_views import (
    MarkdownRenderedView,
    current_heading,
    insert_table,
    remove_formatting,
    set_paragraph,
    toggle_code_block,
    toggle_inline,
    toggle_task_done,
)
from uniti.core.rich_views.editing import EditPlan, EditRejected


def _apply(source: str, plan: EditPlan) -> str:
    for start, end, text in sorted(plan.replacements, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def _spans(source: str, flavour: str = EXTENDED) -> set[tuple[str, str]]:
    projection = MarkdownRenderedView(flavour).project(source)
    projection.source_map.check()
    return {(span.marker, projection.text[span.view_start : span.view_end]) for span in projection.spans}


# --- projection ---------------------------------------------------------------------


def test_extended_forms_render_with_their_delimiters_hidden():
    source = "~~gone~~ x^2^ H~2~O ==hot== <sup>a</sup> <sub>b</sub> <del>c</del>"
    projection = MarkdownRenderedView(EXTENDED).project(source)
    assert projection.text == "gone x2 H2O hot a b c"
    assert {("del", "gone"), ("sup", "2"), ("sub", "2"), ("mark", "hot"), ("sup", "a"), ("sub", "b"), ("del", "c")} <= _spans(source)


def test_flavours_recognise_their_own_forms():
    source = "~~a~~ x^2^ <sup>3</sup>"
    assert MarkdownRenderedView(GITHUB).project(source).text == "a x^2^ 3"
    assert MarkdownRenderedView(COMMONMARK).project(source).text == "~~a~~ x^2^ 3"


def test_emphasis_nests():
    assert {("strong", "bold and it"), ("em", "it")} <= _spans("**bold and *it***")
    assert {("strong", "word"), ("em", "word")} <= _spans("***word***")


def test_numbered_items_keep_their_number_and_enter_continues_them():
    view = MarkdownRenderedView(EXTENDED)
    assert view.project("1. one\n2. **two**").text == "1. one\n2. two"
    assert view.enter_text("3. three", 8) == "\n4. "


def test_pipe_tables_are_an_aligned_monospace_block_with_pipes_kept():
    source = "| a | b |\n|-|-|\n| long cell | x |\nafter"
    projection = MarkdownRenderedView(EXTENDED).project(source)
    projection.source_map.check()
    rows = projection.text.split("\n")
    assert rows[:3] == ["| a         | b |", "|-----------|---|", "| long cell | x |"]
    assert rows[3] == "after"
    assert [block.marker for block in projection.blocks].count("table") == 3
    # CommonMark has no tables: the lines stay text.
    assert MarkdownRenderedView(COMMONMARK).project(source).text == source


# --- character commands --------------------------------------------------------------


@pytest.mark.parametrize(
    ("element", "flavour", "expected"),
    [
        ("strong", EXTENDED, "a **word**"),
        ("em", EXTENDED, "a *word*"),
        ("del", EXTENDED, "a ~~word~~"),
        ("del", COMMONMARK, "a <del>word</del>"),
        ("sup", EXTENDED, "a ^word^"),
        ("sup", GITHUB, "a <sup>word</sup>"),
        ("sub", EXTENDED, "a ~word~"),
        ("sub", GITHUB, "a <sub>word</sub>"),
        ("code", EXTENDED, "a `word`"),
    ],
)
def test_character_commands_wrap_in_the_flavours_syntax(element, flavour, expected):
    assert _apply("a word", toggle_inline("a word", 2, 6, element, flavour)) == expected


def test_a_character_command_inside_its_run_removes_it():
    source = "a **word** b"
    plan = toggle_inline(source, 5, 5, "strong", EXTENDED)  # caret inside "word"
    assert _apply(source, plan) == "a word b"
    assert plan.caret_source == 3
    # Selecting the run with its delimiters removes them too.
    assert _apply(source, toggle_inline(source, 2, 10, "strong", EXTENDED)) == "a word b"
    # Italic inside bold isn't bold's run.
    assert _apply(source, toggle_inline(source, 4, 8, "em", EXTENDED)) == "a ***word*** b"
    # Either syntax of an element is toggled off.
    assert _apply("<sup>x</sup>", toggle_inline("<sup>x</sup>", 5, 6, "sup", EXTENDED)) == "x"


def test_wrapping_skips_spaces_and_wraps_each_line():
    source = "one \ntwo"
    assert _apply(source, toggle_inline(source, 0, 8, "strong", EXTENDED)) == "**one** \n**two**"
    with pytest.raises(EditRejected):
        toggle_inline("a word", 2, 2, "strong", EXTENDED)


def test_remove_formatting_strips_every_inline_delimiter_but_links():
    source = "**b** *i* ~~s~~ [l](u) <sup>x</sup>"
    assert _apply(source, remove_formatting(source, 0, len(source))) == "b i s [l](u) x"
    with pytest.raises(EditRejected):
        remove_formatting("plain", 0, 5)


# --- paragraph commands --------------------------------------------------------------


def test_paragraph_commands_replace_each_other():
    assert _apply("# t", set_paragraph("# t", 2, 2, "quote")) == "> t"
    assert _apply("> t", set_paragraph("> t", 2, 2, "h2")) == "## t"
    assert _apply("- t", set_paragraph("- t", 2, 2, "numbered")) == "1. t"
    assert _apply("t", set_paragraph("t", 0, 0, "bullet")) == "- t"


def test_list_and_quote_commands_toggle_and_number_lines():
    source = "a\nb\nc"
    numbered = _apply(source, set_paragraph(source, 0, 5, "numbered"))
    assert numbered == "1. a\n2. b\n3. c"
    assert _apply(numbered, set_paragraph(numbered, 0, len(numbered), "numbered")) == source
    assert _apply("> q", set_paragraph("> q", 2, 2, "quote")) == "q"


def test_paragraph_caret_follows_the_text():
    plan = set_paragraph("## title", 5, 5, "h1")
    assert plan.caret_source == 4
    plan = set_paragraph("## title", 1, 1, "body")  # caret in the old prefix
    assert plan.caret_source == 0


def test_headings_choice_ticks_the_current_level():
    assert current_heading("## a\nb\n- c", 1) == "H2"
    assert current_heading("## a\nb\n- c", 5) == "Body Text"
    assert current_heading("## a\nb\n- c", 8) is None
    assert current_heading("```\n# not\n```", 5) is None


def test_code_block_fences_and_unfences():
    source = "a\nb"
    fenced = _apply(source, toggle_code_block(source, 0, 3))
    assert fenced == "```\na\nb\n```"
    assert _apply(fenced, toggle_code_block(fenced, 5, 5)) == source


def test_insert_table():
    plan = insert_table("intro\nnext", 2, "2 x 1", EXTENDED)
    assert _apply("intro\nnext", plan) == (
        "intro\n\n| Column 1 | Column 2 |\n| -------- | -------- |\n|          |          |\n\nnext"
    )
    assert _apply("intro\nnext", plan)[plan.caret_source :].startswith("Column 1")
    assert _apply("", insert_table("", 0, "1×1", EXTENDED)) == "| Column 1 |\n| -------- |\n|          |"
    with pytest.raises(EditRejected):
        insert_table("", 0, "3 x 2", COMMONMARK)
    with pytest.raises(EditRejected):
        insert_table("", 0, "lots", EXTENDED)


def test_commands_are_grouped_for_the_menu():
    commands = MarkdownRenderedView(EXTENDED).view_commands()
    groups = [(command.group, command.label) for command in commands]
    assert [label for group, label in groups if group == "character"] == [
        "Bold", "Italic", "Strikethrough", "Superscript", "Subscript", "Code", "Remove Formatting",
    ]
    assert [label for group, label in groups if group == "paragraph"] == [
        "Headings", "Quote", "Bullet List", "Numbered List", "Task List", "Check or Uncheck Task",
        "Indent List Item", "Outdent List Item", "Code Block",
    ]
    assert [label for group, label in groups if group == "insert"] == ["Insert Table…"]
    headings = next(command for command in commands if command.command_id == "heading")
    assert headings.submenu and headings.choices() == ("Body Text", "H1", "H2", "H3", "H4", "H5", "H6")


# --- front matter, task lists, footnotes, definition lists ---------------------------


def _blocks(source: str, flavour: str = EXTENDED) -> list[tuple[str, str]]:
    projection = MarkdownRenderedView(flavour).project(source)
    projection.source_map.check()
    return [(block.marker, projection.text[block.view_start : block.view_end].rstrip("\n")) for block in projection.blocks]


@pytest.mark.parametrize("flavour", [EXTENDED, GITHUB, COMMONMARK])
def test_front_matter_is_shown_as_written_muted_and_monospace(flavour):
    source = "---\ntitle: a_b_ *c*\nstylesheet: [x.css]\n---\n# Head\n---\n"
    projection = MarkdownRenderedView(flavour).project(source)
    assert projection.text.startswith("---\ntitle: a_b_ *c*\nstylesheet: [x.css]\n---\nHead\n")
    matter = [block for block in projection.blocks if block.marker == "front_matter"]
    assert len(matter) == 4
    assert all(block.attrs["monospace"] == "yes" and block.attrs["muted"] == "yes" for block in matter)
    # The `---` after the front matter is an ordinary rule again.
    assert projection.text.endswith("Head\n---\n")


def test_an_unclosed_front_matter_is_markdown():
    assert not any(marker == "front_matter" for marker, _text in _blocks("---\ntitle: x\n"))


def test_task_lists_show_a_box_in_github_and_extended():
    source = "- [ ] todo\n  * [x] **done**\n3. [X] third\n- [ ]\n"
    for flavour in (EXTENDED, GITHUB):
        projection = MarkdownRenderedView(flavour).project(source)
        projection.source_map.check()
        assert projection.text == "☐ todo\n  ☑ done\n3. ☑ third\n☐ \n"
    assert MarkdownRenderedView(COMMONMARK).project(source).text == "• [ ] todo\n  • [x] done\n3. [X] third\n• [ ]\n"


def test_enter_continues_a_task_list_unchecked():
    view = MarkdownRenderedView(EXTENDED)
    assert view.enter_text("  - [x] done", 12) == "\n  - [ ] "
    assert view.enter_text("3. [ ] three", 12) == "\n4. [ ] "
    assert MarkdownRenderedView(COMMONMARK).enter_text("- [ ] a", 7) == "\n- "


def test_task_list_command_replaces_and_toggles_prefixes():
    assert _apply("one\n- two\n# three", set_paragraph("one\n- two\n# three", 0, 15, "task")) == "- [ ] one\n- [ ] two\n- [ ] three"
    assert _apply("- [ ] a\n- [x] b", set_paragraph("- [ ] a\n- [x] b", 0, 14, "task")) == "a\nb"
    assert _apply("- [x] a", set_paragraph("- [x] a", 0, 0, "bullet")) == "- a"
    assert current_heading("- [ ] a", 0) is None
    task_list = next(c for c in MarkdownRenderedView(COMMONMARK).view_commands() if c.command_id == "task_list")
    with pytest.raises(EditRejected):
        task_list.run("a", 0, 0, None)


def test_check_task_checks_then_unchecks():
    source = "- [ ] a\n- [x] b\n1. [ ] c"
    checked = _apply(source, toggle_task_done(source, 0, len(source)))
    assert checked == "- [x] a\n- [x] b\n1. [x] c"
    assert _apply(checked, toggle_task_done(checked, 0, len(checked))) == "- [ ] a\n- [ ] b\n1. [ ] c"
    assert toggle_task_done(source, 3, 3).caret_source == 3
    with pytest.raises(EditRejected):
        toggle_task_done("- a", 0, 0)


def test_footnotes_show_their_label_as_a_superscript():
    source = "Text[^1] and[^note].\n\n[^1]: The **first** note.\n"
    for flavour in (EXTENDED, GITHUB):
        projection = MarkdownRenderedView(flavour).project(source)
        projection.source_map.check()
        assert projection.text == "Text1 andnote.\n\n1 The first note.\n"
        labels = [span for span in projection.spans if span.marker == "footnote"]
        assert [projection.text[s.view_start : s.view_end] for s in labels] == ["1", "note", "1"]
        assert all(span.attrs["superscript"] == "yes" for span in labels)
    assert MarkdownRenderedView(COMMONMARK).project(source).text == "Text[^1] and[^note].\n\n[^1]: The first note.\n"


def test_footnote_references_arent_formatting():
    source = "a[^1] b"
    with pytest.raises(EditRejected):
        remove_formatting(source, 0, len(source))


def test_definition_lists_in_extended_only():
    source = "Term\n: First\n: Second\n\n: no term\n"
    assert _blocks(source)[:3] == [("dt", "Term"), ("dd", "First"), ("dd", "Second")]
    projection = MarkdownRenderedView(EXTENDED).project(source)
    assert projection.text == "Term\nFirst\nSecond\n\n: no term\n"
    assert not any(marker in ("dt", "dd") for marker, _text in _blocks(source, GITHUB))
    assert MarkdownRenderedView(GITHUB).project(source).text == source


def test_built_in_stylesheet_styles_terms_and_definitions():
    from uniti.core.environments.markdown_css import markdown_styles

    styles = markdown_styles(None, "")
    assert styles.for_element("dt")["bold"] == "yes"
    assert float(styles.for_element("dd")["left_margin"]) > 0


def test_format_document_leaves_front_matter_as_written():
    from uniti.core.reformatters import MARKDOWN

    source = "---\ntitle: _x_  \nlist:\n  * a\n\n\n---\n*  item\n"
    assert MARKDOWN.format(source, None) == "---\ntitle: _x_  \nlist:\n  * a\n\n\n---\n- item\n"
