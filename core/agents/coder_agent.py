# -*- coding: utf-8-sig -*-
"""
LCCA V8 -- CoderAgent : corps cognitif generation de code.

Responsabilites :
    1. Recevoir un TaskContract (depuis bus ou run_task direct).
    2. Appeler memory_search MCP pour trouver des skills existants.
    3. Generer du code via LLMGenerator.generate_text() (V8-08).
    4. Appeler edit_batch MCP avec le patch genere.
    5. Retourner AgentResult avec le resultat du patch + generated_code.

V8-08 : integration LLMGenerator — generate_text(system, user) -> str.
        llm_generator=None accepte (mode test sans Ollama).
V8-Regle-20 : ne modifie jamais core/ directement.
V8-Regle-21 : toute communication passe par A2ALocalBus.
REFACTO-07 : prompt/format/patch extraits dans coder_builder.py.
"""
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from .base_agent import BaseAgent, AgentResult
from .agent_card import AgentCard, AGENT_MCP_ALLOWLIST
from .a2a_bus import A2ALocalBus, TaskContract
from .coder_builder import (
    CODER_SYSTEM as _CODER_SYSTEM,
    build_coder_prompt as _build_coder_prompt,
    format_skills_context as _format_skills_context,
    build_patch as _build_patch,
)

if TYPE_CHECKING:
    from core.llm_generator import LLMGenerator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CoderAgent
