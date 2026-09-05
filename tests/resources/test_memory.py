from uniti.resources.memory import (
    GIB,
    MIB,
    MemorySnapshot,
    PressureState,
    automatic_cache_target,
    current_process_handle_count,
    pressure_state,
    probe_memory,
    _parse_macos_memory,
    _probe_with_windows,
)


def test_automatic_policy_matches_64gib_architecture_example():
    snapshot = MemorySnapshot(physical=64 * GIB, available=50 * GIB)
    reserve = max(2 * GIB, min(8 * GIB, snapshot.physical // 10))
    claimable = snapshot.available - reserve
    expected = min(snapshot.physical // 2, claimable * 7 // 10)
    assert automatic_cache_target(snapshot) == expected


def test_effective_available_includes_reclaimable_uniti_cache():
    snapshot = MemorySnapshot(
        physical=64 * GIB,
        available=4 * GIB,
        reclaimable_cache=20 * GIB,
    )
    assert snapshot.effective_available == 24 * GIB
    assert pressure_state(snapshot) is PressureState.GREEN


def test_pressure_states_use_effective_available_ratio():
    assert pressure_state(MemorySnapshot(64 * GIB, 20 * GIB)) is PressureState.GREEN
    assert pressure_state(MemorySnapshot(64 * GIB, 12 * GIB)) is PressureState.YELLOW
    assert pressure_state(MemorySnapshot(64 * GIB, 6 * GIB)) is PressureState.ORANGE
    assert pressure_state(MemorySnapshot(64 * GIB, 3 * GIB)) is PressureState.RED


def test_unknown_memory_uses_conservative_cache_target():
    assert automatic_cache_target(MemorySnapshot(0, 0)) == 128 * MIB


def test_probe_memory_never_returns_negative_values():
    snapshot = probe_memory()
    assert snapshot.physical >= 0
    assert snapshot.available >= 0


def test_windows_native_probe_reports_physical_and_available_bytes():
    class _GlobalMemoryStatusEx:
        def __call__(self, pointer):
            status = pointer._obj
            status.ullTotalPhys = 16 * GIB
            status.ullAvailPhys = 7 * GIB
            return 1

    class _Kernel32:
        GlobalMemoryStatusEx = _GlobalMemoryStatusEx()

    assert _probe_with_windows(
        platform="win32",
        kernel32=_Kernel32(),
    ) == MemorySnapshot(16 * GIB, 7 * GIB)


def test_windows_native_probe_rejects_failed_or_impossible_results():
    class _FailedGlobalMemoryStatusEx:
        def __call__(self, _pointer):
            return 0

    class _FailedKernel32:
        GlobalMemoryStatusEx = _FailedGlobalMemoryStatusEx()

    assert _probe_with_windows(
        platform="win32",
        kernel32=_FailedKernel32(),
    ) is None
    assert _probe_with_windows(platform="linux", kernel32=_FailedKernel32()) is None


def test_macos_vm_stat_parser_reports_physical_and_available_bytes():
    snapshot = _parse_macos_memory(
        "17179869184\n",
        """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               100.
Pages inactive:                           200.
Pages speculative:                         25.
Pages purgeable:                            5.
Pages active:                             500.
""",
    )

    assert snapshot == MemorySnapshot(
        physical=16 * GIB,
        available=(100 + 200 + 25 + 5) * 16384,
    )


def test_macos_vm_stat_parser_rejects_incomplete_output():
    assert _parse_macos_memory("not-a-number", "no page size") is None


def test_windows_native_handle_probe_reports_current_process_count():
    class _GetCurrentProcess:
        def __call__(self):
            return 123

    class _GetProcessHandleCount:
        def __call__(self, process, pointer):
            assert process == 123
            pointer._obj.value = 17
            return 1

    class _Kernel32:
        GetCurrentProcess = _GetCurrentProcess()
        GetProcessHandleCount = _GetProcessHandleCount()

    assert current_process_handle_count(
        platform="win32",
        kernel32=_Kernel32(),
    ) == 17


def test_linux_handle_probe_counts_only_the_supplied_proc_fd_directory(tmp_path):
    proc_fd = tmp_path / "fd"
    proc_fd.mkdir()
    (proc_fd / "0").write_bytes(b"")
    (proc_fd / "1").write_bytes(b"")

    assert current_process_handle_count(
        platform="linux",
        proc_fd_root=proc_fd,
    ) == 2


def test_unavailable_handle_probe_returns_none(tmp_path):
    assert current_process_handle_count(platform="darwin") is None
    assert current_process_handle_count(
        platform="linux",
        proc_fd_root=tmp_path / "missing",
    ) is None
