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


def test_registry_assigns_and_clears_a_single_group_per_document(tmp_path: Path):
    document = _open_document(tmp_path)
    registry = DocumentRegistry(clock=lambda: NOW)
    try:
        entry = registry.adopt(document)
        assert entry.group_id is None

        registry.set_group(entry.document_id, "A")
        assert entry.group_id == "A"

        registry.set_group(entry.document_id, "B")
        assert entry.group_id == "B"

        registry.set_group(entry.document_id, None)
        assert entry.group_id is None

        with pytest.raises(ValueError):
            registry.set_group(entry.document_id, "")
    finally:
        registry.close_all()


def test_registry_detects_an_existing_file_reached_through_a_hard_link(
    tmp_path: Path,
):
    first = _open_document(tmp_path)
    alias = tmp_path / "alias.txt"
    try:
        alias.hardlink_to(first.path)
    except OSError as exc:
        first.close()
        pytest.fail(f"required hard-link fixture is unavailable: {exc}")
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


def test_registry_notifies_when_document_authority_is_removed(tmp_path: Path):
    first = _open_document(tmp_path, "first.txt")
    second = _open_document(tmp_path, "second.txt")
    registry = DocumentRegistry(clock=lambda: NOW)
    first_entry = registry.adopt(first)
    second_entry = registry.adopt(second)
    removed = []
    stop_observing = registry.add_remove_listener(removed.append)

    registry.retire(first_entry.document_id)
    registry.close_all()
    stop_observing()
    stop_observing()

    assert removed == [first_entry, second_entry]


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


def test_adopt_marks_untitled_documents_and_replace_clears_it_on_a_real_path(
    tmp_path: Path,
):
    scratch = _open_document(tmp_path, "Untitled.txt")
    (tmp_path / "real.txt").write_text("x", encoding="utf-8")
    real = Document.open(tmp_path / "real.txt")
    registry = DocumentRegistry(clock=lambda: NOW)
    entry = registry.adopt(scratch, is_untitled=True)
    try:
        assert entry.is_untitled is True

        assert registry.replace_document(
            entry.document_id, real, allow_path_change=True
        ) is scratch
        assert entry.is_untitled is False
        assert entry.canonical_path == real.path.resolve()
        assert registry.find_path(real.path) is entry
    finally:
        registry.close_all()


def test_replace_document_rejects_a_path_change_without_the_explicit_flag(
    tmp_path: Path,
):
    scratch = _open_document(tmp_path, "Untitled.txt")
    (tmp_path / "real.txt").write_text("x", encoding="utf-8")
    real = Document.open(tmp_path / "real.txt")
    registry = DocumentRegistry(clock=lambda: NOW)
    entry = registry.adopt(scratch, is_untitled=True)
    try:
        with pytest.raises(DuplicateDocumentError):
            registry.replace_document(entry.document_id, real)
        assert entry.document is scratch
        assert entry.is_untitled is True
    finally:
        real.close()
        registry.close_all()


def test_replace_document_with_path_change_rejects_a_path_owned_elsewhere(
    tmp_path: Path,
):
    scratch = _open_document(tmp_path, "Untitled.txt")
    other = _open_document(tmp_path, "other.txt")
    collider = Document.open(other.path)
    registry = DocumentRegistry(clock=lambda: NOW)
    entry = registry.adopt(scratch, is_untitled=True)
    registry.adopt(other)
    try:
        with pytest.raises(DuplicateDocumentError):
            registry.replace_document(
                entry.document_id, collider, allow_path_change=True
            )
        assert entry.document is scratch
    finally:
        collider.close()
        registry.close_all()


def test_replacing_document_authority_accepts_a_hard_link_to_the_same_file(
    tmp_path: Path,
):
    original = _open_document(tmp_path)
    alias = tmp_path / "same-file-alias.txt"
    try:
        alias.hardlink_to(original.path)
    except OSError as error:
        original.close()
        pytest.fail(f"required hard-link fixture is unavailable: {error}")
    replacement = Document.open(alias)
    registry = DocumentRegistry(clock=lambda: NOW)
    replacement_owned = False
    try:
        entry = registry.adopt(original)

        assert registry.replace_document(entry.document_id, replacement) is original
        replacement_owned = True
        assert entry.document is replacement
        assert entry.canonical_path == alias.resolve()
        assert registry.find_path(original.path) is entry
    finally:
        registry.close_all()
        if not replacement_owned:
            replacement.close()
