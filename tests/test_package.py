import importlib.util


def test_core_import_does_not_require_pyside6():
    import uniti.core

    assert uniti.core is not None
    assert importlib.util.find_spec("uniti") is not None


def test_regex_engine_dependency_is_exactly_pinned():
    import tomllib
    from pathlib import Path

    import regex

    project = tomllib.loads(Path("pyproject.toml").read_text())
    dependencies = project["project"]["dependencies"]
    assert f"regex=={regex.__version__}" in dependencies


def test_project_versions_are_canonical():
    import tomllib
    from pathlib import Path

    import uniti

    project = tomllib.loads(Path("pyproject.toml").read_text())
    display = Path("VERSION").read_text().strip()
    assert project["project"]["version"] == uniti.__version__
    assert uniti.__display_version__ == display
    assert display.startswith("v0.001a")


def test_project_declares_uniti_console_entrypoint():
    import tomllib
    from pathlib import Path

    project = tomllib.loads(Path("pyproject.toml").read_text())
    assert project["project"]["scripts"]["uniti"] == "uniti.app.application:main"


def test_startup_constructs_one_resource_manager_and_registers_shutdown(
    tmp_path, monkeypatch
):
    from uniti import resources as resource_module
    from uniti.app import application
    from uniti.app.paths import AppPaths
    from uniti.app.startup import StartupContext, StartupPhase

    instances = []

    class FakePressure:
        value = "green"

    class FakeResourceManager:
        cache_budget_bytes = 123
        worker_count = 2
        pressure = FakePressure()

        def __init__(self, *, initial_snapshot):
            self.initial_snapshot = initial_snapshot
            self.shutdown_calls = []
            instances.append(self)

        def shutdown(self, *, wait=True):
            self.shutdown_calls.append(wait)

    monkeypatch.setattr(resource_module, "ResourceManager", FakeResourceManager)
    paths = AppPaths(
        tmp_path / "config",
        tmp_path / "data",
        tmp_path / "state",
        tmp_path / "cache",
    )
    context = StartupContext.create(paths, session_id="test-session")
    callback = application._startup_callbacks(
        application.ApplicationRequest(), tmp_path / "marker.json"
    )[StartupPhase.RESOURCE_CALIBRATION]

    callback(context)
    context.cleanup()

    assert len(instances) == 1
    assert context.data["resource_manager"] is instances[0]
    assert instances[0].shutdown_calls == [True]


def test_startup_registers_recovery_service_shutdown(tmp_path, monkeypatch):
    from uniti.app import application
    from uniti.app import recovery_manager as recovery_module
    from uniti.app.paths import AppPaths
    from uniti.app.startup import StartupContext, StartupPhase

    instances = []

    class FakeRecoveryManager:
        def __init__(self, directory):
            self.directory = directory
            self.shutdown_calls = 0
            instances.append(self)

        def discover(self):
            return ()

        def shutdown(self):
            self.shutdown_calls += 1

    monkeypatch.setattr(recovery_module, "RecoveryManager", FakeRecoveryManager)
    paths = AppPaths(
        tmp_path / "config",
        tmp_path / "data",
        tmp_path / "state",
        tmp_path / "cache",
    )
    context = StartupContext.create(paths, session_id="test-session")
    callback = application._startup_callbacks(
        application.ApplicationRequest(), tmp_path / "marker.json"
    )[StartupPhase.RECOVERY_DISCOVERY]

    callback(context)
    context.cleanup()

    assert len(instances) == 1
    assert instances[0].shutdown_calls == 1
