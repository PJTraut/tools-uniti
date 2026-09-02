from uniti.regex.match_store import MatchStore
from uniti.regex.results import CaptureRecord, MatchRecord


def _records(count: int):
    for index in range(count):
        start = index * 10
        yield MatchRecord(
            start,
            start + 3,
            (CaptureRecord(1, "word", ((start, start + 3),)),),
        )


def test_match_store_behaves_like_navigation_index_before_spill():
    store = MatchStore(memory_budget_bytes=4096, document_revision=7)
    try:
        for record in _records(3):
            store.append(record)

        assert len(store) == 3
        assert store.document_revision == 7
        assert store.records[1].span == (10, 13)
        assert [record.span for record in store.intersecting(2, 11)] == [(0, 3), (10, 13)]
        assert store.next_index(4) == 1
        assert store.previous_index(19) == 1
        assert not store.spilled
    finally:
        store.close()


def test_match_store_spills_records_but_keeps_random_access():
    store = MatchStore(memory_budget_bytes=256, document_revision=11)
    try:
        for record in _records(200):
            store.append(record)

        assert store.spilled
        assert store.resident_record_count <= 2048
        assert store.index_bytes < 4096
        assert len(store) == 200
        assert store.records[137].span == (1370, 1373)
        assert store.records[137].captures[0].name == "word"
        assert [record.span for record in store.intersecting(1369, 1381)] == [
            (1370, 1373),
            (1380, 1383),
        ]
    finally:
        store.close()


def test_match_store_rejects_out_of_order_append():
    store = MatchStore(memory_budget_bytes=4096)
    try:
        store.append(MatchRecord(10, 12))
        try:
            store.append(MatchRecord(5, 7))
        except ValueError as exc:
            assert "sorted" in str(exc)
        else:
            raise AssertionError("out-of-order match append was accepted")
    finally:
        store.close()


def test_spilled_match_store_preserves_append_order_for_equal_spans():
    store = MatchStore(memory_budget_bytes=1, page_size=1)
    try:
        for name in ("first", "second", "third"):
            store.append(
                MatchRecord(2, 2, (CaptureRecord(1, name, ((2, 2),)),))
            )

        assert store.spilled
        assert [record.captures[0].name for record in store] == [
            "first",
            "second",
            "third",
        ]
    finally:
        store.close()


def test_match_store_rejects_invalid_spans():
    store = MatchStore()
    try:
        for record in (MatchRecord(-1, 0), MatchRecord(2, 1)):
            try:
                store.append(record)
            except ValueError as error:
                assert "span" in str(error)
            else:
                raise AssertionError("invalid match span was accepted")
    finally:
        store.close()
