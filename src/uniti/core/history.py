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

    def record(self, transaction: EditTransaction) -> None:
        if not transaction.operations:
            return
        if self._cursor < len(self._transactions):
            if self._saved_cursor is not None and self._saved_cursor > self._cursor:
                self._saved_cursor = None
            del self._transactions[self._cursor :]
        self._transactions.append(transaction)
        self._cursor += 1
        self._enforce_limit()

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
        self._cursor -= 1
        return self._transactions[self._cursor]

    def redo(self) -> EditTransaction:
        if not self.can_redo:
            raise ValueError("nothing to redo")
        transaction = self._transactions[self._cursor]
        self._cursor += 1
        return transaction

    def mark_saved(self) -> None:
        self._saved_cursor = self._cursor
