"""Bounded, page-spooled plans for atomic regex replacement."""

from __future__ import annotations

from array import array
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
import pickle
import struct
import tempfile

from uniti.core.document import ReplacementPlanLimitError


_LENGTH = struct.Struct("!I")


@dataclass(frozen=True, slots=True)
class Replacement:
    start: int
    end: int
    text: str

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError("invalid replacement range")


@dataclass(frozen=True, slots=True)
class ReplacementPlanEstimate:
    count: int
    inserted_chars: int
    deleted_chars: int
    resident_bytes: int
    apply_bytes: int


class ReplacementPlan:
    """Append sorted records while retaining at most two bounded pages."""

    def __init__(
        self,
        *,
        memory_budget_bytes: int,
        document_revision: int,
        page_size: int = 1024,
    ) -> None:
        if memory_budget_bytes <= 0:
            raise ValueError("memory_budget_bytes must be positive")
        if document_revision < 0:
            raise ValueError("document_revision must be non-negative")
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        self.memory_budget_bytes = int(memory_budget_bytes)
        self.document_revision = int(document_revision)
        self._page_size = int(page_size)
        self._memory_records: list[Replacement] = []
        self._memory_estimate = 0
        self._spool = None
        self._page_offsets = array("Q")
        self._write_page: list[Replacement] = []
        self._read_page: tuple[Replacement, ...] = ()
        self._count = 0
        self._inserted_chars = 0
        self._deleted_chars = 0
        self._apply_bytes = 0
        self._last_end: int | None = None
        self._closed = False

    @staticmethod
    def _record_size(record: Replacement) -> int:
        return 64 + len(record.text) * 4

    @property
    def spilled(self) -> bool:
        return self._spool is not None

    @property
    def resident_record_count(self) -> int:
        if self._spool is None:
            return len(self._memory_records)
        return len(self._write_page) + len(self._read_page)

    @property
    def estimate(self) -> ReplacementPlanEstimate:
        if self._spool is None:
            resident = self._memory_estimate
        else:
            resident = (
                len(self._page_offsets) * self._page_offsets.itemsize
                + sum(self._record_size(record) for record in self._write_page)
                + sum(self._record_size(record) for record in self._read_page)
            )
        return ReplacementPlanEstimate(
            count=self._count,
            inserted_chars=self._inserted_chars,
            deleted_chars=self._deleted_chars,
            resident_bytes=resident,
            apply_bytes=self._apply_bytes,
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("ReplacementPlan is closed")

    def _write_records(self, records: list[Replacement]) -> None:
        if self._spool is None or not records:
            return
        payload = pickle.dumps(tuple(records), protocol=5)
        self._page_offsets.append(self._spool.tell())
        self._spool.write(_LENGTH.pack(len(payload)))
        self._spool.write(payload)

    def _flush_write_page(self) -> None:
        if not self._write_page:
            return
        self._write_records(self._write_page)
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

    def append(self, replacement: Replacement) -> None:
        self._ensure_open()
        if not isinstance(replacement, Replacement):
            raise TypeError("replacement must be a Replacement")
        if self._last_end is not None and replacement.start < self._last_end:
            raise ValueError("replacement plan must be sorted and non-overlapping")
        record_size = self._record_size(replacement)
        if (
            self._spool is None
            and self._memory_estimate + record_size > self.memory_budget_bytes
        ):
            self._start_spill()
        if self._spool is None:
            self._memory_records.append(replacement)
            self._memory_estimate += record_size
        else:
            self._write_page.append(replacement)
            if len(self._write_page) >= self._page_size:
                self._flush_write_page()
        self._last_end = replacement.end
        self._count += 1
        inserted = len(replacement.text)
        deleted = replacement.end - replacement.start
        self._inserted_chars += inserted
        self._deleted_chars += deleted
        self._apply_bytes += 64 + 4 * (inserted + deleted)

    def __len__(self) -> int:
        return self._count

    def __iter__(self) -> Iterator[Replacement]:
        self._ensure_open()
        if self._spool is None:
            yield from self._memory_records
            return
        self._flush_write_page()
        self._read_page = ()
        for offset in self._page_offsets:
            self._spool.seek(offset)
            header = self._spool.read(_LENGTH.size)
            if len(header) != _LENGTH.size:
                raise RuntimeError("truncated replacement-plan spool")
            (length,) = _LENGTH.unpack(header)
            payload = self._spool.read(length)
            if len(payload) != length:
                raise RuntimeError("truncated replacement-plan spool")
            page = pickle.loads(payload)
            if not isinstance(page, tuple) or not all(
                isinstance(record, Replacement) for record in page
            ):
                raise RuntimeError("invalid replacement-plan page")
            self._read_page = page
            yield from page

    @classmethod
    def from_iterable(
        cls,
        *,
        document_revision: int,
        replacements: Iterable[Replacement],
        memory_budget_bytes: int,
    ) -> "ReplacementPlan":
        plan = cls(
            memory_budget_bytes=memory_budget_bytes,
            document_revision=document_revision,
        )
        try:
            for replacement in replacements:
                plan.append(replacement)
        except Exception:
            plan.close()
            raise
        return plan

    def close(self) -> None:
        if self._closed:
            return
        if self._spool is not None:
            self._spool.close()
            self._spool = None
        self._memory_records.clear()
        self._write_page.clear()
        self._read_page = ()
        self._closed = True

    def __enter__(self) -> "ReplacementPlan":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
