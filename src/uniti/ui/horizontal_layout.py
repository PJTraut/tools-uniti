"""Progressive pixel checkpoints. Unknown variable-width prefixes stay pending.

BF-064: `offset`/`edge` (`offset + shaped.width`) are a direction-agnostic
reading-order pixel distance from the line's true start — this module never
shapes with `align_width_px`, so `shaped.width` is always this checkpoint's
own tight natural width, regardless of direction. Consuming this correctly
for a right-to-left line is the caller's responsibility: `UNITITextView`
treats `horizontalScrollBar().value()` as the same reading-order distance
(not a raw screen pixel) for both directions, and maps it to actual screen
coordinates itself (`_row_text_x`) — see that module for the non-wrapped/
multi-checkpoint RTL scroll fix. Nothing here needed to change for it.
"""

from bisect import bisect_right
from collections import OrderedDict
import regex
from uniti.ui.text_layout import ShapedWindow, direction_for_text


class HorizontalLayouts:
    def __init__(self, document, font, tab_stop_px):
        self.document, self.font, self.tab_stop_px = document, font, tab_stop_px
        self.checkpoints = {}
        self.cache = OrderedDict()
        # Same per-logical-line detect-once-reuse rationale as
        # `ShapedRowProvider` (`shaped_wrap.py`); this instance is likewise
        # recreated on every document edit (`document.revision` is part of
        # its construction signature in `text_view.py`).
        self.directions: dict[int, object] = {}

    def window(self, line, *, pixel=0.0, column=None):
        checkpoints = self.checkpoints.setdefault(line, [(0, 0.0)])
        coordinate = 0 if column is not None else 1
        target = column if column is not None else pixel
        i = max(0, bisect_right([p[coordinate] for p in checkpoints], target) - 1)
        start, offset = checkpoints[i]
        key = line, start
        cached = self.cache.pop(key, None)
        if cached is None:
            text = self.document.read_line_window(
                line, column_start=start, max_chars=8192
            )
            complete = len(text) < 8192
            if not complete:
                # Retain a whole trailing cluster for the next bounded window.
                matches = list(regex.finditer(r"\X", text))
                stop = matches[-1].start() if matches else 0
                if stop == 0:
                    return start, offset, ShapedWindow("", self.font), False
                text = text[:stop]
            if start == 0:
                self.directions[line] = direction_for_text(text)
            cached_direction = self.directions.get(line)
            direction = (
                direction_for_text(text)
                if cached_direction is None
                else cached_direction
            )
            shaped = ShapedWindow(
                text,
                self.font,
                document_start=start,
                tab_stop_px=self.tab_stop_px,
                tab_origin=offset,
                direction=direction,
            )
            cached = shaped, complete
        shaped, complete = cached
        self.cache[key] = cached
        while len(self.cache) > 64:
            self.cache.popitem(last=False)
        end = start + len(shaped.text)
        edge = offset + shaped.width
        if not complete and i == len(checkpoints) - 1:
            checkpoints.append((end, edge))
        resolved = complete or (column < end if column is not None else pixel < edge)
        return start, offset, shaped, resolved
