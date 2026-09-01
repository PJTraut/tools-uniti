import pytest

from uniti.core.text_format import (
    EOLPolicy,
    OutputFormat,
    encoding_profile,
    encoding_profiles,
    format_summary,
    profile_from_codec,
)


@pytest.mark.parametrize(
    ("key", "label", "codec", "bom"),
    [
        ("utf-8", "UTF-8", "utf-8", b""),
        ("utf-8-bom", "UTF-8 BOM", "utf-8", b"\xef\xbb\xbf"),
        ("windows-1252", "Windows-1252", "windows-1252", b""),
        ("utf-16-le", "UTF-16 LE", "utf-16-le", b""),
        ("utf-16-le-bom", "UTF-16 LE BOM", "utf-16-le", b"\xff\xfe"),
        ("utf-16-be", "UTF-16 BE", "utf-16-be", b""),
        ("utf-16-be-bom", "UTF-16 BE BOM", "utf-16-be", b"\xfe\xff"),
        ("utf-32-le", "UTF-32 LE", "utf-32-le", b""),
        (
            "utf-32-le-bom",
            "UTF-32 LE BOM",
            "utf-32-le",
            b"\xff\xfe\x00\x00",
        ),
        ("utf-32-be", "UTF-32 BE", "utf-32-be", b""),
        (
            "utf-32-be-bom",
            "UTF-32 BE BOM",
            "utf-32-be",
            b"\x00\x00\xfe\xff",
        ),
    ],
)
def test_encoding_profiles_describe_exact_output_bytes(key, label, codec, bom):
    profile = encoding_profile(key)
    assert (profile.label, profile.codec, profile.bom) == (label, codec, bom)


def test_encoding_profiles_have_stable_ui_order():
    assert [profile.key for profile in encoding_profiles()] == [
        "utf-8",
        "utf-8-bom",
        "windows-1252",
        "utf-16-le",
        "utf-16-le-bom",
        "utf-16-be",
        "utf-16-be-bom",
        "utf-32-le",
        "utf-32-le-bom",
        "utf-32-be",
        "utf-32-be-bom",
    ]


def test_bom_omission_and_detection_are_unambiguous():
    assert profile_from_codec("utf-16-le", None).key == "utf-16-le"
    assert profile_from_codec("utf-16-le", b"\xff\xfe").key == "utf-16-le-bom"
    assert profile_from_codec("UTF_8_SIG", b"\xef\xbb\xbf").key == "utf-8-bom"


def test_unknown_or_mismatched_profiles_are_rejected():
    with pytest.raises(ValueError, match="unknown encoding profile"):
        encoding_profile("utf-7")
    with pytest.raises(ValueError, match="unsupported codec/BOM combination"):
        profile_from_codec("utf-8", b"\xff\xfe")


def test_compact_summary_keeps_line_endings_separate():
    output = OutputFormat(encoding_profile("utf-8"), EOLPolicy.CRLF)
    assert format_summary(output.encoding, output.eol) == "UTF-8, CRLF"

