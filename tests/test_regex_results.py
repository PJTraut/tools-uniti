from uniti.regex.results import CaptureRecord, MatchRecord


def test_match_record_keeps_only_compact_absolute_spans():
    record = MatchRecord(
        start=10,
        end=20,
        captures=(CaptureRecord(1, "word", ((11, 14), (16, 19))),),
    )
    assert record.span == (10, 20)
    assert record.captures[0].name == "word"
    assert record.captures[0].spans == ((11, 14), (16, 19))


def test_match_index_queries_viewport_intersections_and_wrap_navigation():
    from uniti.regex.results import MatchIndex

    index = MatchIndex(
        (
            MatchRecord(2, 5),
            MatchRecord(10, 12),
            MatchRecord(20, 25),
        )
    )
    assert [record.span for record in index.intersecting(4, 11)] == [(2, 5), (10, 12)]
    assert index.next_index(0) == 0
    assert index.next_index(6) == 1
    assert index.next_index(30) == 0
    assert index.previous_index(19) == 1
    assert index.previous_index(1) == 2


def test_match_index_handles_empty_and_zero_width_records():
    from uniti.regex.results import MatchIndex

    empty = MatchIndex(())
    assert empty.next_index(0) is None
    assert empty.previous_index(0) is None
    assert empty.intersecting(0, 10) == ()

    zero = MatchIndex((MatchRecord(3, 3),))
    assert zero.intersecting(3, 4) == (MatchRecord(3, 3),)
