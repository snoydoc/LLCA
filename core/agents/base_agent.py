# -*- coding: utf-8-sig -*-
"""
LCCA V8 -- BaseAgent : ABC commun a tous les agents cognitifs.

V8-Regle-20 : les agents ne touchent jamais core/ directement.
V8-Regle-21 : toute communication passe par A2ALocalBus.

_call_mcp() enforce AGENT_MCP_ALLOWLIST avant tout appel effectif.
"""
from __future__ import annotations

import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from .agent_card import AgentCard, AGENT_MCP_ALLOWLIST
from .a2a_bus import A2ALocalBus, TaskContract

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AgentResult
# ---------------------------------------------------------------------------
@dataclass
class AgentResult:
    """
    Resultat produit par run_task().

    success : True si la tache s'est terminee sans erreur fatale.
    payload : donnees utiles retournees par l'agent.
    error   : message d'erreur si success=False.
    retries : nombre de tentatives effectuees.
    """
    success: bool
    payload: dict = field(default_factory=dict)
    error: Optional[str] = None
    retries: int = 0

    def is_ok(self) -> bool:
        return self.success


# ---------------------------------------------------------------------------
# BaseAgent
# ---------------------------------------------------------------------------
class BaseAgent(ABC):
    """
    Classe de base pour tous les agents V8.

    Sous-classes doivent implementer :
        run_task(contract) -> AgentResult

    Methodes utilitaires fournies :
        _call_mcp(tool, params) -> dict       enforce allowlist
        _send(to, task_id, payload)           envoie via bus
        _receive(timeout_sec) -> A2AMessage   recoit du bus
        _handle_error(error, contract) -> AgentResult  politique recovery
    """

    def __init__(
        self,
        card: AgentCard,
        bus: A2ALocalBus,
        mcp_caller=None,
    ) -> None:
        """
        card       : AgentCard de cet agent (identite + allowlist MCP).
        bus        : instance A2ALocalBus partagee.
        mcp_caller : callable(tool, params) -> dict | None.
                     None = mode test (tous les appels MCP retournent {}).
        """
        self.card = card
        self.bus = bus
        self._mcp_caller = mcp_caller

    # ------------------------------------------------------------------
    # Interface publique
    # ------------------------------------------------------------------
    @abstractmethod
    def run_task(self, contract: TaskContract) -> AgentResult:
        """Traite un contrat et retourne un AgentResult."""

    # ------------------------------------------------------------------
    # MCP (enforce allowlist)
    # ------------------------------------------------------------------
    def _call_mcp(self, tool: str, params: dict) -> dict:
        """
        Appelle un tool MCP apres verification de l'allowlist.

        Leve PermissionError si le tool n'est pas dans la liste.
        Retourne {} si mcp_caller n'est pas configure (mode test).
        """
        allowed = AGENT_MCP_ALLOWLIST.get(self.card.name, frozenset())
        if tool not in allowed:
            raise PermissionError(
                f"Agent '{self.card.name}' n'a pas le droit d'appeler '{tool}'. "
                f"Allowlist : {sorted(allowed)}"
            )
        if self._mcp_caller is None:
            logger.debug("[%s] _call_mcp(%s) en mode test -> {}", self.card.name, tool)
            return {}
        return self._mcp_caller(tool, params)

    # ------------------------------------------------------------------
    # Bus helpers
    # ------------------------------------------------------------------
    def _send(self, to: str, task_id: str, payload: dict) -> int:
        """Envoie un message via A2ALocalBus. Retourne l'id du message."""
        return self.bus.send(
            to=to,
            from_=self.card.name,
            task_id=task_id,
            payload=payload,
        )

    def _receive(self, timeout_sec: int = 0):
        """Recoit le prochain message destine a cet agent."""
        return self.bus.receive(self.card.name, timeout_sec=timeout_sec)

    # ------------------------------------------------------------------
    # Gestion d'erreur / recovery
    # ------------------------------------------------------------------
    def _handle_error(
        self,
        error: Exception,
        contract: TaskContract,
        attempt: int = 0,
    ) -> AgentResult:
        """
        Applique la RecoveryPolicy de l'agent.

        - retry    : relance run_task jusqu'a max_retries.
        - escalate : envoie le contrat a fallback_agent via bus.
        - rollback : retourne AgentResult(success=False).
        """
        policy = self.card.recovery_policy
        error_type = type(error).__name__

        logger.warning(
            "[%s] Erreur attempt=%d type=%s : %s",
            self.card.name, attempt, error_type, error,
        )

        # Retry
        if policy.should_retry(error_type, attempt):
            logger.info("[%s] retry %d/%d ...", self.card.name, attempt + 1, policy.max_retries)
            time.sleep(policy.retry_delay_sec)
            try:
                result = self.run_task(contract)
                result.retries = attempt + 1
                return result
            except Exception as e2:
                return self._handle_error(e2, contract, attempt + 1)

        # Escalate
        if policy.on_failure == "escalate" and policy.fallback_agent:
            logger.info("[%s] escalade vers %s", self.card.name, policy.fallback_agent)
            self._send(
                to=policy.fallback_agent,
                task_id=contract.task_id,
                payload={
                    "escalated_by": self.card.name,
                    "error": str(error),
                    "contract": contract.to_dict(),
                },
            )
            return AgentResult(
                success=False,
                error=f"Escalade vers {policy.fallback_agent} : {error}",
                retries=attempt,
            )

        # Rollback (defaut)
        return AgentResult(
            success=False,
            error=f"{error_type}: {error}",
            retries=attempt,
        )
