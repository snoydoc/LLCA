# -*- coding: utf-8-sig -*-
"""
curriculum_tracker.py -- EVAL-03
Gestionnaire de progression par domaine et par palier.

Responsabilites :
  - Lire/ecrire eval_state.json (ecriture atomique -- regle T-14)
  - Decider si un palier est debloque
  - Charger les questions d'un palier depuis les JSON benchmarks
  - Mettre a jour le score moyen apres chaque question
  - (V4) Retrograder si N sessions consecutives < seuil SYS-02

INVARIANT T-14 : ecriture atomique via Path.replace() (jamais Path.rename()).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from EvalLoop.evalloop_types import BenchQuestion, PalierState

log = logging.getLogger("lcca.evalloop.curriculum")

MAX_PALIER           = 5
_RECENT_SCORES_MAX   = 10   # Fenetre glissante pour SYS-02


class CurriculumTracker:
    """Gere la progression curriculum par domaine."""

    def __init__(
        self,
        state_path:     Path,
        benchmarks_dir: Path,
        config:         Dict[str, Any],
    ) -> None:
        self._state_path     = state_path
        self._benchmarks_dir = benchmarks_dir
        self._config         = config

    # ── Etat ──────────────────────────────────────────────────────────────────

    def get_state(self, domain: str) -> PalierState:
        """Retourne l'etat courant du domaine. Cree l'etat par defaut si absent."""
        data = self._load_state()
        if domain not in data:
            return PalierState(domain=domain)
        return PalierState.from_dict(data[domain])

    def update_state(self, domain: str, score: float) -> PalierState:
        """
        Met a jour le score moyen et gere les montees de palier.
        Ecriture atomique (T-14).
        """
        data  = self._load_state()
        state = PalierState.from_dict(data[domain]) if domain in data else PalierState(domain=domain)

        # Mise a jour score
        state.questions_done += 1
        state.avg_score = (
            (state.avg_score * (state.questions_done - 1) + score)
            / state.questions_done
        )

        # Historique recent pour SYS-02 (retrogradation V4)
        state.recent_scores.append(score)
        if len(state.recent_scores) > _RECENT_SCORES_MAX:
            state.recent_scores = state.recent_scores[-_RECENT_SCORES_MAX:]

        # Montee de palier
        unlock_threshold = self._config.get("scoring", {}).get(
            "unlock_threshold", state.unlock_threshold
        )
        if (state.avg_score >= unlock_threshold
                and state.current_palier < MAX_PALIER):
            old_palier = state.current_palier
            state.current_palier   += 1
            state.sessions_completed += 1
            state.avg_score = 0.0   # Reset pour le nouveau palier
            log.info(
                "Progression %s : palier %d -> %d",
                domain, old_palier, state.current_palier,
            )

        # Retrogradation (SYS-02 -- desactivee en V3, activable en V4)
        retrograde_cfg     = self._config.get("sys02_retrograde", {})
        retrograde_enabled = retrograde_cfg.get("retrograde_enabled", False)
        if retrograde_enabled:
            window    = retrograde_cfg.get("retrograde_window", 3)
            threshold = retrograde_cfg.get("retrograde_threshold", 0.50)
            if (len(state.recent_scores) >= window
                    and all(s < threshold for s in state.recent_scores[-window:])
                    and state.current_palier > 0):
                state.current_palier -= 1
                log.warning("Retrogradation %s -> palier %d", domain, state.current_palier)

        data[domain] = state.to_dict()
        self._save_state(data)
        return state

    def is_unlocked(self, domain: str, palier: int) -> bool:
        """Palier 0 toujours debloque. Palier N debloque si current_palier >= N."""
        if palier == 0:
            return True
        return self.get_state(domain).current_palier >= palier

    # ── Questions ─────────────────────────────────────────────────────────────

    def load_questions(self, domain: str, palier: int) -> List[BenchQuestion]:
        """
        Charge palier_N.json depuis benchmarks_dir/domain/.
        Filtre uniquement status == 'active'.
        Retourne [] si le fichier est absent (pas d'exception).
        """
        path = self._benchmarks_dir / domain / f"palier_{palier}.json"
        if not path.exists():
            log.warning("Fichier benchmark absent : %s", path)
            return []
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        return [
            BenchQuestion.from_dict(q)
            for q in raw
            if q.get("status", "active") == "active"
        ]

    # ── I/O atomique ──────────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        """Charge eval_state.json. Retourne {} si absent ou invalide."""
        try:
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_state(self, data: dict) -> None:
        """
        Ecriture atomique -- regle T-14 :
        Path.replace() est atomique sur Windows ET Linux.
        Ne jamais utiliser Path.rename() sur une cible existante sous Windows.
        """
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self._state_path)
