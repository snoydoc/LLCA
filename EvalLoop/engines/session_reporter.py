# -*- coding: utf-8-sig -*-
"""
session_reporter.py — Génère session_report.md + métriques de santé Ollama (OPP-01).

Métriques de santé surveillées :
  - avg_duration_sec   : temps moyen de probe (> 20s → Ollama dégradé)
  - avg_response_words : mots moyens par réponse (< 50 → modèle dégénéré)
  - error_rate         : taux de réponses vides/erreur (> 5% → crashes Ollama)
  - completion_rate    : taux de questions répondues (< 80% → questions incomplètes)

Écriture atomique via Path.replace() — règle T-14.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from EvalLoop.evalloop_types import JudgeScore, ProbeResponse

log = logging.getLogger("lcca.evalloop.reporter")

HEALTH_THRESHOLDS: Dict[str, Any] = {
    "avg_duration_sec":   20.0,   # > 20s → alerte Ollama dégradé
    "avg_response_words": 50,     # < 50 mots → alerte modèle dégénéré
    "error_rate":         0.05,   # > 5% → alerte crashes Ollama
    "completion_rate":    0.80,   # < 80% → alerte questions incomplètes
}


class SessionReporter:
    """Génère session_report.md avec métriques de santé."""

    def generate(
        self,
        session_dir: Path,
        scores: List[JudgeScore],
        responses: List[ProbeResponse],
        domain: str,
        palier: int,
        judge_mode: str,
    ) -> Path:
        """
        Écrit session_report.md dans session_dir (écriture atomique).
        Retourne le chemin du rapport généré.
        """
        metrics = self._compute_health(responses)
        alerts  = self._check_alerts(metrics)
        content = self._render(
            session_dir, scores, responses, domain, palier, judge_mode,
            metrics, alerts,
        )
        report_path = session_dir / "session_report.md"
        tmp = report_path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(report_path)   # T-14 : atomique Windows + Linux
        log.info("Rapport généré : %s", report_path)
        return report_path

    # ── Métriques ─────────────────────────────────────────────────────────────

    def _compute_health(self, responses: List[ProbeResponse]) -> Dict[str, Any]:
        """Calcule les métriques de santé Ollama depuis les réponses brutes."""
        if not responses:
            return {
                "avg_duration_sec":   0.0,
                "avg_response_words": 0,
                "error_rate":         0.0,
                "completion_rate":    0.0,
                "total":              0,
            }

        total     = len(responses)
        durations = [r.duration_sec for r in responses]
        words     = [len(r.response.split()) for r in responses]
        errors    = sum(1 for r in responses if not r.response.strip())

        return {
            "avg_duration_sec":   sum(durations) / total,
            "avg_response_words": sum(words) / total,
            "error_rate":         errors / total,
            "completion_rate":    (total - errors) / total,
            "total":              total,
        }

    def _check_alerts(self, metrics: Dict[str, Any]) -> List[str]:
        """Retourne une liste d'alertes si les seuils sont dépassés."""
        alerts = []
        if metrics.get("avg_duration_sec", 0) > HEALTH_THRESHOLDS["avg_duration_sec"]:
            alerts.append(
                f"⚠️ Temps moyen probe {metrics['avg_duration_sec']:.1f}s "
                f"(seuil > {HEALTH_THRESHOLDS['avg_duration_sec']}s) — Ollama potentiellement dégradé"
            )
        if metrics.get("avg_response_words", 999) < HEALTH_THRESHOLDS["avg_response_words"]:
            alerts.append(
                f"⚠️ Réponses courtes ({metrics['avg_response_words']:.0f} mots) "
                f"(seuil < {HEALTH_THRESHOLDS['avg_response_words']}) — modèle potentiellement dégénéré"
            )
        if metrics.get("error_rate", 0) > HEALTH_THRESHOLDS["error_rate"]:
            alerts.append(
                f"⚠️ Taux erreur {metrics['error_rate']:.1%} "
                f"(seuil > {HEALTH_THRESHOLDS['error_rate']:.0%}) — vérifier Ollama"
            )
        if metrics.get("completion_rate", 1) < HEALTH_THRESHOLDS["completion_rate"]:
            alerts.append(
                f"⚠️ Taux complétion {metrics['completion_rate']:.1%} "
                f"(seuil < {HEALTH_THRESHOLDS['completion_rate']:.0%})"
            )
        return alerts

    # ── Rendu Markdown ────────────────────────────────────────────────────────

    def _render(
        self,
        session_dir: Path,
        scores: List[JudgeScore],
        responses: List[ProbeResponse],
        domain: str,
        palier: int,
        judge_mode: str,
        metrics: Dict[str, Any],
        alerts: List[str],
    ) -> str:
        now    = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        sname  = session_dir.name

        lines = [
            f"# Session EvalLoop — {sname}",
            f"**Domaine** : {domain} | **Palier** : {palier} | **Juge** : {judge_mode}  ",
            f"**Généré** : {now}",
            "",
            "## Résultats",
            "| Question | Score Final | Injecté |",
            "|---|---|---|",
        ]

        score_map = {s.question_id: s for s in scores}
        for resp in responses:
            s = score_map.get(resp.question_id)
            if s:
                injected = "Oui" if s.inject_recommended else "Non"
                lines.append(
                    f"| {resp.question_id} | {s.final_score:.2f} | {injected} |"
                )

        avg_score = (
            sum(s.final_score for s in scores) / len(scores) if scores else 0.0
        )
        lines += [
            "",
            f"**Score moyen** : {avg_score:.2f} | "
            f"**Questions complètes** : {metrics['total'] - int(metrics.get('error_rate', 0) * metrics['total'])}/{metrics['total']}",
            "",
            "## Santé Ollama",
            "| Métrique | Valeur | Seuil | Statut |",
            "|---|---|---|---|",
            f"| Temps moyen probe | {metrics['avg_duration_sec']:.1f}s | > 20s | "
            f"{'✅' if metrics['avg_duration_sec'] <= 20 else '⚠️'} |",
            f"| Longueur moyenne réponse | {metrics['avg_response_words']:.0f} mots | < 50 mots | "
            f"{'✅' if metrics['avg_response_words'] >= 50 else '⚠️'} |",
            f"| Taux erreur Ollama | {metrics['error_rate']:.1%} | > 5% | "
            f"{'✅' if metrics['error_rate'] <= 0.05 else '⚠️'} |",
            f"| Taux complétion | {metrics['completion_rate']:.1%} | < 80% | "
            f"{'✅' if metrics['completion_rate'] >= 0.80 else '⚠️'} |",
        ]

        if alerts:
            lines += ["", "## Alertes"]
            lines += [f"- {a}" for a in alerts]

        return "\n".join(lines) + "\n"
