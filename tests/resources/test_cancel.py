import threading

import pytest

from uniti.resources.cancel import CancellationToken, WorkCancelled


def test_token_starts_active_and_cancel_is_idempotent():
    token = CancellationToken()
    assert not token.cancelled
    token.cancel()
    token.cancel()
    assert token.cancelled


def test_raise_if_cancelled_raises_only_after_cancel():
    token = CancellationToken()
    token.raise_if_cancelled()
    token.cancel()
    with pytest.raises(WorkCancelled):
        token.raise_if_cancelled()


def test_cancellation_is_visible_across_threads():
    token = CancellationToken()
    observed = threading.Event()

    def observer():
        token.wait(1.0)
        if token.cancelled:
            observed.set()

    thread = threading.Thread(target=observer)
    thread.start()
    token.cancel()
    thread.join(timeout=1.0)
    assert observed.is_set()
