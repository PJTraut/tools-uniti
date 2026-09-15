"""Qt-free saved Find/Replace "recipes" and their atomic storage."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from .atomic_json import atomic_write_json


MAX_RECIPES = 50
MAX_NAME_LENGTH = 64
MAX_EXPRESSION_LENGTH = 4096
MAX_BYTES = 128 * 1024

_ID_RE = re.compile(r'[A-Za-z0-9_-]{1,64}')


@dataclass(frozen=True, slots=True)
class FindReplaceRecipe:
    id: str
    name: str
    expression: str
    replacement: str
    regex: bool
    case_sensitive: bool
    whole_word: bool

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _ID_RE.fullmatch(self.id):
            raise ValueError('Recipe id must be 1-64 letters, digits, underscores or hyphens')
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > MAX_NAME_LENGTH or not self.name.isprintable():
            raise ValueError(f'Recipe name must be 1-{MAX_NAME_LENGTH} printable characters')
        if not isinstance(self.expression, str) or len(self.expression) > MAX_EXPRESSION_LENGTH:
            raise ValueError(f'Recipe expression must be at most {MAX_EXPRESSION_LENGTH} characters')
        if not isinstance(self.replacement, str) or len(self.replacement) > MAX_EXPRESSION_LENGTH:
            raise ValueError(f'Recipe replacement must be at most {MAX_EXPRESSION_LENGTH} characters')
        for flag_name in ('regex', 'case_sensitive', 'whole_word'):
            if not isinstance(getattr(self, flag_name), bool):
                raise ValueError(f'Recipe {flag_name} must be a boolean')

    def as_dict(self) -> dict:
        return dict(
            id=self.id,
            name=self.name,
            expression=self.expression,
            replacement=self.replacement,
            regex=self.regex,
            case_sensitive=self.case_sensitive,
            whole_word=self.whole_word,
        )

    @classmethod
    def from_dict(cls, payload: object) -> 'FindReplaceRecipe':
        expected = {
            'id', 'name', 'expression', 'replacement',
            'regex', 'case_sensitive', 'whole_word',
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError('Invalid Find/Replace recipe keys')
        return cls(**payload)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def _validate(recipes: tuple[FindReplaceRecipe, ...]) -> None:
    if len(recipes) > MAX_RECIPES:
        raise ValueError(f'At most {MAX_RECIPES} Find/Replace recipes are supported')
    if len({recipe.id for recipe in recipes}) != len(recipes):
        raise ValueError('Find/Replace recipe ids must be unique')
    for recipe in recipes:
        FindReplaceRecipe.from_dict(recipe.as_dict())


class FindReplaceRecipeStore:
    """Recipes are published in ONE atomic JSON replacement.

    Old settings remain the fallback for first use or a damaged file. Loading
    never repairs/writes a damaged file; an explicit save may replace it.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> tuple[FindReplaceRecipe, ...]:
        try:
            with self.path.open('rb') as handle:
                raw = handle.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError(f'Find/Replace recipe file exceeds {MAX_BYTES // 1024} KiB')
            payload = json.loads(raw, object_pairs_hook=_unique_object)
            if (
                not isinstance(payload, dict)
                or set(payload) != {'schema', 'recipes'}
                or type(payload['schema']) is not int
                or payload['schema'] != 1
            ):
                raise ValueError('Unsupported Find/Replace recipe schema')
            if not isinstance(payload['recipes'], list) or len(payload['recipes']) > MAX_RECIPES:
                raise ValueError(f'At most {MAX_RECIPES} Find/Replace recipes are supported')
            recipes = tuple(
                FindReplaceRecipe.from_dict(item) for item in payload['recipes']
            )
            _validate(recipes)
            return recipes
        except FileNotFoundError:
            return ()
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
            return ()

    def save(self, recipes: tuple[FindReplaceRecipe, ...]):
        _validate(recipes)
        payload = dict(schema=1, recipes=[recipe.as_dict() for recipe in recipes])
        encoded = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
        ).encode('utf-8')
        if len(encoded) > MAX_BYTES:
            raise ValueError(f'Find/Replace recipe file exceeds {MAX_BYTES // 1024} KiB')
        return atomic_write_json(self.path, payload)
