from uniti.core.bidi import is_rtl_paragraph


def test_pure_latin_is_ltr():
    assert is_rtl_paragraph("hello world") is False


def test_pure_arabic_is_rtl():
    assert is_rtl_paragraph("مرحبا بك") is True


def test_pure_hebrew_is_rtl():
    assert is_rtl_paragraph("שלום") is True


def test_arabic_followed_by_latin_is_rtl_by_first_strong_character():
    assert is_rtl_paragraph("مرحبا hello") is True


def test_latin_followed_by_arabic_is_ltr_by_first_strong_character():
    assert is_rtl_paragraph("hello مرحبا") is False


def test_leading_digits_are_weak_and_do_not_determine_direction():
    assert is_rtl_paragraph("123 مرحبا") is True
    assert is_rtl_paragraph("123 hello") is False


def test_leading_whitespace_and_punctuation_are_skipped():
    assert is_rtl_paragraph("   مرحبا") is True
    assert is_rtl_paragraph("!!! hello") is False


def test_empty_or_no_strong_character_defaults_to_ltr():
    assert is_rtl_paragraph("") is False
    assert is_rtl_paragraph("123 456") is False
    assert is_rtl_paragraph("   \t\n") is False
