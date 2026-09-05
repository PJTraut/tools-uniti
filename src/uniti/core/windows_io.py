"""Small Windows handle policy used by replaceable UNITI files."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal


def open_shared_delete_descriptor(
    path: Path,
    *,
    mode: Literal["read", "truncate-write"],
) -> int:
    """Open a CRT descriptor whose native handle permits atomic rename/delete."""

    import ctypes
    import msvcrt
    from ctypes import wintypes

    if mode == "read":
        desired_access = 0x80000000  # GENERIC_READ
        creation_disposition = 3  # OPEN_EXISTING
        descriptor_flags = os.O_RDONLY
    elif mode == "truncate-write":
        desired_access = 0x40000000  # GENERIC_WRITE
        creation_disposition = 2  # CREATE_ALWAYS
        descriptor_flags = os.O_WRONLY
    else:  # pragma: no cover - guarded by the Literal API
        raise ValueError("unsupported Windows file mode")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        desired_access,
        0x00000001 | 0x00000002 | 0x00000004,  # SHARE_READ|WRITE|DELETE
        None,
        creation_disposition,
        0x00000080,  # FILE_ATTRIBUTE_NORMAL
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return msvcrt.open_osfhandle(
            int(handle),
            descriptor_flags | getattr(os, "O_BINARY", 0),
        )
    except Exception:
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL
        close_handle(handle)
        raise


__all__ = ["open_shared_delete_descriptor"]
