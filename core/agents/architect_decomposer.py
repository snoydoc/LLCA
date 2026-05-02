# -*- coding: utf-8-sig -*-
"""
LCCA V8 -- ArchitectDecomposer : logique de decomposition des intents.

Extrait de architect_agent.py (REFACTO-06).

Responsabilites :
    1. Detection de domaine heuristique (_detect_domain, _DOMAIN_HINTS)
    2. Decomposition heuristique (_decompose_intent)
    3. Prompts LLM (_ARCHITECT_SYSTEM, _ARCHITECT_USER_TMPL)
    4. Parsing reponse JSON LLM (_parse_llm_decomposition)
    5. ArchitectDecomposer : orchestre les deux strategies et retourne
       (List[TaskContract], decomposed_by: str)

Ces elements n'ont aucune dependance vers BaseAgent / A2ALocalBus.
Ils peuvent etre testes en complete isolation.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import List, Optional, Tuple, TYPE_CHECKING

from core.agents.a2a_bus import TaskContract

if TYPE_CHECKING:
    from core.llm_generator import LLMGenerator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompts LLM (V8-09)
# ---------------------------------------------------------------------------

_ARCHITECT_SYSTEM = (
    "You are LCCA ArchitectAgent, an expert software planner. "
    "Decompose a development intent into 1 to 3 atomic sub-tasks for a CoderAgent. "
    "Each sub-task must be self-contained and implementable in a single Python function or module. "
    "Respond ONLY with a JSON array, no explanations, no markdown fences. "
    "Format: [{\"intent\": \"...\", \"domain\": \"...\"}] "
    "Domains: ui | api | database | test | infra | global"
)

_ARCHITECT_USER_TMPL = "Decompose this intent into sub-tasks:\n{intent}"


# ---------------------------------------------------------------------------
# Decomposition heuristique
# ---------------------------------------------------------------------------

_DOMAIN_HINTS = {
    "ui":       ["ui", "page", "component", "widget", "form", "modal"],
    "api":      ["api", "endpoint", "route", "rest", "graphql"],
    "database": ["db", "database", "model", "schema", "migration"],
    "test":     ["test", "spec", "coverage", "assert"],
    "infra":    ["deploy", "docker", "ci", "pipeline", "infra"],
}


def _detect_domain(intent: str) -> str:
    """Detecte le domaine d'un intent par correspondance de mots-cles."""
    low = intent.lower()
    for domain, keywords in _DOMAIN_HINTS.items():
        if any(k in low for k in keywords):
            return domain
    return "global"


def _decompose_intent(intent: str, parent_task_id: str) -> List[TaskContract]:
    """
    Decomposition heuristique d'un intent en sous-contrats CoderAgent.

    Regles :
    - Si intent contient ' and ' ou ' et ', on split en 2 sous-taches.
    - Sinon, 1 seul contrat (cas le plus frequent).
    - Chaque sous-contrat a un task_id unique derive du parent + index.
    """
    parts = [intent]
    for sep in (" and ", " et ", " ; ", " + "):
        if sep in intent.lower():
            idx = intent.lower().find(sep)
            parts = [intent[:idx].strip(), intent[idx + len(sep):].strip()]
            break

    contracts = []
    for i, part in enumerate(parts):
        sub_id  = hashlib.md5(f"{parent_task_id}:{i}:{part}".encode()).hexdigest()[:12]
        task_id = f"coder_{sub_id}"
        contracts.append(
            TaskContract(
                task_id=task_id,
                intent=part,
                domain=_detect_domain(part),
                source_agent="architect",
                target_agent="coder",
                context={"decomposition_index": i, "total_parts": len(parts)},
                constraints=[],
                parent_task_id=parent_task_id,
            )
        )
    return contracts


# ---------------------------------------------------------------------------
# Decomposition LLM (V8-09)
# ---------------------------------------------------------------------------

