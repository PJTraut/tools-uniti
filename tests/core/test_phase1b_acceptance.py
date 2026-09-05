import os
from pathlib import Path

import pytest

from uniti.core.document import Document


@pytest.mark.skipif(
    os.name == "nt",
    reason="requires safe native sparse-file creation",
)
def test_sparse_source_above_one_gib_stays_lazy_during_early_edit(tmp_path: Path):
    path = tmp_path / "sparse-large.txt"
    tail_offset = (1 << 30) + 12_345
    try:
        with path.open("wb") as handle:
            handle.write(b"hello\n")
            handle.seek(tail_offset)
            handle.write(b"TAIL")
    except OSError as exc:
        pytest.fail(f"required sparse test fixture is unavailable: {exc}")

    with Document.open(path, encoding="utf-8") as doc:
        assert doc.source.size == tail_offset + 4
        assert doc.source.read(tail_offset, 4) == b"TAIL"
        assert not doc.offset_mapper.complete
        assert not doc.source_line_index.complete

        doc.insert(2, "X")
        assert doc.read(0, 7) == "heXllo\n"
        assert doc.modified
        assert not doc.offset_mapper.complete
        assert not doc.source_line_index.complete
        assert doc.offset_mapper.indexed_byte_end < (1 << 20)
