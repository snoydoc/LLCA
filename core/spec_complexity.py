# -*- coding: utf-8-sig -*-
"""
spec_complexity.py — LCCA V7
Sprint 15 — TASK-15-01
Sprint 18 — Dette 11 : search() sans filtre collection → filtrage explicite sur specs.

Heuristique adaptative : décide si une tâche nécessite une spec.
Aucun I/O disque dans le scoring — basé uniquement sur Intent déjà parsé
et recherches mémoire (MemoryEngine).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.memory_engine import MemoryEngine

import config


_COMPLEX_KEYWORDS = frozenset({
    "rollback", "sandbox", "mcp", "memory-first",
    "transaction", "acid", "async", "multi-agent",
    "spec", "migration", "refactor", "architecture",
})

_DOMAIN_MAP: dict[str, list[str]] = {
    "transaction": ["transaction", "wal", "rollback", "acid"],
    "sandbox":     ["sandbox", "docker", "subprocess", "exec"],
    "mcp":         ["mcp", "json-rpc", "tool", "server"],
    "memory":      ["memory", "chroma", "embedding", "vector"],
    "ast":         ["ast", "libcst", "patcher", "parse"],
    "spec":        ["spec", "specification", "addendum"],
    "orchestration": ["orchestrat", "pipeline", "execute", "workflow"],
}


def _infer_domain(intent) -> str:
    """Infère le domaine depuis les mots-clés du raw intent."""
    raw = getattr(intent, "raw", "").lower()
    for domain, keywords in _DOMAIN_MAP.items():
        if any(kw in raw for kw in keywords):
            return domain
    return "global"


class SpecComplexityEstimator:
    """
    Calcule un score de complexité pour décider si une spec est nécessaire.

    Score 0-100 :
      0-40   → exécution directe pipeline V5
      41-59  → optionnel (mode interactif ou auto_spec=True)
      60-100 → generate_spec() obligatoire

    Règle 16 : aucun I/O disque dans estimate() — seule la mémoire est autorisée.

    Sprint 18 — Dette 11 :
      Les appels search() n'utilisaient pas de filtre collection, ce qui mélangeait
      les résultats de solutions/failures/context/specs dans les heuristiques.
      Correction : on lit uniquement les clés pertinentes du dict retourné :
        - heuristique "domaine connu" → clé "specs" (specs existantes)
        - heuristique "historique d'échec" → clé "failures" uniquement
    """

    def __init__(self, memory_engine: "MemoryEngine") -> None:
        self._mem = memory_engine

    def estimate(self, intent) -> tuple[bool, int]:
        """
        Retourne (need_spec: bool, score: int).

        Args:
            intent: objet Intent (DSLParser output) — déjà parsé, pas d'I/O disque.
        """
        score = 0

        # 1. Nombre de fichiers cibles (attribut Intent déjà calculé)
        n_files = len(getattr(intent, "target_files", []))
        if n_files >= 3:
            score += 30

        # 2. Nouveau domaine — recherche uniquement dans lcca_specs
        #    (Sprint 18 — Dette 11 : filtrage explicite sur clé "specs")
        domain = _infer_domain(intent)
        all_results = self._mem.search(
            query=domain,
            wing="lcca",
            n=1,
        )
        # On ne regarde que les specs existantes pour cette heuristique
        # (ignorer solutions/failures/context qui polluaient le score)
        existing_specs = all_results.get("specs", [])
        if not existing_specs:
            score += 25

        # 3. Mots-clés complexes dans le raw intent
        raw = getattr(intent, "raw", "").lower()
        if any(kw in raw for kw in _COMPLEX_KEYWORDS):
            score += 20

        # 4. Historique d'échec similaire — recherche uniquement dans lcca_failures
        #    (Sprint 18 — Dette 11 : filtrage explicite sur clé "failures")
        details = getattr(intent, "details", raw)
        past_results = self._mem.search(
            query=details,
            wing="lcca",
            n=3,
        )
        # On ne regarde que les failures pour cette heuristique
        past_failures = past_results.get("failures", [])
        if past_failures:
            score += 15

        # 5. Longueur de la description (proxy complexité)
        if len(details) > 100:
            score += 10

        threshold = getattr(config, "SPEC_COMPLEXITY_THRESHOLD", 60)
        score = min(100, score)
        need_spec = score >= threshold
        return need_spec, score
