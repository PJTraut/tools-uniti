from uniti.core.syntax_profiles import (
    PLAIN_TEXT,
    PROFILES_BY_KEY,
    SyntaxToken,
    profile_for_extension,
)


def _tokenize(profile, text, state=None):
    if state is None:
        state = profile.initial_state
    return profile.tokenize(text, state)[0]


def _end_state(profile, text, state=None):
    if state is None:
        state = profile.initial_state
    return profile.tokenize(text, state)[1]


def test_plain_text_never_produces_tokens_regardless_of_content():
    assert _tokenize(PLAIN_TEXT, "anything { at all } 42 \"quoted\"") == ()
    assert _end_state(PLAIN_TEXT, "anything") is None


def test_unrecognized_extension_falls_back_to_plain_text():
    assert profile_for_extension("bogus") is PLAIN_TEXT
    assert profile_for_extension("") is PLAIN_TEXT


def test_extension_matching_is_case_insensitive_and_tolerates_leading_dot():
    assert profile_for_extension(".JSON").key == "json"
    assert profile_for_extension("Json").key == "json"
    assert profile_for_extension("json").key == "json"


def test_json_tokenizes_strings_numbers_keywords_and_punctuation():
    profile = profile_for_extension("json")
    tokens = _tokenize(profile, '{"a": 1, "b": true}')
    categories = {token.category for token in tokens}
    assert categories == {"punctuation", "string", "number", "keyword"}
    keyword = next(t for t in tokens if t.category == "keyword")
    assert "true" == '{"a": 1, "b": true}'[keyword.start : keyword.end]


def test_json_lines_are_stateless():
    profile = profile_for_extension("json")
    assert _end_state(profile, '{"a": 1}') is None


def test_xml_tokenizes_tags_attributes_and_string_values():
    profile = profile_for_extension("xml")
    text = '<book id="1">text</book>'
    tokens = _tokenize(profile, text)
    tags = [text[t.start : t.end] for t in tokens if t.category == "tag"]
    assert tags == ["<book", "</book"]
    attributes = [text[t.start : t.end] for t in tokens if t.category == "attribute"]
    assert attributes == ["id"]
    strings = [text[t.start : t.end] for t in tokens if t.category == "string"]
    assert strings == ['"1"']


def test_xml_recognizes_a_single_line_comment():
    profile = profile_for_extension("xml")
    text = "<!-- a comment --><a>x</a>"
    tokens = _tokenize(profile, text)
    comment = next(t for t in tokens if t.category == "comment")
    assert text[comment.start : comment.end] == "<!-- a comment -->"
    assert _end_state(profile, text) is None


def test_xml_comment_spanning_multiple_lines_is_tracked_across_calls():
    profile = profile_for_extension("xml")
    opening = "<a><!-- start of a"
    tokens, state = profile.tokenize(opening, profile.initial_state)
    comment = next(t for t in tokens if t.category == "comment")
    assert opening[comment.start : comment.end] == "<!-- start of a"
    assert state == "comment"

    middle = "long comment that keeps going"
    tokens, state = profile.tokenize(middle, state)
    assert tokens == (SyntaxToken("comment", 0, len(middle)),)
    assert state == "comment"

    closing = "end of it --><b/>"
    tokens, state = profile.tokenize(closing, state)
    comment = next(t for t in tokens if t.category == "comment")
    assert closing[comment.start : comment.end] == "end of it -->"
    tag = next(t for t in tokens if t.category == "tag")
    assert closing[tag.start : tag.end] == "<b"
    assert state is None


def test_xml_cdata_spanning_multiple_lines_is_tracked_across_calls():
    profile = profile_for_extension("xml")
    opening = "<data><![CDATA[raw <not a tag>"
    tokens, state = profile.tokenize(opening, profile.initial_state)
    cdata = next(t for t in tokens if t.category == "keyword")
    assert opening[cdata.start : cdata.end] == "<![CDATA[raw <not a tag>"
    assert state == "cdata"

    closing = "still raw]]></data>"
    tokens, state = profile.tokenize(closing, state)
    cdata = next(t for t in tokens if t.category == "keyword")
    assert closing[cdata.start : cdata.end] == "still raw]]>"
    tag = next(t for t in tokens if t.category == "tag")
    assert closing[tag.start : tag.end] == "</data"
    assert state is None


def test_markdown_tokenizes_headings_and_emphasis():
    profile = profile_for_extension("md")
    heading_tokens = _tokenize(profile, "## A heading")
    assert heading_tokens == (SyntaxToken("heading", 0, 12),)
    text = "some **bold** and *italic* text"
    tokens = _tokenize(profile, text)
    bold = next(t for t in tokens if t.category == "keyword")
    assert text[bold.start : bold.end] == "**bold**"
    italic = next(t for t in tokens if t.category == "attribute")
    assert text[italic.start : italic.end] == "*italic*"


