# -*- coding: utf-8-sig -*-
"""
nl_intent.py — Dataclass NLIntent + helpers (Sprint REFACTO-01).

Zéro dépendance réseau, zéro import de modules core.
Importé par nl_parser.py, nl_intent_builder.py, nl_orchestrator.py.

Rétrocompatibilité : NLIntent est ré-exporté depuis nl_parser.py,
donc `from core.nl_parser import NLIntent` continue de fonctionner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# Actions valides reconnues par le pipeline NL
VALID_ACTIONS: tuple[str, ...] = (
    "add_function", "modify_function", "create_file",
    "read_file", "delete_function", "unknown"
)


# ---------------------------------------------------------------------------
# NlIntent — Enum des intents speciaux (Educator, etc.)
# Distinct de NLIntent (dataclass) qui reste pour le pipeline LLM classique.
# ---------------------------------------------------------------------------

class NlIntent(Enum):
    """Intents speciaux reconnus par les patterns regex de NlParser (ED-04)."""
    EDUCATOR_RUN  = "educator_run"   # Lancer une curation
    EDUCATOR_DIFF = "educator_diff"  # Mode diff (rapport sans ecriture)


@dataclass
class NLIntent:
    """
    Intent structuré extrait d'une commande en langage naturel.

    Champs :
        action           : Que faire ? (add_function, modify_function,
                           create_file, read_file, unknown)
        target_file      : Fichier Python cible (ex: "core/conversation.py")
                           None si non mentionné ou ambigu
        symbol           : Nom de la fonction/classe cible
                           None si l'action est sur tout le fichier
        description      : Description textuelle de la modification souhaitée
        create_if_missing: True = créer le fichier s'il n'existe pas encore
        confidence       : Confiance du LLM (0.0 à 1.0)
        raw_command      : Commande originale (pour logs et debug)
        from_fallback    : True = NLParser a échoué, intent reconstruit en heuristique
    """
    action:           str
    description:      str
    raw_command:      str
    target_file:      Optional[str]  = None
    symbol:           Optional[str]  = None
    create_if_missing: bool          = False
    confidence:       float          = 0.0
    from_fallback:    bool           = False

    # Champ informatif (non comparé, non repr)
    _valid_actions: tuple = field(
        default_factory=lambda: VALID_ACTIONS,
        repr=False, compare=False,
    )

    def is_actionable(self) -> bool:
        """True si l'intent est suffisamment précis pour être exécuté."""
        return (
            self.action not in ("unknown",)
            and self.confidence >= 0.5
            and self.description.strip() != ""
        )

    def to_dsl(self) -> str:
        """
        Convertit l'NLIntent vers le format DSL existant.
        Utilisé pour brancher sur l'orchestrateur Sprint 04.

        Exemple :
            NLIntent(action='add_function', target_file='core/conv.py',
                     symbol='handle_greeting', ...) →
            "LCCA - conv - handle_greeting - Ajoute handle_greeting"
        """
        project = "LCCA"
        if self.target_file:
            module = self.target_file.replace("\\", "/").split("/")[-1].replace(".py", "")
        else:
            module = "unknown"

        action_verb = {
            "add_function":    "Ajoute",
            "modify_function": "Modifie",
            "create_file":     "Crée",
            "read_file":       "Lit",
            "delete_function": "Supprime",
        }.get(self.action, "Traite")

        symbol_part = f" - {self.symbol}" if self.symbol else ""
        return f"{project} - {module}{symbol_part} - {action_verb} {self.description}"
