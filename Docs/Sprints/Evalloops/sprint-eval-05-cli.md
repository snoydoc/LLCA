# EVAL-05 — CLI + Test Manuel Ollama
**Sprint** : EVAL-05
**Statut** : À FAIRE
**Durée estimée** : 1 session
**Dépendances** : EVAL-01, EVAL-02, EVAL-03, EVAL-04
**Tests cibles** : 5 tests smoke (`tests/test_eval_05_cli.py`) + 1 test manuel Ollama réel

---

## Objectif

Implémenter le CLI `lcca_eval.py` et valider le pipeline complet sur une vraie question
avec Ollama. C'est le premier test de bout en bout sur le hardware réel.

---

## Fichiers à créer

| Fichier | Type | Notes |
|---------|------|-------|
| `lcca_eval.py` | Python | CLI racine — pattern identique à lcca_si.py |
| `EvalLoop/engines/judge_engine.py` | Python | Orchestrateur des juges |
| `EvalLoop/engines/session_reporter.py` | Python | Génère session_report.md + métriques santé |
| `tests/test_eval_05_cli.py` | Python | 5 tests smoke |

---

## Structure CLI (`lcca_eval.py`)

```python
#!/usr/bin/env python
# -*- coding: utf-8-sig -*-
"""
lcca_eval.py — CLI EvalLoop LCCA
Point d'entrée unique. Configure sys.path avant tout import LCCA.
Pattern identique à lcca_si.py.
"""
import sys
from pathlib import Path

# Configuration sys.path — AVANT tout import LCCA ou EvalLoop
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import logging

log = logging.getLogger("lcca.evalloop.cli")


def cmd_probe(args):
    """Probe une question ou un domaine complet."""
    from EvalLoop.engines.probe_engine import ProbeEngine
    from EvalLoop.engines.curriculum_tracker import CurriculumTracker
    from EvalLoop.engines.judge_engine import JudgeEngine
    # ... implémentation


def cmd_run(args):
    """Pipeline complet : probe → judge → distill → report."""
    # 1. Créer session_dir (YYYY-MM-DD_HH-MM)
    # 2. Charger questions (domain + palier courant)
    # 3. ProbeEngine.probe_batch() → responses.jsonl
    # 4. JudgeEngine.judge_all() → scores.jsonl
    # 5. DistillEngine.distill() si --judge claude
    # 6. CurriculumTracker.update_state() par question
    # 7. SessionReporter.generate() → session_report.md
    ...


def cmd_distill(args):
    """Distille une session existante dans MemoryEngine."""
    ...


def cmd_report(args):
    """Génère ou regénère le rapport d'une session."""
    ...


def cmd_review_bench(args):
    """Interface interactive pour valider les questions draft."""
    ...


def main():
    parser = argparse.ArgumentParser(
        prog="lcca_eval",
        description="EvalLoop — Benchmark curriculum LCCA",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # probe
    p_probe = sub.add_parser("probe", help="Soumettre des questions à Ollama")
    p_probe.add_argument("--domain", required=True)
    p_probe.add_argument("--palier", type=int, default=None)
    p_probe.add_argument("--judge", choices=["local", "claude"], default="local")
    p_probe.set_defaults(func=cmd_probe)

    # run (pipeline complet)
    p_run = sub.add_parser("run", help="Pipeline complet probe → judge → distill → report")
    p_run.add_argument("--domain", required=True)
    p_run.add_argument("--judge", choices=["local", "claude"], default="local")
    p_run.set_defaults(func=cmd_run)

    # distill
    p_distill = sub.add_parser("distill", help="Injecter une session dans MemoryEngine")
    p_distill.add_argument("--session", required=True)
    p_distill.set_defaults(func=cmd_distill)

    # report
    p_report = sub.add_parser("report", help="Générer le rapport d'une session")
    p_report.add_argument("--session", required=True)
    p_report.set_defaults(func=cmd_report)

    # review-bench
    p_review = sub.add_parser("review-bench", help="Valider les questions draft")
    p_review.add_argument("--domain", required=True)
    p_review.add_argument("--palier", type=int, required=True)
    p_review.add_argument("--export", default=None, help="Exporter vers JSON au lieu d'interactif")
    p_review.add_argument("--apply", default=None, help="Appliquer un fichier JSON exporté")
    p_review.set_defaults(func=cmd_review_bench)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    main()
```

---

## JudgeEngine — Orchestrateur

