# -*- coding: utf-8-sig -*-
"""
LCCA V8 -- AgentOrchestrator : pipeline Architect → Coder → Reviewer → Tester.

Responsabilites :
    1. run(intent) : declenche le pipeline complet pour un intent.
    2. KarpathyLoop : repete le pipeline si le Tester echoue, avec reflexion injectee.
       - Limite : KARPATHY_MAX_ITERATIONS (config, defaut=20)
       - Arret anticipé : KARPATHY_MAX_STAGNATION iterations sans amelioration (V8-Regle-18)
    3. Injection SkillLibrary : avant chaque appel Coder, retrieve() et format_for_prompt()
       sont appeles pour enrichir le contexte.
    4. Timeout global : AGENT_PIPELINE_TIMEOUT secondes (config, defaut=120)
    5. Retourne OrchestratorResult avec les metriques de la boucle.

V8-Regle-18 : arret apres KARPATHY_MAX_STAGNATION iterations sans amelioration.
V8-Regle-20 : ne modifie jamais core/ directement.
V8-Regle-21 : toute communication passe par A2ALocalBus.

Usage::

    bus = A2ALocalBus(db_path=":memory:")
    orch = AgentOrchestrator.create(bus=bus)
    result = orch.run("Creer une fonction parse_json dans utils/parser.py")
    print(result.success, result.iterations, result.final_quality)
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from config import (
    AGENT_PIPELINE_TIMEOUT,
    KARPATHY_MAX_ITERATIONS,
    KARPATHY_MAX_STAGNATION,
)
from .a2a_bus import A2ALocalBus, TaskContract
from .agent_card import (
    AgentCard,
    AgentRegistry,
    AGENT_MCP_ALLOWLIST,
    ARCHITECT_POLICY,
)
from .base_agent import BaseAgent, AgentResult
from .architect_agent import ArchitectAgent
from .coder_agent import CoderAgent
from .reviewer_agent import ReviewerAgent
from .tester_agent import TesterAgent
from .educator_agent import EducatorAgent  # V9-07
from .orchestrator_loop import KarpathyLoop, LoopResult, _detect_stagnation  # REFACTO-04

logger = logging.getLogger("lcca.agent_orchestrator")


# ---------------------------------------------------------------------------
# OrchestratorResult
# ---------------------------------------------------------------------------

@dataclass
class OrchestratorResult:
    """
    Resultat du pipeline complet pour un intent.

    success         : True si le pipeline s'est termine avec succes (Tester OK).
    iterations      : Nombre d'iterations effectuees dans la KarpathyLoop.
    final_quality   : Dernier quality_score retourne par le Tester (0 si echec).
    task_id         : task_id racine attribue a cet intent.
    error           : Message d'erreur si success=False.
    reflections     : Liste des reflexions accumulees (Reviewer + Tester).
    timed_out       : True si le timeout global a ete depasse.
    educator_skills : Nombre de skills ingestee par l'EducatorAgent (0 si absent). V9-07
    """
    success: bool
    iterations: int = 0
    final_quality: int = 0
    task_id: str = ""
    error: Optional[str] = None
    reflections: list = field(default_factory=list)
    timed_out: bool = False
    educator_skills: int = 0  # V9-07

    def is_ok(self) -> bool:
        return self.success


# ---------------------------------------------------------------------------
# Helpers module-level
# ---------------------------------------------------------------------------

def _make_task_id(intent: str) -> str:
    """MD5 12 chars de l'intent + timestamp ns — garanti unique meme en rafale."""
    raw = f"{intent}:{time.perf_counter_ns()}"
    return "orch_" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

# _detect_stagnation : re-exporte depuis orchestrator_loop (REFACTO-04 retrocompat)


# ---------------------------------------------------------------------------
# AgentOrchestrator
# ---------------------------------------------------------------------------

