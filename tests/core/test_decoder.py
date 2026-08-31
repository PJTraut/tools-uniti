from pathlib import Path

from uniti.core.byte_source import ByteSource
from uniti.core.decoder import decode_span, iter_decoded_spans


def test_utf8_span_maps_character_boundaries_to_bytes(tmp_path: Path):
    path = tmp_path / "utf8.txt"
    path.write_bytes("Aé中Z".encode("utf-8"))
    with ByteSource.open(path) as source:
        span = decode_span(source, 0, source.size, "utf-8")
    assert span.text == "Aé中Z"
    assert span.char_boundaries == (0, 1, 3, 6, 7)
    assert span.byte_offset_for_char_boundary(3) == 6


def test_invalid_utf8_bytes_are_visible_and_preserved(tmp_path: Path):
    path = tmp_path / "bad.txt"
    path.write_bytes(b"A\xffB")
    with ByteSource.open(path) as source:
        span = decode_span(source, 0, 3, "utf-8")
    assert span.text == "A\ufffdB"
    assert len(span.errors) == 1
    assert span.errors[0].byte_start == 1
    assert span.errors[0].byte_end == 2
    assert span.errors[0].raw == b"\xff"
    assert span.char_boundaries == (0, 1, 2, 3)


def test_undefined_cp1252_byte_is_preserved(tmp_path: Path):
    path = tmp_path / "bad-1252.txt"
    path.write_bytes(b"A\x81B")
    with ByteSource.open(path) as source:
        span = decode_span(source, 0, 3, "windows-1252")
    assert span.text == "A\ufffdB"
    assert span.errors[0].raw == b"\x81"


def test_utf8_sig_keeps_bom_outside_visible_text_boundaries(tmp_path: Path):
    path = tmp_path / "bom.txt"
    path.write_bytes(b"\xef\xbb\xbf" + "Aé".encode("utf-8"))
    with ByteSource.open(path) as source:
        span = decode_span(source, 0, source.size, "utf-8-sig")
    assert span.text == "Aé"
    assert span.char_boundaries == (3, 4, 6)
    assert span.byte_offset_for_char_boundary(0) == 3


def test_span_mapping_uses_absolute_source_offsets(tmp_path: Path):
    path = tmp_path / "slice.txt"
    path.write_bytes(b"xx" + "Aé".encode("utf-8") + b"yy")
    with ByteSource.open(path) as source:
        span = decode_span(source, 2, 3, "utf-8")
    assert span.char_boundaries == (0, 1, 3)
    assert span.byte_offset_for_char_boundary(2) == 5


def test_invalid_utf16le_dangling_byte_is_preserved(tmp_path: Path):
    path = tmp_path / "bad-utf16le-tail.txt"
    path.write_bytes(b"A\x00\xff")
    with ByteSource.open(path) as source:
        span = decode_span(source, 0, source.size, "utf-16-le")
    assert span.text == "A\ufffd"
    assert span.char_boundaries == (0, 2, 3)
    assert len(span.errors) == 1
    assert span.errors[0].byte_start == 2
    assert span.errors[0].byte_end == 3
    assert span.errors[0].raw == b"\xff"


def test_invalid_utf16le_code_unit_is_one_error_span(tmp_path: Path):
    path = tmp_path / "bad-utf16le-surrogate.txt"
    path.write_bytes(b"\x00\xd8")
    with ByteSource.open(path) as source:
        span = decode_span(source, 0, source.size, "utf-16-le")
    assert span.text == "\ufffd"
    assert span.char_boundaries == (0, 2)
    assert len(span.errors) == 1
    assert span.errors[0].byte_start == 0
    assert span.errors[0].byte_end == 2
    assert span.errors[0].raw == b"\x00\xd8"


def test_invalid_utf32le_tail_is_preserved_as_one_span(tmp_path: Path):
    path = tmp_path / "bad-utf32le-tail.txt"
    path.write_bytes(b"A\x00\x00\x00\xff\xfe")
    with ByteSource.open(path) as source:
        span = decode_span(source, 0, source.size, "utf-32-le")
    assert span.text == "A\ufffd"
    assert span.char_boundaries == (0, 4, 6)
    assert len(span.errors) == 1
    assert span.errors[0].byte_start == 4
    assert span.errors[0].byte_end == 6
    assert span.errors[0].raw == b"\xff\xfe"


