# -*- coding: utf-8-sig -*-
"""
LCCA V8 -- TesterAgent : sandbox + metriques + ExecutionReceipt.

Responsabilites :
    1. Recevoir le code valide depuis ReviewerAgent.
    2. Executer en sandbox (SandboxEngine mode=soft).
    3. Evaluer la qualite statique (CodeEvaluator).
    4. Construire et signer l'ExecutionReceipt final (HMAC).
    5a. Si succes (sandbox OK + quality >= seuil) :
        - Tenter stockage skill (SkillLibrary -- injectable, peut etre None).
        - Ne PAS emettre de message (pipeline termine avec succes).
    5b. Si echec :
        - Generer une reflexion partielle.
        - Envoyer rejection vers ArchitectAgent.

Tools MCP autorises : sandbox_run, evaluate_quality
V8-Regle-17 : aucun skill stocke sans ExecutionReceipt valide.
V8-Regle-18 : KarpathyLoop s'arrete si 3 stagnations (delegue au loop -- hors scope V8-04).
V8-Regle-20 : ne modifie jamais core/ directement.
V8-Regle-21 : toute communication passe par A2ALocalBus.

Sous-module (REFACTO-05) :
    tester_runner.py -- helpers purs + TesterReceiptBuilder (construction receipt)
"""
from __future__ import annotations

import logging
from typing import Any, Optional, TYPE_CHECKING

from .base_agent import BaseAgent, AgentResult
from .agent_card import AgentCard, AGENT_MCP_ALLOWLIST, TESTER_POLICY
from .a2a_bus import A2ALocalBus, TaskContract
from .tester_runner import (
    _hash,
    _run_sandbox_safe,
    _build_reflection,
    TesterReceiptBuilder,
)
from core.sandbox_engine import SandboxEngine
from core.code_evaluator import CodeEvaluator
from core.receipt_store import ExecutionReceipt

if TYPE_CHECKING:
    from core.skill_library import SkillLibrary    # evite import circulaire

logger = logging.getLogger(__name__)

# Seuil qualite : sous ce score, le skill n'est pas stocke
_MIN_QUALITY_SCORE: int = 70


# ---------------------------------------------------------------------------
# TesterAgent
# ---------------------------------------------------------------------------

