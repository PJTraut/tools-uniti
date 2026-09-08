"""Bounded Unicode extended grapheme navigation; document positions are code points.

Explicit selections remain exact. An unresolvable cluster is a capability limit:
ordinary navigation/deletion leaves the cursor and document unchanged.
"""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import regex

_CLUSTER = regex.compile(r"\X")
_RI = regex.compile(r"\A\p{Regional_Indicator}+")


@dataclass(frozen=True, slots=True)
class BoundaryResult:
    position: int
    complete: bool


def neighbor_boundary(
    document,
    cursor: int,
    direction: int,
    *,
    budget: int = 8192,
    inclusive: bool = False,
) -> BoundaryResult:
    remaining = budget
    for radius in (32, 128, 512, 2048):
        radius = min(radius, remaining // 2)
        if radius <= 0:
            break
        start = max(0, cursor - radius)
        before = document.read(start, cursor)
        iterator = document.iter_text(cursor, chunk_chars=radius)
        try:
            _, after = next(iterator)
        except StopIteration:
            after = ""
        after = after[:radius]
        remaining -= len(before) + radius
        text = before + after
        boundaries = [0, *[m.end() for m in _CLUSTER.finditer(text)]]
        local = cursor - start
        if inclusive and local in boundaries:
            target = local
        elif direction < 0:
            target = boundaries[max(0, bisect_left(boundaries, local) - 1)]
        else:
            target = boundaries[
                min(len(boundaries) - 1, bisect_right(boundaries, local))
            ]
        # A cut first cluster may carry context; RI parity can propagate across
        # several pairs. Only trust positions beyond that uncertain prefix.
        uncertain = boundaries[1] if len(boundaries) > 1 else len(text)
        ri = _RI.match(text)
        if ri:
            uncertain = max(uncertain, ri.end())
        left_known = start == 0 or min(local, target) > uncertain
        right_known = max(local, target) < len(text) or len(after) < radius
        if left_known and right_known:
            return BoundaryResult(start + target, True)
    return BoundaryResult(cursor, False)


def deletion_span(document, cursor: int, direction: int, *, budget: int = 8192):
    """Delete a whole containing cluster even after an explicit interior move."""
    left = neighbor_boundary(
        document, cursor, -1, budget=budget // 2, inclusive=direction > 0
    )
    right = neighbor_boundary(
        document, cursor, 1, budget=budget // 2, inclusive=direction < 0
    )
    if not left.complete or not right.complete:
        return None
    return left.position, right.position
