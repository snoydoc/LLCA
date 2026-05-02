# -*- coding: utf-8-sig -*-
"""
orchestrator_loop.py -- REFACTO-04 : boucle KarpathyLoop extraite de agent_orchestrator.py

Responsabilites :
    - Executer une iteration Architect -> Coder -> Reviewer -> Tester
    - Gerer timeout global, stagnation, reflections
    - Retourner un LoopResult intermediaire consomme par AgentOrchestrator

AgentOrchestrator conserve l'API publique (run, create), la gestion
Educator (V9-07), et la construction de OrchestratorResult.
Cette classe est injectee dans AgentOrchestrator.__init__() pour
permettre les tests unitaires directs de la boucle.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from .a2a_bus import A2ALocalBus, TaskContract
from .base_agent import AgentResult

logger = logging.getLogger("lcca.orchestrator_loop")


# ---------------------------------------------------------------------------
# LoopResult
# ---------------------------------------------------------------------------

@dataclass
class LoopResult:
    """
    Resultat intermediaire de la KarpathyLoop.

    Consomme par AgentOrchestrator pour construire OrchestratorResult.
    """
    success: bool
    iterations: int = 0
    final_quality: int = 0
    last_error: Optional[str] = None
    reflections: list[str] = field(default_factory=list)
    timed_out: bool = False


# ---------------------------------------------------------------------------
# KarpathyLoop
# ---------------------------------------------------------------------------

class KarpathyLoop:
    """
    Boucle d'iteration multi-agent (REFACTO-04).

    Execute le pipeline Architect -> Coder -> Reviewer -> Tester
    en boucle jusqu'au succes, a la stagnation ou au timeout.

    Args:
        architect      : ArchitectAgent
        coder          : CoderAgent
        reviewer       : ReviewerAgent
        tester         : TesterAgent
        skill_library  : SkillLibrary optionnelle
        max_iterations : Nombre max d'iterations
        max_stagnation : Seuil de stagnation avant arret anticipe
        timeout_sec    : Timeout global en secondes

    Usage::

        loop = KarpathyLoop(architect, coder, reviewer, tester,
                            max_iterations=20, max_stagnation=3, timeout_sec=3600)
        result = loop.run(task_id, intent, deadline)
    """

    def __init__(
        self,
        architect,
        coder,
        reviewer,
        tester,
        skill_library=None,
        max_iterations: int = 20,
        max_stagnation: int = 3,
        timeout_sec: int = 3600,
    ) -> None:
        self._architect = architect
        self._coder = coder
        self._reviewer = reviewer
        self._tester = tester
        self._skill_lib = skill_library
        self._max_iter = max_iterations
        self._max_stagnation = max_stagnation
        self._timeout_sec = timeout_sec

    def run(self, task_id: str, intent: str, deadline: float) -> LoopResult:
        """
        Execute la boucle KarpathyLoop jusqu'au succes, stagnation ou timeout.

        Args:
            task_id  : identifiant de la tache racine
            intent   : intent utilisateur
            deadline : time.monotonic() cible — compare a chaque iteration

        Retourne un LoopResult.
        """
        reflections: list[str] = []
        quality_history: list[int] = []
        # FL-01 : accumule les reflexions structurees (liste locale a run())
        structured_reflections: list[dict] = []
        success = False
        final_quality = 0
        last_error: Optional[str] = None

        for iteration in range(self._max_iter):

            # --- Timeout ---
            if time.monotonic() > deadline:
                logger.warning("[loop] timeout apres %d iterations", iteration)
                return LoopResult(
                    success=False,
                    iterations=iteration,
                    final_quality=final_quality,
                    last_error="Pipeline timeout",
                    reflections=reflections,
                    timed_out=True,
                )

            logger.info("[loop] --- iteration %d/%d ---", iteration + 1, self._max_iter)

            # --- Contrat Architect ---
            arch_context: dict = {}
            if reflections:
                arch_context["reflection"] = " | ".join(reflections[-3:])

            # FL-01 : injecter fix_hints + last_quality_score des 2 dernieres iterations
            if structured_reflections:
                recent_hints: list[str] = []
                for sr in structured_reflections[-2:]:
                    recent_hints.extend(sr.get("fix_hints", []))
                seen: set[str] = set()
                deduped: list[str] = []
                for h in recent_hints:
                    if h not in seen:
                        seen.add(h)
                        deduped.append(h)
                arch_context["fix_hints"]          = deduped[:10]
                arch_context["last_quality_score"] = structured_reflections[-1].get("quality_score", 0)

            arch_contract = TaskContract(
                task_id=task_id,
                intent=intent,
                domain="global",
                source_agent="orchestrator",
                target_agent="architect",
                context=arch_context,
            )

            arch_result = self._architect.run_task(arch_contract)

            # Timeout post-Architect
            if time.monotonic() > deadline:
                logger.warning("[loop] timeout post-Architect iteration=%d", iteration)
                return LoopResult(
                    success=False,
                    iterations=iteration + 1,
                    final_quality=final_quality,
                    last_error="Pipeline timeout",
                    reflections=reflections,
                    timed_out=True,
                )

            if not arch_result.success:
                last_error = arch_result.error
                logger.warning("[loop] Architect failed: %s", last_error)
                continue

            dispatched = arch_result.payload.get("dispatched", [])
            if not dispatched:
                last_error = "Architect n'a dispatche aucun sous-contrat"
                logger.warning("[loop] %s", last_error)
                continue

            # --- Sous-contrat Coder ---
            sub_task_id = dispatched[0]
            sub_contract = TaskContract(
                task_id=sub_task_id,
                intent=intent,
                domain="global",
                source_agent="architect",
                target_agent="coder",
                context=arch_context.copy(),
            )

            # Injection SkillLibrary
            skill_ids_used: list[str] = []
            if self._skill_lib is not None:
                try:
                    skill_entries = self._skill_lib.retrieve(intent)
                    if skill_entries:
                        skill_prompt = self._skill_lib.format_for_prompt(skill_entries)
                        sub_contract.context["available_skills"] = skill_prompt
                        skill_ids_used = _extract_skill_ids(skill_entries)
                        for sid in skill_ids_used:
                            self._skill_lib.record_usage(sid)
                except Exception as exc:
                    logger.debug("[loop] skill_library.retrieve error: %s", exc)

            # --- Coder ---
            coder_result = self._coder.run_task(sub_contract)
            if not coder_result.success:
                last_error = coder_result.error
                reflections.append(f"Coder[{iteration}]: {last_error}")
                quality_history.append(0)
                if _detect_stagnation(quality_history, self._max_stagnation):
                    logger.warning("[loop] stagnation detectee -> arret anticipe")
                    break
                continue

            generated_code = (
                coder_result.payload.get("generated_code", "")
                or coder_result.payload.get("patch", {}).get("intent", "")
            )

            # --- Reviewer ---
            review_contract = TaskContract(
                task_id=sub_task_id,
                intent=intent,
                domain="global",
                source_agent="coder",
                target_agent="reviewer",
                context={
                    "code": generated_code,
                    "original_payload": coder_result.payload,
                },
            )
            reviewer_result = self._reviewer.run_task(review_contract)

            if not reviewer_result.success:
                reflection = reviewer_result.payload.get("reflection", "Reviewer: rejected")
                reflections.append(f"Reviewer[{iteration}]: {reflection}")
                quality_history.append(0)
                if _detect_stagnation(quality_history, self._max_stagnation):
                    logger.warning("[loop] stagnation detectee -> arret anticipe")
                    break
                continue

            # --- Tester ---
            test_contract = TaskContract(
                task_id=sub_task_id,
                intent=intent,
                domain="global",
                source_agent="reviewer",
                target_agent="tester",
                context={
                    "code": generated_code,
                    "original_payload": coder_result.payload,
                },
            )
            tester_result = self._tester.run_task(test_contract)
            quality_score = tester_result.payload.get("quality_score", 0)
            quality_history.append(quality_score)

            if tester_result.success:
                final_quality = quality_score
                success = True
                # FL-04 : metriques outcome success
                for sid in skill_ids_used:
                    self._skill_lib.record_outcome(sid, success=True)  # type: ignore[union-attr]
                logger.info(
                    "[loop] succes iteration=%d quality=%d",
                    iteration + 1, final_quality,
                )
                break
            else:
                reflection = tester_result.payload.get("reflection", "Tester: rejected")
                reflections.append(f"Tester[{iteration}]: {reflection}")
                # FL-01 : stocker la reflexion structuree
                sr = tester_result.payload.get("reflection_structured")
                if sr:
                    structured_reflections.append(sr)
                last_error = tester_result.error
                # FL-04 : metriques outcome failure
                for sid in skill_ids_used:
                    self._skill_lib.record_outcome(sid, success=False)  # type: ignore[union-attr]

                if _detect_stagnation(quality_history, self._max_stagnation):
                    logger.warning(
                        "[loop] stagnation quality_history=%s -> arret",
                        quality_history[-self._max_stagnation:],
                    )
                    break

        return LoopResult(
            success=success,
            iterations=len(quality_history),
            final_quality=final_quality,
            last_error=last_error,
            reflections=reflections,
            timed_out=False,
        )


# ---------------------------------------------------------------------------
# Helpers module-level
# ---------------------------------------------------------------------------

def _extract_skill_ids(skill_entries) -> list[str]:
    """
    Extrait les skill_id depuis une liste de SkillEntry.

    Retourne une liste vide si skill_entries est None ou vide.
    Silencieux si un entry n'a pas d'attribut skill_id.

    Args:
        skill_entries : liste de SkillEntry (ou tout objet avec .skill_id).

    Returns:
        list[str] de skill_id.
    """
    if not skill_entries:
        return []
    ids: list[str] = []
    for entry in skill_entries:
        sid = getattr(entry, "skill_id", None)
        if sid:
            ids.append(sid)
    return ids


def _detect_stagnation(history: list[int], max_stagnation: int) -> bool:
    """
    Retourne True si les `max_stagnation` derniers scores sont identiques.
    Retourne False si history contient moins d'elements que max_stagnation.
    """
    if len(history) < max_stagnation:
        return False
    tail = history[-max_stagnation:]
    return len(set(tail)) == 1
