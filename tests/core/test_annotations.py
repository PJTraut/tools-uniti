from pathlib import Path

from uniti.core.document import Document


def test_read_with_annotations_distinguishes_invalid_source_byte_from_real_replacement_char(tmp_path: Path):
    path = tmp_path / "invalid-vs-real.txt"
    path.write_bytes(b"A\xff" + "\ufffd".encode("utf-8") + b"Z")
    with Document.open(path, encoding="utf-8") as document:
        annotated = document.read_with_annotations(0, 4)
        assert annotated.text == "A\ufffd\ufffdZ"
        assert [(span.start, span.end, span.raw) for span in annotated.invalid_bytes] == [
            (1, 2, b"\xff")
        ]


def test_edit_replacing_invalid_source_byte_removes_invalid_annotation(tmp_path: Path):
    path = tmp_path / "invalid-edit.txt"
    path.write_bytes(b"A\xffZ")
    with Document.open(path, encoding="utf-8") as document:
        document.replace(1, 2, "\ufffd")
        annotated = document.read_with_annotations(0, 3)
        assert annotated.text == "A\ufffdZ"
        assert annotated.invalid_bytes == ()


def test_line_window_annotations_are_absolute_document_offsets(tmp_path: Path):
    path = tmp_path / "invalid-line.txt"
    path.write_bytes(b"one\nA\xffZ\n")
    with Document.open(path, encoding="utf-8") as document:
        annotated = document.read_line_window_annotated(1, column_start=0, max_chars=8)
        assert annotated.text == "A\ufffdZ"
        assert [(span.start, span.end, span.raw) for span in annotated.invalid_bytes] == [
            (5, 6, b"\xff")
        ]


def test_annotated_iteration_is_bounded_and_keeps_absolute_offsets(tmp_path: Path):
    path = tmp_path / "invalid-chunks.txt"
    path.write_bytes(b"ab\xffcd\xfeef")
    with Document.open(path, encoding="utf-8") as document:
        chunks = list(document.iter_annotated_text(chunk_chars=3))
    assert [(chunk.document_offset, chunk.text) for chunk in chunks] == [
        (0, "ab\ufffd"),
        (3, "cd\ufffd"),
        (6, "ef"),
    ]
    assert [
        (span.start, span.end, span.raw)
        for chunk in chunks
        for span in chunk.invalid_bytes
    ] == [(2, 3, b"\xff"), (5, 6, b"\xfe")]
