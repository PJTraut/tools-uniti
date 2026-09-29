from __future__ import annotations

from pathlib import Path

import pytest

from uniti.app.file_environment_manager import FileEnvironmentManager
from uniti.core.document import Document
from uniti.core.environment import Environment, EnvironmentContext, PlainEnvironment


def test_resolve_key_matches_existing_extension_resolver():
    manager = FileEnvironmentManager()

    assert manager.resolve_key(".json") == "json"
    assert manager.resolve_key(".txt") == "plain_text"
    assert manager.resolve_key(".unknown-extension") == "plain_text"


def test_resolve_key_honors_overrides_like_the_existing_system():
    manager = FileEnvironmentManager()

    assert manager.resolve_key(".usj", {"usj": "json"}) == "json"


def test_activate_for_falls_back_to_plain_for_unregistered_key(tmp_path: Path):
    path = tmp_path / "doc.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    manager = FileEnvironmentManager()
    with Document.open(path) as document:
        environment = manager.activate_for(document, "json")

        assert isinstance(environment, PlainEnvironment)


def test_activate_for_uses_registered_factory(tmp_path: Path):
    path = tmp_path / "doc.json"
    path.write_text('{"a": 1}', encoding="utf-8")

    activated_with: list[EnvironmentContext] = []

    class _StubJsonEnvironment:
        key = "json"

        def activate(self, context: EnvironmentContext) -> None:
            activated_with.append(context)

        def deactivate(self) -> None:
            pass

        @property
        def decoration_provider(self):
            return None

    manager = FileEnvironmentManager()
    manager.register("json", _StubJsonEnvironment)

    with Document.open(path) as document:
        environment = manager.activate_for(document, "json")

        assert isinstance(environment, _StubJsonEnvironment)
        assert len(activated_with) == 1
        assert activated_with[0].edits.revision == document.revision


def test_activate_for_falls_back_to_plain_when_activation_raises(tmp_path: Path):
    path = tmp_path / "doc.json"
    path.write_text('{"a": 1}', encoding="utf-8")

    class _BrokenEnvironment:
        key = "json"

        def activate(self, context: EnvironmentContext) -> None:
            raise RuntimeError("boom")

        def deactivate(self) -> None:
            pass

        @property
        def decoration_provider(self):
            return None

    manager = FileEnvironmentManager()
    manager.register("json", _BrokenEnvironment)

    with Document.open(path) as document:
        environment = manager.activate_for(document, "json")

        assert isinstance(environment, PlainEnvironment)


def test_register_rejects_empty_key_or_non_callable_factory():
    manager = FileEnvironmentManager()

    with pytest.raises(ValueError, match="non-empty"):
        manager.register("", PlainEnvironment)
    with pytest.raises(TypeError, match="callable"):
        manager.register("json", "not-a-factory")  # type: ignore[arg-type]
