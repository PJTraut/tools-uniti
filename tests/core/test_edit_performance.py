from pathlib import Path
import time

from uniti.core.document import Document


def test_sequential_typing_coalesces_edit_pieces_and_stays_bounded(tmp_path: Path):
    path = tmp_path / "typing.txt"
    path.write_text("abc", encoding="utf-8")
    with Document.open(path) as document:
        started = time.perf_counter()
        for index in range(5_000):
            document.insert(index, "x")
        elapsed = time.perf_counter() - started
        assert document._piece_table.piece_count <= 3
        assert document.read(0, 8) == "xxxxxxxx"
        assert elapsed < 5.0
