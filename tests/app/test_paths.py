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
    assert paths.state_dir == tmp_path / "state" / "uniti"
    assert paths.cache_dir == tmp_path / "cache" / "uniti"
    assert paths.recovery_dir == paths.state_dir / "recovery"
    assert paths.settings_file == paths.config_dir / "settings.json"


def test_macos_paths_use_library_locations(tmp_path: Path):
    paths = AppPaths.for_platform("darwin", home=tmp_path, environ={})
    assert paths.config_dir == tmp_path / "Library" / "Application Support" / "UNITI"
    assert paths.cache_dir == tmp_path / "Library" / "Caches" / "UNITI"
    assert paths.recovery_dir == paths.state_dir / "recovery"


def test_windows_paths_use_localappdata_when_available(tmp_path: Path):
    local = tmp_path / "LocalAppData"
    paths = AppPaths.for_platform(
        "win32", home=tmp_path / "home", environ={"LOCALAPPDATA": str(local)}
    )
    assert paths.config_dir == local / "UNITI"
    assert paths.cache_dir == local / "UNITI" / "Cache"


def test_app_paths_ensure_creates_required_directories(tmp_path: Path):
    paths = AppPaths.for_platform("linux", home=tmp_path, environ={})
    paths.ensure()
    assert paths.config_dir.is_dir()
    assert paths.state_dir.is_dir()
    assert paths.cache_dir.is_dir()
    assert paths.recovery_dir.is_dir()
