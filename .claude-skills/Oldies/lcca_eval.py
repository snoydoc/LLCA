#!/usr/bin/env python
# -*- coding: utf-8-sig -*-
"""
lcca_eval.py — CLI EvalLoop LCCA
Point d'entrée unique. Configure sys.path avant tout import LCCA.
Pattern identique à lcca_si.py.

Commandes :
  probe         Soumettre des questions à Ollama
  run           Pipeline complet probe > judge > distill > report
  distill       Injecter une session existante dans MemoryEngine
  report        Générer ou régénérer le rapport d'une session
  review-bench  Interface interactive pour valider les questions draft
"""
import sys
from pathlib import Path

# Configuration sys.path — AVANT tout import LCCA ou EvalLoop
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import logging
from datetime import datetime, timezone

log = logging.getLogger("lcca.evalloop.cli")

# Racine EvalLoop
_EVALLOOP_ROOT = Path(__file__).resolve().parent / "EvalLoop"
_STATE_PATH    = _EVALLOOP_ROOT / "eval_state.json"
_DEDUP_PATH    = _EVALLOOP_ROOT / "eval_dedup_index.json"
_SESSIONS_DIR  = _EVALLOOP_ROOT / "sessions"
_BENCH_DIR     = _EVALLOOP_ROOT / "benchmarks"


def _load_config() -> dict:
    """Charge eval_config.toml. Retourne un dict avec les défauts si absent."""
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # fallback
        except ImportError:
            return _default_config()

    config_path = _EVALLOOP_ROOT / "eval_config.toml"
    if not config_path.exists():
        return _default_config()
    try:
        return tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return _default_config()


def _default_config() -> dict:
    return {
        "scoring": {
            "min_inject_score": 0.70,
            "unlock_threshold": 0.70,
            "gatekeeper_min":   0.30,
        },
        "sessions": {
            "sessions_dir": str(_SESSIONS_DIR),
            "state_file":   str(_STATE_PATH),
            "dedup_index":  str(_DEDUP_PATH),
        },
        "sys02_retrograde": {"retrograde_enabled": False},
    }


def _new_session_dir() -> Path:
    """Crée et retourne un dossier de session YYYY-MM-DD_HH-MM."""
    stamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d_%H-%M")
    session_dir = _SESSIONS_DIR / stamp
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


# ── Commandes ─────────────────────────────────────────────────────────────────

def cmd_probe(args):
    """Probe une question ou un domaine complet, juge les réponses."""
    import json
    from EvalLoop.engines.probe_engine import ProbeEngine
    from EvalLoop.engines.curriculum_tracker import CurriculumTracker
    from EvalLoop.engines.judge_engine import JudgeEngine

    config  = _load_config()
    tracker = CurriculumTracker(_STATE_PATH, _BENCH_DIR, config)
    palier  = args.palier if args.palier is not None else tracker.get_state(args.domain).current_palier
    questions = tracker.load_questions(args.domain, palier)

    if not questions:
        log.warning("Aucune question active pour %s palier %d", args.domain, palier)
        return

    session_dir = _new_session_dir()
    probe       = ProbeEngine()
    engine      = JudgeEngine(config)

    responses_path = session_dir / "responses.jsonl"
    scores_path    = session_dir / "scores.jsonl"

    for q in questions:
        resp  = probe.probe(q)
        score = engine.judge(resp, mode=args.judge)

        with responses_path.open("a", encoding="utf-8-sig") as f:
            f.write(json.dumps(resp.to_dict()) + "\n")
        with scores_path.open("a", encoding="utf-8-sig") as f:
            f.write(json.dumps(score.to_dict()) + "\n")

        log.info(
            "probe: %s → %.1fs | score=%.2f",
            q.id, resp.duration_sec, score.final_score,
        )

    log.info("Session : %s", session_dir)


def cmd_run(args):
    """Pipeline complet : probe → judge → distill → report."""
    import json
    from EvalLoop.engines.probe_engine import ProbeEngine
    from EvalLoop.engines.curriculum_tracker import CurriculumTracker
    from EvalLoop.engines.judge_engine import JudgeEngine
    from EvalLoop.engines.session_reporter import SessionReporter

    config   = _load_config()
    tracker  = CurriculumTracker(_STATE_PATH, _BENCH_DIR, config)
    state    = tracker.get_state(args.domain)
    palier   = state.current_palier
    questions = tracker.load_questions(args.domain, palier)

    if not questions:
        log.warning("Aucune question active pour %s palier %d", args.domain, palier)
        return

    session_dir = _new_session_dir()
    probe       = ProbeEngine()
    judge_eng   = JudgeEngine(config)
    reporter    = SessionReporter()

    responses  = []
    scores     = []

    responses_path = session_dir / "responses.jsonl"
    scores_path    = session_dir / "scores.jsonl"

    for q in questions:
        resp  = probe.probe(q)
        score = judge_eng.judge(resp, mode=args.judge)

        responses.append(resp)
        scores.append(score)

        with responses_path.open("a", encoding="utf-8-sig") as f:
            f.write(json.dumps(resp.to_dict()) + "\n")
        with scores_path.open("a", encoding="utf-8-sig") as f:
            f.write(json.dumps(score.to_dict()) + "\n")

        tracker.update_state(args.domain, score.final_score)
        log.info("probe: %s → %.1fs | score=%.2f", q.id, resp.duration_sec, score.final_score)

    # Distillation si juge claude
    if args.judge == "claude":
        from EvalLoop.engines.distill_engine import DistillEngine
        distiller = DistillEngine(_DEDUP_PATH, config)
        injected  = distiller.distill(session_dir)
        log.info("distill: %d entrées injectées", injected)

    report = reporter.generate(session_dir, scores, responses, args.domain, palier, args.judge)
    log.info("Rapport : %s", report)


