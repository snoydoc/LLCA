# -*- coding: utf-8-sig -*-
"""
orchestrator_medi.py — LCCA V5 Fusion
Sprint 08 — TASK-08-02

Orchestrateur spécialisé MediBot.
Sous-classe de LCCAV5Fusion pré-configurée pour travailler sur D:\\MediBot.

Usage :
    orchestrator = MediBotOrchestrator()
    orchestrator.execute("DashboardV1 - rdv - Ajoute export_pdf()")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("lcca.orchestrator_medi")

# Chemin par défaut du projet MediBot
MEDI_WORKSPACE_DEFAULT = Path(r"D:\MediBot")


class MediBotOrchestrator:
    """
    Orchestrateur spécialisé MediBot.

    Initialisation automatique :
        1. Connexion au MemPalace MediBot existant
        2. Workspace = D:\\MediBot (code cible)
        3. Indexation du code MediBot au démarrage
        4. Recovery des transactions incomplètes

    Enrichissement contexte :
        Chaque execute() injecte les specs MediBot pertinentes dans le
        contexte de l'intent pour améliorer le stub généré.

    Args:
        workspace: Chemin du projet MediBot (défaut: D:\\MediBot).

    Raises:
        FileNotFoundError: Si le workspace MediBot n'existe pas.
    """

    def __init__(self, workspace: Optional[Path] = None) -> None:
        from core.mempalace_adapter import ExistingMemPalaceAdapter
        from core.orchestrator import LCCAV5Fusion
        from core.transaction_manager import TransactionManager
        from core.ast_indexer import ASTIndexer
        from core.dependency_graph import DependencyGraph
        from core.smart_patcher import SmartPatcher
        from core.file_selector import FileSelector
        from core.planner import MultiFilePlanner
        from core.recovery_service import RecoveryService

        self.workspace: Path = workspace or MEDI_WORKSPACE_DEFAULT

        if not self.workspace.exists():
            raise FileNotFoundError(
                f"MediBotOrchestrator: workspace introuvable — {self.workspace}\n"
                "Vérifiez que D:\\MediBot est présent sur ce poste."
            )

        log.info("MediBotOrchestrator: démarrage sur %s", self.workspace)

        # 1. Connexion au palace existant (silencieux si absent)
        self.palace = ExistingMemPalaceAdapter()
        if self.palace.is_available:
            log.info("MemPalace MediBot connecté : %s", self.palace.palace_path)
        else:
            log.warning("MemPalace MediBot non trouvé — fonctionnement dégradé")

        # 2. Composants avec workspace MediBot
        tx_dir = self.workspace / ".lcca_transactions"
        self.tx_manager = TransactionManager(tx_dir=tx_dir)
        self.indexer    = ASTIndexer(self.workspace)
        self.dep_graph  = DependencyGraph()
        self.patcher    = SmartPatcher()
        self.selector   = FileSelector(self.indexer, self.dep_graph, self.workspace)
        self.planner    = MultiFilePlanner()
        self.recovery   = RecoveryService(self.tx_manager)

        # 3. Chargement contexte MediBot
        self.medi_context = self.palace.wake_up_medi()
        log.debug("Contexte MediBot : %d spec(s)", len(self.palace.specs))

        # 4. Indexation du code MediBot
        log.info("Indexation workspace MediBot: %s", self.workspace)
        try:
            self.indexer.index_repository()
            self.dep_graph.build(self.indexer.files)
            log.info(
                "Indexation terminée : %d fichier(s), %d symbole(s)",
                len(self.indexer.files),
                len(self.indexer.symbols_table),
            )
        except Exception as exc:
            log.warning("Indexation partielle : %s", exc)

        # 5. Recovery au démarrage
        try:
            orphans = self.recovery.boot_check()
            if orphans:
                log.warning("%d transaction(s) orpheline(s) détectée(s)", len(orphans))
                self.recovery.auto_recover_pending(orphans)
        except Exception as exc:
            log.warning("Recovery impossible : %s", exc)

    # ── Interface principale ──────────────────────────────────────────────────

    def execute(self, command: str, auto_rollback: bool = True) -> bool:
        """
        Exécute une commande DSL sur le code MediBot, enrichie du contexte palace.

        Args:
            command:       Commande DSL (ex: "DashV1 - rdv - Ajoute export_pdf()").
            auto_rollback: Rollback auto en cas d'erreur (défaut: True).

        Returns:
            True si exécution et commit réussis.
        """
        from core.dsl_parser import DSLParser
        from core.transaction_manager import OpType

        log.info("▶ MEDI EXECUTE: %r", command)

        try:
            # Parse + enrichissement contexte
            intent = DSLParser().parse(command)
            context_hint = self._enrich_with_medi_context(intent)
            if context_hint:
                log.info("Contexte MediBot injecté :\n%s", context_hint)

            # Délègue l'exécution au flux standard via _fusion (lazy)
            fusion = self._get_fusion()
            return fusion.execute(command, auto_rollback=auto_rollback)

        except Exception as exc:
            log.error("❌ MediBotOrchestrator.execute error : %s", exc, exc_info=True)
            return False

    def dry_run(self, command: str) -> dict:
        """Simulation sans modification de fichiers."""
        return self._get_fusion().dry_run(command)

    def status(self) -> dict:
        """
        Retourne les statistiques courantes du workspace MediBot.

        Returns:
            Dict avec n_files, n_symbols, palace_available, specs_loaded.
        """
        return {
            "workspace": str(self.workspace),
            "n_files": len(self.indexer.files),
            "n_symbols": len(self.indexer.symbols_table),
            "palace_available": self.palace.is_available,
            "palace_path": str(self.palace.palace_path) if self.palace.is_available else None,
            "specs_loaded": len(self.palace.specs),
            "lcca_collections": list(self.palace.lcca_collections.keys()),
        }

    # ── Enrichissement contexte ───────────────────────────────────────────────

    def _enrich_with_medi_context(self, intent) -> str:
        """
        Retourne les specs MediBot pertinentes pour l'intent courant.

        Args:
            intent: Intent parsé (DSLParser).

        Returns:
            Chaîne "[spec_name]: extrait…" ou chaîne vide.
        """
        keywords = [
            w for w in [
                getattr(intent, "target", ""),
                getattr(intent, "sub_target", ""),
                getattr(intent, "details", ""),
            ]
            if w
        ]
        return self.palace.find_relevant_specs(keywords, max_specs=2)

    # ── Fusion lazy ───────────────────────────────────────────────────────────

    def _get_fusion(self):
        """Lazy init LCCAV5Fusion partagé (même workspace + tx_manager)."""
        if not hasattr(self, "_fusion") or self._fusion is None:
            from core.orchestrator import LCCAV5Fusion
            self._fusion = LCCAV5Fusion(
                workspace=self.workspace,
                tx_manager=self.tx_manager,
                indexer=self.indexer,
                dep_graph=self.dep_graph,
                patcher=self.patcher,
            )
        return self._fusion
