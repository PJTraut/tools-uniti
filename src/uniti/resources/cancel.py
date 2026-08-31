"""Cooperative cancellation primitives."""

from __future__ import annotations

import threading


class WorkCancelled(RuntimeError):
    """Raised when cooperative UNITI work is cancelled."""


class CancellationToken:
    """Thread-safe cancellation signal shared by bounded work units."""

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise WorkCancelled("UNITI work cancelled")
