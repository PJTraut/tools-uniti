"""Platform helpers for bounded sparse validation fixtures."""

from __future__ import annotations

import sys


def _windows_sparse_control(
    descriptor: int,
    offset: int | None,
    length: int | None,
) -> bool:
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        handle = wintypes.HANDLE(msvcrt.get_osfhandle(descriptor))
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        device_io_control = kernel32.DeviceIoControl
        device_io_control.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        )
        device_io_control.restype = wintypes.BOOL
        returned = wintypes.DWORD()
        set_sparse = 0x000900C4
        if not device_io_control(
            handle,
            set_sparse,
            None,
            0,
            None,
            0,
            ctypes.byref(returned),
            None,
        ):
            return False
        if offset is None or length is None:
            return True

        class FileZeroDataInformation(ctypes.Structure):
            _fields_ = (
                ("file_offset", ctypes.c_longlong),
                ("beyond_final_zero", ctypes.c_longlong),
            )

        zero_range = FileZeroDataInformation(offset, offset + length)
        set_zero_data = 0x000980C8
        return bool(
            device_io_control(
                handle,
                set_zero_data,
                ctypes.byref(zero_range),
                ctypes.sizeof(zero_range),
                None,
                0,
                ctypes.byref(returned),
                None,
            )
        )
    except (AttributeError, ImportError, OSError, OverflowError, ValueError):
        return False


def enable_sparse_file(descriptor: int) -> bool:
    """Prepare an open file for sparse seek/truncate fixtures."""

    if descriptor < 0:
        raise ValueError("invalid file descriptor")
    if sys.platform.startswith("win"):
        return _windows_sparse_control(descriptor, None, None)
    return True


def deallocate_file_range(descriptor: int, offset: int, length: int) -> bool:
    """Punch a hole where the platform requires an explicit native request."""

    if descriptor < 0 or offset < 0 or length <= 0:
        raise ValueError("invalid file range")
    if sys.platform.startswith("win"):
        return _windows_sparse_control(descriptor, offset, length)
    if sys.platform != "darwin":
        return False
    import fcntl
    import struct

    # Darwin's fpunchhole_t is two unsigned 32-bit fields followed by two
    # aligned signed 64-bit offsets. F_PUNCHHOLE is declared by sys/fcntl.h.
    request = struct.pack("IIqq", 0, 0, offset, length)
    try:
        fcntl.fcntl(descriptor, 99, request)
    except OSError:
        return False
    return True
