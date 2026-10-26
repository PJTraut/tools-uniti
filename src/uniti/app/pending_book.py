"""A project book a search will read, not yet open (scopes plan S3).

A Project or Group search can cover hundreds of books; opening them all up
front would hold a file handle and a mapping for each. The provider hands
the Find window a `PendingBook` for each one that isn't open, and the search
job opens it just in time (`open_for_search`) and drops it (`release_search`)
as soon as there is nothing to keep. A book that is open already is passed
as its `Document`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


class PendingBook:
    """One book of a project that no tab shows."""

    def __init__(
        self,
        path: Path,
        opener: Callable[[Path], object | None],
        closer: Callable[[object], None],
    ) -> None:
        self.path = Path(path)
        self.document = None  # the opened Document, once `open_for_search` ran
        self._opener = opener
        self._closer = closer

    def open_for_search(self):
        """Open the book; None when it can't be read (it is left out)."""

        if self.document is None:
            self.document = self._opener(self.path)
        return self.document

    def release_search(self) -> None:
        """Close the book if this search opened it and nobody chose it."""

        document, self.document = self.document, None
        if document is not None:
            self._closer(document)
