# -*- coding: utf-8-sig -*-
"""
LCCA V8/V9-08/REFACTO-09 -- ReviewerAgent : orchestration validation + analyse LLM.

Responsabilites :
    1. Recevoir un TaskContract enrichi (code + payload) depuis le bus.
    2. Deleguer la validation syntaxique a ReviewerValidator.
    3. Analyser les erreurs connues via ErrorAnalyzer (MCP).
    4. Deleguer l'analyse qualite LLM a ReviewerLlmAnalyzer.
    5. Si OK  -> forward vers TesterAgent avec reviewer_ok=True + review_notes LLM.
    6. Si KO  -> rejeter vers ArchitectAgent avec reflection + reviewer_ok=False.

Sous-modules (REFACTO-09) :
    reviewer_validator.py  -- _check_syntax, _build_reflection
    reviewer_analyzer.py   -- ReviewerLlmAnalyzer, prompts LLM

Tools MCP autorises : validate_spec, analyze_error, memory_search
V8-Regle-19 : produit une reflexion partielle (combinee avec celle du Tester).
V8-Regle-20 : ne modifie jamais core/ directement.
V8-Regle-21 : toute communication passe par A2ALocalBus.
V9-08 : llm_generator optionnel -- retrocompat totale si absent.
"""
from __future__ import annotations

import logging
from typing import Optional

from .base_agent import BaseAgent, AgentResult
from .agent_card import AgentCard, AgentRegistry, AGENT_MCP_ALLOWLIST, REVIEWER_POLICY
from .a2a_bus import A2ALocalBus, TaskContract
from .reviewer_validator import _check_syntax, _build_reflection
from .reviewer_analyzer import ReviewerLlmAnalyzer, REVIEWER_SYSTEM, REVIEWER_USER_TMPL

logger = logging.getLogger(__name__)

# Aliases prives retrocompat (imports directs depuis reviewer_agent)
_REVIEWER_SYSTEM = REVIEWER_SYSTEM
_REVIEWER_USER_TMPL = REVIEWER_USER_TMPL


# ---------------------------------------------------------------------------
# ReviewerAgent
# ---------------------------------------------------------------------------

