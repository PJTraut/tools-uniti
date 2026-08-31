"""Bounded match-result storage with transparent page-spooled records."""

from __future__ import annotations

from array import array
import pickle
import struct
import tempfile
from collections.abc import Iterator, Sequence

from .results import MatchRecord

_LENGTH = struct.Struct("!I")


class _RecordSequence(Sequence[MatchRecord]):
    def __init__(self, store: "MatchStore") -> None:
        self._store = store

    def __len__(self) -> int:
        return len(self._store)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return tuple(self._store[i] for i in range(*index.indices(len(self))))
        return self._store[index]


class MatchStore:
    """Append sorted match records while bounding resident record memory.

    Small searches stay in memory. Once the configured budget is crossed,
    full records (including captures) are written as fixed-size pages to an
    anonymous temporary file. Only one write page, one read page, and a sparse
    page-offset/count index remain resident, so memory does not grow one Python
    object per match.
    """

    def __init__(
        self,
        *,
        memory_budget_bytes: int = 8 * 1024 * 1024,
        document_revision: int = 0,
        page_size: int = 1024,
    ) -> None:
        if memory_budget_bytes <= 0:
            raise ValueError("memory_budget_bytes must be positive")
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        self._budget = int(memory_budget_bytes)
        self._page_size = int(page_size)
        self.document_revision = int(document_revision)
        self._memory_records: list[MatchRecord] = []
        self._memory_estimate = 0
        self._count = 0
        self._last_start: int | None = None
        self._spool = None
        self._page_offsets = array("Q")
        self._page_counts = array("I")
        self._write_page: list[MatchRecord] = []
        self._read_page_index: int | None = None
        self._read_page: tuple[MatchRecord, ...] = ()
        self._closed = False
        self._records_view = _RecordSequence(self)

    @property
    def records(self) -> Sequence[MatchRecord]:
        return self._records_view

    @property
    def spilled(self) -> bool:
        return self._spool is not None

    @property
    def resident_record_count(self) -> int:
        if self._spool is None:
            return len(self._memory_records)
        return len(self._write_page) + len(self._read_page)

    @property
    def index_bytes(self) -> int:
        """Resident sparse spool-index payload, excluding Python object headers."""

        return len(self._page_offsets) * self._page_offsets.itemsize + len(
            self._page_counts
        ) * self._page_counts.itemsize

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("MatchStore is closed")

    @staticmethod
    def _estimate(record: MatchRecord) -> int:
        size = 48
        for capture in record.captures:
            size += 48 + len(capture.spans) * 16
            if capture.name:
                size += len(capture.name.encode("utf-8"))
        return size

    def _write_page_payload(self, records: list[MatchRecord]) -> None:
        if self._spool is None or not records:
            return
        payload = pickle.dumps(tuple(records), protocol=5)
        offset = self._spool.tell()
        self._spool.write(_LENGTH.pack(len(payload)))
        self._spool.write(payload)
        self._page_offsets.append(offset)
        self._page_counts.append(len(records))

    def _flush_write_page(self) -> None:
        if self._spool is None or not self._write_page:
            return
        self._write_page_payload(self._write_page)
        self._write_page.clear()

    def _start_spill(self) -> None:
        if self._spool is not None:
            return
        records = self._memory_records
        self._memory_records = []
        self._memory_estimate = 0
        self._spool = tempfile.TemporaryFile(mode="w+b")
        for record in records:
            self._write_page.append(record)
            if len(self._write_page) >= self._page_size:
                self._flush_write_page()

    def append(self, record: MatchRecord) -> None:
        self._ensure_open()
        if self._last_start is not None and record.start < self._last_start:
            raise ValueError("match records must be appended in sorted order")
        estimate = self._estimate(record)
        if self._spool is None and self._memory_estimate + estimate > self._budget:
            self._start_spill()
        self._last_start = record.start
        self._count += 1
        if self._spool is None:
            self._memory_records.append(record)
            self._memory_estimate += estimate
        else:
            self._write_page.append(record)
            if len(self._write_page) >= self._page_size:
                self._flush_write_page()

    def __len__(self) -> int:
        return self._count

    def __iter__(self) -> Iterator[MatchRecord]:
        for index in range(len(self)):
            yield self[index]

    def _load_page(self, page_index: int) -> tuple[MatchRecord, ...]:
        if page_index == len(self._page_offsets):
            return tuple(self._write_page)
        if self._read_page_index == page_index:
            return self._read_page
        if self._spool is None:
            raise RuntimeError("match spool is not initialized")
        offset = self._page_offsets[page_index]
        self._spool.seek(offset)
        header = self._spool.read(_LENGTH.size)
        if len(header) != _LENGTH.size:
            raise RuntimeError("truncated match spool")
        (length,) = _LENGTH.unpack(header)
        payload = self._spool.read(length)
        if len(payload) != length:
            raise RuntimeError("truncated match spool")
        page = pickle.loads(payload)
        if not isinstance(page, tuple) or not all(isinstance(item, MatchRecord) for item in page):
            raise RuntimeError("invalid match spool page")
        self._read_page_index = page_index
        self._read_page = page
        return page

    def __getitem__(self, index: int) -> MatchRecord:
        self._ensure_open()
        count = len(self)
        if index < 0:
            index += count
        if index < 0 or index >= count:
            raise IndexError(index)
        if self._spool is None:
            return self._memory_records[index]
        page_index, local_index = divmod(index, self._page_size)
        page = self._load_page(page_index)
        return page[local_index]

    def _first_at_or_after(self, position: int) -> int:
        low = 0
        high = len(self)
        while low < high:
            middle = (low + high) // 2
            if self[middle].start < position:
                low = middle + 1
            else:
                high = middle
        return low

    def intersecting(self, start: int, end: int) -> tuple[MatchRecord, ...]:
        self._ensure_open()
        if start < 0 or end < start:
            raise ValueError("invalid match query range")
        if not len(self):
            return ()
        index = self._first_at_or_after(start)
        while index > 0:
            previous = self[index - 1]
            if previous.end <= start:
                break
            index -= 1
        found: list[MatchRecord] = []
        while index < len(self):
            record = self[index]
            if record.start >= end and not (record.start == record.end == start == end):
                break
            intersects = (
                start <= record.start < end
                if record.start == record.end
                else record.end > start and record.start < end
            )
            if start == end == record.start == record.end:
                intersects = True
            if intersects:
                found.append(record)
            index += 1
        return tuple(found)

    def next_index(self, position: int) -> int | None:
        self._ensure_open()
        if not len(self):
            return None
        index = self._first_at_or_after(position)
        return 0 if index >= len(self) else index

    def previous_index(self, position: int) -> int | None:
        self._ensure_open()
        if not len(self):
            return None
        index = self._first_at_or_after(position) - 1
        return len(self) - 1 if index < 0 else index

    def close(self) -> None:
        if self._closed:
            return
        if self._spool is not None:
            self._spool.close()
        self._memory_records.clear()
        self._write_page.clear()
        self._read_page = ()
        self._page_offsets = array("Q")
        self._page_counts = array("I")
        self._closed = True
