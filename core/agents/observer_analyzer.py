# -*- coding: utf-8-sig -*-
"""
observer_analyzer.py -- REFACTO-03 : couche d'analyse memoire de l'ObserverAgent.

Extrait depuis observer_agent.py (V8-07, 16 KB) pour en reduire la taille.

Responsabilites :
    - Detecter les skills a faible score (low_quality)
    - Detecter les doublons (heuristique Jaccard lexicale)
    - Construire le snapshot de l'observation

L'ObserverAgent conserve le chargement des skills (MCP / memory_engine)
et l'archivage des receipts (filesystem). Cette classe est injectee dans
ObserverAgent.__init__() pour permettre les tests unitaires directs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Helpers module-level (repris depuis observer_agent.py -- retrocompat)
# ---------------------------------------------------------------------------

def _is_duplicate(entry_a: Dict[str, Any], entry_b: Dict[str, Any], threshold: float) -> bool:
    """
    Heuristique de dedoublonnage lexical (sans embeddings).

    Compare les corps textuels normalises des deux entrees :
    si le ratio de tokens communs depasse le seuil, elles sont dupliquees.

    Note : en prod, remplacer par une comparaison cosine ChromaDB.
    """
    def _tokens(text: str) -> set:
        return set(text.lower().split())

    body_a = entry_a.get("body", "") or entry_a.get("code", "") or entry_a.get("content", "")
    body_b = entry_b.get("body", "") or entry_b.get("code", "") or entry_b.get("content", "")

    if not body_a or not body_b:
        return False

    tokens_a = _tokens(body_a)
    tokens_b = _tokens(body_b)

    if not tokens_a or not tokens_b:
        return False

    intersection = tokens_a & tokens_b
    union        = tokens_a | tokens_b
    jaccard      = len(intersection) / len(union)
    return jaccard >= threshold


def _build_snapshot(
    skills_count: int,
    low_quality: List[str],
    duplicates: List[tuple],
    archived: List[str],
) -> Dict[str, Any]:
    """
    Construit le dictionnaire snapshot de l'observation.

    Retourne un dict serialisable (aucun objet complexe).
    """
    return {
        "skills_total":      skills_count,
        "low_quality_ids":   low_quality,
        "duplicate_pairs":   [list(p) for p in duplicates],
        "archived_ids":      archived,
        "low_quality_count": len(low_quality),
        "duplicate_count":   len(duplicates),
        "archived_count":    len(archived),
        "observed_at":       datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# ObserverAnalyzer
# ---------------------------------------------------------------------------

class ObserverAnalyzer:
    """
    Couche d'analyse memoire (REFACTO-03).

    Extrait la logique de detection (low_quality, duplicates, snapshot)
    de ObserverAgent pour en reduire la taille et faciliter les tests unitaires.

    Usage::

        analyzer = ObserverAnalyzer(min_skill_score=40, max_duplicate_sim=0.95)
        low      = analyzer.find_low_quality(skills)
        dups     = analyzer.find_duplicates(skills)
        snapshot = analyzer.build_snapshot(len(skills), low, dups, archived=[])
    """

    def __init__(
        self,
        min_skill_score: int   = 40,
        max_duplicate_sim: float = 0.95,
    ) -> None:
        self._min_score  = min_skill_score
        self._max_sim    = max_duplicate_sim

    def find_low_quality(
        self,
        skills: List[Dict[str, Any]],
        min_score: int | None = None,
    ) -> List[str]:
        """Retourne les IDs des skills dont le score < min_score."""
        threshold = min_score if min_score is not None else self._min_score
        return [
            s["id"] for s in skills
            if s.get("score", 0) < threshold and s.get("id")
        ]

    def find_duplicates(
        self,
        skills: List[Dict[str, Any]],
        max_sim: float | None = None,
    ) -> List[tuple]:
        """
        Retourne les paires (id_a, id_b) de skills potentiellement dupliques.

        Complexite O(n^2) — acceptable car lcca_skills < 500 entrees en pratique.
        """
        threshold = max_sim if max_sim is not None else self._max_sim
        pairs: List[tuple] = []
        for i in range(len(skills)):
            for j in range(i + 1, len(skills)):
                if _is_duplicate(skills[i], skills[j], threshold):
                    pairs.append((skills[i]["id"], skills[j]["id"]))
        return pairs

    def build_snapshot(
        self,
        skills_count: int,
        low_quality: List[str],
        duplicates: List[tuple],
        archived: List[str],
    ) -> Dict[str, Any]:
        """Delegue a la fonction module-level _build_snapshot."""
        return _build_snapshot(
            skills_count=skills_count,
            low_quality=low_quality,
            duplicates=duplicates,
            archived=archived,
        )
