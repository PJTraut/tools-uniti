from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from uniti.core.durability import (
    DurabilityError,
    DurabilityLevel,
    DurabilityResult,
    NativeDurabilityAdapter,
    combine_durability,
)


def test_durability_result_is_immutable_and_serializes_stable_values():
    result = DurabilityResult(
        "save",
        DurabilityLevel.FULL,
        True,
        True,
        True,
    )

    assert result.as_dict() == {
        "operation": "save",
        "level": "full",
        "file_synced": True,
        "replaced": True,
        "directory_synced": True,
        "reason": None,
    }
    with pytest.raises(FrozenInstanceError):
        result.level = DurabilityLevel.UNSAFE


@pytest.mark.parametrize(
    "result",
    (
        lambda: DurabilityResult("save", DurabilityLevel.FULL, True, True, False),
        lambda: DurabilityResult(
            "save",
            DurabilityLevel.FILE_SYNCED,
            True,
            True,
            True,
            "directory_sync_unavailable",
        ),
        lambda: DurabilityResult(
            "save",
            DurabilityLevel.UNSAFE,
            True,
            True,
            False,
            "replace:OSError",
        ),
        lambda: DurabilityResult(
            "save",
            DurabilityLevel.UNSAFE,
            False,
            False,
            False,
        ),
    ),
)
def test_durability_result_rejects_inconsistent_facts(result):
    with pytest.raises(ValueError):
        result()


def test_combined_durability_uses_the_weakest_result_and_facts():
    full = DurabilityResult(
        "pack",
        DurabilityLevel.FULL,
        True,
        True,
        True,
    )
    reduced = DurabilityResult(
        "manifest",
        DurabilityLevel.FILE_SYNCED,
        True,
        True,
        False,
        "directory_sync_unavailable",
    )

    combined = combine_durability("session", (full, reduced))

    assert combined == DurabilityResult(
        "session",
        DurabilityLevel.FILE_SYNCED,
        True,
        True,
        False,
        "directory_sync_unavailable",
    )
    with pytest.raises(ValueError, match="at least one"):
        combine_durability("session", ())


def test_durability_error_exposes_safe_stage_not_operating_system_detail():
    cause = OSError("/private/user/path: secret device detail")
    result = DurabilityResult(
        "save",
        DurabilityLevel.UNSAFE,
        True,
        False,
        False,
        "replace:OSError",
    )

    error = DurabilityError(result, cause)

    assert error.result is result
    assert error.cause is cause
    assert str(error) == "save durability failed (replace:OSError)"
    assert "private" not in str(error)


def test_native_directory_sync_ignores_close_failure_after_success(monkeypatch):
    calls = []
    monkeypatch.setattr("uniti.core.durability.os.open", lambda *_args: 73)
    monkeypatch.setattr(
        "uniti.core.durability.os.fsync",
        lambda descriptor: calls.append(("fsync", descriptor)),
    )

    def fail_close(descriptor):
        calls.append(("close", descriptor))
        raise OSError("injected close failure")

    monkeypatch.setattr("uniti.core.durability.os.close", fail_close)

    assert NativeDurabilityAdapter().sync_directory("/owned") is True
    assert calls == [("fsync", 73), ("close", 73)]


def test_native_windows_replace_uses_replacefile_for_existing_target(
    tmp_path: Path,
    monkeypatch,
):
    import uniti.core.durability as durability_module

    source = tmp_path / "staged.txt"
    destination = tmp_path / "document.txt"
    source.write_bytes(b"new")
    destination.write_bytes(b"old")
    calls: list[tuple[Path, Path]] = []
    monkeypatch.setattr(durability_module.sys, "platform", "win32")
    monkeypatch.setattr(
        durability_module,
        "_windows_replace_existing",
        lambda first, second: calls.append((first, second)),
    )
    monkeypatch.setattr(
        durability_module.os,
        "replace",
        lambda *_args: pytest.fail("existing Windows targets require ReplaceFileW"),
    )

    NativeDurabilityAdapter().replace(source, destination)

    assert calls == [(source, destination)]


def test_native_directory_sync_reports_open_or_sync_unavailable(monkeypatch):
    monkeypatch.setattr(
        "uniti.core.durability.os.open",
        lambda *_args: (_ for _ in ()).throw(OSError("unsupported")),
    )
    assert NativeDurabilityAdapter().sync_directory("/owned") is False

    calls = []
    monkeypatch.setattr("uniti.core.durability.os.open", lambda *_args: 81)
    monkeypatch.setattr(
        "uniti.core.durability.os.fsync",
        lambda _descriptor: (_ for _ in ()).throw(OSError("unsupported")),
    )
    monkeypatch.setattr(
        "uniti.core.durability.os.close",
        lambda descriptor: calls.append(descriptor),
    )
    assert NativeDurabilityAdapter().sync_directory("/owned") is False
    assert calls == [81]