```python
# judge_engine.py
class JudgeEngine:
    """
    Orchestre JudgeLocal et JudgeClaude.

    Garanties :
      - JudgeLocal toujours exécuté en premier
      - JudgeClaude exécuté uniquement si final_score >= gatekeeper_min
      - Si scores.jsonl contient déjà des entrées d'un autre juge → WARNING + suggestion nouvelle session
    """

    def __init__(self, config: dict):
        self._local   = JudgeLocal()
        self._claude  = JudgeClaude() if self._claude_available() else None
        self._config  = config

    def judge(self, probe: ProbeResponse, mode: str = "local") -> JudgeScore:
        """
        mode="local"  → JudgeLocal uniquement
        mode="claude" → JudgeLocal gatekeeper + JudgeClaude si score >= 0.30
        """
        local_score = self._local.score(probe.question, probe)
        if mode == "local":
            return local_score

        gatekeeper_min = self._config["scoring"]["gatekeeper_min"]
        if local_score.final_score < gatekeeper_min:
            log.info(
                "judge: %s rejeté par gatekeeper (%.2f < %.2f)",
                probe.question_id, local_score.final_score, gatekeeper_min,
            )
            return local_score

        return self._claude.score(probe.question, probe)
```

---

## SessionReporter — Métriques de Santé (OPP-01)

```python
# session_reporter.py
class SessionReporter:
    """Génère session_report.md avec métriques de santé Ollama."""

    HEALTH_THRESHOLDS = {
        "avg_duration_sec":    20.0,   # > 20s → alerte Ollama dégradé
        "avg_response_words":  50,     # < 50 mots → alerte modèle dégénéré
        "error_rate":          0.05,   # > 5% → alerte crashes Ollama
        "completion_rate":     0.80,   # < 80% → alerte questions incomplètes
    }

    def generate(self, session_dir: Path, scores: list, responses: list) -> None:
        """Écrit session_report.md dans session_dir."""
        metrics = self._compute_health(responses)
        alerts  = self._check_alerts(metrics)
        # ... écriture atomique session_report.md
```

**Format `session_report.md`** :

```markdown
# Session EvalLoop — 2026-04-24_14-30
**Domaine** : python_core | **Palier** : 0 | **Juge** : local

## Résultats
| Question | Score Local | Score Final | Injecté |
|---|---|---|---|
| python_core/p0/gil_001 | 0.64 | 0.64 | Non |
| python_core/p0/list_tuple_001 | 0.78 | 0.78 | Non |
...

**Score moyen** : 0.68 | **Questions complètes** : 10/10

## Santé Ollama
| Métrique | Valeur | Seuil | Statut |
|---|---|---|---|
| Temps moyen probe | 8.4s | > 20s | ✅ |
| Longueur moyenne réponse | 187 mots | < 50 mots | ✅ |
| Taux erreur Ollama | 0% | > 5% | ✅ |
| Taux complétion | 100% | < 80% | ✅ |
```

---

## Tests (`test_eval_05_cli.py`)

5 tests smoke :

```
test_cli_help                       → python lcca_eval.py --help → exit code 0
test_cli_probe_missing_domain       → probe sans --domain → exit code != 0
test_cli_import_no_side_effects     → import lcca_eval → pas d'appel Ollama, pas d'écriture disque
test_cli_run_creates_session_dir    → cmd_run mocké → session_dir créé avec YYYY-MM-DD_HH-MM
test_cli_distill_session_not_found  → distill --session inexistant → log WARNING, exit propre
```

---

## Test Manuel Ollama Réel (non automatisé)

À exécuter manuellement après pytest :

```bash
cd D:\LLMCodeAgent

# S'assurer qu'Ollama est démarré
# python start-ollama.ps1

# Test 1 question réelle, juge local uniquement
python lcca_eval.py probe --domain python_core --palier 0 --judge local

# Vérifier :
#   1. EvalLoop/sessions/YYYY-MM-DD_HH-MM/responses.jsonl créé
#   2. EvalLoop/sessions/YYYY-MM-DD_HH-MM/scores.jsonl créé
#   3. session_report.md créé avec métriques santé
#   4. Temps probe affiché (devrait être 6-15s pour qwen2.5-coder:3b)
#   5. Aucune erreur VRAM / OOM
```

**Résultat attendu** :
```
INFO lcca.evalloop.probe  probe: python_core/p0/gil_001 → 8.4s
INFO lcca.evalloop.judge  judge: local score=0.64 (concept=0.8, coherence=0.5, structure=0.1)
INFO lcca.evalloop.cli    Session terminée : 1 question, score moyen=0.64
INFO lcca.evalloop.cli    Rapport : EvalLoop/sessions/2026-04-24_14-30/session_report.md
```

---

## Checklist

```
[ ] lcca_eval.py créé (racine) avec sys.path.insert en premier
[ ] EvalLoop/engines/judge_engine.py créé
[ ] EvalLoop/engines/session_reporter.py créé (avec métriques santé OPP-01)
[ ] tests/test_eval_05_cli.py créé (5 tests smoke)
[ ] pytest tests/test_eval_*.py -v → 55 passed, 0 failed
[ ] Test manuel Ollama réel : 1 question → session créée, rapport généré
[ ] Vérifier que OLLAMA_TIMEOUT=None est bien transmis (ne pas laisser d'entier)
[ ] git commit -m "EVAL-05: CLI + session_reporter"
```
