from dataclasses import replace

import pytest


def test_recipes_round_trip_through_the_store(tmp_path):
    from uniti.app.find_replace_recipes import FindReplaceRecipe, FindReplaceRecipeStore

    store = FindReplaceRecipeStore(tmp_path / "find-replace-recipes.json")
    assert store.load() == ()

    recipe = FindReplaceRecipe(
        "abc123", "Normalize spaces", r"\s+", " ", True, False, False
    )
    store.save((recipe,))

    assert store.load() == (recipe,)


def test_saving_updates_an_existing_recipe_set(tmp_path):
    from uniti.app.find_replace_recipes import FindReplaceRecipe, FindReplaceRecipeStore

    store = FindReplaceRecipeStore(tmp_path / "find-replace-recipes.json")
    original = FindReplaceRecipe("r1", "Original", "a", "b", False, True, True)
    store.save((original,))

    renamed = replace(original, name="Renamed")
    store.save((renamed,))

    assert store.load() == (renamed,)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(extra=True),
        lambda d: d.update(id="bad id!"),
        lambda d: d.update(name=""),
        lambda d: d.update(name="x" * 65),
        lambda d: d.update(expression="x" * 4097),
        lambda d: d.update(replacement="x" * 4097),
        lambda d: d.update(regex="not-a-bool"),
    ],
)
def test_recipe_validation_rejects_malformed_fields(mutation):
    from uniti.app.find_replace_recipes import FindReplaceRecipe

    data = FindReplaceRecipe("r1", "Name", "a", "b", True, False, False).as_dict()
    mutation(data)
    with pytest.raises(ValueError):
        FindReplaceRecipe.from_dict(data)


def test_store_recovery_does_not_overwrite_damage(tmp_path):
    from uniti.app.find_replace_recipes import FindReplaceRecipeStore

    path = tmp_path / "find-replace-recipes.json"
    original = b'{"schema": 99, "recipes": []}'
    path.write_bytes(original)

    assert FindReplaceRecipeStore(path).load() == ()
    assert path.read_bytes() == original


def test_bounds_and_duplicate_ids_are_rejected(tmp_path):
    from uniti.app.find_replace_recipes import FindReplaceRecipe, FindReplaceRecipeStore

    store = FindReplaceRecipeStore(tmp_path / "find-replace-recipes.json")
    with pytest.raises(ValueError):
        store.save(
            tuple(
                FindReplaceRecipe(f"r{n}", f"r{n}", "a", "b", False, False, False)
                for n in range(51)
            )
        )
    duplicate = FindReplaceRecipe("dup", "Dup", "a", "b", False, False, False)
    with pytest.raises(ValueError):
        store.save((duplicate, duplicate))


def test_oversized_file_falls_back_to_empty(tmp_path):
    from uniti.app.find_replace_recipes import FindReplaceRecipeStore

    store = FindReplaceRecipeStore(tmp_path / "find-replace-recipes.json")
    store.path.write_bytes(b" " * (128 * 1024 + 1))
    assert store.load() == ()


def test_atomic_failure_retains_previous_file(tmp_path, monkeypatch):
    from uniti.app import find_replace_recipes

    store = find_replace_recipes.FindReplaceRecipeStore(
        tmp_path / "find-replace-recipes.json"
    )
    recipe = find_replace_recipes.FindReplaceRecipe(
        "r1", "Name", "a", "b", False, False, False
    )
    store.save((recipe,))
    before = store.path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(find_replace_recipes, "atomic_write_json", fail)
    with pytest.raises(OSError, match="disk full"):
        store.save(())
    assert store.path.read_bytes() == before
