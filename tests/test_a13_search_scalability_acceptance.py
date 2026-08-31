from pathlib import Path

from uniti.core.document import Document
from uniti.regex.engine import compile_pattern
from uniti.regex.match_store import MatchStore
from uniti.regex.results import MatchRecord
from uniti.regex.search import SearchOptions, search_document


def test_200k_match_store_spills_with_sparse_resident_index():
    store = MatchStore(memory_budget_bytes=64 * 1024, page_size=1024, document_revision=3)
    try:
        for index in range(200_000):
            store.append(MatchRecord(index * 2, index * 2 + 1))
        assert len(store) == 200_000
        assert store.spilled
        assert store.resident_record_count <= 2048
        assert store.index_bytes < 16 * 1024
        assert store.records[199_999].span == (399_998, 399_999)
    finally:
        store.close()


def test_search_result_revision_becomes_stale_after_edit(tmp_path: Path):
    path = tmp_path / "revision-search.txt"
    path.write_text("x x x", encoding="utf-8")
    with Document.open(path) as document:
        revision = document.revision
        store = MatchStore(document_revision=revision)
        try:
            for record in search_document(
                document,
                compile_pattern("x"),
                options=SearchOptions(include_captures=False),
            ):
                store.append(record)
            assert len(store) == 3
            document.insert(0, "y")
            assert document.revision != store.document_revision
        finally:
            store.close()
