from pathlib import Path

from uniti.core.byte_source import ByteSource
from uniti.core.decoder import decode_span


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
