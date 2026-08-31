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
