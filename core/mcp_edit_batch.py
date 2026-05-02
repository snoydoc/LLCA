# -*- coding: utf-8-sig -*-
"""
mcp_edit_batch.py — LCCA V7
Sprint 12 — TASK-12-09

Façade transactionnelle MCP pour l'application atomique de patches de code.

McpEditBatch expose un point d'entrée unique `apply()` qui orchestre :
  1. Validation des arguments (MAX_FILES_PER_TX, safe_path, syntaxe)
  2. Ouverture d'une transaction via TransactionManager
  3. Génération du code modifié via SmartPatcher (retourne str, n'écrit pas)
  4. Évaluation qualité via CodeEvaluator (informatif en V1)
  5. Écriture atomique + snapshot WAL via TransactionManager.log_operation()
  6. Commit ou Rollback automatique en cas d'erreur

Règles invariantes :
  - SmartPatcher.apply_patch() retourne str uniquement, jamais n'écrit sur disque
  - MAX_FILES_PER_TX (config) hard-limit sur le nombre de fichiers
  - safe_path() obligatoire avant toute opération disque
  - Encodage utf-8-sig (Windows BOM)
  - OpType.CREATE_FILE pour les fichiers inexistants (rollback = unlink)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import MAX_FILES_PER_TX, WORKSPACE_DIR
from core.code_evaluator import CodeEvaluator
from core.smart_patcher import SmartPatcher
from core.transaction_manager import OpType, TransactionError, TransactionManager
from utils.safe_path import PathSecurityError, safe_path

log = logging.getLogger("lcca.mcp_edit_batch")

# Seuil qualité V1 — informatif, ne bloque pas.
# 80 = standard "bon code" (type hints + docstrings attendus).
_DEFAULT_QUALITY_THRESHOLD = 80


class McpEditBatch:
    """
    Façade transactionnelle pour l'outil MCP `edit_batch`.

    Applique un batch de modifications de fichiers de façon atomique
    en s'appuyant sur TransactionManager V5 (ACID + WAL + Rollback LIFO).

    Injection de dépendances (testabilité) :
        tx_manager : TransactionManager (défaut : nouvelle instance)
        patcher    : SmartPatcher (défaut : workspace=WORKSPACE_DIR)
        evaluator  : CodeEvaluator (défaut : threshold=80)
        workspace  : Path workspace (défaut : config.WORKSPACE_DIR)

    Usage typique (dans mcp_server.py) :
        batch = McpEditBatch()
        result = batch.apply([
            {
                "path": "core/my_module.py",
                "patch_type": "add_function",
                "code": "def hello():\\n    pass",
            }
        ])
        # result = {"success": True, "tx_id": "tx_...", "evaluations": [...]}
    """

    def __init__(
        self,
        tx_manager: Optional[TransactionManager] = None,
        patcher: Optional[SmartPatcher] = None,
        evaluator: Optional[CodeEvaluator] = None,
        workspace: Optional[Path] = None,
    ) -> None:
        self._workspace = workspace or WORKSPACE_DIR
        self._tx = tx_manager or TransactionManager()
        self._patcher = patcher or SmartPatcher(workspace=self._workspace)
        self._evaluator = evaluator or CodeEvaluator(threshold=_DEFAULT_QUALITY_THRESHOLD)

    # ── Entrée publique ───────────────────────────────────────────────────────

    def apply(self, files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Applique un batch de modifications de façon atomique.

        Args:
            files: Liste de dicts décrivant chaque opération.
                Champs communs :
                    path        (str, obligatoire) — chemin relatif au workspace
                    patch_type  (str)              — "add_function" | "modify_function"
                                                     | "add_import" | "create"
                    code        (str)              — code à injecter / contenu complet
                Champs optionnels :
                    symbol      (str)              — nom du symbole (pour modify_function)
                    action      (str)              — "create" pour créer un fichier absent

        Returns:
            Succès :
                {"success": True,  "tx_id": str,  "evaluations": List[dict]}
            Échec :
                {"success": False, "error": str,  "rolled_back": bool}
        """
        # ── Validation pré-transaction ────────────────────────────────────────
        pre_check = self._pre_validate(files)
        if pre_check is not None:
            return pre_check

        # ── Ouverture transaction ─────────────────────────────────────────────
        tx_id = self._tx.begin(
            dsl_input="mcp_edit_batch",
            project="lcca_v7",
            intent=f"batch_{len(files)}_files",
        )
        log.info("McpEditBatch: begin tx=%s (%d fichier(s))", tx_id, len(files))

        evaluations: List[dict] = []

        try:
            for op in files:
                self._apply_one(op, evaluations)

            # Validation syntaxe post-patch (tous les fichiers écrits)
            self._validate_batch_syntax(files)

            self._tx.commit()
            log.info("McpEditBatch: commit tx=%s", tx_id)
            return {"success": True, "tx_id": tx_id, "evaluations": evaluations}

        except (TransactionError, ValueError, SyntaxError, PathSecurityError) as exc:
            rolled_back = self._safe_rollback(str(exc))
            return {"success": False, "error": str(exc), "rolled_back": rolled_back}

        except Exception as exc:  # pragma: no cover
            rolled_back = self._safe_rollback(str(exc))
            log.exception("McpEditBatch: erreur inattendue sur tx=%s", tx_id)
            return {"success": False, "error": str(exc), "rolled_back": rolled_back}

    # ── Validation pré-transaction ─────────────────────────────────────────────

    def _pre_validate(self, files: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Vérifie les contraintes avant d'ouvrir la transaction.

        Returns:
            Dict d'erreur si invalide, None si tout est OK.
        """
        if not files:
            return {"success": False, "error": "Liste de fichiers vide", "rolled_back": False}

        if len(files) > MAX_FILES_PER_TX:
            return {
                "success": False,
                "error": (
                    f"Trop de fichiers : {len(files)} > {MAX_FILES_PER_TX} "
                    f"(MAX_FILES_PER_TX)"
                ),
                "rolled_back": False,
            }

        for op in files:
            path_str = op.get("path", "")
            if not path_str:
                return {
                    "success": False,
                    "error": "Champ 'path' manquant ou vide dans une opération",
                    "rolled_back": False,
                }

            # safe_path lève PathSecurityError si traversal / absolu / ..
            try:
                safe_path(path_str, self._workspace)
            except PathSecurityError as exc:
                return {
                    "success": False,
                    "error": str(exc),
                    "rolled_back": False,
                }

        return None

    # ── Application d'une opération ────────────────────────────────────────────

    def _apply_one(
        self,
        op: Dict[str, Any],
        evaluations: List[dict],
    ) -> None:
        """
        Applique une seule opération dans la transaction active.
        Modifie `evaluations` en place.

        Raises:
            TransactionError:  si l'écriture disque échoue.
            ValueError:        si patch_type inconnu ou args manquants.
            SyntaxError:       si le code à injecter est syntaxiquement invalide.
            PathSecurityError: si le path est hors workspace (défense en profondeur).
        """
        path_str: str = op["path"]
        full_path = safe_path(path_str, self._workspace)  # re-validation interne
        action: str = op.get("action", "patch")
        patch_type: str = op.get("patch_type", "")

        is_create = (
            action == "create"
            or patch_type == "create"
            or not full_path.exists()
        )

        if is_create:
            new_code = op.get("code", "")
            if not new_code:
                raise ValueError(f"'code' manquant pour la création de {path_str}")

            # Validation syntaxe avant écriture
            try:
                compile(new_code, path_str, "exec")
            except SyntaxError as exc:
                raise SyntaxError(
                    f"Code invalide pour la création de {path_str}: {exc}"
                ) from exc

            eval_result = self._evaluator.evaluate(new_code, filename=path_str)
            evaluations.append(eval_result.to_dict())

            def _do_create() -> None:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(new_code, encoding="utf-8-sig")

            self._tx.log_operation(
                target_path=full_path,
                op_type=OpType.CREATE_FILE,
                execute_func=_do_create,
                metadata={
                    "patch_type": "create",
                    "symbol": op.get("symbol"),
                    "quality_score": eval_result.score,
                },
            )

        else:
            # Modification d'un fichier existant via SmartPatcher
            if not patch_type:
                raise ValueError(
                    f"Champ 'patch_type' manquant pour la modification de {path_str}"
                )

            # Construire les kwargs pour SmartPatcher
            patch_kwargs: Dict[str, Any] = {}
            if "code" in op:
                patch_kwargs["code"] = op["code"]
            if "symbol" in op:
                # modify_function attend 'name', add_function n'en a pas besoin
                patch_kwargs["name"] = op["symbol"]
            if "preserve_docstring" in op:
                patch_kwargs["preserve_docstring"] = op["preserve_docstring"]
            if "module" in op:
                patch_kwargs["module"] = op["module"]
            if "names" in op:
                patch_kwargs["names"] = op["names"]

            # SmartPatcher retourne str, n'écrit PAS sur disque
            new_code = self._patcher.apply_patch(
                file_path=path_str,
                patch_type=patch_type,
                **patch_kwargs,
            )

            eval_result = self._evaluator.evaluate(new_code, filename=path_str)
            evaluations.append(eval_result.to_dict())

            # V1 informatif : on logue le score sans bloquer
            if not eval_result.passed:
                log.warning(
                    "McpEditBatch: qualité insuffisante %s (score=%d/%d)",
                    path_str,
                    eval_result.score,
                    eval_result.threshold,
                )

            def _do_write() -> None:
                full_path.write_text(new_code, encoding="utf-8-sig")

            self._tx.log_operation(
                target_path=full_path,
                op_type=OpType.PATCH_FILE,
                execute_func=_do_write,
                metadata={
                    "patch_type": patch_type,
                    "symbol": op.get("symbol"),
                    "quality_score": eval_result.score,
                },
            )

    # ── Validation syntaxe post-patch ──────────────────────────────────────────

    def _validate_batch_syntax(self, files: List[Dict[str, Any]]) -> None:
        """
        Re-lit chaque fichier modifié et compile() pour détecter toute
        corruption de syntaxe introduite par le patch.

        Raises:
            SyntaxError: si un fichier résultant est syntaxiquement invalide.
        """
        for op in files:
            full_path = safe_path(op["path"], self._workspace)
            if not full_path.exists():
                continue  # CREATE_FILE peut avoir rollbacké avant cet appel
            source = full_path.read_text(encoding="utf-8-sig")
            compile(source, op["path"], "exec")

    # ── Rollback sécurisé ─────────────────────────────────────────────────────

    def _safe_rollback(self, reason: str) -> bool:
        """
        Tente un rollback sans lever d'exception.

        Returns:
            True si rollback réussi, False si la transaction était déjà fermée.
        """
        try:
            self._tx.rollback(reason=reason)
            log.warning("McpEditBatch: rollback — %s", reason)
            return True
        except RuntimeError:
            # Aucune transaction active (déjà commitée ou non ouverte)
            return False
