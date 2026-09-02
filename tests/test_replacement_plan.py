from __future__ import annotations

from pathlib import Path

import pytest

from uniti.core.document import Document
from uniti.core.pieces import PieceTable
from uniti.regex.replacement_plan import (
    Replacement,
    ReplacementPlan,
    ReplacementPlanLimitError,
)


def test_replacement_plan_spills_and_stays_bounded():
    plan = ReplacementPlan(memory_budget_bytes=64 * 1024, document_revision=4)
    try:
        for index in range(100_000):
            plan.append(Replacement(index * 2, index * 2 + 1, "xy"))

        assert plan.spilled
        assert plan.resident_record_count <= 2048
        assert plan.estimate.count == 100_000
        assert plan.estimate.inserted_chars == 200_000
    finally:
        plan.close()


def test_replacement_plan_rejects_overlapping_or_out_of_order_records():
    plan = ReplacementPlan(memory_budget_bytes=1024, document_revision=0)
    try:
        plan.append(Replacement(2, 5, "x"))
        with pytest.raises(ValueError, match="sorted and non-overlapping"):
            plan.append(Replacement(4, 6, "y"))
    finally:
        plan.close()


def test_bulk_replace_is_one_undo_and_refuses_over_budget(tmp_path: Path):
    path = tmp_path / "bulk.txt"
    path.write_text("abc", encoding="utf-8")
    with Document.open(path) as document:
        plan = ReplacementPlan.from_iterable(
            document_revision=document.revision,
            replacements=(Replacement(0, 1, "A"), Replacement(2, 3, "B")),
            memory_budget_bytes=1 << 20,
        )
        try:
            assert document.apply_replacement_plan(
                plan,
                expected_revision=document.revision,
                memory_limit_bytes=1 << 20,
            ) == 2
        finally:
            plan.close()
        assert document.read(0, 3) == "AbB"
        document.undo()
        assert document.read(0, 3) == "abc"
        document.redo()
        assert document.read(0, 3) == "AbB"

        oversized = ReplacementPlan.from_iterable(
            document_revision=document.revision,
            replacements=(Replacement(0, 1, "x" * 1000),),
            memory_budget_bytes=1 << 20,
        )
        try:
            with pytest.raises(ReplacementPlanLimitError):
                document.apply_replacement_plan(
                    oversized,
                    expected_revision=document.revision,
                    memory_limit_bytes=16,
                )
        finally:
            oversized.close()


def test_bulk_replace_uses_monotonic_builder_not_per_edit_splitting(
    tmp_path: Path,
    monkeypatch,
):
    path = tmp_path / "monotonic.txt"
    path.write_text("abc abc abc", encoding="utf-8")
    with Document.open(path) as document:
        plan = ReplacementPlan.from_iterable(
            document_revision=document.revision,
            replacements=(
                Replacement(0, 3, "A"),
                Replacement(4, 7, "B"),
                Replacement(8, 11, "C"),
            ),
            memory_budget_bytes=1 << 20,
        )
        monkeypatch.setattr(
            PieceTable,
            "_split_at",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("bulk apply used per-edit splitting")
            ),
        )
        try:
            document.apply_replacement_plan(
                plan,
                expected_revision=document.revision,
                memory_limit_bytes=1 << 20,
            )
        finally:
            plan.close()

        assert document.read(0, 5) == "A B C"


def test_bulk_replace_preserves_equal_empty_range_order_in_one_undo_step(
    tmp_path: Path,
):
    path = tmp_path / "empty-ranges.txt"
    path.write_text("ab", encoding="utf-8")
    with Document.open(path) as document:
        plan = ReplacementPlan.from_iterable(
            document_revision=document.revision,
            replacements=(
                Replacement(0, 0, "A"),
                Replacement(0, 0, "B"),
                Replacement(1, 1, "C"),
            ),
            memory_budget_bytes=1 << 20,
        )
        try:
            assert document.apply_replacement_plan(
                plan,
                expected_revision=document.revision,
                memory_limit_bytes=1 << 20,
            ) == 3
        finally:
            plan.close()

        assert document.read(0, document.total_chars()) == "ABaCb"
        document.undo()
        assert document.read(0, document.total_chars()) == "ab"
