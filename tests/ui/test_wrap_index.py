from pathlib import Path

from uniti.core.document import Document
from uniti.ui.wrap_index import WrappedRowIndex


def test_exact_width_line_end_maps_to_the_final_wrapped_row(tmp_path: Path):
    path = tmp_path / "exact-width.txt"
    path.write_text("abcdefgh", encoding="utf-8")

    with Document.open(path, encoding="utf-8") as document:
        index = WrappedRowIndex(document, columns=4)

        assert index.row_for_position(0, 8) == 1
        assert index.row(1).column_start == 4
