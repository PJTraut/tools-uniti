from uniti.core.syntax_profiles import (
    PLAIN_TEXT,
    PROFILES_BY_KEY,
    SyntaxToken,
    profile_for_extension,
)


def test_plain_text_never_produces_tokens_regardless_of_content():
    assert PLAIN_TEXT.tokenize("anything { at all } 42 \"quoted\"") == ()


def test_unrecognized_extension_falls_back_to_plain_text():
    assert profile_for_extension("bogus") is PLAIN_TEXT
    assert profile_for_extension("") is PLAIN_TEXT


def test_extension_matching_is_case_insensitive_and_tolerates_leading_dot():
    assert profile_for_extension(".JSON").key == "json"
    assert profile_for_extension("Json").key == "json"
    assert profile_for_extension("json").key == "json"


def test_json_tokenizes_strings_numbers_keywords_and_punctuation():
    profile = profile_for_extension("json")
    tokens = profile.tokenize('{"a": 1, "b": true}')
    categories = {token.category for token in tokens}
    assert categories == {"punctuation", "string", "number", "keyword"}
    keyword = next(t for t in tokens if t.category == "keyword")
    assert "true" == '{"a": 1, "b": true}'[keyword.start : keyword.end]


def test_xml_tokenizes_tags_attributes_and_string_values():
    profile = profile_for_extension("xml")
    text = '<book id="1">text</book>'
    tokens = profile.tokenize(text)
    tags = [text[t.start : t.end] for t in tokens if t.category == "tag"]
    assert tags == ["<book", "</book"]
    attributes = [text[t.start : t.end] for t in tokens if t.category == "attribute"]
    assert attributes == ["id"]
    strings = [text[t.start : t.end] for t in tokens if t.category == "string"]
    assert strings == ['"1"']


def test_xml_recognizes_a_single_line_comment():
    profile = profile_for_extension("xml")
    text = "<!-- a comment --><a>x</a>"
    tokens = profile.tokenize(text)
    comment = next(t for t in tokens if t.category == "comment")
    assert text[comment.start : comment.end] == "<!-- a comment -->"


def test_markdown_tokenizes_headings_and_emphasis():
    profile = profile_for_extension("md")
    heading_tokens = profile.tokenize("## A heading")
    assert heading_tokens == (SyntaxToken("heading", 0, 12),)
    text = "some **bold** and *italic* text"
    tokens = profile.tokenize(text)
    bold = next(t for t in tokens if t.category == "keyword")
    assert text[bold.start : bold.end] == "**bold**"
    italic = next(t for t in tokens if t.category == "attribute")
    assert text[italic.start : italic.end] == "*italic*"


def test_sfm_tokenizes_backslash_markers():
    profile = profile_for_extension("sfm")
    text = r"\v 1 In the beginning God created"
    tokens = profile.tokenize(text)
    assert len(tokens) == 1
    assert tokens[0].category == "keyword"
    assert text[tokens[0].start : tokens[0].end] == r"\v"


def test_csv_tokenizes_quoted_fields_and_commas():
    profile = profile_for_extension("csv")
    text = 'a,b,"c,d"'
    tokens = profile.tokenize(text)
    assert [t.category for t in tokens] == ["punctuation", "punctuation", "string"]
    string_token = tokens[-1]
    assert text[string_token.start : string_token.end] == '"c,d"'


def test_tsv_tokenizes_tab_delimiters_only():
    profile = profile_for_extension("tsv")
    text = "a\tb\tc"
    tokens = profile.tokenize(text)
    assert all(token.category == "punctuation" for token in tokens)
    assert len(tokens) == 2


def test_yaml_tokenizes_comments_keys_and_scalars():
    profile = profile_for_extension("yaml")
    tokens = profile.tokenize("name: value  # a comment")
    categories = [t.category for t in tokens]
    assert "attribute" in categories
    assert "comment" in categories


def test_tokens_never_overlap_and_stay_within_line_bounds():
    for profile in PROFILES_BY_KEY.values():
        text = '<a b="c">\\v \t{"x": 1} # y ## z **w** *v* `code` [t](u)'
        tokens = profile.tokenize(text)
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
