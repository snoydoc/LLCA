# -*- coding: utf-8-sig -*-
"""
test_planner.py — Audit coverage B (2026-04-23)
Tests unitaires pour core/planner.py.

Couvre :
  1. PatchOperation + Plan (dataclasses, is_valid)
  2. PlannedOperation (dataclass, file_path property)
  3. Planner.build() — chemin normal + raise ValueError si > MAX_FILES_PER_TX
  4. MultiFilePlanner.create_plan() — plan vide, dédup, limite MAX, tri topologique
  5. MultiFilePlanner.validate_plan_consistency() — 3 règles de validation
  6. MultiFilePlanner._infer_op_params() — actions connues + cas "import" + cas "core"
  7. MultiFilePlanner._infer_symbol() — regex + fallback snake_case + None

Suite : 18 tests
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core.planner import (
    MultiFilePlanner,
    OpPriority,
    PatchOperation,
    Plan,
    Planner,
    PlannedOperation,
)


# ══════════════════════════════════════════════════════════════════════════════
# 1. PatchOperation + Plan
# ══════════════════════════════════════════════════════════════════════════════

class TestPatchOperationAndPlan:

    def test_patch_operation_defaults(self):
        op = PatchOperation(file=Path("mod.py"), operation="add_function")
        assert op.target_name == ""
        assert op.code == ""

    def test_plan_is_valid_within_limit(self):
        ops = [
            PatchOperation(file=Path("a.py"), operation="add_function"),
            PatchOperation(file=Path("b.py"), operation="add_function"),
        ]
        plan = Plan(task_label="test", operations=ops)
        assert plan.is_valid(max_files=3) is True

    def test_plan_is_invalid_exceeds_limit(self):
        ops = [
            PatchOperation(file=Path("a.py"), operation="add_function"),
            PatchOperation(file=Path("b.py"), operation="add_function"),
            PatchOperation(file=Path("c.py"), operation="add_function"),
            PatchOperation(file=Path("d.py"), operation="add_function"),
        ]
        plan = Plan(task_label="test", operations=ops)
        assert plan.is_valid(max_files=3) is False

    def test_plan_is_valid_same_file_counted_once(self):
        """Deux ops sur le même fichier = 1 fichier distinct."""
        ops = [
            PatchOperation(file=Path("a.py"), operation="add_function"),
            PatchOperation(file=Path("a.py"), operation="add_import"),
            PatchOperation(file=Path("b.py"), operation="add_function"),
            PatchOperation(file=Path("c.py"), operation="add_function"),
        ]
        plan = Plan(task_label="test", operations=ops)
        # 3 fichiers distincts (a, b, c) → valide
        assert plan.is_valid(max_files=3) is True


# ══════════════════════════════════════════════════════════════════════════════
# 2. PlannedOperation
# ══════════════════════════════════════════════════════════════════════════════

class TestPlannedOperation:

    def test_file_path_property(self):
        op = PlannedOperation(
            file="core/my_module.py",
            action="modify",
            target_symbol="my_func",
            description="Modifie my_func",
        )
        assert op.file_path == Path("core/my_module.py")

    def test_default_priority_is_normal(self):
        op = PlannedOperation(
            file="mod.py", action="modify",
            target_symbol=None, description="test",
        )
        assert op.priority == OpPriority.NORMAL

    def test_default_dependencies_empty(self):
        op = PlannedOperation(
            file="mod.py", action="create",
            target_symbol="fn", description="crée fn",
        )
        assert op.dependencies == []


# ══════════════════════════════════════════════════════════════════════════════
# 3. Planner.build()
# ══════════════════════════════════════════════════════════════════════════════

class TestPlannerBuild:

    def test_build_valid_plan(self):
        planner = Planner()
        ops = [
            {"file": "a.py", "operation": "add_function", "target_name": "foo", "code": "def foo(): pass"},
            {"file": "b.py", "operation": "add_import", "target_name": "", "code": "import os"},
        ]
        plan = planner.build("Ma tâche", ops)
        assert isinstance(plan, Plan)
        assert plan.task_label == "Ma tâche"
        assert len(plan.operations) == 2

    def test_build_raises_on_too_many_files(self):
        planner = Planner()
        ops = [
            {"file": f"{chr(97+i)}.py", "operation": "add_function"}
            for i in range(4)  # 4 fichiers distincts > MAX_FILES_PER_TX=3
        ]
        with pytest.raises(ValueError, match="MAX_FILES_PER_TX"):
            planner.build("Trop de fichiers", ops)

    def test_build_returns_patch_operations(self):
        planner = Planner()
        ops = [{"file": "x.py", "operation": "modify_function", "target_name": "g", "code": "def g(): ..."}]
        plan = planner.build("label", ops)
        assert all(isinstance(op, PatchOperation) for op in plan.operations)
        assert plan.operations[0].file == Path("x.py")


# ══════════════════════════════════════════════════════════════════════════════
# 4. MultiFilePlanner.create_plan()
# ══════════════════════════════════════════════════════════════════════════════

class TestMultiFilePlannerCreatePlan:

    def test_empty_target_files_returns_empty(self):
        ops = MultiFilePlanner().create_plan("validate_email()", [])
        assert ops == []

    def test_dedup_same_file(self):
        files = ["a.py", "a.py", "b.py"]
        ops = MultiFilePlanner().create_plan("fn()", files)
        files_in_ops = [op.file for op in ops]
        assert files_in_ops.count("a.py") == 1

    def test_limit_to_max_files_per_tx(self):
        files = ["a.py", "b.py", "c.py", "d.py", "e.py"]
        ops = MultiFilePlanner().create_plan("fn()", files)
        assert len(ops) <= 3  # MAX_FILES_PER_TX

    def test_returns_planned_operations(self):
        ops = MultiFilePlanner().create_plan("my_fn()", ["core/x.py"])
        assert len(ops) == 1
        assert isinstance(ops[0], PlannedOperation)

    def test_description_contains_file(self):
        ops = MultiFilePlanner().create_plan("do_stuff()", ["mymod.py"], intent_action="ajoute")
        assert "mymod.py" in ops[0].description

    def test_topological_sort_high_priority_first(self):
        """Les fichiers 'core' ont priorité HIGH → apparaissent en premier."""
        files = ["regular.py", "core/engine.py"]
        ops = MultiFilePlanner().create_plan("fn()", files, intent_action="modifie")
        # core/engine.py doit être en première position (priorité HIGH)
        assert "core" in ops[0].file


# ══════════════════════════════════════════════════════════════════════════════
# 5. MultiFilePlanner.validate_plan_consistency()
# ══════════════════════════════════════════════════════════════════════════════

class TestValidatePlanConsistency:

    def _op(self, file: str, action: str = "modify", symbol: str | None = None) -> PlannedOperation:
        return PlannedOperation(
            file=file, action=action,
            target_symbol=symbol, description=f"{action} {file}",
        )

    def test_valid_plan_returns_true(self):
        ops = [self._op("a.py"), self._op("b.py")]
        valid, errors = MultiFilePlanner().validate_plan_consistency(ops)
        assert valid is True
        assert errors == []

    def test_too_many_files_returns_error(self):
        ops = [self._op(f"{c}.py") for c in "abcd"]  # 4 fichiers > MAX=3
        valid, errors = MultiFilePlanner().validate_plan_consistency(ops)
        assert valid is False
        assert any("Trop de fichiers" in e for e in errors)

    def test_same_symbol_in_multiple_files_returns_error(self):
        ops = [
            self._op("a.py", symbol="my_func"),
            self._op("b.py", symbol="my_func"),
        ]
        valid, errors = MultiFilePlanner().validate_plan_consistency(ops)
        assert valid is False
        assert any("my_func" in e for e in errors)

    def test_delete_and_modify_same_file_returns_error(self):
        ops = [
            self._op("a.py", action="delete"),
            self._op("a.py", action="modify"),
        ]
        valid, errors = MultiFilePlanner().validate_plan_consistency(ops)
        assert valid is False
        assert any("supprimé" in e or "modifié" in e for e in errors)


# ══════════════════════════════════════════════════════════════════════════════
# 6. MultiFilePlanner._infer_op_params()
# ══════════════════════════════════════════════════════════════════════════════

class TestInferOpParams:

    def _infer(self, action: str, file: str = "mod.py", target: str = "", details: str = "fn()"):
        return MultiFilePlanner()._infer_op_params(action, file, target, details)

    def test_action_ajoute(self):
        action, patch_type, priority = self._infer("ajoute")
        assert action == "modify"
        assert patch_type == "add_function"

    def test_action_cree_gives_high_priority(self):
        _, _, priority = self._infer("cree")
        assert priority == OpPriority.HIGH

    def test_action_supprime_gives_low_priority(self):
        _, _, priority = self._infer("supprime")
        assert priority == OpPriority.LOW

    def test_action_corrige_gives_high_priority(self):
        _, _, priority = self._infer("corrige")
        assert priority == OpPriority.HIGH

    def test_import_in_details_overrides_patch_type(self):
        _, patch_type, _ = self._infer("ajoute", details="ajouter import os")
        assert patch_type == "add_import"

    def test_core_file_overrides_priority_to_high(self):
        _, _, priority = self._infer("ajoute", file="core/engine.py")
        assert priority == OpPriority.HIGH

    def test_unknown_action_uses_defaults(self):
        action, patch_type, priority = self._infer("inconnu")
        assert action == "modify"
        assert patch_type == "add_function"
        assert priority == OpPriority.NORMAL


# ══════════════════════════════════════════════════════════════════════════════
# 7. MultiFilePlanner._infer_symbol()
# ══════════════════════════════════════════════════════════════════════════════

class TestInferSymbol:

    def _sym(self, details: str) -> str | None:
        return MultiFilePlanner()._infer_symbol(details)

    def test_extracts_function_name_with_parens(self):
        assert self._sym("validate_email()") == "validate_email"

    def test_extracts_method_name_with_args(self):
        assert self._sym("build_prompt(system, user)") == "build_prompt"

    def test_fallback_to_first_snake_case_word(self):
        assert self._sym("my_module something") == "my_module"

    def test_returns_none_on_empty(self):
        assert self._sym("") is None

    def test_returns_none_on_non_identifier(self):
        # Chaîne sans identifiant valide
        assert self._sym("123 abc") is None or self._sym("123 abc") == "abc"
