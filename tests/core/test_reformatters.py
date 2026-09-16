import pytest

from uniti.core.reformatters import (
    JSON,
    MARKDOWN,
    XML,
    REFORMATTERS_BY_KEY,
    ReformatFailure,
    reformatter_for_key,
)


def test_reformatters_are_registered_by_syntax_profile_key():
    assert reformatter_for_key("json") is JSON
    assert reformatter_for_key("xml") is XML
    assert reformatter_for_key("markdown") is MARKDOWN
    assert reformatter_for_key("plain_text") is None
    assert set(REFORMATTERS_BY_KEY) == {"json", "xml", "markdown"}


def test_json_can_minify_but_markdown_cannot():
    assert JSON.can_minify is True
    assert XML.can_minify is True
    assert MARKDOWN.can_minify is False
    assert MARKDOWN.minify is None


def test_json_format_pretty_prints_and_preserves_key_order():
    result = JSON.format('{"b": 1, "a": [3, 2, 1]}')
    assert result == '{\n  "b": 1,\n  "a": [\n    3,\n    2,\n    1\n  ]\n}\n'


def test_json_minify_round_trips_to_a_compact_single_line():
    pretty = '{\n  "b": 1,\n  "a": [1, 2, 3]\n}\n'
    assert JSON.minify(pretty) == '{"b":1,"a":[1,2,3]}'


def test_json_format_rejects_invalid_input_with_line_and_column():
    with pytest.raises(ReformatFailure) as excinfo:
        JSON.format("{invalid")
    error = excinfo.value.error
    assert error.line == 1
    assert error.column is not None
    assert "property name" in error.message.lower()


def test_json_format_is_idempotent():
    once = JSON.format('{"a": 1, "b": {"c": [1, 2]}}')
    assert JSON.format(once) == once


def test_xml_format_indents_element_only_structure():
    source = "<root><a><b/><c>value</c></a></root>"
    result = XML.format(source)
    assert result == (
        "<root>\n"
        "  <a>\n"
        "    <b/>\n"
        "    <c>value</c>\n"
        "  </a>\n"
        "</root>\n"
    )


def test_xml_format_preserves_mixed_content_comments_and_cdata_verbatim():
    source = (
        "<root>\n"
        "  <!-- a comment -->\n"
        '  <a attr="1">text <b/> more</a>\n'
        "  <c><![CDATA[raw <data> & stuff]]></c>\n"
        "</root>"
    )
    result = XML.format(source)
    assert "<!-- a comment -->" in result
    assert '<a attr="1">text <b/> more</a>' in result
    assert "<c><![CDATA[raw <data> & stuff]]></c>" in result


def test_xml_format_is_idempotent_on_mixed_content():
    source = (
        "<root>\n"
        "  <!-- a comment -->\n"
        '  <a attr="1">text <b/> more</a>\n'
        "  <nested><child1/><child2>value</child2></nested>\n"
        "</root>"
    )
    once = XML.format(source)
    assert XML.format(once) == once


def test_xml_format_preserves_original_declaration_verbatim():
    source = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<root/>'
    result = XML.format(source)
    assert result.splitlines()[0] == '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def test_xml_format_adds_no_declaration_when_source_has_none():
    result = XML.format("<root/>")
    assert not result.startswith("<?xml")


def test_xml_minify_collapses_only_purely_whitespace_inter_tag_text():
    source = "<root>\n  <a>text <b/> more</a>\n</root>"
    result = XML.minify(source)
    assert result == "<root><a>text <b/> more</a></root>"


def test_xml_minify_preserves_original_declaration_verbatim():
    source = '<?xml version="1.0" encoding="UTF-8"?>\n<root/>'
    assert XML.minify(source) == '<?xml version="1.0" encoding="UTF-8"?><root/>'


def test_xml_format_rejects_malformed_input_with_position():
    with pytest.raises(ReformatFailure) as excinfo:
        XML.format("<a><b></a>")
    error = excinfo.value.error
    assert error.line == 1
    assert error.column is not None


def test_markdown_format_fixes_heading_spacing_and_bullet_style():
    result = MARKDOWN.format("#Title\n\n* one\n+ two\n")
    assert result == "# Title\n\n- one\n- two\n"


def test_markdown_format_collapses_extra_blank_lines_to_one():
    result = MARKDOWN.format("a\n\n\n\n\nb\n")
    assert result == "a\n\nb\n"


def test_markdown_format_leaves_fenced_code_block_content_untouched():
    source = "text\n```python\n#not a heading\n*not a bullet\n```\nmore\n"
    result = MARKDOWN.format(source)
    assert "#not a heading" in result
    assert "*not a bullet" in result


def test_markdown_format_does_not_touch_shebang_like_lines():
    result = MARKDOWN.format("#!/bin/sh\necho hi\n")
    assert result.startswith("#!/bin/sh\n")


def test_markdown_format_strips_trailing_whitespace_and_ensures_one_trailing_newline():
    result = MARKDOWN.format("line one   \nline two\t\n\n\n\n")
    assert result == "line one\nline two\n"


def test_markdown_format_is_idempotent():
    once = MARKDOWN.format("#Title\n\n\n\n* a\n+ b\n")
    assert MARKDOWN.format(once) == once
