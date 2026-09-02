"""Platform helper for bounded sparse validation fixtures."""

from __future__ import annotations

import sys


def deallocate_file_range(descriptor: int, offset: int, length: int) -> bool:
    """Punch a hole on macOS, where seek-and-write may allocate the gap."""

    if descriptor < 0 or offset < 0 or length <= 0:
        raise ValueError("invalid file range")
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
