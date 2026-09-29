from __future__ import annotations

from pathlib import Path

from uniti.core.decoration import SyntaxProfileDecorationAdapter
from uniti.core.document import Document
from uniti.core.environment import EnvironmentContext, PlainEnvironment
from uniti.core.resource_profile import ResourceProfile
from uniti.core.syntax_profiles import JSON, PLAIN_TEXT


def test_environment_context_for_document_reflects_size_and_revision(tmp_path: Path):
    path = tmp_path / "doc.txt"
    path.write_text("hello world", encoding="utf-8")
    with Document.open(path) as document:
        context = EnvironmentContext.for_document(document)

        assert isinstance(context.resource_profile, ResourceProfile)
        assert context.resource_profile.size_bytes == path.stat().st_size
        assert context.edits.revision == document.revision


def test_environment_edit_facade_delegates_mutations_and_bumps_revision(tmp_path: Path):
    path = tmp_path / "doc.txt"
    path.write_text("hello", encoding="utf-8")
    with Document.open(path) as document:
        context = EnvironmentContext.for_document(document)
        before = context.edits.revision

        context.edits.insert(5, " world")

        assert document.read(0, 11) == "hello world"
        assert context.edits.revision == before + 1
        # The facade reflects the live Document, not a stale copy.
        assert context.edits.revision == document.revision


def test_environment_edit_facade_replace_many(tmp_path: Path):
    path = tmp_path / "doc.txt"
    path.write_text("aXbXc", encoding="utf-8")
    with Document.open(path) as document:
        context = EnvironmentContext.for_document(document)

        applied = context.edits.replace_many([(1, 2, "-"), (3, 4, "-")])

        assert applied == 2
        assert document.read(0, 5) == "a-b-c"


def test_plain_environment_activate_deactivate_never_raises(tmp_path: Path):
    path = tmp_path / "doc.txt"
    path.write_text("anything at all", encoding="utf-8")
    with Document.open(path) as document:
        context = EnvironmentContext.for_document(document)
        environment = PlainEnvironment()

        environment.activate(context)
        environment.deactivate()

        assert environment.key == "plain_text"


def test_plain_environment_decoration_provider_matches_plain_text_profile():
    environment = PlainEnvironment()
    provider = environment.decoration_provider

    assert provider is not None
    assert provider.key == PLAIN_TEXT.key
    tokens, state = provider.tokenize("not actually tokenized", None)
    assert tokens == ()
    assert state is None


def test_syntax_profile_decoration_adapter_wraps_without_reimplementing():
    adapter = SyntaxProfileDecorationAdapter(JSON)

    tokens, _state = adapter.tokenize('{"a": 1}', JSON.initial_state)

    # Delegates straight to the existing JSON profile: real tokens come back,
    # proving this is a pass-through adapter, not a reimplementation.
    assert len(tokens) > 0
    assert adapter.key == "json"
