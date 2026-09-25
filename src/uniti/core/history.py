"""Undo/redo transaction history for UNITI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


_COALESCE_KINDS = frozenset({"typing", "backspace", "delete_forward"})


@dataclass(frozen=True, slots=True)
class EditOperation:
    start: int
    deleted_text: str
    inserted_text: str

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError("edit start must be non-negative")


@dataclass(frozen=True, slots=True)
class EditTransaction:
    operations: tuple[EditOperation, ...]


class HistoryEventKind(StrEnum):
    TRANSACTION = "transaction"
    UNDO = "undo"
    REDO = "redo"
    SAVE_POINT = "save_point"
    METADATA = "metadata"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class HistoryEvent:
    kind: HistoryEventKind
    transaction: EditTransaction | None
    cursor: int
    saved_cursor: int | None
    revision: int
    coalesce: str | None
    metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class HistoryTruncation:
    reason: str
    dropped_transactions: int
    dropped_bytes: int


@dataclass(frozen=True, slots=True)
class HistorySnapshot:
    transactions: tuple[EditTransaction, ...]
    cursor: int
    saved_cursor: int | None
    coalesce: str | None
    decoded_bytes: int
    persistable: bool = True
    truncations: tuple[HistoryTruncation, ...] = ()

    @classmethod
    def empty(cls) -> "HistorySnapshot":
        return cls((), 0, 0, None, 0)


class EditHistory:
    """Cursor-based immutable transaction history with saved-revision tracking."""

    def __init__(self, max_transactions: int = 100) -> None:
        if type(max_transactions) is not int or max_transactions <= 0:
            raise ValueError("max_transactions must be a positive integer")
        self._max_transactions = max_transactions
        self._transactions: list[EditTransaction] = []
        self._cursor = 0
        self._saved_cursor: int | None = 0
        self._coalesce: str | None = None

    @property
    def can_undo(self) -> bool:
        return self._cursor > 0

    @property
    def can_redo(self) -> bool:
        return self._cursor < len(self._transactions)

    @property
    def modified(self) -> bool:
        return self._saved_cursor is None or self._cursor != self._saved_cursor

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def saved_cursor(self) -> int | None:
        return self._saved_cursor

    def export_snapshot(
        self,
        *,
        max_transactions: int = 100,
        max_bytes: int = 64 << 20,
    ) -> HistorySnapshot:
        if type(max_transactions) is not int or max_transactions <= 0:
            raise ValueError("max_transactions must be a positive integer")
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")

        transactions = list(self._transactions)
        original_sizes = [estimate_transaction_bytes(item) for item in transactions]
        sizes = list(original_sizes)
        cursor = self._cursor
        saved_cursor = self._saved_cursor
        truncations: list[HistoryTruncation] = []

        def drop_one() -> tuple[int, int]:
            nonlocal cursor, saved_cursor
            if cursor > 0:
                size = sizes.pop(0)
                transactions.pop(0)
                cursor -= 1
                if saved_cursor is not None:
                    saved_cursor = saved_cursor - 1 if saved_cursor > 0 else None
            else:
                size = sizes.pop()
                transactions.pop()
                if saved_cursor is not None and saved_cursor > len(transactions):
                    saved_cursor = None
            return 1, size

        depth_count = 0
        depth_bytes = 0
        while len(transactions) > max_transactions:
            count, size = drop_one()
            depth_count += count
            depth_bytes += size
        if depth_count:
            truncations.append(
                HistoryTruncation("depth_limit", depth_count, depth_bytes)
            )

        decoded_bytes = sum(sizes)
        byte_count = 0
        byte_bytes = 0
        while decoded_bytes > max_bytes and transactions:
            count, size = drop_one()
            byte_count += count
            byte_bytes += size
            decoded_bytes -= size
        if byte_count:
            truncations.append(
                HistoryTruncation("byte_limit", byte_count, byte_bytes)
            )

        oversized_sizes = [size for size in original_sizes if size > max_bytes]
        persistable = not oversized_sizes
        if oversized_sizes:
            truncations.append(
                HistoryTruncation(
                    "transaction_over_limit",
                    len(oversized_sizes),
                    sum(oversized_sizes),
                )
            )

        coalesce = self._coalesce
        if not transactions or cursor != len(transactions):
            coalesce = None
        return HistorySnapshot(
            transactions=tuple(transactions),
            cursor=cursor,
            saved_cursor=saved_cursor,
            coalesce=coalesce,
            decoded_bytes=decoded_bytes,
            persistable=persistable,
            truncations=tuple(truncations),
        )

    def restore(self, snapshot: HistorySnapshot) -> None:
        if not isinstance(snapshot, HistorySnapshot):
            raise TypeError("snapshot must be a HistorySnapshot")
        if (
            self._transactions
            or self._cursor != 0
            or self._saved_cursor != 0
            or self._coalesce is not None
        ):
            raise ValueError("history must be pristine before restore")
        if len(snapshot.transactions) > self._max_transactions:
            raise ValueError("snapshot exceeds the live history depth")
        if type(snapshot.cursor) is not int or not (
            0 <= snapshot.cursor <= len(snapshot.transactions)
        ):
            raise ValueError("snapshot cursor is outside its history")
        if snapshot.saved_cursor is not None and (
            type(snapshot.saved_cursor) is not int
            or not 0 <= snapshot.saved_cursor <= len(snapshot.transactions)
        ):
            raise ValueError("snapshot saved cursor is outside its history")
        if snapshot.coalesce is not None and snapshot.coalesce not in _COALESCE_KINDS:
            raise ValueError("snapshot has an unsupported coalescing kind")
        if snapshot.coalesce is not None and (
            not snapshot.transactions
            or snapshot.cursor != len(snapshot.transactions)
        ):
            raise ValueError("snapshot coalescing boundary is invalid")
        if type(snapshot.decoded_bytes) is not int or snapshot.decoded_bytes < 0:
            raise ValueError("snapshot decoded byte count is invalid")
        if type(snapshot.persistable) is not bool:
            raise ValueError("snapshot persistable flag is invalid")

        decoded_bytes = 0
        for transaction in snapshot.transactions:
            if not isinstance(transaction, EditTransaction) or not transaction.operations:
                raise ValueError("snapshot contains an invalid transaction")
            for operation in transaction.operations:
                if (
                    not isinstance(operation, EditOperation)
                    or type(operation.start) is not int
                    or operation.start < 0
                    or not isinstance(operation.deleted_text, str)
                    or not isinstance(operation.inserted_text, str)
                ):
                    raise ValueError("snapshot contains an invalid edit operation")
            decoded_bytes += estimate_transaction_bytes(transaction)
        if snapshot.decoded_bytes != decoded_bytes:
            raise ValueError("snapshot decoded byte count does not match its history")

        for truncation in snapshot.truncations:
            if (
                not isinstance(truncation, HistoryTruncation)
                or not isinstance(truncation.reason, str)
                or not truncation.reason
                or type(truncation.dropped_transactions) is not int
                or truncation.dropped_transactions < 0
                or type(truncation.dropped_bytes) is not int
                or truncation.dropped_bytes < 0
            ):
                raise ValueError("snapshot contains an invalid truncation record")

        self._transactions = list(snapshot.transactions)
        self._cursor = snapshot.cursor
        self._saved_cursor = snapshot.saved_cursor
        self._coalesce = snapshot.coalesce

    @staticmethod
    def _can_coalesce(
        existing: EditTransaction,
        incoming: EditTransaction,
        coalesce: str,
    ) -> bool:
        if not existing.operations or len(incoming.operations) != 1:
            return False
        previous = existing.operations[-1]
        current = incoming.operations[0]
        if coalesce == "typing":
            return (
                not previous.deleted_text
                and not current.deleted_text
                and current.start == previous.start + len(previous.inserted_text)
            )
        if coalesce == "backspace":
            return (
                not previous.inserted_text
                and not current.inserted_text
                and current.start + len(current.deleted_text) == previous.start
            )
        if coalesce == "delete_forward":
            return (
                not previous.inserted_text
                and not current.inserted_text
                and current.start == previous.start
            )
        return False

    def record(
        self,
        transaction: EditTransaction,
        *,
        coalesce: str | None = None,
    ) -> None:
        if not transaction.operations:
            return
        if coalesce is not None and coalesce not in _COALESCE_KINDS:
            raise ValueError(f"unsupported coalescing kind: {coalesce}")
        if self._cursor < len(self._transactions):
            if self._saved_cursor is not None and self._saved_cursor > self._cursor:
                self._saved_cursor = None
            del self._transactions[self._cursor :]
            self._coalesce = None
        if (
            coalesce is not None
            and self._coalesce == coalesce
            and self._transactions
            and self._can_coalesce(self._transactions[-1], transaction, coalesce)
        ):
            previous = self._transactions[-1]
            self._transactions[-1] = EditTransaction(
                previous.operations + transaction.operations
            )
            return
        self._transactions.append(transaction)
        self._cursor += 1
        self._coalesce = coalesce
        self._enforce_limit()

    def break_coalescing(self) -> None:
        self._coalesce = None

    def _enforce_limit(self) -> None:
        excess = len(self._transactions) - self._max_transactions
        if excess <= 0:
            return
        del self._transactions[:excess]
        self._cursor -= excess
        if self._saved_cursor is not None:
            self._saved_cursor = (
                self._saved_cursor - excess
                if self._saved_cursor >= excess
                else None
            )

    def undo(self) -> EditTransaction:
        if not self.can_undo:
            raise ValueError("nothing to undo")
        self.break_coalescing()
        self._cursor -= 1
        return self._transactions[self._cursor]

    def redo(self) -> EditTransaction:
        if not self.can_redo:
            raise ValueError("nothing to redo")
        self.break_coalescing()
        transaction = self._transactions[self._cursor]
        self._cursor += 1
        return transaction

    def mark_saved(self) -> None:
        self._saved_cursor = self._cursor
        self.break_coalescing()


def estimate_transaction_bytes(transaction: EditTransaction) -> int:
    """Return conservative decoded UTF-8 storage for one transaction."""

    return 32 + sum(
        24
        + len(operation.deleted_text.encode("utf-8"))
        + len(operation.inserted_text.encode("utf-8"))
        for operation in transaction.operations
    )
