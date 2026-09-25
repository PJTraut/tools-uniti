from __future__ import annotations

import ast
import os
from datetime import timedelta
from pathlib import Path

from uniti.app.document_registry import CLOSED_HISTORY_RETENTION
from uniti.app.recovery_manager import RECOVERY_FREE_SPACE_RESERVE
from uniti.app.session import (
    MAX_DOCUMENTS,
    MAX_FIND_REPLACE_DECODED_BYTES,
    MAX_INPUT_HISTORY_STATES,
    MAX_LEAF_PANES,
    MAX_MANIFEST_BYTES,
    MAX_PACK_DECODED_BYTES,
    MAX_VIEWS,
    MAX_WINDOWS,
)
from uniti.app.session_store import AGGREGATE_HISTORY_BYTES, HISTORY_RETENTION
from uniti.core.history import EditHistory, EditOperation, EditTransaction
from uniti.ui.recovery_center import (
    RecoveryAction,
    RecoveryEntry,
    RecoveryEntryKind,
)


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


_A20_TEST_FILES = (
    Path("tests/test_a20_recovery_session_acceptance.py"),
    Path("tests/app/test_document_registry.py"),
    Path("tests/app/test_instance_service.py"),
    Path("tests/app/test_recovery_manager.py"),
    Path("tests/app/test_service.py"),
    Path("tests/app/test_settings.py"),
    Path("tests/app/test_session.py"),
    Path("tests/app/test_session_orchestration.py"),
    Path("tests/app/test_session_roundtrip.py"),
    Path("tests/app/test_session_store.py"),
    Path("tests/app/test_setup_state.py"),
    Path("tests/ui/test_find_replace_contract.py"),
    Path("tests/ui/test_main_window_contract.py"),
    Path("tests/ui/test_panes.py"),
    Path("tests/ui/test_resource_status.py"),
    Path("tests/test_a21_cross_platform_acceptance.py"),
    Path("tests/performance/test_faults.py"),
)
_FORBIDDEN_CAPACITY_CALLS = {
    "posix_fallocate",
    "fallocate",
    "ftruncate",
    "reserve_volume",
    "set_disk_capacity",
    "truncate",
}
_FORBIDDEN_CAPACITY_COMMANDS = {"diskutil", "fallocate", "mkfile"}


def _called_name(node: ast.Call) -> str | None:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return None


