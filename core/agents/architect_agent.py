# -*- coding: utf-8-sig -*-
"""
LCCA V8 -- ArchitectAgent : corps cognitif planification.

Responsabilites :
    1. Recevoir un intent (TaskContract depuis bus ou run_task direct).
    2. Appeler memory_search MCP pour chercher des specs existantes.
    3. Decomposer l'intent en sous-contrats CoderAgent (LLM si dispo, sinon heuristique).
    4. Publier chaque sous-contrat sur A2ALocalBus.
    5. Retourner AgentResult avec la liste des task_ids emis.

V8-09 : integration LLMGenerator pour decomposition intelligente.
        Fallback transparent sur heuristique si LLM absent ou echec.
V8-Regle-20 : ne modifie jamais core/ directement.
V8-Regle-21 : toute communication passe par A2ALocalBus.

Sous-module (REFACTO-06) :
    architect_decomposer.py -- logique decomposition (heuristique + LLM + parsing JSON)
"""
from __future__ import annotations

import logging
from typing import List, Optional, TYPE_CHECKING

from .base_agent import BaseAgent, AgentResult
from .agent_card import AgentCard, AgentRegistry, AGENT_MCP_ALLOWLIST, RecoveryPolicy
from .a2a_bus import A2ALocalBus, TaskContract
from .architect_decomposer import (
    ArchitectDecomposer,
    _detect_domain,
    _decompose_intent,
    _parse_llm_decomposition,
    _ARCHITECT_SYSTEM,
    _ARCHITECT_USER_TMPL,
    _DOMAIN_HINTS,
)

if TYPE_CHECKING:
    from core.llm_generator import LLMGenerator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ArchitectAgent
# ---------------------------------------------------------------------------
class ArchitectAgent(BaseAgent):
    """
    Agent Architecte V8.

    Flux principal (run_task) :
        1. memory_search -> specs existantes (optionnel, mode test = {})
        2. _decompose_with_llm() si LLM dispo, sinon _decompose_intent() heuristique
        3. Envoie chaque contrat sur le bus (vers "coder")
        4. Retourne AgentResult(payload={"dispatched": [task_ids]})

    V8-09 : llm_generator injecte pour decomposition JSON intelligente.
            Fallback heuristique transparent si LLM None ou reponse invalide.
    """

    def __init__(
        self,
        card: AgentCard,
        bus: A2ALocalBus,
        mcp_caller=None,
        llm_generator: "Optional[LLMGenerator]" = None,
    ) -> None:
        super().__init__(card=card, bus=bus, mcp_caller=mcp_caller)
        self._llm = llm_generator
        self._decomposer = ArchitectDecomposer()  # REFACTO-06

    @classmethod
    def create(cls, bus: A2ALocalBus, mcp_caller=None, llm_generator: "Optional[LLMGenerator]" = None) -> "ArchitectAgent":
        """Factory : cree une instance avec AgentCard par defaut.

        Si llm_generator=None, tente d'instancier LLMGenerator automatiquement.
        Si Ollama est indisponible, llm reste None (mode heuristique silencieux).
        """
        from .agent_card import ARCHITECT_POLICY
        card = AgentCard(
            name="architect",
            version="8.1.0",
            capabilities=["planning", "decomposition", "memory_search", "llm_generation"],
            mcp_tools=AGENT_MCP_ALLOWLIST["architect"],
            recovery_policy=ARCHITECT_POLICY,
            description="Planifie et decompose les taches via LLM ou heuristique (V8-09)",
        )

        # Auto-instanciation LLMGenerator si non injecte (V8-09)
        if llm_generator is None:
            try:
                from core.llm_generator import LLMGenerator
                candidate = LLMGenerator()
                if isinstance(candidate.ollama.model, str) and candidate.ollama.model:
                    llm_generator = candidate
                    logger.info("[architect] LLMGenerator auto-instancie model=%s", candidate.ollama.model)
            except Exception as exc:
                logger.debug("[architect] LLMGenerator non disponible : %s", exc)

        return cls(card=card, bus=bus, mcp_caller=mcp_caller, llm_generator=llm_generator)

    def _decompose_with_llm(self, contract: TaskContract) -> List[TaskContract]:
        """Retrocompat : delegue a self._decomposer._decompose_with_llm (REFACTO-06)."""
        return self._decomposer._decompose_with_llm(contract, self._llm)

    # ------------------------------------------------------------------
    def run_task(self, contract: TaskContract) -> AgentResult:
        """
        Traite un contrat d'intent et emet des sous-contrats vers CoderAgent.

        Strategie de decomposition (V8-09) :
        1. Tente _decompose_with_llm() -> LLM JSON
        2. Si retourne [] -> fallback _decompose_intent() heuristique
        """
        logger.info("[architect] run_task intent=%r llm=%s",
                    contract.intent, "oui" if self._llm else "non (heuristique)")

        try:
            # 1. Recherche specs existantes (non bloquant si MCP absent)
            memory_result = self._call_mcp(
                "memory_search",
                {"query": contract.intent, "collection": "lcca_specs", "limit": 3},
            )
            existing_specs = memory_result.get("results", [])

            # 2. Decomposition : LLM en priorite, heuristique en fallback (REFACTO-06)
            sub_contracts, decomposed_by = self._decomposer.decompose(contract, self._llm)

            # 3. Dispatch bus
            dispatched_ids = []
            for sub in sub_contracts:
                if existing_specs:
                    sub.context["existing_specs"] = existing_specs[:1]

                self._send(
                    to="coder",
                    task_id=sub.task_id,
                    payload={"contract": sub.to_dict()},
                )
                dispatched_ids.append(sub.task_id)
                logger.info("[architect] -> coder task_id=%s intent=%r", sub.task_id, sub.intent)

            return AgentResult(
                success=True,
                payload={
                    "dispatched":    dispatched_ids,
                    "sub_contracts": len(sub_contracts),
                    "specs_found":   len(existing_specs),
                    "decomposed_by": decomposed_by,
                },
            )

        except PermissionError:
            raise  # Ne pas swallow les violations d'allowlist
        except Exception as e:
            return self._handle_error(e, contract)
