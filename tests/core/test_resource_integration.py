from pathlib import Path

from uniti.core.document import Document
from uniti.core.offsets import ReadIntent
from uniti.resources import MemorySnapshot, ResourceManager
from uniti.resources.memory import GIB


def test_document_mapper_registers_reclaimable_spans_with_resource_manager(tmp_path: Path):
    path = tmp_path / "resource-map.txt"
    path.write_text(("éabc" * 100_000), encoding="utf-8")
    manager = ResourceManager(
        max_workers=1,
        initial_snapshot=MemorySnapshot(physical=16 * GIB, available=10 * GIB),
    )
    try:
        document = Document.open(path, resource_manager=manager)
        try:
            byte = document.offset_mapper.char_to_byte(70_000)
            assert byte > 70_000
            assert manager.cache.used_bytes > 0
        finally:
            document.close()
        assert manager.cache.used_bytes == 0
    finally:
        manager.shutdown()


def test_streaming_document_iteration_bypasses_reusable_span_cache(tmp_path: Path):
    path = tmp_path / "streaming-large.txt"
    path.write_bytes(b"x" * (8 << 20))
    manager = ResourceManager(
        max_workers=1,
        initial_snapshot=MemorySnapshot(16 * GIB, 8 * GIB),
    )
    try:
        with Document.open(path, encoding="utf-8", resource_manager=manager) as document:
            before = manager.cache.used_bytes
            consumed = sum(
                len(text)
                for _, text in document.iter_text(intent=ReadIntent.STREAMING)
            )

            assert consumed == 8 << 20
            assert manager.cache.used_bytes - before < 4 << 20
    finally:
        manager.shutdown()
