import json
import os
import sys
import venv
from pathlib import Path

import pytest

from uniti.bootstrap.discovery import query_python
from uniti.bootstrap.environment import EnvironmentManager
from uniti.bootstrap.model import BootstrapError, BootstrapMode


@pytest.fixture
def source_root(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "src" / "uniti").mkdir(parents=True)
    (source / "pyproject.toml").write_text(
        '[project]\nname = "uniti-editor"\nversion = "0.1a15"\n', encoding="utf-8"
    )
    return source


@pytest.fixture
def host_python():
    return query_python((sys.executable,))


def manager_for(source_root: Path, host_python, mode: BootstrapMode, path: Path, **kwargs):
    return EnvironmentManager(
        source_root=source_root,
        environment_path=path,
        mode=mode,
        host=host_python,
        platform_name=sys.platform,
        **kwargs,
    )


def test_local_existing_unmarked_target_is_refused(source_root, host_python, tmp_path):
    target = tmp_path / "local-runtime"
    target.mkdir()
    manager = manager_for(source_root, host_python, BootstrapMode.LOCAL, target)

    with pytest.raises(BootstrapError) as caught:
        manager.ensure()

    assert caught.value.exit_code == 11
    assert "not UNITI-owned" in str(caught.value)


def test_source_virtualenv_is_adopted_with_unhealthy_marker(source_root, host_python):
    target = source_root / ".venv"
    venv.EnvBuilder(with_pip=False, clear=False).create(target)
    manager = manager_for(source_root, host_python, BootstrapMode.SOURCE, target)

    runtime, marker = manager.ensure()

    assert runtime.is_file()
    assert marker.mode is BootstrapMode.SOURCE
    assert marker.healthy is False
    assert marker.environment_path == target.resolve()
    assert json.loads(manager.marker_path.read_text(encoding="utf-8"))["owner"] == "uniti-editor"


def test_missing_environment_writes_unhealthy_marker_before_builder_failure(
    source_root, host_python, tmp_path
):
    target = tmp_path / "new-local"

    class BrokenBuilder:
        def create(self, path):
            assert (Path(path) / ".uniti-runtime.json").is_file()
            raise RuntimeError("venv creation stopped")

    manager = manager_for(
        source_root,
        host_python,
        BootstrapMode.LOCAL,
        target,
        builder_factory=lambda: BrokenBuilder(),
    )

    with pytest.raises(BootstrapError) as caught:
        manager.ensure()

    assert caught.value.exit_code == 11
    assert target.is_dir()
    assert json.loads(manager.marker_path.read_text(encoding="utf-8"))["healthy"] is False


def test_mismatched_marked_environment_is_refused(source_root, host_python, tmp_path):
    target = tmp_path / "local-runtime"
    target.mkdir()
    manager = manager_for(source_root, host_python, BootstrapMode.LOCAL, target)
    payload = manager.new_marker().as_dict()
    payload["environment_path"] = str(tmp_path / "other")
    manager.marker_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BootstrapError) as caught:
        manager.ensure()

    assert caught.value.exit_code == 11


def test_mark_healthy_updates_fingerprint_and_source_provenance(
    source_root, host_python, tmp_path
):
    target = source_root / ".venv"
    venv.EnvBuilder(with_pip=False, clear=False).create(target)
    manager = manager_for(source_root, host_python, BootstrapMode.SOURCE, target)
    _, marker = manager.ensure()

    healthy = manager.mark_healthy(marker, "abc123")

    assert healthy.healthy is True
    assert healthy.dependency_fingerprint == "abc123"
    persisted = json.loads(manager.marker_path.read_text(encoding="utf-8"))
    assert persisted["dependency_fingerprint"] == "abc123"


def test_stale_lock_is_preserved_before_new_lock_is_acquired(
    source_root, host_python, tmp_path
):
    target = tmp_path / "runtime"
    manager = manager_for(source_root, host_python, BootstrapMode.LOCAL, target)
    manager.lock_path.parent.mkdir(parents=True, exist_ok=True)
    manager.lock_path.write_text(
        json.dumps({"session_id": "dead", "pid": 999_999_999}), encoding="utf-8"
    )

    with manager.lock() as acquired:
        assert acquired.session_id
        assert manager.lock_path.is_file()

    assert not manager.lock_path.exists()
    stale = list(manager.lock_path.parent.glob(f"{manager.lock_path.name}.*.stale"))
    assert len(stale) == 1


def test_live_lock_owner_is_refused(source_root, host_python, tmp_path):
    target = tmp_path / "runtime"
    manager = manager_for(source_root, host_python, BootstrapMode.LOCAL, target)
    manager.lock_path.parent.mkdir(parents=True, exist_ok=True)
    manager.lock_path.write_text(
        json.dumps({"session_id": "live", "pid": os.getpid()}), encoding="utf-8"
    )

    with pytest.raises(BootstrapError) as caught:
        with manager.lock():
            raise AssertionError("unreachable")

    assert caught.value.exit_code == 11
    assert manager.lock_path.exists()
