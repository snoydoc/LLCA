# -*- coding: utf-8-sig -*-
"""
distill_engine.py — Injection des skills évalués dans MemoryEngine.

ATTENTION : Ce module importe `core.memory_engine` au chargement.
Il ne peut pas être importé sans que sys.path contienne la racine LCCA.
Point d'entrée : lcca_eval.py (configure sys.path automatiquement).
Tests : tests/conftest.py configure sys.path (existant dans le projet LCCA).

DÉCISIONS ARCHITECTURALES (verrouillées — voir Spec_EvalLoop_Final.md) :
  1. Import direct MemoryEngine — pas d'import lazy (pas de dépendance circulaire)
  2. Guard autonome _MIN_INJECT_SCORE — indépendant des internals MemoryEngine
  3. Payload strict — clé "content" uniquement (voir §3 pour raison)
  4. Dedup index : charge-une-fois / écrit-une-fois (anti-pattern O-01)
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Set

from core.memory_engine import MemoryEngine       # Import DIRECT — pas de lazy
from EvalLoop.evalloop_types import JudgeScore, DistilledSkill

log = logging.getLogger("lcca.evalloop.distill")

# Seuil d'injection — source de vérité EvalLoop, indépendante de _THRESHOLD_CONTEXT=0.6
# Redondance intentionnelle : EvalLoop ne délègue jamais ce contrôle à MemoryEngine.
_MIN_INJECT_SCORE: float = 0.70


class DistillEngine:
    """Sélectionne les réponses JudgeClaude éligibles et les injecte dans lcca_context."""

    def __init__(self, dedup_path: Path, config: dict):
        self._mem        = MemoryEngine()          # Instanciation directe
        self._dedup_path = dedup_path
        self._config     = config

    # ── API publique ──────────────────────────────────────────────────────────

    def distill(self, session_dir: Path) -> int:
        """
        Lit scores.jsonl, injecte les entrées éligibles dans lcca_context.

        Pattern O-01 : index chargé AVANT la boucle, écrit UNE FOIS après.
        Retourne le nombre d'entrées injectées.
        """
        scores_path = session_dir / "scores.jsonl"
        if not scores_path.exists():
            log.warning("distill: scores.jsonl absent dans %s", session_dir)
            return 0

        index      = self._load_dedup_index()   # LECTURE UNIQUE
        injected   = 0
        new_hashes: Set[str] = set()

        for line in scores_path.read_text(encoding="utf-8-sig").strip().splitlines():
            if not line.strip():
                continue

            try:
                score = JudgeScore(**json.loads(line))
            except (json.JSONDecodeError, TypeError) as exc:
                log.warning("distill: ligne invalide — %s", exc)
                continue

            if not self._is_eligible(score):
                continue

            dedup_hash = hashlib.sha256(score.improved_answer.encode()).hexdigest()[:16]

            if dedup_hash in index:
                log.debug("distill: doublon %s — skip", dedup_hash)
                continue

            payload = self._build_payload(score, dedup_hash)
            result  = self._mem.store("lcca_context", payload)

            if result.stored:
                injected += 1
                new_hashes.add(dedup_hash)
                log.info(
                    "distill: injecté %s (score=%.2f, hash=%s)",
                    score.question_id, score.final_score, dedup_hash,
                )
            else:
                log.warning(
                    "distill: store refusé pour %s — %s",
                    score.question_id, result.reason,
                )

        if new_hashes:
            index.update(new_hashes)
            self._save_dedup_index(index)   # ÉCRITURE UNIQUE si changements

        return injected

    # ── Critères d'éligibilité ────────────────────────────────────────────────

    def _is_eligible(self, score: JudgeScore) -> bool:
        """
        Critères d'injection — vérifiés par EvalLoop indépendamment des internals MemoryEngine.

        RÈGLE : Ne jamais lire mem._enforce ou tout autre attribut interne de MemoryEngine.
        Le seuil 0.70 est une redondance intentionnelle — pas une délégation.
        """
        if score.judge != "claude":
            return False
        if not score.inject_recommended:
            return False
        if score.final_score < _MIN_INJECT_SCORE:
            return False
        if not score.improved_answer.strip():
            return False
        return True

    # ── Payload ───────────────────────────────────────────────────────────────

    def _build_payload(self, score: JudgeScore, dedup_hash: str) -> dict:
        """
        Payload pour lcca_context.

        RÈGLE STRICTE : "content" est la seule clé textuelle autorisée.
        Raison : extract_content() dans memory_engine_store.py cherche les clés dans
        l'ordre ("code", "snippet", "error", "content", "text"). Si une de ces clés
        précédentes était présente, elle serait indexée à la place de improved_answer.

        INTERDIT dans ce payload : "code", "snippet", "error", "text"
        """
        return {
            "content":    score.improved_answer,   # SEULE clé textuelle — invariant
            "score":      score.final_score,
            "source":     "evalloop",
            "domain":     score.domain,
            "palier":     score.palier,
            "judge":      score.judge,
            "dedup_hash": dedup_hash,
            # Pas de "code", "snippet", "error", "text"
        }

    # ── Index dedup — charge-une-fois / écrit-une-fois ────────────────────────

    def _load_dedup_index(self) -> Set[str]:
        """Charge l'index en mémoire. Set pour lookup O(1). Retourne set vide si absent."""
        try:
            data = json.loads(self._dedup_path.read_text(encoding="utf-8"))
            return set(data)
        except (FileNotFoundError, json.JSONDecodeError):
            return set()

    def _save_dedup_index(self, index: Set[str]) -> None:
        """Écriture atomique — pattern T-14 (Path.replace() atomique Windows + Linux)."""
        tmp = self._dedup_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(sorted(index), indent=2), encoding="utf-8")
        tmp.replace(self._dedup_path)   # Path.replace() — jamais Path.rename()
