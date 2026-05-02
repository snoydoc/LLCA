# -*- coding: utf-8-sig -*-
"""
test_mcp_edit_batch.py — LCCA V7
Sprint 12 — TASK-12-09

Tests unitaires pour McpEditBatch (façade transactionnelle MCP).

Stratégie :
  - Injection de dépendances via MagicMock (tx_manager, patcher, evaluator)
  - Tests workspace réels via tmp_path (pytest fixture)
  - Couverture : validation pré-TX, CREATE_FILE, PATCH_FILE, rollback, sécurité
  - Pattern : jamais instancier ExistingMemPalaceAdapter en test (FS dépendant)

Suite : 28 tests
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from core.mcp_edit_batch import McpEditBatch
from core.transaction_manager import OpType, TransactionError, TransactionManager
from utils.safe_path import PathSecurityError


# ──────────────────────────────────────────────────────────────────────────────
# Helpers & fixtures
# ──────────────────────────────────────────────────────────────────────────────

_SIMPLE_MODULE = '''\
"""Module minimal."""


def hello() -> str:
    """Retourne un salut."""
    return "hello"
'''


def _make_batch(tmp_path: Path, **overrides) -> McpEditBatch:
    """
    Crée un McpEditBatch avec des vraies dépendances (pour tests réels).
    Le workspace est tmp_path.
    """
    return McpEditBatch(workspace=tmp_path, **overrides)


def _make_batch_mocked(tmp_path: Path) -> tuple[McpEditBatch, MagicMock, MagicMock, MagicMock]:
    """
    Crée un McpEditBatch avec tx_manager, patcher et evaluator mockés.
    Retourne (batch, mock_tx, mock_patcher, mock_evaluator).
    """
    mock_tx = MagicMock(spec=TransactionManager)
    mock_tx.begin.return_value = "tx_test123"
    mock_tx.commit.return_value = "tx_test123"

    mock_patcher = MagicMock()
    mock_patcher.apply_patch.return_value = _SIMPLE_MODULE

    mock_eval = MagicMock()
    mock_eval_result = MagicMock()
    mock_eval_result.score = 75
    mock_eval_result.threshold = 60
    mock_eval_result.passed = True
    mock_eval_result.to_dict.return_value = {"score": 75, "passed": True}
    mock_eval.evaluate.return_value = mock_eval_result

    batch = McpEditBatch(
        tx_manager=mock_tx,
        patcher=mock_patcher,
        evaluator=mock_eval,
        workspace=tmp_path,
    )
    return batch, mock_tx, mock_patcher, mock_eval


# ──────────────────────────────────────────────────────────────────────────────
# 1. Constructeur & injection de dépendances
# ──────────────────────────────────────────────────────────────────────────────

class TestMcpEditBatchConstructor:

    def test_defaults_instantiate(self, tmp_path: Path) -> None:
        """Instanciation sans args ne doit pas lever d'exception."""
        batch = McpEditBatch(workspace=tmp_path)
        assert batch._workspace == tmp_path

    def test_injection_overrides(self, tmp_path: Path) -> None:
        """Les dépendances injectées sont utilisées."""
        mock_tx = MagicMock(spec=TransactionManager)
        mock_tx.begin.return_value = "tx_inject"
        mock_patcher = MagicMock()
        mock_eval = MagicMock()

        batch = McpEditBatch(
            tx_manager=mock_tx,
            patcher=mock_patcher,
            evaluator=mock_eval,
            workspace=tmp_path,
        )
        assert batch._tx is mock_tx
        assert batch._patcher is mock_patcher
        assert batch._evaluator is mock_eval


# ──────────────────────────────────────────────────────────────────────────────
# 2. Validation pré-transaction (_pre_validate)
# ──────────────────────────────────────────────────────────────────────────────

