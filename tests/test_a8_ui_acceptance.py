import importlib.util
from pathlib import Path

from uniti.app.editor_state import EditorState
from uniti.core.document import Document


def test_editor_state_open_edit_save_forms_ui_engine_contract(tmp_path: Path):
    source = tmp_path / "alpha.txt"
    target = tmp_path / "alpha-saved.txt"
    source.write_text("one\r\ntwo\r\n", encoding="utf-8")
    with Document.open(source, encoding="utf-8") as document:
        state = EditorState(document)
        state.move_to(3)
        state.insert_text("!")
        document.save(target, eol="LF")
    assert target.read_text(encoding="utf-8") == "one!\ntwo\n"


def test_qt_imports_are_confined_to_ui_and_launcher_modules():
    forbidden_roots = (
        Path("src/uniti/core"),
        Path("src/uniti/regex"),
        Path("src/uniti/resources"),
    )
    for root in forbidden_roots:
        for path in root.glob("*.py"):
            source = path.read_text()
            assert "PySide6" not in source
            assert "PyQt" not in source


def test_pyside6_is_declared_as_optional_ui_dependency():
    import tomllib

    project = tomllib.loads(Path("pyproject.toml").read_text())
    assert any(dep.startswith("PySide6") for dep in project["project"]["optional-dependencies"]["ui"])


def test_launcher_is_importable_without_optional_ui_dependency():
    from uniti.app.application import main

    assert callable(main)
    if importlib.util.find_spec("PySide6") is None:
        assert main(["uniti", "--not-opened-because-ui-is-missing"]) == 2
