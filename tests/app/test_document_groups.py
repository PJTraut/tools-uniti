from dataclasses import replace

import pytest


def test_default_groups_are_a_b_c_and_round_trip(tmp_path):
    from uniti.app.document_groups import DocumentGroup, DocumentGroupStore, default_groups

    defaults = default_groups()
    assert [group.id for group in defaults] == ["A", "B", "C"]

    store = DocumentGroupStore(tmp_path / "document-groups.json")
    assert store.load() == defaults

    renamed = (replace(defaults[0], name="Reviewed", color="#ff0000"), *defaults[1:])
    store.save(renamed)
    assert store.load() == renamed


def test_custom_groups_can_be_added_and_persisted(tmp_path):
    from uniti.app.document_groups import DocumentGroup, DocumentGroupStore, default_groups

    store = DocumentGroupStore(tmp_path / "document-groups.json")
    extra = DocumentGroup("custom-1", "Drafts", "#8888ff")
    groups = (*default_groups(), extra)
    store.save(groups)
    assert store.load() == groups


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(extra=True),
        lambda d: d.update(id="bad id!"),
        lambda d: d.update(name=""),
        lambda d: d.update(name="x" * 65),
        lambda d: d.update(color="red"),
        lambda d: d.update(color="#gggggg"),
    ],
)
def test_group_validation_rejects_malformed_fields(mutation):
    from uniti.app.document_groups import DocumentGroup

    data = DocumentGroup("A", "A", "#e06c75").as_dict()
    mutation(data)
    with pytest.raises(ValueError):
        DocumentGroup.from_dict(data)


def test_store_recovery_does_not_overwrite_damage(tmp_path):
    from uniti.app.document_groups import DocumentGroupStore, default_groups

    path = tmp_path / "document-groups.json"
    original = b'{"schema": 99, "groups": []}'
    path.write_bytes(original)

    assert DocumentGroupStore(path).load() == default_groups()
    assert path.read_bytes() == original


def test_bounds_and_duplicate_ids_are_rejected(tmp_path):
    from uniti.app.document_groups import DocumentGroup, DocumentGroupStore

    store = DocumentGroupStore(tmp_path / "document-groups.json")
    with pytest.raises(ValueError):
        store.save(
            tuple(DocumentGroup(f"g{n}", f"g{n}", "#123456") for n in range(33))
        )
    duplicate = DocumentGroup("dup", "Dup", "#123456")
    with pytest.raises(ValueError):
        store.save((duplicate, duplicate))


def test_oversized_file_falls_back_to_defaults(tmp_path):
    from uniti.app.document_groups import DocumentGroupStore, default_groups

    store = DocumentGroupStore(tmp_path / "document-groups.json")
    store.path.write_bytes(b" " * (64 * 1024 + 1))
    assert store.load() == default_groups()


def test_atomic_failure_retains_previous_file(tmp_path, monkeypatch):
    from uniti.app import document_groups

    store = document_groups.DocumentGroupStore(tmp_path / "document-groups.json")
    store.save(document_groups.default_groups())
    before = store.path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(document_groups, "atomic_write_json", fail)
    with pytest.raises(OSError, match="disk full"):
        store.save(())
    assert store.path.read_bytes() == before