def test_utf16le_bom_is_not_visible_text(tmp_path: Path):
    path = tmp_path / "utf16le-bom.txt"
    path.write_bytes(b"\xff\xfe" + "Aé".encode("utf-16-le"))
    with ByteSource.open(path) as source:
        span = decode_span(source, 0, source.size, "utf-16-le")
    assert span.text == "Aé"
    assert span.char_boundaries == (2, 4, 6)
    assert span.byte_offset_for_char_boundary(0) == 2


def test_utf32be_bom_is_not_visible_text(tmp_path: Path):
    path = tmp_path / "utf32be-bom.txt"
    path.write_bytes(b"\x00\x00\xfe\xff" + "AZ".encode("utf-32-be"))
    with ByteSource.open(path) as source:
        span = decode_span(source, 0, source.size, "utf-32-be")
    assert span.text == "AZ"
    assert span.char_boundaries == (4, 8, 12)
    assert span.byte_offset_for_char_boundary(0) == 4


def test_iter_decoded_spans_keeps_utf8_character_intact(tmp_path: Path):
    path = tmp_path / "utf8-window.txt"
    path.write_bytes("AB€CD".encode("utf-8"))
    with ByteSource.open(path) as source:
        spans = list(iter_decoded_spans(source, "utf-8", chunk_size=4))
    assert "".join(span.text for span in spans) == "AB€CD"
    assert not any(span.errors for span in spans)


def test_iter_decoded_spans_keeps_utf16_surrogate_pair_intact(tmp_path: Path):
    path = tmp_path / "utf16-window.txt"
    path.write_bytes("A😀B".encode("utf-16-le"))
    with ByteSource.open(path) as source:
        spans = list(iter_decoded_spans(source, "utf-16-le", chunk_size=4))
    assert "".join(span.text for span in spans) == "A😀B"
    assert not any(span.errors for span in spans)


def test_iter_decoded_spans_preserves_bom_only_on_first_span(tmp_path: Path):
    path = tmp_path / "bom-window.txt"
    path.write_bytes(b"\xef\xbb\xbf" + "ABéCD".encode("utf-8"))
    with ByteSource.open(path) as source:
        spans = list(iter_decoded_spans(source, "utf-8-sig", chunk_size=4))
    assert "".join(span.text for span in spans) == "ABéCD"
    assert spans[0].char_boundaries[0] == 3


def test_iter_decoded_spans_preserves_invalid_utf8(tmp_path: Path):
    path = tmp_path / "invalid-window.txt"
    path.write_bytes(b"ab\xffcd")
    with ByteSource.open(path) as source:
        spans = list(iter_decoded_spans(source, "utf-8", chunk_size=2))
    assert "".join(span.text for span in spans) == "ab\ufffdcd"
    errors = [error for span in spans for error in span.errors]
    assert [(error.byte_start, error.byte_end, error.raw) for error in errors] == [
        (2, 3, b"\xff")
    ]


def test_iter_decoded_spans_validates_range_and_chunk_size(tmp_path: Path):
    import pytest

    path = tmp_path / "range.txt"
    path.write_bytes(b"abc")
    with ByteSource.open(path) as source:
        with pytest.raises(ValueError):
            list(iter_decoded_spans(source, "utf-8", start=-1))
        with pytest.raises(ValueError):
            list(iter_decoded_spans(source, "utf-8", end=4))
        with pytest.raises(ValueError):
            list(iter_decoded_spans(source, "utf-8", chunk_size=0))


def test_iter_decoded_spans_reassembles_many_small_windows(tmp_path: Path):
    text = "αβγ😀é中" * 20
    path = tmp_path / "many-windows.txt"
    path.write_bytes(text.encode("utf-8"))
    with ByteSource.open(path) as source:
        spans = list(iter_decoded_spans(source, "utf-8", chunk_size=5))
    assert "".join(span.text for span in spans) == text
    assert not any(span.errors for span in spans)
