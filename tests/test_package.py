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
    assert project["project"]["version"] == "0.1a12"
    assert uniti.__version__ == "0.1a12"
    assert uniti.__display_version__ == "v0.001a12"
    assert Path("VERSION").read_text().strip() == "v0.001a12"


def test_project_declares_uniti_console_entrypoint():
    import tomllib
    from pathlib import Path

    project = tomllib.loads(Path("pyproject.toml").read_text())
    assert project["project"]["scripts"]["uniti"] == "uniti.app.application:main"
