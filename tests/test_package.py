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


def test_application_constructs_one_resource_manager_for_desktop_runtime():
    from pathlib import Path

    source = Path("src/uniti/app/application.py").read_text()
    assert "ResourceManager" in source
    assert "resource_manager=resources" in source


def test_application_finally_shuts_down_recovery_and_resource_services():
    from pathlib import Path

    source = Path("src/uniti/app/application.py").read_text()
    assert "recovery_manager.shutdown()" in source
    assert "resources.shutdown(wait=True)" in source