class TestPreValidate:

    def test_empty_list_rejected(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        result = batch.apply([])
        assert result["success"] is False
        assert "vide" in result["error"]
        assert result["rolled_back"] is False

    def test_too_many_files_rejected(self, tmp_path: Path) -> None:
        """MAX_FILES_PER_TX = 3 par défaut."""
        batch = _make_batch(tmp_path)
        files = [{"path": f"file{i}.py", "patch_type": "add_function", "code": "def f(): pass"} for i in range(4)]
        result = batch.apply(files)
        assert result["success"] is False
        assert "Trop de fichiers" in result["error"]
        assert result["rolled_back"] is False

    def test_missing_path_field_rejected(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        result = batch.apply([{"patch_type": "add_function", "code": "def f(): pass"}])
        assert result["success"] is False
        assert "'path'" in result["error"]

    def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        result = batch.apply([{"path": "../../../etc/passwd", "patch_type": "add_function", "code": "x=1"}])
        assert result["success"] is False
        assert result["rolled_back"] is False

    def test_absolute_path_rejected(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        result = batch.apply([{"path": "/etc/passwd", "patch_type": "add_function", "code": "x=1"}])
        assert result["success"] is False
        assert result["rolled_back"] is False

    def test_valid_single_file_passes_prevalidation(self, tmp_path: Path) -> None:
        """Un fichier valide ne doit pas être rejeté à la pré-validation."""
        # Le fichier n'existe pas encore → sera une création
        batch, mock_tx, mock_patcher, mock_eval = _make_batch_mocked(tmp_path)
        # On simule un commit réussi (aucune exception)
        mock_tx.commit.return_value = "tx_test123"
        # On crée un fichier factice pour éviter CREATE_FILE path
        target = tmp_path / "mod.py"
        target.write_text(_SIMPLE_MODULE, encoding="utf-8-sig")
        # Test : la validation passe (pas d'erreur pré-TX)
        pre = batch._pre_validate([{"path": "mod.py", "patch_type": "add_function", "code": "def g(): pass"}])
        assert pre is None


# ──────────────────────────────────────────────────────────────────────────────
# 3. CREATE_FILE — création de fichiers inexistants
# ──────────────────────────────────────────────────────────────────────────────

class TestCreateFile:

    def test_create_new_file_success(self, tmp_path: Path) -> None:
        """Crée un nouveau fichier Python via action='create'."""
        batch = _make_batch(tmp_path)
        new_code = 'def greet() -> str:\n    """Salut."""\n    return "hi"\n'
        result = batch.apply([
            {"path": "new_module.py", "action": "create", "code": new_code}
        ])
        assert result["success"] is True, result.get("error")
        assert (tmp_path / "new_module.py").exists()
        content = (tmp_path / "new_module.py").read_text(encoding="utf-8-sig")
        assert "def greet" in content

    def test_create_missing_code_fails(self, tmp_path: Path) -> None:
        """CREATE_FILE sans 'code' doit échouer avec rollback."""
        batch = _make_batch(tmp_path)
        result = batch.apply([
            {"path": "empty.py", "action": "create"}
        ])
        assert result["success"] is False
        assert "code" in result["error"]
        assert result["rolled_back"] is True

    def test_create_invalid_syntax_fails(self, tmp_path: Path) -> None:
        """CREATE_FILE avec syntaxe invalide doit échouer avec rollback."""
        batch = _make_batch(tmp_path)
        result = batch.apply([
            {"path": "bad.py", "action": "create", "code": "def broken(:\n    pass\n"}
        ])
        assert result["success"] is False
        assert result["rolled_back"] is True

    def test_create_file_uses_create_file_optype(self, tmp_path: Path) -> None:
        """log_operation doit être appelé avec OpType.CREATE_FILE."""
        batch, mock_tx, _, _ = _make_batch_mocked(tmp_path)
        new_code = 'x = 1\n'
        batch.apply([{"path": "new.py", "action": "create", "code": new_code}])
        # Vérifie que log_operation a été appelé avec CREATE_FILE
        call_args = mock_tx.log_operation.call_args
        assert call_args is not None
        assert call_args.kwargs.get("op_type") == OpType.CREATE_FILE

    def test_create_file_rollback_removes_file(self, tmp_path: Path) -> None:
        """Après rollback d'un CREATE_FILE, le fichier ne doit plus exister."""
        batch = _make_batch(tmp_path)
        target = tmp_path / "will_be_deleted.py"
        assert not target.exists()

        # On provoque un rollback en créant un 2e fichier avec syntaxe invalide
        result = batch.apply([
            {"path": "will_be_deleted.py", "action": "create", "code": "x = 1\n"},
            {"path": "bad2.py", "action": "create", "code": "def broken(:\n    pass\n"},
        ])
        assert result["success"] is False
        assert result["rolled_back"] is True
        # Le 1er fichier doit avoir été supprimé par le rollback
        assert not target.exists()

    def test_create_evaluates_code(self, tmp_path: Path) -> None:
        """L'évaluation qualité est incluse dans les résultats."""
        batch = _make_batch(tmp_path)
        new_code = 'def greet() -> str:\n    """Say hi."""\n    return "hi"\n'
        result = batch.apply([
            {"path": "eval_test.py", "action": "create", "code": new_code}
        ])
        assert result["success"] is True
        assert len(result["evaluations"]) == 1
        assert "score" in result["evaluations"][0]


# ──────────────────────────────────────────────────────────────────────────────
# 4. PATCH_FILE — modification de fichiers existants
# ──────────────────────────────────────────────────────────────────────────────

class TestPatchFile:

    def test_add_function_to_existing_file(self, tmp_path: Path) -> None:
        """Ajoute une fonction à un fichier existant via SmartPatcher réel."""
        target = tmp_path / "mod.py"
        target.write_text(_SIMPLE_MODULE, encoding="utf-8-sig")

        batch = _make_batch(tmp_path)
        result = batch.apply([
            {
                "path": "mod.py",
                "patch_type": "add_function",
                "code": "def farewell() -> str:\n    return 'bye'\n",
            }
        ])
        assert result["success"] is True, result.get("error")
        content = target.read_text(encoding="utf-8-sig")
        assert "def farewell" in content
        assert "def hello" in content  # Fonction originale conservée

    def test_patch_file_uses_patch_file_optype(self, tmp_path: Path) -> None:
        """log_operation doit être appelé avec OpType.PATCH_FILE."""
        batch, mock_tx, mock_patcher, _ = _make_batch_mocked(tmp_path)
        # Fichier existant (simulé via patcher mock)
        target = tmp_path / "existing.py"
        target.write_text(_SIMPLE_MODULE, encoding="utf-8-sig")

        batch.apply([
            {"path": "existing.py", "patch_type": "add_function", "code": "def g(): pass"}
        ])
        call_args = mock_tx.log_operation.call_args
        assert call_args is not None
        assert call_args.kwargs.get("op_type") == OpType.PATCH_FILE

    def test_patch_missing_patch_type_fails(self, tmp_path: Path) -> None:
        """Un fichier existant sans patch_type doit échouer."""
        target = tmp_path / "existing.py"
        target.write_text(_SIMPLE_MODULE, encoding="utf-8-sig")

        batch = _make_batch(tmp_path)
        result = batch.apply([{"path": "existing.py"}])
        assert result["success"] is False
        assert "patch_type" in result["error"]

    def test_patch_calls_patcher_apply_patch(self, tmp_path: Path) -> None:
        """SmartPatcher.apply_patch() doit être appelé avec les bons args."""
        batch, mock_tx, mock_patcher, _ = _make_batch_mocked(tmp_path)
        target = tmp_path / "module.py"
        target.write_text(_SIMPLE_MODULE, encoding="utf-8-sig")

        batch.apply([
            {"path": "module.py", "patch_type": "add_function", "code": "def g(): pass"}
        ])
        mock_patcher.apply_patch.assert_called_once_with(
            file_path="module.py",
            patch_type="add_function",
            code="def g(): pass",
        )

    def test_patch_symbol_kwarg_passed_as_name(self, tmp_path: Path) -> None:
        """Le champ 'symbol' doit être transmis comme kwarg 'name' au patcher."""
        batch, mock_tx, mock_patcher, _ = _make_batch_mocked(tmp_path)
        target = tmp_path / "module.py"
        target.write_text(_SIMPLE_MODULE, encoding="utf-8-sig")

        batch.apply([
            {
                "path": "module.py",
                "patch_type": "modify_function",
                "symbol": "hello",
                "code": "    return 'modified'\n",
            }
        ])
        call_kwargs = mock_patcher.apply_patch.call_args.kwargs
        assert call_kwargs["name"] == "hello"

    def test_patch_evaluations_returned(self, tmp_path: Path) -> None:
        """Les évaluations sont incluses dans le résultat du batch."""
        target = tmp_path / "mod.py"
        target.write_text(_SIMPLE_MODULE, encoding="utf-8-sig")

        batch = _make_batch(tmp_path)
        result = batch.apply([
            {
                "path": "mod.py",
                "patch_type": "add_function",
                "code": "def g() -> None:\n    pass\n",
            }
        ])
        assert result["success"] is True
        assert len(result["evaluations"]) == 1
        assert "score" in result["evaluations"][0]

    def test_patch_rollback_on_tx_error(self, tmp_path: Path) -> None:
        """Un TransactionError dans log_operation déclenche le rollback."""
        batch, mock_tx, mock_patcher, _ = _make_batch_mocked(tmp_path)
        mock_tx.log_operation.side_effect = TransactionError("Disk fail")

        target = tmp_path / "mod.py"
        target.write_text(_SIMPLE_MODULE, encoding="utf-8-sig")

        result = batch.apply([
            {"path": "mod.py", "patch_type": "add_function", "code": "def g(): pass"}
        ])
        assert result["success"] is False
        assert "Disk fail" in result["error"]
        assert result["rolled_back"] is True
        mock_tx.rollback.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# 5. Transactions — flux nominal & rollback
# ──────────────────────────────────────────────────────────────────────────────

class TestTransactionFlow:

    def test_begin_and_commit_called(self, tmp_path: Path) -> None:
        """begin() et commit() doivent être appelés exactement une fois."""
        batch, mock_tx, _, _ = _make_batch_mocked(tmp_path)
        target = tmp_path / "mod.py"
        target.write_text(_SIMPLE_MODULE, encoding="utf-8-sig")

        batch.apply([{"path": "mod.py", "patch_type": "add_function", "code": "def g(): pass"}])
        mock_tx.begin.assert_called_once()
        mock_tx.commit.assert_called_once()
        mock_tx.rollback.assert_not_called()

    def test_tx_id_returned_on_success(self, tmp_path: Path) -> None:
        """Le tx_id retourné par begin() est inclus dans le résultat."""
        batch, mock_tx, _, _ = _make_batch_mocked(tmp_path)
        mock_tx.begin.return_value = "tx_abc123"
        target = tmp_path / "mod.py"
        target.write_text(_SIMPLE_MODULE, encoding="utf-8-sig")

        result = batch.apply([{"path": "mod.py", "patch_type": "add_function", "code": "def g(): pass"}])
        assert result["tx_id"] == "tx_abc123"

    def test_rollback_called_on_patcher_error(self, tmp_path: Path) -> None:
        """Une ValueError du patcher déclenche le rollback."""
        batch, mock_tx, mock_patcher, _ = _make_batch_mocked(tmp_path)
        mock_patcher.apply_patch.side_effect = ValueError("fonction introuvable")
        target = tmp_path / "mod.py"
        target.write_text(_SIMPLE_MODULE, encoding="utf-8-sig")

        result = batch.apply([{"path": "mod.py", "patch_type": "modify_function", "symbol": "ghost", "code": "pass"}])
        assert result["success"] is False
        mock_tx.rollback.assert_called_once()

    def test_multiple_files_in_batch(self, tmp_path: Path) -> None:
        """Deux fichiers dans un batch : les deux sont créés."""
        batch = _make_batch(tmp_path)
        result = batch.apply([
            {"path": "a.py", "action": "create", "code": "x = 1\n"},
            {"path": "b.py", "action": "create", "code": "y = 2\n"},
        ])
        assert result["success"] is True
        assert (tmp_path / "a.py").exists()
        assert (tmp_path / "b.py").exists()
        assert len(result["evaluations"]) == 2


# ──────────────────────────────────────────────────────────────────────────────
# 6. Sécurité — safe_path dans _apply_one
# ──────────────────────────────────────────────────────────────────────────────

class TestSecurity:

    def test_path_traversal_in_apply_fails(self, tmp_path: Path) -> None:
        """Path traversal dans apply() doit être bloqué avant la TX."""
        batch = _make_batch(tmp_path)
        result = batch.apply([
            {"path": "../../../etc/passwd", "action": "create", "code": "x=1"}
        ])
        assert result["success"] is False

    def test_absolute_path_in_apply_fails(self, tmp_path: Path) -> None:
        """Chemin absolu dans apply() doit être bloqué avant la TX."""
        batch = _make_batch(tmp_path)
        result = batch.apply([
            {"path": "/tmp/evil.py", "action": "create", "code": "x=1"}
        ])
        assert result["success"] is False

    def test_dotdot_in_path_rejected(self, tmp_path: Path) -> None:
        """Path avec '..' doit être rejeté."""
        batch = _make_batch(tmp_path)
        result = batch.apply([
            {"path": "subdir/../../../etc/passwd", "action": "create", "code": "x=1"}
        ])
        assert result["success"] is False


# ──────────────────────────────────────────────────────────────────────────────
# 7. Qualité — évaluation informatique (V1)
# ──────────────────────────────────────────────────────────────────────────────

class TestQualityEvaluation:

    def test_low_quality_does_not_block_v1(self, tmp_path: Path) -> None:
        """En V1, un score insuffisant ne bloque PAS le patch."""
        batch = _make_batch(tmp_path)
        # Code fonctionnel mais sans type hints ni docstrings → score < 60
        minimal_code = (
            "def bad_func(a, b):\n"
            "    if a:\n"
            "        if b:\n"
            "            if a > 0:\n"
            "                if b > 0:\n"
            "                    if a > b:\n"
            "                        if b > 1:\n"
            "                            return a\n"
            "    return b\n"
        )
        result = batch.apply([
            {"path": "minimal.py", "action": "create", "code": minimal_code}
        ])
        # V1 informatif : le patch passe quand même
        assert result["success"] is True
        assert result["evaluations"][0]["score"] < result["evaluations"][0]["threshold"]
        assert (tmp_path / "minimal.py").exists()

    def test_evaluation_dict_contains_required_fields(self, tmp_path: Path) -> None:
        """Le dict d'évaluation doit contenir les champs attendus."""
        batch = _make_batch(tmp_path)
        new_code = 'def f() -> int:\n    """Docs."""\n    return 1\n'
        result = batch.apply([{"path": "q.py", "action": "create", "code": new_code}])
        assert result["success"] is True
        ev = result["evaluations"][0]
        for field in ("score", "passed", "filename", "threshold"):
            assert field in ev, f"Champ manquant: {field}"
