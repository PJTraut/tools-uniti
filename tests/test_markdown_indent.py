"""N35: Tab / Shift+Tab over selected Markdown list items moves them together."""

import pytest

from uniti.core.environments.markdown_views import indent_list_lines
from uniti.core.rich_views.editing import EditRejected


def apply(source: str, plan) -> str:
    out, position = [], 0
    for a, b, text in plan.replacements:
        out.append(source[position:a])
        out.append(text)
        position = b
    out.append(source[position:])
    return "".join(out)


def test_selected_items_indent_together_by_marker_width():
    source = "intro\n- a\n- b\n1. c\n\nafter\n"
    plan = indent_list_lines(source, source.index("a"), source.index("c"))
    assert apply(source, plan) == "intro\n  - a\n  - b\n   1. c\n\nafter\n"


def test_outdent_removes_one_level_and_stops_at_zero():
    source = "    - a\n  - b\n- c\n"
    plan = indent_list_lines(source, 0, len(source) - 1, outdent=True)
    assert apply(source, plan) == "  - a\n- b\n- c\n"


def test_non_list_lines_are_left_alone_and_none_is_rejected():
    source = "text\n- a\n"
    assert apply(source, indent_list_lines(source, 0, len(source) - 1)) == "text\n  - a\n"
    with pytest.raises(EditRejected):
        indent_list_lines("just text\n", 0, 5)


def test_a_rule_and_fenced_lines_are_not_items():
    source = "```\n- code\n```\n---\n- a\n"
    assert apply(source, indent_list_lines(source, 0, len(source) - 1)) == "```\n- code\n```\n---\n  - a\n"
