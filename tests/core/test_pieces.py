from pathlib import Path

from uniti.core.byte_source import ByteSource
from uniti.core.offsets import OffsetMapper
from uniti.core.pieces import EditStore, PieceTable, SourcePiece


def test_insert_splits_source_tail_without_counting_entire_document(tmp_path: Path):
    path = tmp_path / "doc.txt"
    path.write_text("abcdefghij", encoding="utf-8")
    with ByteSource.open(path) as source:
        mapper = OffsetMapper(source, "utf-8", checkpoint_bytes=4)
        table = PieceTable(source, "utf-8", mapper, EditStore())
        table.insert(3, "XYZ")
        assert table.read(0, 8) == "abcXYZde"
        assert table.piece_count == 3
        assert isinstance(table._pieces[-1], SourcePiece)
        assert table._pieces[-1].char_length is None
        assert not mapper.complete


def test_edit_store_reads_slices_without_copying_block_identity():
    store = EditStore()
    ref = store.append("abcdef")
    sliced = store.slice(ref, 2, 5)
    assert sliced.block == ref.block
    assert store.read(sliced) == "cde"
    assert store.read(sliced, 1, 3) == "de"


def test_replace_across_source_and_edit_pieces(tmp_path: Path):
    path = tmp_path / "replace.txt"
    path.write_text("abcdef", encoding="utf-8")
    with ByteSource.open(path) as source:
        mapper = OffsetMapper(source, "utf-8")
        table = PieceTable(source, "utf-8", mapper, EditStore())
        table.insert(3, "XYZ")
        table.replace(2, 7, "!")
        assert table.read(0, table.total_chars()) == "ab!ef"


def test_multibyte_source_edits_use_character_offsets(tmp_path: Path):
    path = tmp_path / "unicode.txt"
    path.write_text("Aé中😀Z", encoding="utf-8")
    with ByteSource.open(path) as source:
        mapper = OffsetMapper(source, "utf-8", checkpoint_bytes=4)
        table = PieceTable(source, "utf-8", mapper, EditStore())
        table.insert(2, "++")
        table.delete(4, 5)
        assert table.read(0, table.total_chars()) == "Aé++😀Z"


def test_invalid_source_byte_remains_visible_through_piece_reads(tmp_path: Path):
    path = tmp_path / "invalid.txt"
    path.write_bytes(b"A\xffB")
    with ByteSource.open(path) as source:
        mapper = OffsetMapper(source, "utf-8", checkpoint_bytes=2)
        table = PieceTable(source, "utf-8", mapper, EditStore())
        table.insert(1, "X")
        assert table.read(0, 4) == "AX\ufffdB"


def test_delete_entire_document_then_insert(tmp_path: Path):
    path = tmp_path / "all.txt"
    path.write_text("abcdef", encoding="utf-8")
    with ByteSource.open(path) as source:
        mapper = OffsetMapper(source, "utf-8")
        table = PieceTable(source, "utf-8", mapper, EditStore())
        table.delete(0, 6)
        assert table.total_chars() == 0
        assert table.read(0, 0) == ""
        table.insert(0, "new")
        assert table.read(0, 3) == "new"


def test_empty_operations_are_noops_but_validate_boundaries(tmp_path: Path):
    import pytest

    path = tmp_path / "noop.txt"
    path.write_text("abc", encoding="utf-8")
    with ByteSource.open(path) as source:
        mapper = OffsetMapper(source, "utf-8")
        table = PieceTable(source, "utf-8", mapper, EditStore())
        table.insert(1, "")
        table.delete(2, 2)
        table.replace(3, 3, "")
        assert table.read(0, 3) == "abc"
        with pytest.raises(ValueError):
            table.insert(4, "")
        with pytest.raises(ValueError):
            table.read(0, 4)
        with pytest.raises(ValueError):
            table.delete(-1, 1)
