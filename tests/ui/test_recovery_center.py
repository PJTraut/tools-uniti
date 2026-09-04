from __future__ import annotations

import os
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from uniti.ui.recovery_center import (
    MAX_RECOVERY_ENTRIES,
    RecoveryAction,
    RecoveryCenterDialog,
    RecoveryCenterModel,
    RecoveryEntry,
    RecoveryEntryKind,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def make_entry(kind: RecoveryEntryKind, index: int = 0) -> RecoveryEntry:
    path = Path(f"/safe/document-{index}.txt")
    return RecoveryEntry.create(
        entry_id=f"entry-{index}",
        kind=kind,
        path=path,
        message="UNITI found saved state that needs a decision.",
        evidence_path=Path(f"/owned/evidence-{index}.data"),
    )


@pytest.mark.parametrize(
    ("kind", "actions"),
    [
        (
            RecoveryEntryKind.RECOVERABLE,
            {RecoveryAction.RECOVER, RecoveryAction.SKIP, RecoveryAction.DISCARD},
        ),
        (
            RecoveryEntryKind.SESSION_READY,
            {RecoveryAction.RECOVER, RecoveryAction.SKIP, RecoveryAction.DISCARD},
        ),
        (
            RecoveryEntryKind.TRUNCATED,
            {RecoveryAction.RECOVER, RecoveryAction.SKIP, RecoveryAction.DISCARD},
        ),
        (
            RecoveryEntryKind.CHANGED,
            {RecoveryAction.OPEN_DISK, RecoveryAction.SKIP, RecoveryAction.DISCARD},
        ),
        (
            RecoveryEntryKind.MISSING,
            {
                RecoveryAction.LOCATE_MATCH,
                RecoveryAction.SKIP,
                RecoveryAction.DISCARD,
            },
        ),
        (
            RecoveryEntryKind.CORRUPT,
            {RecoveryAction.SKIP, RecoveryAction.DISCARD},
        ),
        (
            RecoveryEntryKind.UNSUPPORTED,
            {RecoveryAction.SKIP, RecoveryAction.DISCARD},
        ),
        (
            RecoveryEntryKind.DEGRADED,
            {RecoveryAction.RECOVER, RecoveryAction.SKIP, RecoveryAction.DISCARD},
        ),
    ],
)
def test_recovery_center_enables_only_safe_actions(kind, actions):
    assert set(make_entry(kind).actions) == actions


def test_model_exposes_bounded_safe_accessible_rows_without_document_content(qapp):
    entry = make_entry(RecoveryEntryKind.RECOVERABLE)
    model = RecoveryCenterModel((entry,))

    accessible = model.data(model.index(0, 0), Qt.ItemDataRole.AccessibleTextRole)

    assert "Recoverable changes" in accessible
    assert str(entry.path) in accessible
    assert "Recover restores saved UNITI state" in accessible
    assert "private document contents" not in accessible
    assert model.data(model.index(0, 0), model.EntryRole) is entry


def test_model_rejects_more_than_the_bounded_entry_limit(qapp):
    entries = tuple(
        make_entry(RecoveryEntryKind.CORRUPT, index)
        for index in range(MAX_RECOVERY_ENTRIES + 1)
    )

    with pytest.raises(ValueError, match="too many recovery entries"):
        RecoveryCenterModel(entries)


def test_closing_dialog_returns_skip_for_every_entry(qapp):
    entries = (
        make_entry(RecoveryEntryKind.RECOVERABLE, 1),
        make_entry(RecoveryEntryKind.CHANGED, 2),
    )
    dialog = RecoveryCenterDialog(entries)
    assert dialog.select_action(entries[0].entry_id, RecoveryAction.RECOVER)
    assert dialog.select_action(entries[1].entry_id, RecoveryAction.OPEN_DISK)

    dialog.reject()

    assert tuple(decision.action for decision in dialog.decisions()) == (
        RecoveryAction.SKIP,
        RecoveryAction.SKIP,
    )


def test_discard_requires_confirmation_before_decision_changes(qapp):
    entry = make_entry(RecoveryEntryKind.CORRUPT)
    confirmations: list[str] = []
    allowed = False

    def confirm(selected: RecoveryEntry) -> bool:
        confirmations.append(selected.entry_id)
        return allowed

    dialog = RecoveryCenterDialog((entry,), confirm_discard=confirm)

    assert dialog.select_action(entry.entry_id, RecoveryAction.DISCARD) is False
    assert dialog.decisions()[0].action is RecoveryAction.SKIP
    allowed = True
    assert dialog.select_action(entry.entry_id, RecoveryAction.DISCARD) is True
    assert dialog.decisions()[0].action is RecoveryAction.DISCARD
    assert confirmations == [entry.entry_id, entry.entry_id]


def test_action_combo_records_the_selected_enum_action(qapp):
    entry = make_entry(RecoveryEntryKind.RECOVERABLE)
    dialog = RecoveryCenterDialog((entry,))

    recover_index = entry.actions.index(RecoveryAction.RECOVER)
    dialog.action_combo.setCurrentIndex(recover_index)

    assert dialog.decisions()[0].action is RecoveryAction.RECOVER
