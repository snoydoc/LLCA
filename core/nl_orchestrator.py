# -*- coding: utf-8-sig -*-
"""
nl_orchestrator.py — LCCA V5 Fusion
Sprint 10 — TASK-10-02

Orchestre l'exécution d'une commande en langage naturel de bout en bout :
    Phrase NL → NLParser → NLIntent → LCCAV5Fusion → Code modifié

Sprint REFACTO-01 — NLResult + NLSession extraits dans nl_types.py,
                    boucle REPL extraite dans nl_repl.py (NLRepl).
                    Rétrocompat : NLResult et NLSession restent importables depuis ce module.

Flux complet :
    1. NLParser.parse()          → NLIntent (action + fichier + symbole + confiance)
    2. NLOrchestrator._validate  → Refuse si confiance < seuil ou action inconnue
    3. NLIntent.to_dsl()         → Commande DSL compatible Sprint 04
    4. LCCAV5Fusion.execute()    → Transaction atomique (patch + validate + commit)
    5. NLResult                  → Succès / Echec + métadonnées
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import List, Optional

from core.nl_parser import NLParser
from core.orchestrator import LCCAV5Fusion

# ── Types (ré-exportés pour rétrocompat) ──────────────────────────────────
from core.nl_types import NLResult, NLSession  # noqa: F401

log = logging.getLogger("lcca.nl_orchestrator")


# ──────────────────────────────────────────────────────────────────────────────
# NLOrchestrator — Interface publique
# ──────────────────────────────────────────────────────────────────────────────

class NLOrchestrator:
    """
    Orchestre l'exécution de commandes en langage naturel.

    Connecte NLParser → LCCAV5Fusion en une seule interface.

    Args :
        project_dir    : Dossier racine du projet cible (workspace).
        nl_parser      : Instance NLParser (injection de dépendance, pour tests).
        orchestrator   : Instance LCCAV5Fusion (injection, pour tests).
        min_confidence : Seuil minimum de confiance pour exécuter (défaut 0.4).
        auto_confirm   : Si True, exécute même si confiance < seuil.
    """

    def __init__(
        self,
        project_dir:    Optional[Path] = None,
        nl_parser=None,
        orchestrator=None,
        min_confidence: float = 0.4,
        auto_confirm:   bool  = False,
    ) -> None:
        from config import WORKSPACE_DIR

        self.project_dir    = project_dir or WORKSPACE_DIR
        self.min_confidence = min_confidence
        self.auto_confirm   = auto_confirm

        self.nl_parser    = nl_parser    or NLParser()
        self.orchestrator = orchestrator or LCCAV5Fusion(workspace=self.project_dir)

        self._project_files: List[str] = self._scan_project_files()

        log.info(
            "NLOrchestrator init — projet=%s fichiers=%d min_conf=%.0f%%",
            self.project_dir, len(self._project_files), min_confidence * 100
        )

    # ── Interface publique ─────────────────────────────────────────────────────

    def run(self, command: str, dry_run: bool = False) -> NLResult:
        """
        Exécute une commande NL de bout en bout.

        Args :
            command : Commande en langage naturel.
            dry_run : Si True, simule sans écrire sur disque.

        Returns :
            NLResult avec le résultat complet.
        """
        t0 = time.monotonic()

        if not command.strip():
            return NLResult(
                success=False, command=command,
                error="Commande vide.", duration_s=0.0
            )

        # Étape 1 : NLParser → NLIntent
        log.info("NLOrchestrator.run — parse: %r", command)
        intent = self.nl_parser.parse(command, self._project_files)

        log.info(
            "Intent — action=%s file=%s symbol=%s conf=%.2f fallback=%s",
            intent.action, intent.target_file, intent.symbol,
            intent.confidence, intent.from_fallback
        )

        # Étape 2 : Validation de l'intent
        validation_error = self._validate_intent(intent)
        if validation_error:
            return NLResult(
                success       = False,
                command       = command,
                intent_action = intent.action,
                intent_file   = intent.target_file,
                intent_symbol = intent.symbol,
                confidence    = intent.confidence,
                from_fallback = intent.from_fallback,
                error         = validation_error,
                duration_s    = time.monotonic() - t0,
                dry_run       = dry_run,
            )

        # Étape 3 : NLIntent → DSL
        dsl_command = intent.to_dsl()
        log.info("DSL généré : %s", dsl_command)

        # Étape 4 : Exécution via LCCAV5Fusion
        try:
            if dry_run:
                tx_meta = self.orchestrator.dry_run(dsl_command)
                success = True
                error   = ""
            else:
                exec_result = self.orchestrator.execute(dsl_command)
                if isinstance(exec_result, dict):
                    tx_meta = exec_result
                    status = exec_result.get("status", "")
                    success = status not in ("error", "rollback", "failed") and bool(status or exec_result)
                else:
                    tx_meta = {}
                    success = bool(exec_result)
                error = "" if success else "L'execution a echoue ou a ete annulee."

        except Exception as exc:
            log.error("Erreur LCCAV5Fusion sur '%s': %s", dsl_command, exc)
            return NLResult(
                success       = False,
                command       = command,
                intent_action = intent.action,
                intent_file   = intent.target_file,
                intent_symbol = intent.symbol,
                confidence    = intent.confidence,
                from_fallback = intent.from_fallback,
                dsl_command   = dsl_command,
                error         = str(exc),
                duration_s    = time.monotonic() - t0,
                dry_run       = dry_run,
            )

        return NLResult(
            success       = success,
            command       = command,
            intent_action = intent.action,
            intent_file   = intent.target_file,
            intent_symbol = intent.symbol,
            confidence    = intent.confidence,
            from_fallback = intent.from_fallback,
            dsl_command   = dsl_command,
            error         = error,
            duration_s    = time.monotonic() - t0,
            dry_run       = dry_run,
            tx_metadata   = tx_meta if isinstance(tx_meta, dict) else {},
        )

    def dry_run(self, command: str) -> NLResult:
        """Alias pour run(command, dry_run=True)."""
        return self.run(command, dry_run=True)

    def repl(self) -> None:
        """Lance le REPL interactif (délégué à NLRepl)."""
        from core.nl_repl import NLRepl
        NLRepl(self).start()

    # ── Méthodes internes ──────────────────────────────────────────────────────

    def _validate_intent(self, intent) -> str:
        """
        Valide un NLIntent avant exécution.
        Returns : "" si valide, message d'erreur sinon.
        """
        if intent.action == "unknown":
            return (
                "Action non reconnue. Essayez : "
                "'Ajoute une fonction X', 'Modifie Y', 'Crée un fichier Z.py'"
            )

        if not intent.description.strip():
            return "Description vide — impossible d'exécuter sans description."

        if intent.confidence < self.min_confidence and not self.auto_confirm:
            return (
                f"Confiance trop faible ({intent.confidence:.0%} < {self.min_confidence:.0%}). "
                "Soyez plus précis ou utilisez auto_confirm=True."
            )

        return ""

    def _scan_project_files(self) -> List[str]:
        """Scanne le projet pour obtenir la liste des fichiers .py."""
        if not self.project_dir.exists():
            log.warning("project_dir introuvable : %s", self.project_dir)
            return []

        try:
            files = [
                str(p.relative_to(self.project_dir)).replace("\\", "/")
                for p in self.project_dir.rglob("*.py")
                if "__pycache__" not in str(p)
            ]
            return sorted(files)
        except Exception as exc:
            log.warning("Erreur scan project_dir (%s): %s", self.project_dir, exc)
            return []

    def refresh_project_files(self) -> int:
        """
        Rafraîchit la liste des fichiers du projet.
        Returns : Nombre de fichiers trouvés.
        """
        self._project_files = self._scan_project_files()
        log.info("Fichiers projet rafraîchis : %d fichiers", len(self._project_files))
        return len(self._project_files)
