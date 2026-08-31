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
