from pathlib import Path

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


def test_macos_paths_use_library_locations(tmp_path: Path):
    paths = AppPaths.for_platform("darwin", home=tmp_path, environ={})
    assert paths.config_dir == tmp_path / "Library" / "Application Support" / "UNITI"
    assert paths.data_dir == paths.config_dir
    assert paths.cache_dir == tmp_path / "Library" / "Caches" / "UNITI"
    assert paths.recovery_dir == paths.state_dir / "recovery"
    assert paths.durable_session_dir == paths.state_dir / "session"


def test_windows_paths_use_localappdata_when_available(tmp_path: Path):
    local = tmp_path / "LocalAppData"
    paths = AppPaths.for_platform(
        "win32", home=tmp_path / "home", environ={"LOCALAPPDATA": str(local)}
    )
    assert paths.config_dir == local / "UNITI"
    assert paths.data_dir == local / "UNITI"
    assert paths.cache_dir == local / "UNITI" / "Cache"
    assert paths.durable_session_dir == paths.state_dir / "session"


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
