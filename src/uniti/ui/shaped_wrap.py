"""Bounded cluster-safe soft-wrap row provider."""

from collections import OrderedDict
import regex
from uniti.ui.text_layout import ShapedWindow, direction_for_text


class ShapedRowProvider:
    def __init__(self, document, font, width_px, tab_stop_px, *, direction_override=None):
        self.document, self.font = document, font
        self.width_px, self.tab_stop_px = width_px, tab_stop_px
        self.cache = OrderedDict()
        self.read_chars = 0
        self.blocked = False
        # BF-064: direction is a per-logical-line property, detected once
        # from the line's true start (column 0) and reused for every later
        # window of that line — a continuation window starting mid-line
        # would misjudge a paragraph whose first strong character came
        # earlier. This provider is recreated on every document edit (its
        # signature includes `document.revision` in `text_view.py`), so no
        # separate invalidation is needed here.
        self.directions: dict[int, object] = {}
        # The "primary direction" switch: when set, bypasses per-line
        # first-strong-character detection entirely (see
        # `HorizontalLayouts.direction_override`'s matching comment).
        self.direction_override = direction_override

    def __call__(self, line, column):
        key = line, column
        value = self.cache.pop(key, None)
        if value is not None:
            self.cache[key] = value
            return value
        if self.read_chars >= 8192:
            raise ValueError("shaped wrap pending")
        limit = min(8192, 8192 - self.read_chars)
        text = self.document.read_line_window(
            line, column_start=column, max_chars=limit
        )
        self.read_chars += max(1, len(text))
        complete = len(text) < limit
        if not text:
            return 0, True
        if not complete:
            clusters = list(regex.finditer(r"\X", text))
            stop = clusters[-1].start()
            if not stop:
                self.blocked = limit == 8192
                raise ValueError("grapheme exceeds layout budget")
            text = text[:stop]
        if column == 0:
            self.directions[line] = (
                self.direction_override
                if self.direction_override is not None
                else direction_for_text(text)
            )
        cached_direction = self.directions.get(line)
        if cached_direction is not None:
            direction = cached_direction
        elif self.direction_override is not None:
            direction = self.direction_override
        else:
            direction = direction_for_text(text)
        shaped = ShapedWindow(
            text,
            self.font,
            width_px=self.width_px,
            tab_stop_px=self.tab_stop_px,
            direction=direction,
        )
        for i in range(len(shaped.lines)):
            start, end = shaped.row_span(i)
            # The incomplete tail may wrap differently once continuation arrives.
            if not complete and i == len(shaped.lines) - 1:
                break
            self.cache[line, column + start] = (
                end - start,
                complete and end == len(text),
            )
        while len(self.cache) > 512:
            self.cache.popitem(last=False)
        value = self.cache.get(key)
        if value is None:
            raise ValueError("shaped wrap pending")
        return value
