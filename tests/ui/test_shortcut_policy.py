from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_shortcut_policy_requires_an_existing_qapplication():
    script = """
from uniti.ui.shortcut_policy import build_shortcut_policy
try:
    build_shortcut_policy({})
except RuntimeError as error:
    print(error)
    raise SystemExit(0)
raise SystemExit(1)
"""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "QApplication" in completed.stdout


def test_standard_commands_use_qt_resolved_portable_sequences(qapp):
    from uniti.ui import shortcut_policy

    build_shortcut_policy = shortcut_policy.build_shortcut_policy

    standards = {
        "file.open": QKeySequence.StandardKey.Open,
        "file.save": QKeySequence.StandardKey.Save,
        "file.save_as": QKeySequence.StandardKey.SaveAs,
        "file.close": QKeySequence.StandardKey.Close,
        "file.quit": QKeySequence.StandardKey.Quit,
        "editing.undo": QKeySequence.StandardKey.Undo,
        "editing.redo": QKeySequence.StandardKey.Redo,
        "editing.cut": QKeySequence.StandardKey.Cut,
        "editing.copy": QKeySequence.StandardKey.Copy,
        "editing.paste": QKeySequence.StandardKey.Paste,
        "editing.select_all": QKeySequence.StandardKey.SelectAll,
        "find.open": QKeySequence.StandardKey.Find,
        "find.replace": QKeySequence.StandardKey.Replace,
        "find.next": QKeySequence.StandardKey.FindNext,
        "find.previous": QKeySequence.StandardKey.FindPrevious,
        "editor.zoom_in": QKeySequence.StandardKey.ZoomIn,
        "editor.zoom_out": QKeySequence.StandardKey.ZoomOut,
        "find.zoom_in": QKeySequence.StandardKey.ZoomIn,
        "find.zoom_out": QKeySequence.StandardKey.ZoomOut,
        "window.new": QKeySequence.StandardKey.New,
        "navigation.page_up": QKeySequence.StandardKey.MoveToPreviousPage,
        "navigation.page_down": QKeySequence.StandardKey.MoveToNextPage,
        "navigation.document_start": QKeySequence.StandardKey.MoveToStartOfDocument,
        "navigation.document_end": QKeySequence.StandardKey.MoveToEndOfDocument,
        "navigation.word_left": QKeySequence.StandardKey.MoveToPreviousWord,
        "navigation.word_right": QKeySequence.StandardKey.MoveToNextWord,
    }
    policy = build_shortcut_policy({})
    definitions = {item.command_id: item for item in policy.definitions}

    for command_id, standard in standards.items():
        expected = QKeySequence(standard)
        actual = QKeySequence.fromString(
            definitions[command_id].default_shortcut,
            QKeySequence.SequenceFormat.PortableText,
        )
        assert definitions[command_id].default_shortcut == expected.toString(
            QKeySequence.SequenceFormat.PortableText
        )
        if expected.isEmpty():
            assert actual.isEmpty()
            continue
        assert actual[0] == expected[0]
        assert actual.matches(expected) is QKeySequence.SequenceMatch.ExactMatch
    assert set(shortcut_policy._UNITI_FALLBACKS) == {
        "file.reload",
        "window.new",
        "editor.zoom_reset",
        "find.zoom_reset",
        "editor.wrap",
        "view.pause_background",
        "find.report_cycle",
    }


def test_portable_overrides_normalize_and_clear_differs_from_reset(qapp):
    from uniti.ui.shortcut_policy import build_shortcut_policy

    policy = build_shortcut_policy(
        {
            "editor.zoom_in": " ctrl + k ",
            "editor.zoom_out": "",
        }
    )

    assert dict(policy.overrides) == {
        "editor.zoom_in": "Ctrl+K",
        "editor.zoom_out": "",
    }
    assert "find.zoom_in" not in policy.overrides
    with pytest.raises(TypeError):
        policy.overrides["editor.zoom_in"] = "Ctrl+J"


def test_disjoint_scopes_accept_same_override_but_overlapping_conflicts_do_not(qapp):
    from uniti.ui.shortcut_policy import build_shortcut_policy

    disjoint = build_shortcut_policy(
        {
            "editor.zoom_in": "Ctrl+K",
            "find.zoom_in": "Ctrl+K",
        }
    )
    conflicting = build_shortcut_policy(
        {
            "editor.zoom_in": "Ctrl+K",
            "editor.zoom_out": "ctrl+k",
        }
    )

    assert dict(disjoint.overrides) == {
        "editor.zoom_in": "Ctrl+K",
        "find.zoom_in": "Ctrl+K",
    }
    assert dict(conflicting.overrides) == {"editor.zoom_in": "Ctrl+K"}
    assert conflicting.notices[-1].command_id == "editor.zoom_out"
    assert conflicting.notices[-1].reason == "conflict"


def test_unknown_invalid_and_conflicting_notices_are_deduplicated_and_bounded(qapp):
    from uniti.ui.shortcut_policy import build_shortcut_policy

    overrides = {
        **{f"unknown.{index}": "Ctrl+K" for index in range(40)},
        "editor.zoom_in": "Ctrl+K",
        "editor.zoom_out": "Ctrl+K",
        "file.save": "not a shortcut",
    }

    policy = build_shortcut_policy(overrides)

    assert len(policy.notices) == 32
    assert len({(item.command_id, item.reason) for item in policy.notices}) == 32
    assert all(item.reason in {"unknown", "invalid", "conflict"} for item in policy.notices)
    assert dict(policy.overrides) == {"editor.zoom_in": "Ctrl+K"}
