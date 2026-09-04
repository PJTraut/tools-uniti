from pathlib import Path

import pytest

from uniti.app.platform_policy import (
    PlatformFamily,
    UnsupportedPlatformError,
    absolute_environment_root,
    classify_platform,
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