def _constant_command(node: ast.Call) -> str | None:
    if not node.args:
        return None
    argument = node.args[0]
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return Path(argument.value.split(maxsplit=1)[0]).name
    if isinstance(argument, (ast.List, ast.Tuple)) and argument.elts:
        first = argument.elts[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return Path(first.value).name
    return None


def test_a20_history_and_storage_budgets_are_exact_and_bounded():
    history = EditHistory()
    for index in range(110):
        history.record(EditTransaction((EditOperation(index, "", "x"),)))
    assert len(history.export_snapshot().transactions) == 100
    assert MAX_PACK_DECODED_BYTES == 64 << 20
    assert MAX_INPUT_HISTORY_STATES == 50
    assert MAX_FIND_REPLACE_DECODED_BYTES == 4 << 20
    assert AGGREGATE_HISTORY_BYTES == 512 << 20
    assert RECOVERY_FREE_SPACE_RESERVE == 512 << 20
    assert CLOSED_HISTORY_RETENTION == HISTORY_RETENTION == timedelta(days=7)
    assert MAX_MANIFEST_BYTES == 1 << 20
    assert (MAX_WINDOWS, MAX_LEAF_PANES, MAX_VIEWS, MAX_DOCUMENTS) == (
        32,
        128,
        256,
        128,
    )


def test_a20_low_disk_tests_never_allocate_or_fill_real_capacity():
    violations: list[str] = []
    for path in _A20_TEST_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _called_name(node)
            if name in _FORBIDDEN_CAPACITY_CALLS:
                violations.append(f"{path}:{node.lineno}:{name}")
            if name in {"run", "Popen", "call", "check_call", "check_output"}:
                command = _constant_command(node)
                if command in _FORBIDDEN_CAPACITY_COMMANDS:
                    violations.append(f"{path}:{node.lineno}:{command}")
        for loop in (
            node for node in ast.walk(tree) if isinstance(node, (ast.For, ast.While))
        ):
            for node in ast.walk(loop):
                if isinstance(node, ast.Call) and _called_name(node) == "write":
                    violations.append(f"{path}:{node.lineno}:looped-write")
    assert violations == []


def test_a20_observability_contracts_are_registered():
    from benchmarks.scenarios import initial_scenario_names
    from uniti.app.self_check import SelfCheckRunner

    assert hasattr(SelfCheckRunner, "_deep_recovery_session")
    assert "session_restore" in initial_scenario_names("quick")
    assert "session_restore" in initial_scenario_names("routine")
    assert "session_restore" not in initial_scenario_names("design_target")


def test_a20_recovery_conflicts_offer_only_explicit_safe_actions(tmp_path: Path):
    expected = {
        RecoveryEntryKind.CHANGED: (
            RecoveryAction.OPEN_DISK,
            RecoveryAction.SKIP,
            RecoveryAction.DISCARD,
        ),
        RecoveryEntryKind.MISSING: (
            RecoveryAction.LOCATE_MATCH,
            RecoveryAction.SKIP,
            RecoveryAction.DISCARD,
        ),
        RecoveryEntryKind.CORRUPT: (
            RecoveryAction.SKIP,
            RecoveryAction.DISCARD,
        ),
        RecoveryEntryKind.UNSUPPORTED: (
            RecoveryAction.SKIP,
            RecoveryAction.DISCARD,
        ),
        RecoveryEntryKind.TRUNCATED: (
            RecoveryAction.RECOVER,
            RecoveryAction.SKIP,
            RecoveryAction.DISCARD,
        ),
    }
    for index, (kind, actions) in enumerate(expected.items()):
        evidence = tmp_path / f"evidence-{index}"
        entry = RecoveryEntry.create(
            entry_id=f"entry-{index}",
            kind=kind,
            path=tmp_path / f"source-{index}",
            message="Bounded recovery decision.",
            evidence_path=evidence,
        )
        assert entry.actions == actions


def test_a20_recovery_session_probe_preserves_external_source(tmp_path: Path):
    from uniti.app.self_check import SelfCheckRunner

    _summary, details = SelfCheckRunner._deep_recovery_session(tmp_path)

    assert details["session_hash_exact"] is True
    assert details["recovery_undo_available"] is True
    assert details["recovery_redo_exact"] is True
    assert details["external_change_detected"] is True
    assert details["external_source_preserved"] is True


def test_a20_second_crash_during_recovery_publication_keeps_usable_evidence(
    tmp_path: Path,
):
    from uniti.app.recovery_manager import RecoveryManager
    from uniti.core.document import Document

    source = tmp_path / "second-crash.txt"
    source.write_text("base", encoding="utf-8")
    recovery_root = tmp_path / "second-crash-recovery"
    first = RecoveryManager(recovery_root)
    document = Document.open(source)
    first.attach(document)
    document.insert(document.total_chars(), " unsaved")
    first.detach(document, clean=False)
    document.close()
    first.shutdown()

    second = RecoveryManager(recovery_root)
    candidate = second.discover()[0]
    recovered = second.prepare_recovery(candidate)
    original_path = recovered.original.evidence_path
    fresh_path = recovered.fresh_journal
    assert original_path.exists()
    assert fresh_path.exists()
    second.shutdown()
    recovered.document.close()

    third = RecoveryManager(recovery_root)
    try:
        candidates = third.discover()
        assert candidates
        assert any(item.session is not None for item in candidates)
        assert original_path.exists() or fresh_path.exists()
    finally:
        third.shutdown()


def test_a20_service_lifetime_restart_and_global_panel_smoke(tmp_path: Path):
    from uniti.app.smoke import run_gui_smoke

    result = run_gui_smoke(tmp_path / "service-smoke")

    assert result["ok"] is True
    assert result["service_remained_running"] is True
    assert result["activation_created_window"] is True
    assert result["one_document_authority"] is True
    assert result["session_restored"] is True
    assert result["history_restored"] is True
    assert result["find_replace_attached"] is True
    assert result["find_replace_followed_window"] is True
    assert result["find_replace_detached"] is True
    assert result["find_replace_restored"] is True
    assert result["display_settings_applied"] is True
    assert result["explicit_quit"] is True


def test_a20_inherited_acceptance_contracts_remain_present():
    inherited = (
        Path("tests/test_a17_text_integrity_acceptance.py"),
        Path("tests/test_a18_large_file_acceptance.py"),
        Path("tests/test_a19_regex_intelligence_acceptance.py"),
    )
    assert all(path.is_file() for path in inherited)
