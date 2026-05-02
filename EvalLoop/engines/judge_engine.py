# -*- coding: utf-8-sig -*-
"""
judge_engine.py — Orchestrateur des juges EvalLoop.

Garanties :
  - JudgeLocal toujours exécuté en premier (gatekeeper)
  - JudgeClaude exécuté uniquement si local.final_score >= gatekeeper_min
  - Guard VIG-03 : si scores.jsonl contient un juge différent → WARNING
"""
from __future__ import annotations

import logging
from pathlib import Path

from EvalLoop.evalloop_types import BenchQuestion, JudgeScore, ProbeResponse
from EvalLoop.judges.judge_local import JudgeLocal
from EvalLoop.judges.judge_claude import JudgeClaude

log = logging.getLogger("lcca.evalloop.judge")


class JudgeEngine:
    """Orchestre JudgeLocal et JudgeClaude selon le mode demandé."""

    def __init__(self, config: dict):
        self._local  = JudgeLocal()
        self._claude = JudgeClaude()
        self._config = config

    def judge(self, probe: ProbeResponse, mode: str = "local") -> JudgeScore:
        """
        mode='local'  → JudgeLocal uniquement.
        mode='claude' → JudgeLocal gatekeeper + JudgeClaude si score >= gatekeeper_min.
        """
        local_score = self._local.score(probe.question, probe)

        if mode == "local":
            return local_score

        gatekeeper_min = self._config.get("scoring", {}).get("gatekeeper_min", 0.30)
        if local_score.final_score < gatekeeper_min:
            log.info(
                "judge: %s rejeté par gatekeeper (%.2f < %.2f)",
                probe.question_id, local_score.final_score, gatekeeper_min,
            )
            return local_score

        return self._claude.score(probe.question, probe)

    def check_mixed_judges(self, session_dir: Path, current_mode: str) -> bool:
        """
        VIG-03 : retourne True si scores.jsonl contient des entrées d'un juge différent.
        Log WARNING si mélange détecté.
        """
        import json
        scores_path = session_dir / "scores.jsonl"
        if not scores_path.exists():
            return False

        expected_judge = current_mode  # "local" ou "claude"
        for line in scores_path.read_text(encoding="utf-8-sig").strip().splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if data.get("judge") != expected_judge:
                    log.warning(
                        "VIG-03 : mélange de juges dans %s — "
                        "juge existant '%s' != juge actuel '%s'. "
                        "Créer une nouvelle session pour éviter un score faussé.",
                        session_dir, data.get("judge"), expected_judge,
                    )
                    return True
            except json.JSONDecodeError:
                continue
        return False
