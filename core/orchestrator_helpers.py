# -*- coding: utf-8-sig -*-
"""
orchestrator_helpers.py — REFACTO-18
Helpers extraits de LCCAV5Fusion : _update_sprint_log() + dry_run().

Responsabilite unique : helpers sans effet de bord sur le pipeline TX.

Expose :
    update_sprint_log(intent, plan, tx_id, llm) -> None
    dry_run(intent_raw, selector, planner, llm) -> dict
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List

log = logging.getLogger("lcca.orchestrator_helpers")


def update_sprint_log(intent, plan: list, tx_id: str, llm) -> None:
    """
    Ajoute une entree dans Docs/Sprints/current-sprint.md.
    Extrait de LCCAV5Fusion._update_sprint_log() — REFACTO-18.
    """
    from config import DOCS_DIR

    log_path = DOCS_DIR / "Sprints" / "current-sprint.md"
    files_str  = ", ".join(op.file for op in plan)
    llm_status = "Ollama" if llm.is_available() else "stub"
    entry = (
        f"\n### {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"- **Commande**: `{intent.raw}`\n"
        f"- **Projet**: {intent.project} | **Action**: {intent.action}\n"
        f"- **Fichiers modifies**: {files_str}\n"
        f"- **TX**: `{tx_id}` | **LLM**: {llm_status}\n"
    )
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)
        log.info("Sprint log mis a jour: %s", log_path)
    except Exception as exc:
        log.warning("Impossible de mettre a jour le sprint log: %s", exc)


def dry_run(intent_raw: str, selector, planner, llm) -> dict:
    """
    Simule l'execution sans toucher au disque.
    Extrait de LCCAV5Fusion.dry_run() — REFACTO-18.

    Args:
        intent_raw : commande brute (str).
        selector   : FileSelector.
        planner    : MultiFilePlanner.
        llm        : LLMGenerator.

    Returns:
        dict avec intent, target_files, plan, plan_valid, plan_errors, llm_available.
    """
    from core.dsl_parser import DSLParser

    intent       = DSLParser().parse(intent_raw)
    target_files = selector.select(intent)
    plan         = planner.create_plan(
        intent_details=intent.details,
        target_files=target_files,
        intent_action=intent.action,
        intent_target=intent.target,
    )
    valid, errors = planner.validate_plan_consistency(plan)

    return {
        "intent":        intent,
        "target_files":  target_files,
        "plan":          plan,
        "plan_valid":    valid,
        "plan_errors":   errors,
        "llm_available": llm.is_available(),
    }
