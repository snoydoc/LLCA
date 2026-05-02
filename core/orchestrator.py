# -*- coding: utf-8-sig -*-
"""
orchestrator.py — LCCA V5 Fusion (façade légère — REFACTO-18)
Sprint 04 — TASK-04-04 + TASK-04-05
Sprint 09 — Intégration LLMGenerator (Ollama)
Sprint 15 — Intégration Spec Layer adaptative
Sprint 19 — Dette 16 : f-strings dans log.* remplacés par lazy %s formatting
Sprint 22 — Migration V7.2 : _run_spec_layer() dict V7.2, domain propagé.
REFACTO-01 — _run_spec_layer() extraite vers OrchestratorSpecMixin.
REFACTO-18 — Pipeline TX/LLM/Patch → orchestrator_pipeline.py (OrchestratorPipeline)
             Helpers sprint_log + dry_run → orchestrator_helpers.py
             orchestrator.py : façade pure (~5 KB), délègue aux sous-modules.

Classe principale : LCCAV5Fusion (hérite OrchestratorSpecMixin)
Alias legacy    : Orchestrator (rétrocompatibilité Sprint 01)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from core.orchestrator_spec    import OrchestratorSpecMixin
from core.orchestrator_pipeline import OrchestratorPipeline, _validate_changes  # noqa: F401 rétrocompat
from core.orchestrator_helpers  import update_sprint_log, dry_run as _dry_run_fn  # noqa: F401

log = logging.getLogger("lcca.orchestrator")


# ──────────────────────────────────────────────────────────────────────────────
# LCCAV5Fusion — Orchestrateur principal
# ──────────────────────────────────────────────────────────────────────────────

class LCCAV5Fusion(OrchestratorSpecMixin, OrchestratorPipeline):
    """
    Orchestre l'exécution complète d'une commande LCCA.

    Flux :
        0. [Sprint 15] Spec Layer adaptative (si adaptive_spec=True)
        1. DSLParser     → Intent structuré
        2. FileSelector  → Fichiers cibles (max 3)
        3. MultiFilePlanner → Plan d'opérations ordonné
        4. TransactionManager → BEGIN + snapshots
        5. LLMGenerator  → Code via Ollama (ou stub si indisponible)
        6. SmartPatcher  → Patches libcst
        7. _validate_changes() → Syntaxe Python vérifiée
        8. COMMIT (ou ROLLBACK si erreur)
        9. Re-indexation AST + log sprint
    """

    def __init__(
        self,
        workspace: Optional[Path] = None,
        tx_manager=None,
        indexer=None,
        dep_graph=None,
        patcher=None,
        llm=None,
        memory_engine=None,
        complexity_estimator=None,
        spec_generator=None,
        spec_validator=None,
    ) -> None:
        from config import WORKSPACE_DIR, TRANSACTIONS_DIR
        from core.transaction_manager import TransactionManager
        from core.ast_indexer import ASTIndexer
        from core.dependency_graph import DependencyGraph
        from core.smart_patcher import SmartPatcher
        from core.file_selector import FileSelector
        from core.planner import MultiFilePlanner
        from core.llm_generator import LLMGenerator

        self.workspace: Path = workspace or WORKSPACE_DIR

        self.tx_manager = tx_manager or TransactionManager(TRANSACTIONS_DIR)
        self.indexer    = indexer    or ASTIndexer(self.workspace)
        self.dep_graph  = dep_graph  or DependencyGraph()
        self.patcher    = patcher    or SmartPatcher()
        self.llm        = llm        or LLMGenerator()

        self.selector = FileSelector(self.indexer, self.dep_graph, self.workspace)
        self.planner  = MultiFilePlanner()

        # Sprint 15 — Spec Layer (injection optionnelle, instanciation lazy)
        self._memory             = memory_engine
        self._complexity         = complexity_estimator
        self._spec_generator     = spec_generator
        self._spec_validator     = spec_validator

        # Index initial du workspace (idempotent si vide)
        try:
            self.indexer.index_repository()
            self.dep_graph.build(self.indexer.files)
        except Exception as exc:
            log.warning("Index initial impossible (workspace vide ?): %s", exc)

        if self.llm.is_available():
            log.info(
                "LCCAV5Fusion initialisé — workspace: %s, %d fichier(s) indexé(s), "
                "Ollama disponible (model=%s)",
                self.workspace,
                len(self.indexer.files),
                self.llm.ollama.model,
            )
        else:
            log.warning(
                "LCCAV5Fusion initialisé — workspace: %s, %d fichier(s) indexé(s), "
                "Ollama INDISPONIBLE → mode stub",
                self.workspace,
                len(self.indexer.files),
            )

    # ── Exécution principale ──────────────────────────────────────────────────

    def execute(
        self,
        command: str,
        auto_rollback: bool = True,
        adaptive_spec: bool = True,
    ) -> bool:
        """
        Exécute une commande DSL complète.

        Phases 1-2 : Parse + Spec Layer (ici).
        Phases 3-9 : déléguées à OrchestratorPipeline.run_pipeline() — REFACTO-18.

        Args:
            command:       Commande utilisateur.
            auto_rollback: Si True, rollback automatique en cas d'erreur.
            adaptive_spec: Si True, active la Spec Layer (Sprint 15).

        Returns:
            True si la commande a été exécutée et commitée avec succès.
        """
        from core.dsl_parser import DSLParser
        import config as _config

        log.info("EXECUTE: %r", command)

        # ── Phase 1 : Parse ───────────────────────────────────────────────────
        intent = DSLParser().parse(command)
        log.info("Intent: %s", intent.summary())

        if not intent.is_confident():
            log.warning(
                "Confidence faible (%.0f%%) pour: %r. Procede quand meme.",
                intent.confidence * 100,
                command,
            )

        # ── Phase 2 : Spec Layer adaptative (Sprint 15) ───────────────────────
        if adaptive_spec and getattr(_config, "ADAPTIVE_SPEC_ENABLED", False):
            spec_ok = self._run_spec_layer(intent)
            if not spec_ok:
                log.error("Spec Layer a bloque l'execution.")
                return False

        # ── Phases 3-9 : pipeline V5 core (OrchestratorPipeline) ─────────────
        ok = self.run_pipeline(
            intent=intent,
            tx_manager=self.tx_manager,
            workspace=self.workspace,
            llm=self.llm,
            patcher=self.patcher,
            indexer=self.indexer,
            dep_graph=self.dep_graph,
            planner=self.planner,
            selector=self.selector,
            auto_rollback=auto_rollback,
        )

        if ok:
            # Re-lecture du plan depuis le TX log pour le sprint_log
            try:
                ops = self.tx_manager.current_tx.operations if self.tx_manager.current_tx else []
            except Exception:
                ops = []
            update_sprint_log(intent, ops, getattr(self.tx_manager, "_last_tx_id", "unknown"), self.llm)

        return ok

    # ── dry_run ───────────────────────────────────────────────────────────────

    def dry_run(self, command: str) -> dict:
        """Simule l'execution sans toucher au disque — délégué à orchestrator_helpers."""
        return _dry_run_fn(command, self.selector, self.planner, self.llm)

    # ── Aliases rétrocompat méthodes internes ─────────────────────────────────

    def _validate_changes(self) -> bool:
        """Alias rétrocompat — délégué à orchestrator_pipeline._validate_changes."""
        return _validate_changes(self.tx_manager, self.workspace)

    def _update_sprint_log(self, intent, plan: list, tx_id: str) -> None:
        """Alias rétrocompat — délégué à orchestrator_helpers.update_sprint_log."""
        update_sprint_log(intent, plan, tx_id, self.llm)


# ──────────────────────────────────────────────────────────────────────────────
# Alias rétrocompatibilité → orchestrator_compat.py (Sprint REFACTO-01)
# ──────────────────────────────────────────────────────────────────────────────
# L'alias Orchestrator est défini dans orchestrator_compat.py.
# `from core.orchestrator import Orchestrator` fonctionne via orchestrator_compat.
from core.orchestrator_compat import Orchestrator  # noqa: F401  (rétrocompat)
