"""Cross-platform process liveness without sending Windows console events."""

from __future__ import annotations

import os
import sys


def _windows_process_is_live(pid: int) -> bool:
    """Query a Windows process handle, retaining state when status is unknown."""

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        open_process.restype = wintypes.HANDLE
        wait_for_single_object = kernel32.WaitForSingleObject
        wait_for_single_object.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        wait_for_single_object.restype = wintypes.DWORD
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL

        synchronize = 0x00100000
        wait_object_0 = 0x00000000
        handle = open_process(synchronize, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87
        try:
            return wait_for_single_object(handle, 0) != wait_object_0
        finally:
            close_handle(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return True


def process_is_live(pid: int) -> bool:
    """Return conservatively whether *pid* identifies a running process."""

    if pid <= 0 or pid > 0xFFFFFFFF:
        return False
    if sys.platform.startswith("win"):
        return _windows_process_is_live(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
