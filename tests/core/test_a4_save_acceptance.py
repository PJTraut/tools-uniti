from pathlib import Path

from uniti.core.document import Document


def test_streaming_save_handles_normal_large_workload_without_whole_document_copy(tmp_path: Path):
    source = tmp_path / "large-source.txt"
    target = tmp_path / "large-target.txt"
    block = b"0123456789abcdef\r\n" * 4096
    with source.open("wb") as handle:
        for _ in range(160):
            handle.write(block)
    original_size = source.stat().st_size
    assert original_size > 10 * 1024 * 1024

    with Document.open(source, encoding="utf-8") as doc:
        doc.insert(8, "X")
        doc.save(target)
        assert not doc.modified

    assert target.stat().st_size == original_size + 1
    with target.open("rb") as handle:
        assert handle.read(20) == b"01234567X89abcdef\r\n0"
        handle.seek(-18, 2)
        assert handle.read() == b"0123456789abcdef\r\n"