def cmd_distill(args):
    """Distille une session existante dans MemoryEngine."""
    from EvalLoop.engines.distill_engine import DistillEngine
    config    = _load_config()
    session   = Path(args.session)
    if not session.exists():
        log.warning("Session introuvable : %s", session)
        return
    distiller = DistillEngine(_DEDUP_PATH, config)
    injected  = distiller.distill(session)
    log.info("distill: %d entrées injectées depuis %s", injected, session)


def cmd_report(args):
    """Génère ou régénère le rapport d'une session."""
    import json
    from EvalLoop.engines.session_reporter import SessionReporter
    from EvalLoop.evalloop_types import JudgeScore, ProbeResponse

    session = Path(args.session)
    if not session.exists():
        log.warning("Session introuvable : %s", session)
        return

    scores_path    = session / "scores.jsonl"
    responses_path = session / "responses.jsonl"
    scores    = []
    responses = []

    if scores_path.exists():
        for line in scores_path.read_text(encoding="utf-8-sig").strip().splitlines():
            if line.strip():
                scores.append(JudgeScore(**json.loads(line)))

    if responses_path.exists():
        for line in responses_path.read_text(encoding="utf-8-sig").strip().splitlines():
            if line.strip():
                responses.append(ProbeResponse.from_dict(json.loads(line)))

    reporter = SessionReporter()
    report   = reporter.generate(session, scores, responses, "unknown", 0, "local")
    log.info("Rapport généré : %s", report)


def cmd_review_bench(args):
    """Interface interactive (ou export/apply) pour valider les questions draft."""
    import json
    from EvalLoop.evalloop_types import BenchQuestion

    bench_path = _BENCH_DIR / args.domain / f"palier_{args.palier}.json"
    if not bench_path.exists():
        log.warning("Fichier benchmark absent : %s", bench_path)
        return

    questions = json.loads(bench_path.read_text(encoding="utf-8-sig"))
    drafts    = [q for q in questions if q.get("status") == "draft"]

    if not drafts:
        print("Aucune question draft à valider.")
        return

    if args.export:
        export_path = Path(args.export)
        export_path.write_text(json.dumps(drafts, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Exporté {len(drafts)} questions draft vers {export_path}")
        return

    if args.apply:
        apply_path = Path(args.apply)
        updated    = json.loads(apply_path.read_text(encoding="utf-8"))
        updated_ids = {q["id"]: q for q in updated}
        new_questions = []
        for q in questions:
            if q["id"] in updated_ids:
                new_questions.append(updated_ids[q["id"]])
            else:
                new_questions.append(q)
        tmp = bench_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(new_questions, indent=2, ensure_ascii=False), encoding="utf-8-sig")
        tmp.replace(bench_path)
        print(f"Applied {len(updated)} updates.")
        return

    # Mode interactif
    for i, q in enumerate(drafts, 1):
        print(f"\n[{i}/{len(drafts)}] {q['question']}")
        print(f"  Concepts : {q.get('expected_concepts', [])}")
        choice = input("[y] Activer | [n] Rejeter | [s] Sauter > ").strip().lower()
        if choice == "y":
            q["status"] = "active"
        elif choice == "n":
            q["status"] = "rejected"

    tmp = bench_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(questions, indent=2, ensure_ascii=False), encoding="utf-8-sig")
    tmp.replace(bench_path)
    print("Benchmark mis à jour.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="lcca_eval",
        description="EvalLoop - Benchmark curriculum LCCA",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # probe
    p_probe = sub.add_parser("probe", help="Soumettre des questions a Ollama")
    p_probe.add_argument("--domain", required=True)
    p_probe.add_argument("--palier", type=int, default=None)
    p_probe.add_argument("--judge", choices=["local", "claude"], default="local")
    p_probe.set_defaults(func=cmd_probe)

    # run
    p_run = sub.add_parser("run", help="Pipeline complet probe -> judge -> distill -> report")
    p_run.add_argument("--domain", required=True)
    p_run.add_argument("--judge", choices=["local", "claude"], default="local")
    p_run.set_defaults(func=cmd_run)

    # distill
    p_distill = sub.add_parser("distill", help="Injecter une session dans MemoryEngine")
    p_distill.add_argument("--session", required=True)
    p_distill.set_defaults(func=cmd_distill)

    # report
    p_report = sub.add_parser("report", help="Generer le rapport d'une session")
    p_report.add_argument("--session", required=True)
    p_report.set_defaults(func=cmd_report)

    # review-bench
    p_review = sub.add_parser("review-bench", help="Valider les questions draft")
    p_review.add_argument("--domain", required=True)
    p_review.add_argument("--palier", type=int, required=True)
    p_review.add_argument("--export", default=None)
    p_review.add_argument("--apply", default=None)
    p_review.set_defaults(func=cmd_review_bench)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    main()
