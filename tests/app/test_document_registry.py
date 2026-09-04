from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from uniti.app.document_registry import DocumentRegistry, DuplicateDocumentError
from uniti.core.document import Document


NOW = datetime(2026, 9, 4, 10, tzinfo=UTC)


def _open_document(tmp_path: Path, name: str = "doc.txt") -> Document:
    path = tmp_path / name
    path.write_text("abc", encoding="utf-8")
    return Document.open(path)


def test_registry_adopts_one_document_per_canonical_path(tmp_path: Path):
    first = _open_document(tmp_path)
    duplicate = Document.open(tmp_path / "doc.txt")
    registry = DocumentRegistry(clock=lambda: NOW)
    try:
        entry = registry.adopt(first)

        assert registry.find_path(tmp_path / "." / "doc.txt") is entry
        with pytest.raises(DuplicateDocumentError):
            registry.adopt(duplicate)
        assert registry.count == 1
    finally:
        registry.close_all()
        duplicate.close()


def test_registry_detects_an_existing_file_reached_through_a_hard_link(
    tmp_path: Path,
):
    first = _open_document(tmp_path)
    alias = tmp_path / "alias.txt"
    try:
        alias.hardlink_to(first.path)
    except OSError as exc:
        first.close()
        pytest.skip(f"hard links are unavailable: {exc}")
    duplicate = Document.open(alias)
    registry = DocumentRegistry(clock=lambda: NOW)
    try:
        entry = registry.adopt(first)

        assert registry.find_path(alias) is entry
        with pytest.raises(DuplicateDocumentError):
            registry.adopt(duplicate)
    finally:
        registry.close_all()
        duplicate.close()


def test_release_keeps_a_shared_document_live_until_its_last_view(
    tmp_path: Path,
):
    document = _open_document(tmp_path)
    registry = DocumentRegistry(clock=lambda: NOW)
    entry = registry.adopt(document)
    registry.bind_view(entry.document_id, "view-a")
    registry.bind_view(entry.document_id, "view-b")

    released = registry.release_view("view-a")

    assert released is entry
    assert entry.view_ids == ("view-b",)
    assert entry.closed_at is None
    assert document.read(0, 3) == "abc"
    registry.close_all()


def test_saved_document_history_expires_at_exactly_seven_days(tmp_path: Path):
    document = _open_document(tmp_path)
    registry = DocumentRegistry(clock=lambda: NOW)
    entry = registry.adopt(document)
    registry.bind_view(entry.document_id, "view-a")

    registry.release_view("view-a")

    assert entry.closed_at == NOW
    assert registry.close_expired(NOW + timedelta(days=7) - timedelta(microseconds=1)) == ()
    assert registry.get(entry.document_id) is entry
    assert registry.close_expired(NOW + timedelta(days=7)) == (entry.document_id,)
    assert registry.count == 0
    with pytest.raises(ValueError, match="closed"):
        document.read(0, 1)


def test_modified_document_without_views_is_not_expired_as_saved_history(
    tmp_path: Path,
):
    document = _open_document(tmp_path)
    registry = DocumentRegistry(clock=lambda: NOW)
    entry = registry.adopt(document)
    registry.bind_view(entry.document_id, "view-a")
    document.insert(0, "X")

    registry.release_view("view-a")

    assert entry.closed_at is None
    assert registry.close_expired(NOW + timedelta(days=30)) == ()
    assert registry.get(entry.document_id) is entry
    registry.close_all()


def test_view_id_cannot_be_bound_to_two_authoritative_documents(tmp_path: Path):
    first = _open_document(tmp_path, "first.txt")
    second = _open_document(tmp_path, "second.txt")
    registry = DocumentRegistry(clock=lambda: NOW)
    first_entry = registry.adopt(first)
    second_entry = registry.adopt(second)
    registry.bind_view(first_entry.document_id, "view-a")

    with pytest.raises(ValueError, match="already bound"):
        registry.bind_view(second_entry.document_id, "view-a")

    assert registry.entry_for_view("view-a") is first_entry
    registry.close_all()


def test_retire_requires_all_views_to_be_released(tmp_path: Path):
    document = _open_document(tmp_path)
    registry = DocumentRegistry(clock=lambda: NOW)
    entry = registry.adopt(document)
    registry.bind_view(entry.document_id, "view-a")

    with pytest.raises(ValueError, match="live views"):
        registry.retire(entry.document_id)

    assert document.read(0, 3) == "abc"
    registry.release_view("view-a")
    assert registry.retire(entry.document_id) is entry
    with pytest.raises(ValueError, match="closed"):
        document.read(0, 1)


def test_replacing_document_authority_preserves_view_bindings(tmp_path: Path):
    original = _open_document(tmp_path)
    replacement = Document.open(original.path)
    registry = DocumentRegistry(clock=lambda: NOW)
    entry = registry.adopt(original)
    registry.bind_view(entry.document_id, "view-a")
    registry.bind_view(entry.document_id, "view-b")

    assert registry.replace_document(entry.document_id, replacement) is original
    assert entry.document is replacement
    assert entry.view_ids == ("view-a", "view-b")
    assert registry.find_path(replacement.path) is entry
    with pytest.raises(ValueError, match="closed"):
        original.read(0, 1)
    registry.close_all()
