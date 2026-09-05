from __future__ import annotations

import pytest

from uniti.app import sparse


def test_windows_sparse_preparation_and_hole_punch_use_native_control(monkeypatch):
    calls: list[tuple[int, int | None, int | None]] = []
    monkeypatch.setattr(sparse.sys, "platform", "win32")
    monkeypatch.setattr(
        sparse,
        "_windows_sparse_control",
        lambda descriptor, offset, length: (
            calls.append((descriptor, offset, length)) or True
        ),
    )

    assert sparse.enable_sparse_file(7) is True
    assert sparse.deallocate_file_range(7, 4096, 8192) is True
    assert calls == [(7, None, None), (7, 4096, 8192)]


@pytest.mark.parametrize(
    "arguments",
    [(-1, 0, 1), (1, -1, 1), (1, 0, 0)],
)
def test_sparse_range_rejects_invalid_arguments(arguments):
    with pytest.raises(ValueError, match="invalid file range"):
        sparse.deallocate_file_range(*arguments)
