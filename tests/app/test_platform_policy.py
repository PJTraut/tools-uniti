from dataclasses import FrozenInstanceError
import os
from pathlib import Path

import pytest

from uniti.app.platform_policy import (
    PlatformFamily,
    UnsupportedPlatformError,
    absolute_environment_root,
    classify_platform,
    native_paths_equal,
    normalize_native_path,
)


@pytest.mark.parametrize(
    ("runtime", "expected"),
    (
        ("darwin", PlatformFamily.MACOS),
        ("win32", PlatformFamily.WINDOWS),
        ("windows", PlatformFamily.WINDOWS),
        ("linux", PlatformFamily.LINUX),
        ("linux-musl", PlatformFamily.LINUX),
    ),
)
def test_supported_runtime_names_select_one_explicit_family(runtime, expected):
    assert classify_platform(runtime) is expected


@pytest.mark.parametrize(
    "runtime",
    ("", "Darwin", "WIN32", "freebsd14", "cygwin", "emscripten"),
)
def test_unknown_runtime_names_never_inherit_linux_policy(runtime):
    with pytest.raises(UnsupportedPlatformError) as caught:
        classify_platform(runtime)

    assert caught.value.platform_name == runtime
    assert str(caught.value) == f"Unsupported UNITI platform: {runtime or '<empty>'}"


def test_platform_classifier_rejects_non_string_runtime_names():
    with pytest.raises(TypeError, match="platform name must be a string"):
        classify_platform(None)  # type: ignore[arg-type]


def test_unsupported_platform_message_is_single_line_and_bounded():
    runtime = "bad\nplatform-" + "x" * 200

    with pytest.raises(UnsupportedPlatformError) as caught:
        classify_platform(runtime)

    message = str(caught.value)
    assert "\n" not in message
    assert len(message) <= len("Unsupported UNITI platform: ") + 64
    assert caught.value.platform_name == runtime


@pytest.mark.parametrize("configured", (None, "", "relative/root", "/absolute/\0bad"))
def test_environment_root_falls_back_when_value_is_not_absolute(
    tmp_path: Path,
    configured: str | None,
):
    fallback = tmp_path / "fallback"
    environ = {} if configured is None else {"UNITI_ROOT": configured}

    assert absolute_environment_root(environ, "UNITI_ROOT", fallback) == fallback


def test_environment_root_accepts_an_absolute_unicode_path(tmp_path: Path):
    configured = tmp_path / "absolute Ω & (safe)"

    assert absolute_environment_root(
        {"UNITI_ROOT": str(configured)},
        "UNITI_ROOT",
        tmp_path / "fallback",
    ) == configured


def test_environment_root_requires_an_absolute_fallback():
    with pytest.raises(ValueError, match="fallback root must be absolute"):
        absolute_environment_root({}, "UNITI_ROOT", Path("relative/fallback"))


def test_native_path_normalizes_relative_dot_components_against_explicit_cwd(
    tmp_path: Path,
):
    cwd = tmp_path / "working Ω & (safe)"
    cwd.mkdir()

    normalized = normalize_native_path(
        Path("nested") / ".." / "missing document.txt",
        cwd=cwd,
    )

    assert normalized.path == cwd / "missing document.txt"
    assert normalized.comparison_key == os.path.normcase(str(normalized.path))
    assert normalized.exists is False
    assert normalized.path.is_absolute()
    with pytest.raises(FrozenInstanceError):
        normalized.exists = True


def test_native_paths_use_samefile_for_existing_hard_links(tmp_path: Path):
    source = tmp_path / "source.txt"
    alias = tmp_path / "alias.txt"
    source.write_text("same bytes", encoding="utf-8")
    try:
        alias.hardlink_to(source)
    except OSError as error:
        pytest.fail(f"required hard-link fixture is unavailable: {error}")

    assert native_paths_equal(source, alias)


def test_missing_posix_paths_remain_case_sensitive(tmp_path: Path):
    assert not native_paths_equal(
        tmp_path / "Missing.txt",
        tmp_path / "missing.txt",
        platform_name="linux",
    )


def test_missing_windows_paths_use_case_insensitive_lexical_keys(tmp_path: Path):
    assert native_paths_equal(
        tmp_path / "Folder" / "Missing.TXT",
        tmp_path / "folder" / "missing.txt",
        platform_name="win32",
    )


@pytest.mark.skipif(os.name != "nt", reason="requires Windows native paths")
def test_windows_native_drive_and_unc_paths():
    cases = (
        (r"C:\UNITI\Folder\Missing.TXT", r"c:/uniti/folder/missing.txt"),
        (
            r"\\server\share\UNITI\Folder\..\Missing.txt",
            r"\\SERVER\SHARE\uniti\missing.TXT",
        ),
    )
    for first, second in cases:
        assert native_paths_equal(first, second, platform_name="win32")


@pytest.mark.parametrize("path", ("", "bad\0path"))
def test_native_path_rejects_empty_and_nul_strings(path: str):
    with pytest.raises(ValueError, match="native path"):
        normalize_native_path(path)


def test_native_path_rejects_a_relative_explicit_cwd():
    with pytest.raises(ValueError, match="working directory must be absolute"):
        normalize_native_path("document.txt", cwd=Path("relative"))


def test_absolute_native_path_does_not_require_the_process_cwd(
    tmp_path: Path,
    monkeypatch,
):
    absolute = tmp_path / "absolute.txt"

    def unavailable_cwd(cls):
        raise OSError("injected unavailable cwd")

    monkeypatch.setattr(Path, "cwd", classmethod(unavailable_cwd))

    assert normalize_native_path(absolute).path == absolute


def test_native_path_reports_resolution_failure_explicitly(
    tmp_path: Path,
    monkeypatch,
):
    original = Path.resolve

    def fail_selected(self, *args, **kwargs):
        if self.name == "blocked.txt":
            raise RuntimeError("injected resolution loop")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fail_selected)

    with pytest.raises(ValueError, match="native path cannot be normalized"):
        normalize_native_path(tmp_path / "blocked.txt")
