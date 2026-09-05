from pathlib import Path

from uniti.app.editor_state import EditorState
from uniti.app.sparse import enable_sparse_file
from uniti.core.document import Document


def test_a12_version_and_large_file_invariants(tmp_path: Path):
    path = tmp_path / "gib.txt"
    with path.open("wb") as handle:
        assert enable_sparse_file(handle.fileno())
        handle.write(b"abc\n")
        handle.seek((1 << 30) + 31)
        handle.write(b"END")
    with Document.open(path, encoding="utf-8") as document:
        document.insert(1, "X")
        assert document.read(0, 5) == "aXbc\n"
        assert not document.offset_mapper.complete
        assert not document.document_line_index.complete


def test_a12_sequential_typing_and_giant_line_navigation(tmp_path: Path):
    typing_path = tmp_path / "typing.txt"
    typing_path.write_text("abc", encoding="utf-8")
    with Document.open(typing_path) as document:
        for index in range(5_000):
            document.insert(index, "x")
        assert document._piece_table.piece_count <= 3

    giant = tmp_path / "giant.txt"
    giant.write_bytes(b"x" * (16 * 1024 * 1024))
    with Document.open(giant, encoding="utf-8") as document:
        state = EditorState(document)
        state.move_end()
        assert state.cursor == 16 * 1024 * 1024
