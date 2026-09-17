from uniti.core.text_diff import (
    Hunk,
    HunkKind,
    align_left_to_right,
    align_right_to_left,
    changed_hunks,
    diff_lines,
)


def test_identical_lines_are_one_equal_hunk():
    lines = ["alpha", "beta", "gamma"]
    hunks = diff_lines(lines, lines)
    assert hunks == (Hunk(HunkKind.EQUAL, 0, 3, 0, 3),)
    assert changed_hunks(hunks) == ()


def test_empty_sequences_produce_no_hunks():
    assert diff_lines([], []) == ()
    assert diff_lines([], ["only"]) == (Hunk(HunkKind.INSERT, 0, 0, 0, 1),)
    assert diff_lines(["only"], []) == (Hunk(HunkKind.DELETE, 0, 1, 0, 0),)


def test_appended_line_is_an_insert_hunk():
    left = ["alpha", "beta"]
    right = ["alpha", "beta", "gamma"]
    hunks = diff_lines(left, right)
    assert hunks == (
        Hunk(HunkKind.EQUAL, 0, 2, 0, 2),
        Hunk(HunkKind.INSERT, 2, 2, 2, 3),
    )


def test_removed_line_is_a_delete_hunk():
    left = ["alpha", "beta", "gamma"]
    right = ["alpha", "gamma"]
    hunks = diff_lines(left, right)
    assert hunks == (
        Hunk(HunkKind.EQUAL, 0, 1, 0, 1),
        Hunk(HunkKind.DELETE, 1, 2, 1, 1),
        Hunk(HunkKind.EQUAL, 2, 3, 1, 2),
    )


def test_changed_line_is_a_replace_hunk():
    left = ["alpha", "beta", "gamma"]
    right = ["alpha", "BETA", "gamma"]
    hunks = diff_lines(left, right)
    assert hunks == (
        Hunk(HunkKind.EQUAL, 0, 1, 0, 1),
        Hunk(HunkKind.REPLACE, 1, 2, 1, 2),
        Hunk(HunkKind.EQUAL, 2, 3, 2, 3),
    )
    assert changed_hunks(hunks) == (Hunk(HunkKind.REPLACE, 1, 2, 1, 2),)


def test_align_left_to_right_within_an_equal_hunk_is_exact():
    hunks = (Hunk(HunkKind.EQUAL, 0, 5, 0, 5),)
    for line in range(5):
        assert align_left_to_right(hunks, line) == line
        assert align_right_to_left(hunks, line) == line


def test_align_across_an_unequal_length_replace_hunk_is_fractional():
    # 4 lines on the left become 2 lines on the right (e.g. two lines merged).
    hunks = (Hunk(HunkKind.REPLACE, 0, 4, 0, 2),)
    assert align_left_to_right(hunks, 0) == 0
    assert align_left_to_right(hunks, 1) == 0.5
    assert align_left_to_right(hunks, 2) == 1
    assert align_left_to_right(hunks, 3) == 1.5


def test_align_left_to_right_past_the_end_clamps_to_the_last_hunks_right_end():
    hunks = (Hunk(HunkKind.EQUAL, 0, 3, 0, 3),)
    assert align_left_to_right(hunks, 3) == 3
    assert align_left_to_right(hunks, 100) == 3


def test_align_with_no_hunks_is_zero():
    assert align_left_to_right((), 5) == 0.0
    assert align_right_to_left((), 5) == 0.0


def test_align_left_to_right_skips_an_insert_hunk_with_no_left_span():
    # An insert hunk has an empty left range, so no left line can land
    # "inside" it; a left line right before the insertion should map to
    # just before the inserted content on the right.
    hunks = (
        Hunk(HunkKind.EQUAL, 0, 2, 0, 2),
        Hunk(HunkKind.INSERT, 2, 2, 2, 5),
        Hunk(HunkKind.EQUAL, 2, 4, 5, 7),
    )
    assert align_left_to_right(hunks, 1) == 1
    assert align_left_to_right(hunks, 2) == 5
    assert align_right_to_left(hunks, 3) == 2
