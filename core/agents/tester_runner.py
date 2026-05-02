# -*- coding: utf-8-sig -*-
"""
LCCA V8 -- TesterRunner : helpers purs + construction des ExecutionReceipts.

Extrait de tester_agent.py (REFACTO-05).

Responsabilites :
    1. Helpers purs : _hash, _run_sandbox_safe, _build_reflection
    2. TesterReceiptBuilder : construit, signe, verifie et stocke un ExecutionReceipt

Ces elements n'ont aucune dependance vers BaseAgent / A2ALocalBus.
Ils peuvent etre testes en complete isolation.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, asdict as _asdict
from typing import TYPE_CHECKING, List, Dict, Any

from core.receipt_store import (
    ExecutionReceipt,
    sign_receipt,
    store_receipt,
    verify_receipt,
)

if TYPE_CHECKING:
    from core.agents.a2a_bus import TaskContract

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FL-01 : StructuredReflection + helpers
# ---------------------------------------------------------------------------

@dataclass
class StructuredReflection:
    """
    FL-01 : Diagnostic actionnable produit par TesterAgent.
    Remplace la chaine vague "Tester: sandbox_passed=False...".
    """
    sandbox_passed:    bool
    quality_score:     int
    quality_criteria:  List[Dict[str, Any]]   # [{name, score, max, details}, ...]
    stderr_short:      str                    # 200 chars max
    fix_hints:         List[str]              # instructions LLM, max 5
    iteration:         int

    def to_dict(self) -> Dict[str, Any]:
        return _asdict(self)


# Mapping nom critere CodeEvaluator -> instruction LLM actionnable
_HINT_MAP: Dict[str, Any] = {
    "Syntaxe Python": None,   # bloquant -- pas de hint utile (code invalide)
    "Type hints":     "Add type annotations to all function arguments and return values",
    "Docstrings":     "Add a docstring to every function and class",
    "Complexite":     "Reduce cyclomatic complexity -- split functions exceeding 10 branches",
    "Anti-patterns":  None,   # detaille via criterion.details ci-dessous
}


def _criteria_to_fix_hints(criteria: list) -> List[str]:
    """
    Traduit les criteres CodeEvaluator en instructions correctables.
    Retourne max 5 hints, les criteres les plus impactants en premier.

    Args:
        criteria : list[CriterionScore] -- chaque objet a .name .score .max .details

    Returns:
        List[str] -- vide si criteria est vide ou None.
    """
    if not criteria:
        return []

    hints: List[str] = []
    sorted_crit = sorted(criteria, key=lambda c: getattr(c, "score", 0))

    for c in sorted_crit:
        score   = getattr(c, "score",   0)
        max_s   = getattr(c, "max",     1)
        name    = getattr(c, "name",    "Unknown")
        details = getattr(c, "details", "") or ""

        if score >= max_s:
            continue   # critere plein -- rien a corriger

        generic = _HINT_MAP.get(name)
        if generic:
            hints.append(generic)

        if details and details not in ("Valide", "Valid"):
            specific = f"Fix: {details}"
            if specific not in hints:
                hints.append(specific)

    return hints[:5]


# ---------------------------------------------------------------------------
# Helpers purs (module-level)
# ---------------------------------------------------------------------------

def _hash(text: str) -> str:
    """MD5 court (12 chars) -- identique au pattern LCCA."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


def _run_sandbox_safe(sandbox, code: str) -> dict:
    """
    Enveloppe SandboxEngine.run() dans un try/except.
    Retourne toujours un dict avec les cles : success, stdout, stderr, exit_code.

    Args:
        sandbox : SandboxEngine (ou mock compatible).
        code    : code Python a executer.

    Returns:
        dict avec cles success (bool), stdout, stderr, exit_code.
    """
    try:
        success, stdout, stderr, exit_code = sandbox.run(code, timeout=30)
        return {
            "success": success,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
        }
    except Exception as exc:
        logger.debug("[tester_runner] _run_sandbox_safe exception: %s", exc)
        return {
            "success": False,
            "stdout": "",
            "stderr": str(exc),
            "exit_code": -1,
        }


