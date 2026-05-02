# -*- coding: utf-8-sig -*-
"""
nl_types.py — Dataclasses NLResult et NLSession (Sprint REFACTO-01).

Zéro dépendance réseau, zéro import de modules core.
Importé par nl_orchestrator.py et nl_repl.py.

Rétrocompatibilité : NLResult et NLSession sont ré-exportés depuis nl_orchestrator.py,
donc les imports existants continuent de fonctionner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class NLResult:
    """
    Résultat structuré d'une commande NL exécutée par NLOrchestrator.

    Champs :
        success        : True si la modification a été commitée
        command        : Commande NL originale
        intent_action  : Action détectée (add_function, modify_function, ...)
        intent_file    : Fichier cible détecté (peut être None)
        intent_symbol  : Symbole cible (peut être None)
        confidence     : Confiance du NLParser (0.0 à 1.0)
        from_fallback  : True si le NLParser a utilisé l'heuristique
        dsl_command    : Commande DSL générée et envoyée à LCCAV5Fusion
        error          : Message d'erreur si success=False
        duration_s     : Durée totale d'exécution en secondes
        dry_run        : True si exécution simulée (pas d'écriture disque)
        tx_metadata    : Métadonnées de la transaction (si success)
    """
    success:       bool
    command:       str
    intent_action: str           = "unknown"
    intent_file:   Optional[str] = None
    intent_symbol: Optional[str] = None
    confidence:    float         = 0.0
    from_fallback: bool          = False
    dsl_command:   str           = ""
    error:         str           = ""
    duration_s:    float         = 0.0
    dry_run:       bool          = False
    tx_metadata:   dict          = field(default_factory=dict)

    def __str__(self) -> str:
        status = "✅ OK" if self.success else "❌ ECHEC"
        conf   = f"{self.confidence:.0%}"
        fb     = " [heuristique]" if self.from_fallback else ""
        dr     = " [dry-run]" if self.dry_run else ""
        parts  = [
            f"{status}{dr}",
            f"  Action    : {self.intent_action} (confiance {conf}{fb})",
        ]
        if self.intent_file:
            parts.append(f"  Fichier   : {self.intent_file}")
        if self.intent_symbol:
            parts.append(f"  Symbole   : {self.intent_symbol}")
        if self.dsl_command:
            parts.append(f"  DSL       : {self.dsl_command}")
        if self.error:
            parts.append(f"  Erreur    : {self.error}")
        parts.append(f"  Durée     : {self.duration_s:.2f}s")
        return "\n".join(parts)


@dataclass
class NLSession:
    """Historique léger d'une session REPL."""
    results:        List[NLResult] = field(default_factory=list)
    commands_total: int            = 0
    commands_ok:    int            = 0

    def add(self, result: NLResult) -> None:
        self.results.append(result)
        self.commands_total += 1
        if result.success:
            self.commands_ok += 1

    def summary(self) -> str:
        rate = (self.commands_ok / self.commands_total * 100) if self.commands_total else 0
        return (
            f"Session : {self.commands_total} commandes, "
            f"{self.commands_ok} réussies ({rate:.0f}%)"
        )
