from pathlib import Path

from uniti.core.document import Document
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