class ReviewerAgent(BaseAgent):
    """
    Agent Reviewer V8/V9-08.

    Flux principal (run_task) :
        1. Extraire code depuis contract.context["code"]
        2. _check_syntax(code) -> (ok, issues)
        3. Analyse qualite LLM (optionnel, V9-08) : quality_score + suggestions
        4. Si ok   : send(to="tester", payload enrichi reviewer_ok=True + llm_notes
        5. Si !ok  : analyze_error MCP (optionnel) + send(to="architect", rejected=True)
        6. Retourner AgentResult

    Parametres V9-08 :
        llm_generator : LLMGenerator ou None (retrocompat totale si absent)

    Compatibilite run_from_bus() :
        La methode run_from_bus() heritee de BaseAgent n'existe pas --
        on fournit run_once() qui lit le bus et appelle run_task().
    """

    def __init__(self, card: AgentCard, bus: A2ALocalBus, mcp_caller=None,
                 llm_generator=None) -> None:
        super().__init__(card, bus, mcp_caller)
        self._llm = llm_generator
        self._analyzer = ReviewerLlmAnalyzer(llm_generator)

    @classmethod
    def create(cls, bus: A2ALocalBus, mcp_caller=None,
               llm_generator=None) -> "ReviewerAgent":
        """Factory : cree une instance avec AgentCard par defaut."""
        card = AgentCard(
            name="reviewer",
            version="9.0.0",
            capabilities=["validation", "static_analysis", "error_reflection", "llm_review"],
            mcp_tools=AGENT_MCP_ALLOWLIST["reviewer"],
            recovery_policy=REVIEWER_POLICY,
            description="Valide la coherence et detecte les regressions",
        )
        # Auto-instanciation LLM si Ollama disponible (duck-typing)
        if llm_generator is None:
            try:
                import config
                from core.llm_generator import LLMGenerator
                import ollama as _ollama
                if isinstance(_ollama.model, str):
                    llm_generator = LLMGenerator()
            except Exception:
                pass
        return cls(card=card, bus=bus, mcp_caller=mcp_caller, llm_generator=llm_generator)

    # ------------------------------------------------------------------
    # Analyse LLM (V9-08) -- wrapper retrocompat -> delegue a ReviewerLlmAnalyzer
    # ------------------------------------------------------------------

    def _analyze_with_llm(self, code: str, intent: str, domain: str) -> dict:
        """Wrapper retrocompat : delegue a self._analyzer.analyze()."""
        return self._analyzer.analyze(code, intent, domain)

    # ------------------------------------------------------------------
    # Interface BaseAgent
    # ------------------------------------------------------------------

    def run_task(self, contract: TaskContract) -> AgentResult:
        """
        Valide le code contenu dans contract.context["code"].

        Si "code" est absent du contexte, considere comme code vide.
        V9-08 : enrichit le payload avec llm_review si llm_generator fourni.
        """
        logger.info("[reviewer] run_task task_id=%s", contract.task_id)

        code = contract.context.get("code", "")
        original_payload = contract.context.get("original_payload", {})
        receipt_hash = contract.context.get("receipt_hash")

        try:
            # 1. Validation syntaxique
            syntax_ok, issues = _check_syntax(code)

            # 2. Analyse erreur via MCP (non bloquant si MCP absent)
            error_suggestion = ""
            if not syntax_ok and issues:
                try:
                    mcp_result = self._call_mcp(
                        "analyze_error",
                        {
                            "error_type": "SyntaxError",
                            "error_msg": "; ".join(issues),
                            "code": code[:500],
                        },
                    )
                    error_suggestion = mcp_result.get("suggestion", "")
                except Exception:
                    pass  # MCP non disponible -- reflexion heuristique

            # Analyse LLM (V9-08, optionnelle, silencieuse)
            llm_review = self._analyze_with_llm(code, contract.intent, contract.domain)
            llm_used = self._llm is not None

            if syntax_ok:
                # 3a. OK -> forward vers Tester
                forward_payload = {
                    **original_payload,
                    "code": code,
                    "reviewer_ok": True,
                    "review_notes": llm_review["suggestions"],
                    "llm_review": llm_review,
                    "llm_used": llm_used,
                    "receipt_hash": receipt_hash,
                }
                self._send(
                    to="tester",
                    task_id=contract.task_id,
                    payload=forward_payload,
                )
                logger.info("[reviewer] -> tester task_id=%s llm_used=%s", contract.task_id, llm_used)
                return AgentResult(
                    success=True,
                    payload={
                        "task_id": contract.task_id,
                        "reviewer_ok": True,
                        "forwarded_to": "tester",
                        "llm_review": llm_review,
                        "llm_used": llm_used,
                    },
                )
            else:
                # 3b. KO -> rejection vers Architect
                reflection = _build_reflection(issues, error_suggestion)
                original_intent = (
                    original_payload.get("contract", {}).get("intent", "")
                    or contract.intent
                )
                reject_payload = {
                    "rejected": True,
                    "reviewer_ok": False,
                    "reflection": reflection,
                    "review_notes": issues,
                    "original_intent": original_intent,
                    "task_id": contract.task_id,
                    "llm_review": llm_review,
                    "llm_used": llm_used,
                }
                self._send(
                    to="architect",
                    task_id=contract.task_id,
                    payload=reject_payload,
                )
                logger.warning(
                    "[reviewer] -> architect (rejected) task_id=%s issues=%s",
                    contract.task_id, issues,
                )
                return AgentResult(
                    success=False,
                    payload={
                        "task_id": contract.task_id,
                        "reviewer_ok": False,
                        "reflection": reflection,
                        "forwarded_to": "architect",
                        "llm_review": llm_review,
                        "llm_used": llm_used,
                    },
                    error="; ".join(issues),
                )

        except PermissionError:
            raise  # Ne pas swallow les violations d'allowlist
        except Exception as exc:
            return self._handle_error(exc, contract)

    # ------------------------------------------------------------------
    # Boucle de consommation bus
    # ------------------------------------------------------------------

    def run_once(self, timeout_sec: int = 5) -> Optional[AgentResult]:
        """
        Consomme un message du bus et execute run_task.

        Retourne None si aucun message disponible dans timeout_sec.
        """
        msg = self._receive(timeout_sec=timeout_sec)
        if msg is None:
            return None

        # Reconstruire un TaskContract depuis le payload du message
        # Le Coder envoie : {"code": ..., "task_id": ..., "contract": {...}, ...}
        payload = msg.payload
        contract_dict = payload.get("contract", {})

        if contract_dict:
            contract = TaskContract.from_dict(contract_dict)
        else:
            # Payload direct sans sous-cle "contract"
            contract = TaskContract(
                task_id=msg.task_id,
                intent=payload.get("intent", ""),
                domain=payload.get("domain", "global"),
                source_agent=msg.from_agent,
                target_agent="reviewer",
            )

        # Injecter le code et les metadonnees dans le contexte du contrat
        # Retirer la cle "contract" de original_payload pour eviter la reference
        # circulaire : payload["contract"] -> context -> original_payload -> ...
        safe_payload = {k: v for k, v in payload.items() if k != "contract"}
        contract.context["code"] = safe_payload.get("code", "")
        contract.context["original_payload"] = safe_payload
        contract.context["receipt_hash"] = msg.receipt_hash

        return self.run_task(contract)
