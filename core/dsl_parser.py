# -*- coding: utf-8-sig -*-
"""
dsl_parser.py — LCCA V5 Fusion
Sprint 04 — TASK-04-01

Parser du langage de commande LCCA. Format structuré :
    "Projet - Cible - [Sous-cible -] Action Details"

Exemples :
    "DashV1 - Auth - Ajoute validate_email()"
    "DashV1 - RDV - Modal - Modifie send_sms()"
    "Ajoute une validation email dans auth.py"  → confidence < 0.5
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Actions reconnues (en minuscule, sans accent)
ACTIONS: set[str] = {
    "ajoute", "modifie", "supprime", "cree", "crée",
    "refactor", "corrige", "renomme", "deplace",
}

# Normalisation accent → sans accent pour la comparaison
_ACCENT_MAP: dict[str, str] = {
    "crée": "cree",
    "déplace": "deplace",
    "corrigé": "corrige",
}


def _normalize_action(word: str) -> str:
    """Normalise une action : lowercase + diacritiques."""
    w = word.lower().strip()
    return _ACCENT_MAP.get(w, w)


# ──────────────────────────────────────────────────────────────────────────────
# Dataclass Intent
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Intent:
    """Représentation structurée d'une commande utilisateur LCCA."""
    project: str                      # "DashboardV1"
    target: str                       # "Page RDV" | "auth"
    sub_target: Optional[str]         # "Modal En Consultation" (optionnel)
    action: str                       # "ajoute" | "modifie" | "supprime" | "cree"
    details: str                      # "validate_email()" | contenu brut
    raw: str                          # Commande originale non modifiée
    confidence: float = 1.0           # Score de confiance (<0.5 → demande confirmation)

    def is_confident(self) -> bool:
        """Retourne True si le parsing est suffisamment fiable."""
        return self.confidence >= 0.5

    def summary(self) -> str:
        """Résumé lisible de l'intent pour les logs."""
        parts = [self.project, self.target]
        if self.sub_target:
            parts.append(self.sub_target)
        return f"[{' > '.join(parts)}] {self.action} → {self.details}"


# ──────────────────────────────────────────────────────────────────────────────
# DSLParser
# ──────────────────────────────────────────────────────────────────────────────

class DSLParser:
    """
    Parse les commandes DSL LCCA en objets Intent.

    Formats supportés :
        Structuré 3 parties : "Projet - Cible - Action Details"
        Structuré 4 parties : "Projet - Cible - Sous-cible - Action Details"
        Langage naturel     : confidence < 0.5
    """

    def parse(self, command: str) -> Intent:
        """
        Point d'entrée principal. Toujours retourne un Intent (jamais d'exception).

        Args:
            command: Commande brute de l'utilisateur.

        Returns:
            Intent avec confidence indiquant la qualité du parsing.
        """
        raw = command.strip()
        if not raw:
            return Intent(
                project="inconnu", target="inconnu", sub_target=None,
                action="modifie", details="", raw=raw, confidence=0.0,
            )

        parts = [p.strip() for p in raw.split("-")]
        # Filtre les parties vides (double tirets, tirets en fin)
        parts = [p for p in parts if p]

        if len(parts) >= 3:
            return self._parse_structured(parts, raw)
        else:
            return self._parse_natural(raw)

    # ── Parsing structuré ─────────────────────────────────────────────────────

    def _parse_structured(self, parts: list[str], raw: str) -> Intent:
        """Gère les formats à 3 ou 4 parties séparées par ' - '."""
        project = parts[0]
        target = parts[1]

        if len(parts) == 3:
            # Format: Projet - Cible - Action Details
            action, details = self._split_action(parts[2])
            return Intent(
                project=project, target=target, sub_target=None,
                action=action, details=details, raw=raw, confidence=1.0,
            )

        # Format: Projet - Cible - Sous-cible - Action Details
        sub_target = parts[2]
        action_str = " - ".join(parts[3:])
        action, details = self._split_action(action_str)
        return Intent(
            project=project, target=target, sub_target=sub_target,
            action=action, details=details, raw=raw, confidence=0.95,
        )

    def _split_action(self, text: str) -> tuple[str, str]:
        """
        Sépare 'Ajoute validate_email()' en ('ajoute', 'validate_email()').
        Si aucun mot d'action trouvé → ('modifie', text).
        """
        text = text.strip()
        words = text.split(None, 1)   # Split sur premier espace

        if not words:
            return "modifie", ""

        first = _normalize_action(words[0])
        if first in ACTIONS:
            details = words[1].strip() if len(words) > 1 else ""
            return first, details

        # Premier mot n'est pas une action connue → cherche dans toute la chaîne
        for action in sorted(ACTIONS, key=len, reverse=True):
            match = re.search(r'\b' + re.escape(action) + r'\b', text.lower())
            if match:
                details = text[match.end():].strip()
                return action, details or text

        # Aucune action trouvée
        return "modifie", text

    # ── Parsing langage naturel ───────────────────────────────────────────────

    def _parse_natural(self, command: str) -> Intent:
        """
        Parsing best-effort d'une phrase en langage naturel.
        Confidence réduite : 0.4 si action trouvée, 0.2 sinon.
        """
        lower = command.lower()

        # Cherche une action dans la commande
        found_action = "modifie"
        found = False
        for action in sorted(ACTIONS, key=len, reverse=True):
            if action in lower:
                found_action = action
                found = True
                break

        # Essaie d'extraire un fichier mentionné ("dans auth.py" / "auth.py")
        file_match = re.search(r'[\w/\\]+\.py', command)
        target = file_match.group(0).replace(".py", "") if file_match else "inconnu"

        return Intent(
            project="inconnu",
            target=target,
            sub_target=None,
            action=found_action,
            details=command,
            raw=command,
            confidence=0.4 if found else 0.2,
        )