def test_markdown_fenced_code_block_is_tracked_across_lines():
    profile = profile_for_extension("md")
    opening = "```python"
    tokens, state = profile.tokenize(opening, profile.initial_state)
    assert tokens == (SyntaxToken("string", 0, len(opening)),)
    assert state == ("fence", "`", 3)

    content = "def f(): pass"
    tokens, state = profile.tokenize(content, state)
    assert tokens == (SyntaxToken("string", 0, len(content)),)
    assert state == ("fence", "`", 3)

    closing = "```"
    tokens, state = profile.tokenize(closing, state)
    assert tokens == (SyntaxToken("string", 0, len(closing)),)
    assert state is None

    # Normal Markdown tokenizing resumes after the fence closes.
    after = "## back to normal"
    tokens, state = profile.tokenize(after, state)
    assert tokens == (SyntaxToken("heading", 0, len(after)),)
    assert state is None


def test_markdown_fence_shorter_than_the_opener_does_not_close_it():
    profile = profile_for_extension("md")
    _, state = profile.tokenize("````", profile.initial_state)
    # Three backticks is shorter than the four that opened the fence, so
    # this must not be treated as the closing delimiter.
    tokens, state = profile.tokenize("```", state)
    assert state == ("fence", "`", 4)
    tokens, state = profile.tokenize("````", state)
    assert state is None


def test_sfm_tokenizes_backslash_markers():
    profile = profile_for_extension("sfm")
    text = r"\v 1 In the beginning God created"
    tokens = _tokenize(profile, text)
    assert len(tokens) == 1
    assert tokens[0].category == "keyword"
    assert text[tokens[0].start : tokens[0].end] == r"\v"


def test_csv_tokenizes_quoted_fields_and_commas():
    profile = profile_for_extension("csv")
    text = 'a,b,"c,d"'
    tokens = _tokenize(profile, text)
    assert [t.category for t in tokens] == ["punctuation", "punctuation", "string"]
    string_token = tokens[-1]
    assert text[string_token.start : string_token.end] == '"c,d"'


def test_tsv_tokenizes_tab_delimiters_only():
    profile = profile_for_extension("tsv")
    text = "a\tb\tc"
    tokens = _tokenize(profile, text)
    assert all(token.category == "punctuation" for token in tokens)
    assert len(tokens) == 2


def test_yaml_tokenizes_comments_keys_and_scalars():
    profile = profile_for_extension("yaml")
    tokens = _tokenize(profile, "name: value  # a comment")
    categories = [t.category for t in tokens]
    assert "attribute" in categories
    assert "comment" in categories


def test_yaml_block_scalar_is_tracked_across_lines_by_its_own_indent():
    profile = profile_for_extension("yaml")
    opening = "description: |"
    tokens, state = profile.tokenize(opening, profile.initial_state)
    assert any(t.category == "attribute" for t in tokens)
    assert state == ("block_scalar", None)

    first_content = "    line one"
    tokens, state = profile.tokenize(first_content, state)
    assert tokens == (SyntaxToken("string", 0, len(first_content)),)
    assert state == ("block_scalar", 4)

    blank = ""
    tokens, state = profile.tokenize(blank, state)
    assert tokens == ()
    assert state == ("block_scalar", 4)

    second_content = "    line two"
    tokens, state = profile.tokenize(second_content, state)
    assert tokens == (SyntaxToken("string", 0, len(second_content)),)
    assert state == ("block_scalar", 4)

    dedented = "next_key: value"
    tokens, state = profile.tokenize(dedented, state)
    assert any(t.category == "attribute" for t in tokens)
    assert state is None


def test_tokens_never_overlap_and_stay_within_line_bounds():
    for profile in PROFILES_BY_KEY.values():
        text = '<a b="c">\\v \t{"x": 1} # y ## z **w** *v* `code` [t](u)'
        tokens = _tokenize(profile, text)
        previous_end = 0
        for token in tokens:
            assert 0 <= token.start < token.end <= len(text)
            assert token.start >= previous_end
            previous_end = token.end


def test_extension_override_takes_priority_over_the_default_mapping():
    assert profile_for_extension("usj").key == "plain_text"
    assert profile_for_extension("usj", overrides={"usj": "json"}).key == "json"


def test_an_override_naming_an_unknown_profile_falls_back_to_plain_text():
    assert profile_for_extension("txt", overrides={"txt": "not-a-real-profile"}) is PLAIN_TEXT
