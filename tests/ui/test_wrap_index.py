from pathlib import Path

from uniti.core.document import Document
from uniti.ui.wrap_index import WrappedRowIndex


class _GiantLineDocument:
    def __init__(self, length: int) -> None:
        self.length = length

    def line_start(self, line: int) -> int:
        if line == 0:
            return 0
        raise ValueError("line is beyond end of document")

    def line_end(self, line: int) -> int:
        if line == 0:
            return self.length
        raise ValueError("line is beyond end of document")

    def read_line_window(
        self,
        line: int,
        *,
        column_start: int = 0,
        max_chars: int = 4096,
    ) -> str:
        if line != 0 or column_start >= self.length:
            return ""
        return "x" * min(max_chars, self.length - column_start)


def test_exact_width_line_end_maps_to_the_final_wrapped_row(tmp_path: Path):
    path = tmp_path / "exact-width.txt"
    path.write_text("abcdefgh", encoding="utf-8")

    with Document.open(path, encoding="utf-8") as document:
        index = WrappedRowIndex(document, columns=4)

        assert index.row_for_position(0, 8) == 1
        assert index.row(1).column_start == 4


def test_giant_wrapped_line_does_not_allocate_one_object_per_visual_row():
    document = _GiantLineDocument(8_000_000)
    index = WrappedRowIndex(
        document,
        columns=80,
        row_block_size=512,
        max_blocks=4,
    )

    assert index.row_for_position(0, 8_000_000) == 99_999
    assert index.resident_row_count <= 2048
