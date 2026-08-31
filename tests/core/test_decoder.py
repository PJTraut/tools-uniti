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