class AgentOrchestrator:
    """
    Orchestrateur du pipeline multi-agent V8.

    Le pipeline est synchrone et lineaire (V8-06) :
        Architect -> Coder -> Reviewer -> Tester

    Si Reviewer ou Tester rejette, la reflexion est injectee dans le
    prochain contrat Architect (KarpathyLoop).

    Args:
        bus            : A2ALocalBus partagee entre tous les agents.
        architect      : ArchitectAgent injecte.
        coder          : CoderAgent injecte.
        reviewer       : ReviewerAgent injecte.
        tester         : TesterAgent injecte.
        skill_library  : SkillLibrary optionnelle — enrichit le contexte Coder.
        max_iterations : Override config.KARPATHY_MAX_ITERATIONS.
        max_stagnation : Override config.KARPATHY_MAX_STAGNATION.
        timeout_sec    : Override config.AGENT_PIPELINE_TIMEOUT.
    """

    def __init__(
        self,
        bus: A2ALocalBus,
        architect: ArchitectAgent,
        coder: CoderAgent,
        reviewer: ReviewerAgent,
        tester: TesterAgent,
        skill_library=None,
        educator: Optional[EducatorAgent] = None,
        model_router=None,                          # FL-02
        max_iterations: int = KARPATHY_MAX_ITERATIONS,
        max_stagnation: int = KARPATHY_MAX_STAGNATION,
        timeout_sec: int = AGENT_PIPELINE_TIMEOUT,
    ) -> None:
        self._bus = bus
        self._architect = architect
        self._coder = coder
        self._reviewer = reviewer
        self._tester = tester
        self._skill_lib = skill_library
        self._educator = educator
        self._model_router = model_router           # FL-02
        self._max_iter = max_iterations
        self._max_stagnation = max_stagnation
        self._timeout_sec = timeout_sec
        # REFACTO-04 : boucle decouple
        self._loop = KarpathyLoop(
            architect=architect,
            coder=coder,
            reviewer=reviewer,
            tester=tester,
            skill_library=skill_library,
            max_iterations=max_iterations,
            max_stagnation=max_stagnation,
            timeout_sec=timeout_sec,
        )

    @classmethod
    def create(
        cls,
        bus: A2ALocalBus,
        mcp_caller=None,
        skill_library=None,
        educator: Optional[EducatorAgent] = None,
        model_router=None,                          # FL-02 : injectable pour les tests
        max_iterations: int = KARPATHY_MAX_ITERATIONS,
        max_stagnation: int = KARPATHY_MAX_STAGNATION,
        timeout_sec: int = AGENT_PIPELINE_TIMEOUT,
    ) -> "AgentOrchestrator":
        """
        Factory : cree un orchestrateur avec les 4 agents par defaut.

        mcp_caller et skill_library sont injectes dans tous les agents.
        educator optionnel (V9-07) : si None, le satellite de curation est desactive.
        model_router optionnel (FL-02) : si None, ModelRouter est instancie automatiquement.
        """
        # FL-02 : instancier ModelRouter par defaut si non injecte
        if model_router is None:
            try:
                from core.model_router import ModelRouter
                model_router = ModelRouter()
            except Exception as exc:
                logger.debug("[orchestrator] ModelRouter non disponible : %s", exc)
                model_router = None

        coder = CoderAgent.create(
            bus=bus,
            mcp_caller=mcp_caller,
            model_router=model_router,              # FL-02
        )
        return cls(
            bus=bus,
            architect=ArchitectAgent.create(bus=bus, mcp_caller=mcp_caller),
            coder=coder,
            reviewer=ReviewerAgent.create(bus=bus, mcp_caller=mcp_caller),
            tester=TesterAgent.create(bus=bus, mcp_caller=mcp_caller, skill_library=skill_library),
            skill_library=skill_library,
            educator=educator,
            model_router=model_router,              # FL-02
            max_iterations=max_iterations,
            max_stagnation=max_stagnation,
            timeout_sec=timeout_sec,
        )

    # ------------------------------------------------------------------
    # API principale
    # ------------------------------------------------------------------

    def run(self, intent: str) -> OrchestratorResult:
        """
        Declenche le pipeline complet pour un intent.

        Delegue la boucle KarpathyLoop a self._loop (REFACTO-04).
        Gere le timeout immediat (timeout_sec <= 0) et l'Educator post-pipeline (V9-07).

        Retourne OrchestratorResult.
        """
        task_id = _make_task_id(intent)
        logger.info("[orchestrator] run intent=%r task_id=%s", intent, task_id)

        # timeout_sec=0 ou negatif -> timeout immediat sans entrer dans la boucle
        if self._timeout_sec <= 0:
            return OrchestratorResult(
                success=False,
                iterations=0,
                final_quality=0,
                task_id=task_id,
                error="Pipeline timeout",
                reflections=[],
                timed_out=True,
            )

        deadline = time.monotonic() + self._timeout_sec
        loop_result: LoopResult = self._loop.run(task_id, intent, deadline)

        # V9-07 : declencher une passe de curation EducatorAgent si disponible
        educator_skills = 0
        if self._educator is not None:
            try:
                from .a2a_bus import TaskContract as _TC
                edu_contract = _TC(
                    task_id=task_id,
                    intent=intent,
                    domain="global",
                    source_agent="orchestrator",
                    target_agent="educator",
                    context={"dry_run": False},
                )
                edu_result = self._educator.run_task(edu_contract)
                if edu_result.success:
                    educator_skills = edu_result.payload.get("skills_ingested", 0)
                    logger.info("[orchestrator] educator skills_ingested=%d", educator_skills)
            except Exception as _exc:
                logger.debug("[orchestrator] educator.run_task error: %s", _exc)

        # Timeout detecte dans la loop -> retour immediat
        if loop_result.timed_out:
            return OrchestratorResult(
                success=False,
                iterations=loop_result.iterations,
                final_quality=loop_result.final_quality,
                task_id=task_id,
                error=loop_result.last_error,
                reflections=loop_result.reflections,
                timed_out=True,
            )

        return OrchestratorResult(
            success=loop_result.success,
            iterations=loop_result.iterations,
            final_quality=loop_result.final_quality,
            task_id=task_id,
            error=loop_result.last_error if not loop_result.success else None,
            reflections=loop_result.reflections,
            timed_out=False,
            educator_skills=educator_skills,
        )
