import importlib.util
import os

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None, reason="PySide6 is not installed"
)


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("base_hex", ("#ffffff", "#1e1e1e"))
def test_syntax_category_palette_colors_are_all_distinct(app, base_hex):
    from PySide6.QtGui import QColor

    from uniti.ui.syntax_theme import syntax_category_palette

    base = QColor(base_hex)
    palette = syntax_category_palette(base)
    names = [color.name() for color in palette.values()]
    assert len(set(names)) == len(names)


@pytest.mark.parametrize("base_hex", ("#ffffff", "#1e1e1e"))
def test_syntax_category_palette_covers_every_tokenizer_category(app, base_hex):
    from PySide6.QtGui import QColor

    from uniti.core.syntax_profiles import PROFILES
    from uniti.ui.syntax_theme import syntax_category_palette

    base = QColor(base_hex)
    palette = syntax_category_palette(base)
    used_categories = {
        category
        for profile in PROFILES
        for category, _ in _rules_of(profile)
    }
    assert used_categories <= set(palette)


def _rules_of(profile):
    # Exercise the tokenizer against representative content instead of
    # reaching into its private rule table, so this stays valid even if a
    # profile's implementation changes shape.
    samples = {
        "json": '{"a": "b", "n": 1, "t": true} // c',
        "yaml": "a: b  # c\n- item",
        "xml": '<!-- c --><a b="c">d</a>',
        "markdown": "# H\n**b** *i* `c` [t](u)",
        "sfm": r"\v 1 text",
        "csv": 'a,"b"',
        "tsv": "a\tb",
        "plain_text": "anything",
    }
    text = samples.get(profile.key, "")
    tokens, _state = profile.tokenize(text, profile.initial_state)
    return [(token.category, None) for token in tokens]


@pytest.mark.parametrize("base_hex", ("#ffffff", "#1e1e1e"))
def test_syntax_category_palette_meets_contrast_floor_against_base(app, base_hex):
    from PySide6.QtGui import QColor

    from uniti.ui.color_contrast import contrast_ratio
    from uniti.ui.syntax_theme import syntax_category_palette

    base = QColor(base_hex)
    palette = syntax_category_palette(base)
    for category, color in palette.items():
        assert contrast_ratio(color, base) >= 4.5, category