def _parse_llm_decomposition(raw: str, parent_task_id: str) -> List[TaskContract]:
    """
    Parse la reponse JSON du LLM en liste de TaskContracts.

    Format attendu : [{"intent": str, "domain": str}, ...]
    Retourne [] si la reponse est malformee (le fallback heuristique prend le relai).

    Securite :
    - Nettoie les fences markdown eventuelles.
    - Plafonne a 3 sous-contrats.
    - Valide que chaque item a une cle 'intent' non vide.
    - Domaine invalide -> "global".
    """
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()

    try:
        items = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        logger.debug("[architect] _parse_llm_decomposition: JSON invalide raw=%r", raw[:120])
        return []

    if not isinstance(items, list) or not items:
        return []

    contracts = []
    for i, item in enumerate(items[:3]):  # plafond 3
        if not isinstance(item, dict):
            continue
        intent_str = str(item.get("intent", "")).strip()
        if not intent_str:
            continue
        domain_str = str(item.get("domain", "global")).strip().lower()
        if domain_str not in {"ui", "api", "database", "test", "infra", "global"}:
            domain_str = "global"
        sub_id  = hashlib.md5(f"{parent_task_id}:llm:{i}:{intent_str}".encode()).hexdigest()[:12]
        task_id = f"coder_{sub_id}"
        contracts.append(
            TaskContract(
                task_id=task_id,
                intent=intent_str,
                domain=domain_str,
                source_agent="architect",
                target_agent="coder",
                context={
                    "decomposition_index": i,
                    "total_parts": len(items[:3]),
                    "decomposed_by": "llm",
                },
                constraints=[],
                parent_task_id=parent_task_id,
            )
        )
    return contracts


# ---------------------------------------------------------------------------
# ArchitectDecomposer
# ---------------------------------------------------------------------------

class ArchitectDecomposer:
    """
    Orchestre les deux strategies de decomposition (LLM et heuristique).

    Usage :
        decomposer = ArchitectDecomposer()
        contracts, by = decomposer.decompose(contract, llm=self._llm)
        # by == "llm" ou "heuristic"

    Separation des responsabilites :
        - ArchitectDecomposer : connait la decomposition, rien d'autre.
        - ArchitectAgent      : connait le bus, le MCP, le routage.
    """

    def decompose(
        self,
        contract: TaskContract,
        llm: "Optional[LLMGenerator]" = None,
    ) -> Tuple[List[TaskContract], str]:
        """
        Decompose un contrat en sous-contrats CoderAgent.

        Strategie :
        1. Tente la decomposition LLM si llm n'est pas None.
        2. Si le LLM retourne [] (absent, echec, JSON invalide) -> heuristique.

        Args:
            contract : contrat source (intent + task_id utilises).
            llm      : LLMGenerator injecte, ou None.

        Returns:
            Tuple (List[TaskContract], decomposed_by)
            decomposed_by : "llm" | "heuristic"
        """
        sub_contracts = self._decompose_with_llm(contract, llm)
        if sub_contracts:
            return sub_contracts, "llm"

        sub_contracts = _decompose_intent(contract.intent, contract.task_id)
        logger.debug(
            "[architect_decomposer] heuristique -> %d contrat(s)", len(sub_contracts)
        )
        return sub_contracts, "heuristic"

    def _decompose_with_llm(
        self,
        contract: TaskContract,
        llm: "Optional[LLMGenerator]",
    ) -> List[TaskContract]:
        """
        Tente une decomposition via LLMGenerator.generate_text().

        Retourne [] si llm est None, si la reponse est vide,
        si le JSON est malforme, ou si une exception est levee.
        Ne leve jamais — le fallback heuristique prend le relai.
        """
        if llm is None:
            return []

        user_prompt = _ARCHITECT_USER_TMPL.format(intent=contract.intent)
        try:
            raw = llm.generate_text(system=_ARCHITECT_SYSTEM, user=user_prompt)
            if not raw or not raw.strip():
                logger.debug("[architect_decomposer] reponse LLM vide")
                return []
            contracts = _parse_llm_decomposition(raw.strip(), contract.task_id)
            if contracts:
                logger.info(
                    "[architect_decomposer] LLM OK : %d sous-contrat(s) pour %r",
                    len(contracts), contract.intent[:60],
                )
            else:
                logger.debug("[architect_decomposer] parse retourne [] -> fallback")
            return contracts
        except Exception as exc:
            logger.warning("[architect_decomposer] erreur LLM : %s", exc)
            return []
