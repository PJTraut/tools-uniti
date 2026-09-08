"""Progressive pixel checkpoints. Unknown variable-width prefixes stay pending."""

from bisect import bisect_right
from collections import OrderedDict
import regex
from uniti.ui.text_layout import ShapedWindow


class HorizontalLayouts:
    def __init__(self, document, font, tab_stop_px):
        self.document, self.font, self.tab_stop_px = document, font, tab_stop_px
        self.checkpoints = {}
        self.cache = OrderedDict()

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
            shaped = ShapedWindow(
                text,
                self.font,
                document_start=start,
                tab_stop_px=self.tab_stop_px,
                tab_origin=offset,
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