def _build_reflection(
    sandbox_result: dict,
    receipt: "ExecutionReceipt",
    eval_result=None,    # EvaluationResult (CodeEvaluator) -- optionnel
    iteration: int = 0,
) -> StructuredReflection:
    """
    FL-01 : Construit une reflexion structuree depuis les resultats sandbox.

    Retrocompat : eval_result=None -> fix_hints=[], quality_criteria=[]
                  Les appelants existants qui ne passent pas eval_result
                  continuent de fonctionner sans modification.

    Args:
        sandbox_result : dict retourne par _run_sandbox_safe.
        receipt        : ExecutionReceipt construit (avant ou apres signature).
        eval_result    : EvaluationResult optionnel (CodeEvaluator).
        iteration      : numero d'iteration courant.

    Returns:
        StructuredReflection.
    """
    sandbox_ok   = sandbox_result.get("success", False)
    stderr       = sandbox_result.get("stderr", "") or ""
    stderr_short = stderr[:200]

    quality_score    = 0
    quality_criteria: List[Dict[str, Any]] = []
    fix_hints:        List[str] = []

    if eval_result is not None:
        quality_score = getattr(eval_result, "score", 0)
        criteria = getattr(eval_result, "criteria", [])
        for c in (criteria or []):
            quality_criteria.append({
                "name":    getattr(c, "name",    "Unknown"),
                "score":   getattr(c, "score",   0),
                "max":     getattr(c, "max",     1),
                "details": getattr(c, "details", "") or "",
            })
        fix_hints = _criteria_to_fix_hints(criteria)

    return StructuredReflection(
        sandbox_passed   = sandbox_ok,
        quality_score    = quality_score,
        quality_criteria = quality_criteria,
        stderr_short     = stderr_short,
        fix_hints        = fix_hints,
        iteration        = iteration,
    )


# ---------------------------------------------------------------------------
# TesterReceiptBuilder
# ---------------------------------------------------------------------------

class TesterReceiptBuilder:
    """
    Construit, signe, verifie et stocke un ExecutionReceipt.

    Usage :
        builder = TesterReceiptBuilder()
        receipt = builder.build(
            task_id="tx_abc123",
            agent_name="tester",
            sandbox_result={"success": True, ...},
            code="def foo(): pass",
            original_payload={},
        )
        # receipt est deja signe et persiste sur disque

    Separation des responsabilites :
        - TesterReceiptBuilder : connait les receipts, rien d'autre.
        - TesterAgent          : connait le bus, les agents, le routage.
    """

    def build(
        self,
        task_id: str,
        agent_name: str,
        sandbox_result: dict,
        code: str,
        original_payload: dict,
    ) -> ExecutionReceipt:
        """
        Construit un ExecutionReceipt signe et persiste sur disque.

        Leve AssertionError si la verification HMAC echoue (V8-Regle-17).

        Args:
            task_id          : identifiant de la tache courante.
            agent_name       : nom de l'agent (ex: "tester").
            sandbox_result   : dict retourne par _run_sandbox_safe.
            code             : code evalue.
            original_payload : payload amont (pour recuperer input_hash + tx_id).

        Returns:
            ExecutionReceipt signe et verifie.
        """
        sandbox_ok = sandbox_result.get("success", False)
        input_hash = original_payload.get("output_hash", _hash(code))
        output_hash = _hash(code)

        receipt = ExecutionReceipt(
            task_id=task_id,
            agent=agent_name,
            input_hash=input_hash,
            output_hash=output_hash,
            sandbox_passed=sandbox_ok,
            tests_passed=1 if sandbox_ok else 0,
            tests_failed=0 if sandbox_ok else 1,
            tx_id=original_payload.get("tx_id"),
            signature="",
        )
        receipt.signature = sign_receipt(task_id, output_hash)

        # V8-Regle-17 : anti-tamper -- leve AssertionError si HMAC invalide
        assert verify_receipt(receipt), (
            f"Receipt HMAC invalide pour task_id={task_id} "
            "-- possible tampering detecte"
        )

        # Persistance audit trail (silencieux si echec disque)
        try:
            store_receipt(receipt)
        except Exception as exc:
            logger.debug("[tester_runner] store_receipt failed: %s", exc)

        return receipt
