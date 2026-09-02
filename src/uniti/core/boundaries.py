"""Compact immutable byte-boundary sequences for decoded spans."""

from __future__ import annotations

import sys
from array import array
from collections.abc import Iterable, Iterator, Sequence
from typing import Protocol, overload


class BoundaryMap(Protocol):
    @overload
    def __getitem__(self, index: int) -> int: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[int, ...]: ...

    def __len__(self) -> int: ...

    @property
    def retained_size_bytes(self) -> int: ...


class LinearBoundaries(Sequence[int]):
    """An arithmetic boundary sequence with constant retained size."""

    __slots__ = ("first", "step", "count")

    def __init__(self, first: int, step: int, count: int) -> None:
        if first < 0 or step < 0 or count < 0:
            raise ValueError("linear boundaries must be non-negative")
        self.first = first
        self.step = step
        self.count = count

    def __len__(self) -> int:
        return self.count

    @overload
    def __getitem__(self, index: int) -> int: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[int, ...]: ...

    def __getitem__(self, index: int | slice) -> int | tuple[int, ...]:
        if isinstance(index, slice):
            return tuple(self[item] for item in range(*index.indices(self.count)))
        normalized = index + self.count if index < 0 else index
        if normalized < 0 or normalized >= self.count:
            raise IndexError(index)
        return self.first + normalized * self.step

    def __eq__(self, other: object) -> bool:
        if isinstance(other, LinearBoundaries):
            return (
                self.first,
                self.step,
                self.count,
            ) == (other.first, other.step, other.count)
        if not isinstance(other, Sequence) or len(other) != self.count:
            return False
        return all(value == other[index] for index, value in enumerate(self))

    @property
    def retained_size_bytes(self) -> int:
        return sys.getsizeof(self)


class ArrayBoundaries(Sequence[int]):
    """A packed 32/64-bit boundary sequence for variable-width text."""

    __slots__ = ("_values",)

    def __init__(self, values: Iterable[int]) -> None:
        collected = tuple(values)
        typecode = "I" if not collected or max(collected) <= 0xFFFFFFFF else "Q"
        self._values = array(typecode, collected)

    def __len__(self) -> int:
        return len(self._values)

    @overload
    def __getitem__(self, index: int) -> int: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[int, ...]: ...

    def __getitem__(self, index: int | slice) -> int | tuple[int, ...]:
        value = self._values[index]
        if isinstance(index, slice):
            return tuple(value)
        return int(value)

    def __iter__(self) -> Iterator[int]:
        return (int(value) for value in self._values)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Sequence) or len(other) != len(self):
            return False
        return all(value == other[index] for index, value in enumerate(self))

    @property
    def retained_size_bytes(self) -> int:
        return sys.getsizeof(self) + sys.getsizeof(self._values)


def boundary_map(values: Iterable[int]) -> BoundaryMap:
    """Validate boundaries and choose their smallest useful representation."""

    collected = tuple(values)
    if any(value < 0 for value in collected) or any(
        right < left for left, right in zip(collected, collected[1:])
    ):
        raise ValueError("boundaries must be non-negative and ascending")
    if len(collected) <= 1:
        return LinearBoundaries(collected[0] if collected else 0, 0, len(collected))
    step = collected[1] - collected[0]
    if all(value == collected[0] + index * step for index, value in enumerate(collected)):
        return LinearBoundaries(collected[0], step, len(collected))
    return ArrayBoundaries(collected)
