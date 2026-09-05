from pathlib import Path

from uniti.app.sparse import enable_sparse_file
from uniti.core.document import Document


def test_over_1gib_source_supports_early_line_navigation_and_edit_without_full_index(tmp_path: Path):
    path = tmp_path / "huge.txt"
    with path.open("wb") as handle:
        assert enable_sparse_file(handle.fileno())
        handle.write(b"abc\n" * 1024)
        handle.seek((1 << 30) + 12345)
        handle.write(b"Z")

    with Document.open(path, encoding="utf-8") as doc:
        assert doc.source.size > (1 << 30)
        assert doc.line_start(100) == 400
        doc.insert(402, "X")
        assert doc.read_line(100) == "abXc"
        assert not doc.document_line_index.complete
        assert not doc.offset_mapper.complete