# ---------------------------------------------------------------------------
class CoderAgent(BaseAgent):
    """
    Agent Codeur V8.

    Flux principal (run_task) :
        1. memory_search -> skills existants (optionnel, mode test = {})
        2. _generate_code() -> LLMGenerator.generate_text() ou stub
        3. _build_patch()   -> dict edit_batch avec generated_code
        4. edit_batch MCP   -> result
        5. AgentResult(payload={"patch": ..., "generated_code": ..., ...})

    Args :
        llm_generator : LLMGenerator injecte (V8-08).
                        None = mode test (stub code, sans Ollama).
    """

    def __init__(
        self,
        card: AgentCard,
        bus: A2ALocalBus,
        mcp_caller=None,
        llm_generator: "Optional[LLMGenerator]" = None,
        model_router=None,                          # FL-02
    ) -> None:
        super().__init__(card=card, bus=bus, mcp_caller=mcp_caller)
        self._llm = llm_generator
        self._model_router = model_router           # FL-02

    @classmethod
    def create(
        cls,
        bus: A2ALocalBus,
        mcp_caller=None,
        llm_generator: "Optional[LLMGenerator]" = None,
        model_router=None,                          # FL-02
    ) -> "CoderAgent":
        """
        Factory : cree une instance avec AgentCard par defaut.

        Si llm_generator=None, tente d'instancier LLMGenerator automatiquement.
        Si Ollama est indisponible, llm reste None (mode stub silencieux).
        """
        from .agent_card import CODER_POLICY
        card = AgentCard(
            name="coder",
            version="8.0.0",
            capabilities=["code_generation", "ast_patching", "skill_injection", "llm_generation"],
            mcp_tools=AGENT_MCP_ALLOWLIST["coder"],
            recovery_policy=CODER_POLICY,
            description="Genere le code via LLM et applique les patches ACID (V8-08)",
        )

        # Auto-instanciation LLMGenerator si non injecte (V8-08)
        if llm_generator is None:
            try:
                from core.llm_generator import LLMGenerator
                candidate = LLMGenerator()
                if isinstance(candidate.ollama.model, str) and candidate.ollama.model:
                    llm_generator = candidate
                    logger.info("[coder] LLMGenerator auto-instancie model=%s", candidate.ollama.model)
            except Exception as exc:
                logger.debug("[coder] LLMGenerator non disponible : %s", exc)

        return cls(card=card, bus=bus, mcp_caller=mcp_caller, llm_generator=llm_generator, model_router=model_router)

    # ------------------------------------------------------------------
    # Generation de code (V8-08)
    # ------------------------------------------------------------------

    def _generate_code(self, contract: TaskContract, skills_ctx: str) -> str:
        """
        Appelle LLMGenerator.generate_text() pour produire du code Python.

        Retourne une chaine vide si :
        - llm_generator est None (mode test)
        - Ollama est indisponible (ConnectionError swallowe)
        - Le code genere est invalide syntaxiquement (swallowe, log warn)

        Ne leve jamais d'exception — le pipeline doit continuer.
        """
        if self._llm is None:
            logger.debug("[coder] _generate_code : llm=None -> stub vide")
            return ""

        # FL-02 : consulter le ModelRouter — model_override local a l'appel (sans mutation)
        model_override: Optional[str] = None
        if self._model_router is not None:
            try:
                complexity = (
                    contract.context.get("complexity_score", 5)
                    if isinstance(contract.context, dict) else 5
                )
                decision = self._model_router.get_model(
                    task_type="coding",
                    complexity_score=complexity,
                )
                if decision.model_name != self._llm.ollama.model:
                    model_override = decision.model_name
                    logger.info(
                        "[coder] model_router: %s -> %s (reason: %s)",
                        self._llm.ollama.model, model_override, decision.reason,
                    )
            except Exception as exc:
                logger.debug("[coder] model_router.get_model error (ignored): %s", exc)

        prompt = _build_coder_prompt(
            contract.intent,
            contract.domain,
            skills_ctx,
            fix_hints          = contract.context.get("fix_hints") if isinstance(contract.context, dict) else None,
            last_quality_score = contract.context.get("last_quality_score") if isinstance(contract.context, dict) else None,
        )
        try:
            raw = self._llm.generate_text(
                system=_CODER_SYSTEM,
                user=prompt,
                model_override=model_override,    # FL-02 : local, sans effet de bord
            )
            if not raw or not raw.strip():
                logger.debug("[coder] _generate_code : reponse LLM vide")
                return ""
            # Validation syntaxique rapide
            try:
                compile(raw.strip(), "<coder_agent>", "exec")
                logger.info(
                    "[coder] code genere OK intent=%r len=%d",
                    contract.intent[:60], len(raw),
                )
                return raw.strip()
            except SyntaxError as exc:
                logger.warning(
                    "[coder] code LLM invalide (SyntaxError: %s) -> stub vide", exc
                )
                return ""
        except Exception as exc:
            logger.warning("[coder] _generate_code erreur LLM : %s", exc)
            return ""

    # ------------------------------------------------------------------
    # Interface principale
    # ------------------------------------------------------------------

    def run_task(self, contract: TaskContract) -> AgentResult:
        """
        Genere du code via LLM et applique le patch via edit_batch MCP.
        """
        logger.info("[coder] run_task task_id=%s intent=%r", contract.task_id, contract.intent)

        try:
            # 1. Recherche skills existants
            memory_result = self._call_mcp(
                "memory_search",
                {
                    "query": contract.intent,
                    "collection": "lcca_solutions",
                    "limit": 3,
                },
            )
            skills = memory_result.get("results", [])

            # Contexte skills pour le prompt LLM + injection orchestrateur
            orchestrator_skills = contract.context.get("available_skills", "")
            memory_skills_ctx   = _format_skills_context(skills)
            skills_ctx = orchestrator_skills or memory_skills_ctx

            # 2. Generation LLM (V8-08) — jamais bloquant
            generated_code = self._generate_code(contract, skills_ctx)

            # 3. Construction du patch
            patch = _build_patch(contract, skills, generated_code)

            # 4. Application via edit_batch
            edit_result = self._call_mcp("edit_batch", patch)

            # 5. Resultat
            return AgentResult(
                success=True,
                payload={
                    "task_id":        contract.task_id,
                    "patch":          patch,
                    "edit_result":    edit_result,
                    "generated_code": generated_code,
                    "skills_used":    len(skills),
                    "llm_used":       self._llm is not None,
                },
            )

        except PermissionError:
            raise  # Violations d'allowlist : non swallow
        except SyntaxError as e:
            return self._handle_error(e, contract)
        except Exception as e:
            return self._handle_error(e, contract)

    # ------------------------------------------------------------------
    def run_from_bus(self, timeout_sec: int = 5) -> Optional[AgentResult]:
        """
        Consomme un message du bus et execute run_task.

        Retourne None si aucun message disponible.
        Utile pour la boucle agentique.
        """
        msg = self._receive(timeout_sec=timeout_sec)
        if msg is None:
            return None

        contract_dict = msg.payload.get("contract")
        if not contract_dict:
            logger.error("[coder] Message sans 'contract' : %s", msg.payload)
            return AgentResult(
                success=False,
                error="Payload invalide : cle 'contract' manquante",
            )

        contract = TaskContract.from_dict(contract_dict)
        return self.run_task(contract)
