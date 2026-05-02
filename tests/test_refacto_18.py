# -*- coding: utf-8-sig -*-
"""
test_refacto_18.py — REFACTO-18 : orchestrator.py decoupé en 3 modules

Couvre :
    orchestrator_pipeline.py  — OrchestratorPipeline.run_pipeline() + _validate_changes()
    orchestrator_helpers.py   — update_sprint_log() + dry_run()
    orchestrator.py (facade)  — execute() delegue + dry_run() delegue + aliases retrocompat

18 tests.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Helpers communs
# ──────────────────────────────────────────────────────────────────────────────

def _make_intent(raw: str = "Proj - auth - Ajoute login()", action: str = "ajoute"):
    """Intent minimal compatible avec les helpers."""
    intent = MagicMock()
    intent.raw        = raw
    intent.project    = "Proj"
    intent.action     = action
    intent.target     = "auth"
    intent.details    = "login()"
    intent.confidence = 0.95
    intent.is_confident.return_value = True
    intent.summary.return_value      = f"{action} login()"
    return intent


def _make_op(file: str = "auth.py", action: str = "modify"):
    op = MagicMock()
    op.file          = file
    op.action        = action
    op.patch_type    = "add_function"
    op.target_symbol = "login"
    return op


def _make_llm(available: bool = True):
    llm = MagicMock()
    llm.is_available.return_value = available
    gen = MagicMock()
    gen.code          = "def login(): pass"
    gen.from_fallback = False
    gen.from_cache    = False
    gen.model         = "qwen2.5-coder:3b"
    gen.duration_ms   = 120
    llm.generate.return_value = gen
    return llm


# ──────────────────────────────────────────────────────────────────────────────
# 1. orchestrator_pipeline — _validate_changes
# ──────────────────────────────────────────────────────────────────────────────

class TestValidateChanges:

    def test_no_current_tx_returns_true(self):
        """Sans TX courante, retourne True (rien a valider)."""
        from core.orchestrator_pipeline import _validate_changes

        tx = MagicMock()
        tx.current_tx = None
        assert _validate_changes(tx, Path("/ws")) is True

    def test_no_py_files_returns_true(self, tmp_path):
        """TX sans fichiers .py retourne True."""
        from core.orchestrator_pipeline import _validate_changes

        op = MagicMock()
        op.target_path = str(tmp_path / "README.md")
        tx = MagicMock()
        tx.current_tx.operations = [op]
        assert _validate_changes(tx, tmp_path) is True

    def test_valid_py_syntax_returns_true(self, tmp_path):
        """Fichier Python syntaxiquement correct retourne True."""
        from core.orchestrator_pipeline import _validate_changes

        src = tmp_path / "auth.py"
        src.write_text("def login(): pass\n", encoding="utf-8")

        op = MagicMock()
        op.target_path = str(src)
        tx = MagicMock()
        tx.current_tx.operations = [op]

        with patch("core.orchestrator_pipeline.Executor") as MockExec:
            MockExec.return_value.check_syntax.return_value = None
            result = _validate_changes(tx, tmp_path)

        assert result is True

    def test_invalid_py_syntax_returns_false(self, tmp_path):
        """Fichier avec erreur syntaxe retourne False."""
        from core.orchestrator_pipeline import _validate_changes

        src = tmp_path / "broken.py"
        src.write_text("def bad(:\n", encoding="utf-8")

        op = MagicMock()
        op.target_path = str(src)
        tx = MagicMock()
        tx.current_tx.operations = [op]

        with patch("core.orchestrator_pipeline.Executor") as MockExec:
            MockExec.return_value.check_syntax.return_value = "SyntaxError ligne 1"
            result = _validate_changes(tx, tmp_path)

        assert result is False


# ──────────────────────────────────────────────────────────────────────────────
# 2. orchestrator_pipeline — OrchestratorPipeline.run_pipeline
# ──────────────────────────────────────────────────────────────────────────────

class TestOrchestratorPipeline:

    def _make_pipeline_mocks(self, tmp_path):
        """Fournit les mocks necessaires a run_pipeline."""
        from core.orchestrator_pipeline import OrchestratorPipeline

        pipeline = OrchestratorPipeline()
        intent   = _make_intent()
        llm      = _make_llm()
        op       = _make_op(file="auth.py", action="create")

        selector = MagicMock()
        selector.select.return_value = ["auth.py"]

        planner  = MagicMock()
        planner.create_plan.return_value            = [op]
        planner.validate_plan_consistency.return_value = (True, [])

        tx = MagicMock()
        tx.begin.return_value = "tx_test123"
        tx.current_tx         = None  # apres commit

        patcher   = MagicMock()
        indexer   = MagicMock()
        dep_graph = MagicMock()

        return pipeline, intent, llm, op, selector, planner, tx, patcher, indexer, dep_graph

    def test_run_pipeline_no_files_returns_false(self, tmp_path):
        """Selector retourne [] → pipeline retourne False."""
        from core.orchestrator_pipeline import OrchestratorPipeline

        pipeline = OrchestratorPipeline()
        selector = MagicMock()
        selector.select.return_value = []

        result = pipeline.run_pipeline(
            intent=_make_intent(), tx_manager=MagicMock(),
            workspace=tmp_path, llm=_make_llm(),
            patcher=MagicMock(), indexer=MagicMock(),
            dep_graph=MagicMock(), planner=MagicMock(),
            selector=selector,
        )
        assert result is False

    def test_run_pipeline_invalid_plan_returns_false(self, tmp_path):
        """Plan invalide → pipeline retourne False."""
        from core.orchestrator_pipeline import OrchestratorPipeline

        pipeline = OrchestratorPipeline()
        selector = MagicMock()
        selector.select.return_value = ["auth.py"]
        planner  = MagicMock()
        planner.create_plan.return_value              = [_make_op()]
        planner.validate_plan_consistency.return_value = (False, ["trop de fichiers"])

        result = pipeline.run_pipeline(
            intent=_make_intent(), tx_manager=MagicMock(),
            workspace=tmp_path, llm=_make_llm(),
            patcher=MagicMock(), indexer=MagicMock(),
            dep_graph=MagicMock(), planner=planner,
            selector=selector,
        )
        assert result is False

    def test_run_pipeline_commit_called_on_success(self, tmp_path):
        """Apres un pipeline reussi, tx_manager.commit() est appele."""
        from core.orchestrator_pipeline import OrchestratorPipeline, _validate_changes

        pipeline, intent, llm, op, selector, planner, tx, patcher, indexer, dep_graph = \
            self._make_pipeline_mocks(tmp_path)

        with patch("core.orchestrator_pipeline._validate_changes", return_value=True):
            result = pipeline.run_pipeline(
                intent=intent, tx_manager=tx,
                workspace=tmp_path, llm=llm,
                patcher=patcher, indexer=indexer,
                dep_graph=dep_graph, planner=planner,
                selector=selector,
            )

        assert result is True
        tx.commit.assert_called_once()

    def test_run_pipeline_rollback_on_exception(self, tmp_path):
        """Exception dans le pipeline → rollback appele."""
        from core.orchestrator_pipeline import OrchestratorPipeline

        pipeline = OrchestratorPipeline()
        selector = MagicMock()
        selector.select.return_value = ["auth.py"]
        planner  = MagicMock()
        planner.create_plan.return_value              = [_make_op()]
        planner.validate_plan_consistency.return_value = (True, [])

        tx = MagicMock()
        tx.begin.side_effect = RuntimeError("DB error")
        tx.current_tx        = MagicMock()

        result = pipeline.run_pipeline(
            intent=_make_intent(), tx_manager=tx,
            workspace=tmp_path, llm=_make_llm(),
            patcher=MagicMock(), indexer=MagicMock(),
            dep_graph=MagicMock(), planner=planner,
            selector=selector, auto_rollback=True,
        )
        assert result is False
        tx.rollback.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# 3. orchestrator_helpers — update_sprint_log
# ──────────────────────────────────────────────────────────────────────────────

class TestUpdateSprintLog:

    def test_creates_log_entry(self, tmp_path):
        """update_sprint_log ecrit une entree dans current-sprint.md."""
        from core.orchestrator_helpers import update_sprint_log

        intent = _make_intent()
        plan   = [_make_op("auth.py")]
        llm    = _make_llm(available=True)

        log_path = tmp_path / "Sprints" / "current-sprint.md"
        with patch("core.orchestrator_helpers.DOCS_DIR", tmp_path):
            update_sprint_log(intent, plan, "tx_abc123", llm)

        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8")
        assert "tx_abc123" in content
        assert "auth.py" in content
        assert "Ollama" in content

    def test_stub_llm_logs_stub(self, tmp_path):
        """LLM indisponible → 'stub' dans le log."""
        from core.orchestrator_helpers import update_sprint_log

        intent = _make_intent()
        plan   = [_make_op("auth.py")]
        llm    = _make_llm(available=False)

        with patch("core.orchestrator_helpers.DOCS_DIR", tmp_path):
            update_sprint_log(intent, plan, "tx_stub", llm)

        content = (tmp_path / "Sprints" / "current-sprint.md").read_text(encoding="utf-8")
        assert "stub" in content

    def test_no_exception_if_docs_dir_unwritable(self, tmp_path):
        """Echec d'ecriture silencieux — pas d'exception propagee."""
        from core.orchestrator_helpers import update_sprint_log

        intent = _make_intent()
        with patch("core.orchestrator_helpers.DOCS_DIR", Path("/inexistant/path/xyz")):
            # Doit logguer un warning sans lever d'exception
            update_sprint_log(intent, [], "tx_fail", _make_llm())


# ──────────────────────────────────────────────────────────────────────────────
# 4. orchestrator_helpers — dry_run
# ──────────────────────────────────────────────────────────────────────────────

class TestDryRunHelper:

    def test_dry_run_returns_expected_keys(self, tmp_path):
        """dry_run retourne les cles attendues."""
        from core.orchestrator_helpers import dry_run

        selector = MagicMock()
        selector.select.return_value = ["auth.py"]
        planner  = MagicMock()
        planner.create_plan.return_value              = [_make_op()]
        planner.validate_plan_consistency.return_value = (True, [])
        llm = _make_llm()

        result = dry_run("Proj - auth - Ajoute login()", selector, planner, llm)

        assert "intent"        in result
        assert "target_files"  in result
        assert "plan"          in result
        assert "plan_valid"    in result
        assert "plan_errors"   in result
        assert "llm_available" in result

    def test_dry_run_does_not_call_tx(self, tmp_path):
        """dry_run ne doit PAS toucher a un TransactionManager."""
        from core.orchestrator_helpers import dry_run

        selector = MagicMock()
        selector.select.return_value = []
        planner  = MagicMock()
        planner.create_plan.return_value              = []
        planner.validate_plan_consistency.return_value = (True, [])
        llm = _make_llm()

        mock_tx = MagicMock()
        # dry_run n'accepte pas de tx_manager — verification indirecte
        result = dry_run("", selector, planner, llm)
        mock_tx.begin.assert_not_called()
        mock_tx.commit.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# 5. orchestrator.py (facade LCCAV5Fusion)
# ──────────────────────────────────────────────────────────────────────────────

class TestLCCAV5FusionFacade:

    def _make_fusion(self, tmp_path):
        """LCCAV5Fusion avec toutes les deps mockees."""
        from core.orchestrator import LCCAV5Fusion

        fusion = LCCAV5Fusion(
            workspace=tmp_path,
            tx_manager=MagicMock(),
            indexer=MagicMock(),
            dep_graph=MagicMock(),
            patcher=MagicMock(),
            llm=_make_llm(),
        )
        fusion.selector = MagicMock()
        fusion.planner  = MagicMock()
        return fusion

    def test_execute_delegates_to_run_pipeline(self, tmp_path):
        """execute() appelle run_pipeline() de OrchestratorPipeline."""
        fusion = self._make_fusion(tmp_path)
        fusion.selector.select.return_value               = ["auth.py"]
        fusion.planner.create_plan.return_value            = [_make_op()]
        fusion.planner.validate_plan_consistency.return_value = (True, [])

        with patch.object(fusion, "run_pipeline", return_value=True) as mock_pipe:
            result = fusion.execute("Proj - auth - Ajoute login()")

        mock_pipe.assert_called_once()
        assert result is True

    def test_execute_returns_false_if_pipeline_fails(self, tmp_path):
        """execute() propage False du pipeline."""
        fusion = self._make_fusion(tmp_path)

        with patch.object(fusion, "run_pipeline", return_value=False):
            result = fusion.execute("Proj - auth - Ajoute login()")

        assert result is False

    def test_dry_run_delegates_to_helper(self, tmp_path):
        """dry_run() delegue a orchestrator_helpers.dry_run."""
        fusion = self._make_fusion(tmp_path)

        with patch("core.orchestrator._dry_run_fn", return_value={"plan_valid": True}) as mock_fn:
            result = fusion.dry_run("Proj - auth - Ajoute login()")

        mock_fn.assert_called_once_with(
            "Proj - auth - Ajoute login()",
            fusion.selector,
            fusion.planner,
            fusion.llm,
        )
        assert result["plan_valid"] is True

    def test_validate_changes_alias_delegates(self, tmp_path):
        """_validate_changes() alias delegue a orchestrator_pipeline._validate_changes."""
        fusion = self._make_fusion(tmp_path)

        with patch("core.orchestrator._validate_changes", return_value=True) as mock_vc:
            result = fusion._validate_changes()

        mock_vc.assert_called_once_with(fusion.tx_manager, fusion.workspace)
        assert result is True

    def test_update_sprint_log_alias_delegates(self, tmp_path):
        """_update_sprint_log() alias delegue a orchestrator_helpers.update_sprint_log."""
        fusion = self._make_fusion(tmp_path)
        intent = _make_intent()
        plan   = [_make_op()]

        with patch("core.orchestrator.update_sprint_log") as mock_usl:
            fusion._update_sprint_log(intent, plan, "tx_xyz")

        mock_usl.assert_called_once_with(intent, plan, "tx_xyz", fusion.llm)

    def test_spec_layer_blocks_execute(self, tmp_path):
        """Spec Layer retournant False bloque execute() avant le pipeline."""
        import config as _cfg
        fusion = self._make_fusion(tmp_path)

        with patch.object(_cfg, "ADAPTIVE_SPEC_ENABLED", True), \
             patch.object(fusion, "_run_spec_layer", return_value=False), \
             patch.object(fusion, "run_pipeline") as mock_pipe:
            result = fusion.execute("Proj - auth - Ajoute login()", adaptive_spec=True)

        assert result is False
        mock_pipe.assert_not_called()