class TesterAgent(BaseAgent):
    """
    Agent Testeur V8.

    Flux principal (run_task) :
        1. Extraire code depuis contract.context["code"]
        2. Sandbox run -> (success, stdout, stderr)
        3. CodeEvaluator.evaluate() -> quality_score
        4. Construire + signer ExecutionReceipt
        5. verify_receipt() -- assertion anti-tamper
        6. store_receipt() -- audit trail
        7a. succes : _maybe_store_skill() + AgentResult(success=True)
        7b. echec  : send(to="architect", rejected=True + reflection)

    Injection optionnelle :
        skill_library : SkillLibrary -- None en mode test
                        Injecte depuis AgentOrchestrator en prod (evite import
                        circulaire entre agents et skill_library).
    """

    __test__ = False  # Empeche pytest de collecter cette classe (PytestCollectionWarning)

    def __init__(
        self,
        card: AgentCard,
        bus: A2ALocalBus,
        mcp_caller=None,
        sandbox: Optional[SandboxEngine] = None,
        evaluator: Optional[CodeEvaluator] = None,
        skill_library: "Optional[SkillLibrary]" = None,
        min_quality_score: int = _MIN_QUALITY_SCORE,
    ) -> None:
        super().__init__(card=card, bus=bus, mcp_caller=mcp_caller)
        self._sandbox = sandbox or SandboxEngine(mode="soft")
        self._evaluator = evaluator or CodeEvaluator()
        self._skill_lib = skill_library
        self._min_quality = min_quality_score
        self._builder = TesterReceiptBuilder()  # REFACTO-05

    @classmethod
    def create(
        cls,
        bus: A2ALocalBus,
        mcp_caller=None,
        skill_library=None,
    ) -> "TesterAgent":
        """Factory : cree une instance avec AgentCard par defaut."""
        card = AgentCard(
            name="tester",
            version="8.0.0",
            capabilities=["sandbox_execution", "metric_collection", "receipt_signing"],
            mcp_tools=AGENT_MCP_ALLOWLIST["tester"],
            recovery_policy=TESTER_POLICY,
            description="Execute le sandbox et produit les ExecutionReceipts",
        )
        return cls(
            card=card,
            bus=bus,
            mcp_caller=mcp_caller,
            skill_library=skill_library,
        )

    # ------------------------------------------------------------------
    # Interface BaseAgent
    # ------------------------------------------------------------------

    def run_task(self, contract: TaskContract) -> AgentResult:
        """
        Execute le code en sandbox, evalue, signe le receipt, route le resultat.
        """
        logger.info("[tester] run_task task_id=%s", contract.task_id)

        code = contract.context.get("code", "")
        original_payload = contract.context.get("original_payload", {})

        try:
            # 1. Sandbox
            sandbox_result = _run_sandbox_safe(self._sandbox, code)
            sandbox_ok = sandbox_result["success"]

            # 2. Evaluation qualite statique
            try:
                eval_result = self._evaluator.evaluate(code, filename="<agent_output>")
                quality_score = eval_result.score
            except Exception as exc:
                logger.debug("[tester] evaluator error: %s", exc)
                eval_result   = None
                quality_score = 0

            # 3. Construire, signer, verifier et persister le receipt (REFACTO-05)
            receipt = self._builder.build(
                task_id=contract.task_id,
                agent_name=self.card.name,
                sandbox_result=sandbox_result,
                code=code,
                original_payload=original_payload,
            )

            # 4. Routage selon le resultat
            if sandbox_ok and quality_score >= self._min_quality:
                # 6a. Succes -> stockage skill optionnel
                self._maybe_store_skill(code, receipt, contract, quality_score)
                logger.info(
                    "[tester] OK task_id=%s sandbox=True quality=%d",
                    contract.task_id, quality_score,
                )
                return AgentResult(
                    success=True,
                    payload={
                        "task_id": contract.task_id,
                        "sandbox_passed": True,
                        "quality_score": quality_score,
                        "receipt_task_id": receipt.task_id,
                        "tester_ok": True,
                    },
                )
            else:
                # 6b. Echec -> reflexion + rejection vers Architect
                reflection_struct = _build_reflection(
                    sandbox_result,
                    receipt,
                    eval_result=eval_result,
                    iteration=contract.context.get("iteration", 0),
                )
                original_intent = (
                    original_payload.get("contract", {}).get("intent", "")
                    or contract.intent
                )
                reject_payload = {
                    "rejected":              True,
                    "tester_ok":             False,
                    "sandbox_passed":        sandbox_ok,
                    "quality_score":         quality_score,
                    "reflection":            reflection_struct.stderr_short,   # str -- retrocompat
                    "reflection_structured": reflection_struct.to_dict(),       # FL-01 : nouveau
                    "fix_hints":             reflection_struct.fix_hints,       # FL-01 : raccourci
                    "original_intent":       original_intent,
                    "task_id":               contract.task_id,
                }
                self._send(
                    to="architect",
                    task_id=contract.task_id,
                    payload=reject_payload,
                )
                logger.warning(
                    "[tester] -> architect (rejected) task_id=%s sandbox=%s quality=%d",
                    contract.task_id, sandbox_ok, quality_score,
                )
                return AgentResult(
                    success=False,
                    payload=reject_payload,
                    error=(
                        f"sandbox_passed={sandbox_ok}, "
                        f"quality_score={quality_score} < {self._min_quality}"
                    ),
                )

        except AssertionError:
            raise  # Ne pas swallow les violations V8-Regle-17
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

        payload = msg.payload
        contract_dict = payload.get("contract", {})

        if contract_dict:
            contract = TaskContract.from_dict(contract_dict)
        else:
            contract = TaskContract(
                task_id=msg.task_id,
                intent=payload.get("intent", ""),
                domain=payload.get("domain", "global"),
                source_agent=msg.from_agent,
                target_agent="tester",
            )

        # Injecter le code et les metadonnees dans le contexte
        # Retirer la cle "contract" de original_payload pour eviter la reference
        # circulaire : payload["contract"] -> context -> original_payload -> ...
        safe_payload = {k: v for k, v in payload.items() if k != "contract"}
        contract.context["code"] = safe_payload.get("code", "")
        contract.context["original_payload"] = safe_payload
        contract.context["receipt_hash"] = msg.receipt_hash

        return self.run_task(contract)

    # ------------------------------------------------------------------
    # Helpers prives
    # ------------------------------------------------------------------

    def _maybe_store_skill(
        self,
        code: str,
        receipt: ExecutionReceipt,
        contract: TaskContract,
        quality_score: int,
    ) -> None:
        """
        V8-Regle-17 : stockage uniquement si receipt valide ET skill_lib injecte.
        Silencieux si skill_library=None (mode test sans SkillLibrary).
        """
        if self._skill_lib is None:
            return
        try:
            self._skill_lib.extract_and_store(
                code=code,
                receipt=receipt,
                source_intent=contract.intent,
                quality_score=quality_score,
            )
        except Exception as exc:
            logger.debug("[tester] _maybe_store_skill failed: %s", exc)
