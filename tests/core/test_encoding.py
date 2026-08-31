from pathlib import Path

from uniti.core.byte_source import ByteSource
from uniti.core.encoding import detect_encoding


def detect(tmp_path: Path, payload: bytes):
    path = tmp_path / "sample.txt"
    path.write_bytes(payload)
    with ByteSource.open(path) as source:
        return detect_encoding(source)


def test_utf8_bom_is_authoritative(tmp_path: Path):
    info = detect(tmp_path, b"\xef\xbb\xbfhello")
    assert info.detected == "utf-8-sig"
    assert info.bom == b"\xef\xbb\xbf"
    assert info.confidence == 1.0


def test_valid_utf8_without_bom_is_detected(tmp_path: Path):
    info = detect(tmp_path, "café 世界".encode("utf-8"))
    assert info.detected == "utf-8"
    assert info.bom is None
    assert info.confidence >= 0.95


def test_utf16le_bom_is_authoritative(tmp_path: Path):
    info = detect(tmp_path, b"\xff\xfeA\x00")
    assert info.detected == "utf-16-le"
    assert info.bom == b"\xff\xfe"
    assert info.confidence == 1.0


def test_utf32le_bom_is_checked_before_utf16le(tmp_path: Path):
    info = detect(tmp_path, b"\xff\xfe\x00\x00A\x00\x00\x00")
    assert info.detected == "utf-32-le"
    assert info.bom == b"\xff\xfe\x00\x00"
    assert info.confidence == 1.0


def test_utf16le_without_bom_uses_null_structure(tmp_path: Path):
    info = detect(tmp_path, "Alpha Beta\n".encode("utf-16-le"))
    assert info.detected == "utf-16-le"
    assert 0.7 <= info.confidence < 1.0


def test_invalid_utf8_falls_back_conservatively(tmp_path: Path):
    info = detect(tmp_path, b"Price \x96 10\x80")
    assert info.detected == "windows-1252"
    assert info.confidence < 0.8
    assert "iso-8859-1" in info.alternatives


def test_utf16be_without_bom_uses_null_structure(tmp_path: Path):
    info = detect(tmp_path, "Alpha Beta\n".encode("utf-16-be"))
    assert info.detected == "utf-16-be"
    assert 0.7 <= info.confidence < 1.0
