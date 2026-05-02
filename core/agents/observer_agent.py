# -*- coding: utf-8-sig -*-
"""
LCCA V8 -- ObserverAgent : maintenance memoire et audit trail.

Responsabilites :
    1. Surveiller la collection lcca_skills (dedoublonnage, elagage des scores faibles).
    2. Archiver les ExecutionReceipts anciens (> seuil).
    3. Construire un rapport d'etat memoire (snapshot).
    4. Signaler les anomalies via A2ALocalBus (sans modifier core/).

Tools MCP autorises : memory_search, memory_store
V8-Regle-20 : ne modifie jamais core/ directement.
V8-Regle-21 : toute communication passe par A2ALocalBus.
REFACTO-03 : analyse extraite dans observer_analyzer.py.
REFACTO-08 : rapport/archivage extraits dans observer_reporter.py.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent, AgentResult
from .agent_card import AgentCard, AGENT_MCP_ALLOWLIST, OBSERVER_POLICY
from .a2a_bus import A2ALocalBus, TaskContract
from .observer_analyzer import ObserverAnalyzer, _is_duplicate, _build_snapshot  # REFACTO-03
from .observer_reporter import (                                                   # REFACTO-08
    ObserverReporter,
    make_report_id,
    should_archive,
    _make_report_id,
    _should_archive,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
_MIN_SKILL_SCORE       : int   = 40
_MAX_DUPLICATE_SIM     : float = 0.95
_DEFAULT_ARCHIVE_AFTER_DAYS: int = 30


# ---------------------------------------------------------------------------
# ObserverAgent
# ---------------------------------------------------------------------------

class ObserverAgent(BaseAgent):
    """
    Agent Observateur V8.

    Flux principal (run_task) :
        1. Recuperer les skills depuis lcca_skills.
        2. Identifier les skills a faible score (< _MIN_SKILL_SCORE).
        3. Identifier les doublons (heuristique Jaccard).
        4. Archiver les receipts anciens (via ObserverReporter).
        5. Construire un snapshot (via ObserverAnalyzer).
        6. Stocker le snapshot (via ObserverReporter).
        7. Retourner AgentResult(success=True, payload=snapshot).
    """

    def __init__(
        self,
        card: AgentCard,
        bus: A2ALocalBus,
        mcp_caller=None,
        memory_engine=None,
        receipts_dir: Optional[Path] = None,
        archive_after_days: int = _DEFAULT_ARCHIVE_AFTER_DAYS,
        min_skill_score: int = _MIN_SKILL_SCORE,
        max_duplicate_sim: float = _MAX_DUPLICATE_SIM,
    ) -> None:
        super().__init__(card=card, bus=bus, mcp_caller=mcp_caller)
        self._memory             = memory_engine
        self._archive_after_days = archive_after_days
        self._min_skill_score    = min_skill_score
        self._max_duplicate_sim  = max_duplicate_sim

        # REFACTO-03 : couche d'analyse
        self._analyzer = ObserverAnalyzer(
            min_skill_score=min_skill_score,
            max_duplicate_sim=max_duplicate_sim,
        )

        # Chemin des receipts
        if receipts_dir is not None:
            self._receipts_dir = receipts_dir
        else:
            try:
                from core.receipt_store import RECEIPTS_DIR
                self._receipts_dir = RECEIPTS_DIR
            except ImportError:
                self._receipts_dir = None

        # REFACTO-08 : couche rapport/archivage
        self._reporter = ObserverReporter(
            receipts_dir=self._receipts_dir,
            archive_after_days=archive_after_days,
            memory_engine=memory_engine,
            mcp_caller=mcp_caller,
        )

    @classmethod
    def create(
        cls,
        bus: A2ALocalBus,
        mcp_caller=None,
        memory_engine=None,
        receipts_dir: Optional[Path] = None,
        archive_after_days: int = _DEFAULT_ARCHIVE_AFTER_DAYS,
    ) -> "ObserverAgent":
        """Factory : cree une instance avec AgentCard par defaut."""
        card = AgentCard(
            name="observer",
            version="8.0.0",
            capabilities=["maintenance", "memory_search", "memory_store"],
            mcp_tools=AGENT_MCP_ALLOWLIST["observer"],
            recovery_policy=OBSERVER_POLICY,
            description="Maintenance memoire : dedoublonnage skills, archivage receipts",
        )
        return cls(
            card=card,
            bus=bus,
            mcp_caller=mcp_caller,
            memory_engine=memory_engine,
            receipts_dir=receipts_dir,
            archive_after_days=archive_after_days,
        )

    # ------------------------------------------------------------------
    # Interface BaseAgent
    # ------------------------------------------------------------------

    def run_task(self, contract: TaskContract) -> AgentResult:
        """Execute le cycle d'observation memoire."""
        logger.info("[observer] run_task task_id=%s", contract.task_id)

        min_score  = contract.context.get("min_skill_score",   self._min_skill_score)
        max_sim    = contract.context.get("max_duplicate_sim",  self._max_duplicate_sim)
        force_arch = bool(contract.context.get("force_archive", False))

        try:
            skills       = self._load_skills()
            skills_count = len(skills)

            low_quality = self._analyzer.find_low_quality(skills, min_score=min_score)
            duplicates  = self._analyzer.find_duplicates(skills, max_sim=max_sim)
            archived    = self._reporter.archive_old_receipts(force=force_arch)

            snapshot = self._analyzer.build_snapshot(
                skills_count=skills_count,
                low_quality=low_quality,
                duplicates=duplicates,
                archived=archived,
            )

            self._reporter.store_snapshot(snapshot)

            logger.info(
                "[observer] OK skills=%d low=%d dup=%d archived=%d",
                skills_count, len(low_quality), len(duplicates), len(archived),
            )
            return AgentResult(
                success=True,
                payload={
                    "task_id":   contract.task_id,
                    "snapshot":  snapshot,
                    "report_id": make_report_id(
                        self.card.name,
                        snapshot["observed_at"],
                    ),
                },
            )

        except PermissionError:
            raise
        except Exception as exc:
            return self._handle_error(exc, contract)

    # ------------------------------------------------------------------
    # Boucle de consommation bus
    # ------------------------------------------------------------------

    def run_once(self, timeout_sec: int = 5) -> Optional[AgentResult]:
        """Consomme un message du bus et execute run_task."""
        msg = self._receive(timeout_sec=timeout_sec)
        if msg is None:
            return None

        payload      = msg.payload
        contract_dict = payload.get("contract", {})

        if contract_dict:
            contract = TaskContract.from_dict(contract_dict)
        else:
            contract = TaskContract(
                task_id=msg.task_id,
                intent=payload.get("intent", "observe"),
                domain=payload.get("domain", "global"),
                source_agent=msg.from_agent,
                target_agent="observer",
            )

        for key in ("min_skill_score", "max_duplicate_sim", "force_archive"):
            if key in payload:
                contract.context[key] = payload[key]

        return self.run_task(contract)

    # ------------------------------------------------------------------
    # Helpers prives : chargement skills
    # ------------------------------------------------------------------

    def _load_skills(self) -> List[Dict[str, Any]]:
        """Charge les skills depuis lcca_skills (memory_engine ou MCP)."""
        if self._memory is not None:
            try:
                results = self._memory.search("skill", n=200)
                raw = results.get("skills", [])
                return [
                    {
                        "id":       getattr(e, "id",       ""),
                        "body":     getattr(e, "content",  ""),
                        "score":    float(getattr(e, "metadata", {}).get("quality_score", 0)),
                        "metadata": getattr(e, "metadata", {}),
                    }
                    for e in raw
                ]
            except Exception as exc:
                logger.debug("[observer] _load_skills memory_engine: %s", exc)

        try:
            result = self._call_mcp("memory_search", {"query": "skill", "n": 200})
            items  = result.get("items", result.get("results", []))
            if isinstance(items, list):
                return [
                    {
                        "id":       item.get("id", ""),
                        "body":     item.get("content", item.get("body", "")),
                        "score":    float(item.get("score", item.get("quality_score", 0))),
                        "metadata": item,
                    }
                    for item in items
                ]
        except PermissionError:
            raise
        except Exception as exc:
            logger.debug("[observer] _load_skills MCP: %s", exc)

        return []

    # ------------------------------------------------------------------
    # Wrappers retrocompat REFACTO-03
    # ------------------------------------------------------------------

    def _find_low_quality(self, skills, min_score):
        """Wrapper retrocompat -> ObserverAnalyzer.find_low_quality()."""
        return self._analyzer.find_low_quality(skills, min_score=min_score)

    def _find_duplicates(self, skills, max_sim):
        """Wrapper retrocompat -> ObserverAnalyzer.find_duplicates()."""
        return self._analyzer.find_duplicates(skills, max_sim=max_sim)

    # ------------------------------------------------------------------
    # Wrappers retrocompat REFACTO-08
    # ------------------------------------------------------------------

    def _archive_old_receipts(self, force: bool = False) -> List[str]:
        """Wrapper retrocompat -> ObserverReporter.archive_old_receipts()."""
        return self._reporter.archive_old_receipts(force=force)

    def _store_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Wrapper retrocompat -> ObserverReporter.store_snapshot()."""
        self._reporter.store_snapshot(snapshot)
