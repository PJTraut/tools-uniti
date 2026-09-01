"""Undo/redo transaction history for UNITI."""

from __future__ import annotations

from dataclasses import dataclass


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


class EditHistory:
    """Cursor-based immutable transaction history with saved-revision tracking."""

    def __init__(self, max_transactions: int = 50) -> None:
        if max_transactions <= 0:
            raise ValueError("max_transactions must be positive")
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
