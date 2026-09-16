import pytest


def test_hex_run_matches_plain_digits():
    from uniti.core.unicode_hex import hex_run_before_cursor

    assert hex_run_before_cursor("type 48") == (2, 0x48)


def test_hex_run_matches_u_plus_prefix():
    from uniti.core.unicode_hex import hex_run_before_cursor

    assert hex_run_before_cursor("U+0041") == (6, 0x41)
    assert hex_run_before_cursor("u+0041") == (6, 0x41)


def test_hex_run_matches_0x_prefix():
    from uniti.core.unicode_hex import hex_run_before_cursor

    assert hex_run_before_cursor("0x1F600") == (7, 0x1F600)
    assert hex_run_before_cursor("0X1F600") == (7, 0x1F600)


def test_hex_run_takes_at_most_six_digits():
    from uniti.core.unicode_hex import hex_run_before_cursor

    run_length, code_point = hex_run_before_cursor("910FFFF")
    assert run_length == 6
    assert code_point == 0x10FFFF


def test_hex_run_none_when_not_hex():
    from uniti.core.unicode_hex import hex_run_before_cursor

    assert hex_run_before_cursor("hello") is None
    assert hex_run_before_cursor("") is None


def test_hex_run_rejects_out_of_range_code_point():
    from uniti.core.unicode_hex import hex_run_before_cursor

    assert hex_run_before_cursor("110000") is None


def test_hex_run_rejects_surrogate_code_point():
    from uniti.core.unicode_hex import hex_run_before_cursor

    assert hex_run_before_cursor("D800") is None
    assert hex_run_before_cursor("DFFF") is None


def test_hex_notation_formats_uppercase_at_least_four_digits():
    from uniti.core.unicode_hex import hex_notation

    assert hex_notation("A") == "U+0041"
    assert hex_notation("\U0001F600") == "U+1F600"


def test_hex_notation_rejects_multi_character_input():
    from uniti.core.unicode_hex import hex_notation

    with pytest.raises(ValueError):
        hex_notation("AB")
