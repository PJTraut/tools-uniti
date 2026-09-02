from __future__ import annotations

from uniti.core.boundaries import ArrayBoundaries, LinearBoundaries, boundary_map


def test_linear_boundaries_support_sequence_index_slice_and_equality():
    boundaries = LinearBoundaries(first=3, step=2, count=5)

    assert len(boundaries) == 5
    assert boundaries[0] == 3
    assert boundaries[-1] == 11
    assert boundaries[1:4] == (5, 7, 9)
    assert boundaries == (3, 5, 7, 9, 11)
    assert boundaries.retained_size_bytes < 256


def test_boundary_map_selects_linear_or_compact_array_representation():
    linear = boundary_map([0, 1, 2, 3, 4])
    variable = boundary_map([0, 1, 3, 7, 8])

    assert isinstance(linear, LinearBoundaries)
    assert isinstance(variable, ArrayBoundaries)
    assert tuple(variable) == (0, 1, 3, 7, 8)
    assert variable.retained_size_bytes < 256


def test_boundary_map_rejects_negative_or_descending_values():
    for values in ([-1, 0], [0, 2, 1]):
        try:
            boundary_map(values)
        except ValueError as error:
            assert "boundaries" in str(error)
        else:
            raise AssertionError(f"invalid boundaries accepted: {values!r}")
