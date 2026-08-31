from pathlib import Path

import pytest

from uniti.core.byte_source import ByteSource
from uniti.core.offsets import OffsetMapper


class CountingByteSource(ByteSource):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.read_calls = 0

    def read(self, start: int, length: int) -> bytes:
        self.read_calls += 1
        return super().read(start, length)


def test_utf8_character_boundaries_round_trip(tmp_path: Path):
    path = tmp_path / "map.txt"
    path.write_bytes("Aé中Z".encode("utf-8"))
    with ByteSource.open(path) as source:
        mapper = OffsetMapper(source, "utf-8", checkpoint_bytes=3)
        assert mapper.char_to_byte(3) == 6
        assert mapper.byte_to_char(6) == 3


def test_small_mapping_does_not_index_entire_large_source(tmp_path: Path):
    path = tmp_path / "large.txt"
    path.write_bytes(("0123456789\n" * 20_000).encode())
    with ByteSource.open(path) as source:
        mapper = OffsetMapper(source, "utf-8", checkpoint_bytes=1024)
        assert mapper.char_to_byte(10) == 10
        assert mapper.indexed_byte_end < source.size
        assert not mapper.complete


@pytest.mark.parametrize(
    ("encoding", "text"),
    [
        ("utf-16-le", "Aé😀Z"),
        ("utf-16-be", "Aé😀Z"),
        ("utf-32-le", "Aé中Z"),
        ("utf-32-be", "Aé中Z"),
    ],
)
def test_multibyte_unicode_mappings_round_trip(tmp_path: Path, encoding: str, text: str):
    path = tmp_path / f"{encoding}.txt"
    path.write_bytes(text.encode(encoding))
    with ByteSource.open(path) as source:
        mapper = OffsetMapper(source, encoding, checkpoint_bytes=5)
        for char_offset in range(len(text) + 1):
            byte_offset = mapper.char_to_byte(char_offset)
            assert mapper.byte_to_char(byte_offset) == char_offset


def test_bom_prefix_maps_character_zero_after_bom(tmp_path: Path):
    path = tmp_path / "bom.txt"
    path.write_bytes(b"\xef\xbb\xbf" + "Aé".encode("utf-8"))
    with ByteSource.open(path) as source:
        mapper = OffsetMapper(source, "utf-8-sig", checkpoint_bytes=2)
        assert mapper.char_to_byte(0) == 3
        assert mapper.byte_to_char(3) == 0
        with pytest.raises(ValueError):
            mapper.byte_to_char(0)


def test_byte_inside_utf8_character_is_rejected(tmp_path: Path):
    path = tmp_path / "inside.txt"
    path.write_bytes("A€B".encode("utf-8"))
    with ByteSource.open(path) as source:
        mapper = OffsetMapper(source, "utf-8", checkpoint_bytes=4)
        assert mapper.byte_to_char(1) == 1
        with pytest.raises(ValueError, match="character boundary"):
            mapper.byte_to_char(2)


def test_eof_and_requests_beyond_eof(tmp_path: Path):
    path = tmp_path / "eof.txt"
    path.write_text("Aé", encoding="utf-8")
    with ByteSource.open(path) as source:
        mapper = OffsetMapper(source, "utf-8", checkpoint_bytes=2)
        assert mapper.char_to_byte(2) == source.size
        assert mapper.byte_to_char(source.size) == 2
        assert mapper.total_chars() == 2
        assert mapper.complete
        with pytest.raises(ValueError):
            mapper.char_to_byte(3)
        with pytest.raises(ValueError):
            mapper.byte_to_char(source.size + 1)


def test_invalid_utf8_byte_occupies_one_character(tmp_path: Path):
    path = tmp_path / "invalid.txt"
    path.write_bytes(b"A\xffB")
    with ByteSource.open(path) as source:
        mapper = OffsetMapper(source, "utf-8", checkpoint_bytes=2)
        assert mapper.char_to_byte(2) == 2
        assert mapper.byte_to_char(2) == 2
        assert mapper.total_chars() == 3


def test_repeated_mapping_reuses_checkpoint_decoded_span(tmp_path: Path):
    path = tmp_path / "cached-span.txt"
    path.write_text("a" * 60_000, encoding="utf-8")
    with CountingByteSource.open(path) as source:
        mapper = OffsetMapper(source, "utf-8", checkpoint_bytes=65_536)
        assert mapper.char_to_byte(1) == 1
        reads_after_first_mapping = source.read_calls

        for char_offset in range(2, 10_000, 137):
            assert mapper.char_to_byte(char_offset) == char_offset

        assert source.read_calls == reads_after_first_mapping
