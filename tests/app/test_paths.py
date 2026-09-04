from pathlib import Path

import pytest

from uniti.app.platform_policy import PlatformFamily, UnsupportedPlatformError
from uniti.app.paths import AppPaths


def test_linux_paths_honor_xdg_environment(tmp_path: Path):
    env = {
        "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }
    paths = AppPaths.for_platform("linux", home=tmp_path / "home", environ=env)
    assert paths.config_dir == tmp_path / "cfg" / "uniti"
    assert paths.data_dir == tmp_path / "home" / ".local" / "share" / "uniti"
    assert paths.state_dir == tmp_path / "state" / "uniti"
    assert paths.cache_dir == tmp_path / "cache" / "uniti"
    assert paths.recovery_dir == paths.state_dir / "recovery"
    assert paths.settings_file == paths.config_dir / "settings.json"
    assert paths.family is PlatformFamily.LINUX


@pytest.mark.parametrize(
    ("variable", "fallback"),
    (
        ("XDG_CONFIG_HOME", Path(".config")),
        ("XDG_DATA_HOME", Path(".local/share")),
        ("XDG_STATE_HOME", Path(".local/state")),
        ("XDG_CACHE_HOME", Path(".cache")),
    ),
)
@pytest.mark.parametrize("configured", ("", "relative/root"))
def test_linux_paths_ignore_empty_and_relative_xdg_roots(
    tmp_path: Path,
    variable: str,
    fallback: Path,
    configured: str,
):
    home = tmp_path / "home Ω & (safe)"

    paths = AppPaths.for_platform(
        "linux",
        home=home,
        environ={variable: configured},
    )

    selected = {
        "XDG_CONFIG_HOME": paths.config_dir,
        "XDG_DATA_HOME": paths.data_dir,
        "XDG_STATE_HOME": paths.state_dir,
        "XDG_CACHE_HOME": paths.cache_dir,
    }[variable]
    assert selected == home / fallback / "uniti"
    assert all(path.is_absolute() for path in paths.owned_roots)


def test_macos_paths_use_library_locations(tmp_path: Path):
    paths = AppPaths.for_platform("darwin", home=tmp_path, environ={})
    assert paths.config_dir == tmp_path / "Library" / "Application Support" / "UNITI"
    assert paths.data_dir == paths.config_dir
    assert paths.cache_dir == tmp_path / "Library" / "Caches" / "UNITI"
    assert paths.recovery_dir == paths.state_dir / "recovery"
    assert paths.durable_session_dir == paths.state_dir / "session"
    assert paths.family is PlatformFamily.MACOS


def test_windows_paths_use_localappdata_when_available(tmp_path: Path):
    local = tmp_path / "LocalAppData"
    paths = AppPaths.for_platform(
        "win32", home=tmp_path / "home", environ={"LOCALAPPDATA": str(local)}
    )
    assert paths.config_dir == local / "UNITI"
    assert paths.data_dir == local / "UNITI"
    assert paths.cache_dir == local / "UNITI" / "Cache"
    assert paths.durable_session_dir == paths.state_dir / "session"
    assert paths.family is PlatformFamily.WINDOWS


@pytest.mark.parametrize("configured", ("", "relative\\LocalAppData"))
def test_windows_paths_ignore_empty_and_relative_localappdata(
    tmp_path: Path,
    configured: str,
):
    home = tmp_path / "home Ω & (safe)"

    paths = AppPaths.for_platform(
        "win32",
        home=home,
        environ={"LOCALAPPDATA": configured},
    )

    expected = home / "AppData" / "Local" / "UNITI"
    assert paths.config_dir == expected
    assert paths.data_dir == expected
    assert paths.state_dir == expected / "State"
    assert paths.cache_dir == expected / "Cache"


@pytest.mark.parametrize("runtime", ("", "freebsd14", "cygwin", "emscripten"))
def test_unknown_platform_does_not_receive_xdg_paths(tmp_path: Path, runtime: str):
    with pytest.raises(UnsupportedPlatformError):
        AppPaths.for_platform(runtime, home=tmp_path, environ={})


def test_for_platform_requires_an_absolute_home():
    with pytest.raises(ValueError, match="home directory must be absolute"):
        AppPaths.for_platform("linux", home=Path("relative/home"), environ={})


def test_direct_app_paths_require_absolute_owned_roots(tmp_path: Path):
    with pytest.raises(ValueError, match="application roots must be absolute"):
        AppPaths(
            Path("relative/config"),
            tmp_path / "data",
            tmp_path / "state",
            tmp_path / "cache",
        )


def test_direct_app_paths_reject_nul_in_owned_roots(tmp_path: Path):
    with pytest.raises(ValueError, match="application roots must be absolute"):
        AppPaths(
            Path(f"{tmp_path}/bad\0config"),
            tmp_path / "data",
            tmp_path / "state",
            tmp_path / "cache",
        )


def test_app_paths_ensure_creates_required_directories(tmp_path: Path):
    paths = AppPaths.for_platform("linux", home=tmp_path, environ={})
    paths.ensure()
    assert paths.config_dir.is_dir()
    assert paths.state_dir.is_dir()
    assert paths.cache_dir.is_dir()
    assert paths.recovery_dir.is_dir()
    assert paths.log_dir.is_dir()
    assert paths.temp_dir.is_dir()
    assert paths.session_dir.is_dir()
    assert paths.durable_session_dir.is_dir()


def test_lifecycle_paths_are_derived_from_owned_roots(tmp_path: Path):
    paths = AppPaths.for_platform("linux", home=tmp_path, environ={})

    assert paths.local_runtime_dir == paths.data_dir / "runtime" / "venv"
    assert paths.setup_state_file == paths.state_dir / "setup-state.json"
    assert paths.startup_log_file == paths.log_dir / "startup.jsonl"
    assert paths.temp_dir == paths.cache_dir / "temp"
    assert paths.session_dir == paths.cache_dir / "sessions"
    assert paths.durable_session_dir == paths.state_dir / "session"
    assert paths.instance_lock_file == paths.state_dir / "uniti-instance.lock"
    assert paths.instance_endpoint_name.startswith("uniti-")
    assert len(paths.instance_endpoint_name) == len("uniti-") + 24
    assert paths.owned_roots == (
        paths.config_dir,
        paths.data_dir,
        paths.state_dir,
        paths.cache_dir,
    )


def test_instance_endpoint_is_stable_per_owned_data_root(tmp_path: Path):
    first = AppPaths.for_platform("linux", home=tmp_path / "one", environ={})
    same = AppPaths(
        config_dir=tmp_path / "elsewhere",
        data_dir=first.data_dir,
        state_dir=tmp_path / "other-state",
        cache_dir=tmp_path / "other-cache",
    )
    second = AppPaths.for_platform("linux", home=tmp_path / "two", environ={})

    assert first.instance_endpoint_name == same.instance_endpoint_name
    assert first.instance_endpoint_name != second.instance_endpoint_name
