# Sprint V8-04 — ReviewerAgent + TesterAgent + ExecutionReceipts
<!-- AI-READY | Sprint V8 | Phase beta | 2026-04-20 -->

## Objectif

Compléter le pipeline A2A avec les deux agents de validation :

- **ReviewerAgent** : valide la cohérence du code produit par le Coder. Si KO, génère une réflexion et rejette (route vers Architect). Si OK, forward au Tester.
- **TesterAgent** : exécute le code en sandbox, mesure les métriques, produit l'`ExecutionReceipt` final signé. Si OK, stocke le skill potentiel. Si KO, appelle le `ReflexionEngine`.

C'est ici que se ferme la boucle : Tester → Architect si échec total.

---

## Fichiers à créer / modifier

| # | Fichier | Opération |
|---|---------|-----------|
| 1 | `core/agents/reviewer.py` | CREATE |
| 2 | `core/agents/tester.py` | CREATE |
| 3 | `core/agents/__init__.py` | PATCH — exporter les deux agents |
| 4 | `tests/test_reviewer_agent.py` | CREATE — 8 tests |
| 5 | `tests/test_tester_agent.py` | CREATE — 8 tests |

> **Prérequis** : Sprint V8-01 (bus), V8-02 (cards), V8-03 (architect/coder), V8-05 (skill_library — peut être mocké), V8-06 (reflexion_engine — peut être mocké).

---

## Spécification : `core/agents/reviewer.py`

```python
# core/agents/reviewer.py
"""
ReviewerAgent — Validation et critique.
Pattern cognitif : Spec validator.
Tools MCP autorisés : validate_spec, analyze_error, memory_search
V8-Règle-19 : Produit une réflexion, à combiner avec celle du Tester.
"""
import logging
from typing import Optional

from core.agents.a2a_bus import A2ALocalBus, A2AMessage, TaskContract
from core.agents.agent_card import REVIEWER_POLICY
from core.spec_validator import SpecValidatorService
from core.error_analyzer import ErrorAnalyzer
import config

log = logging.getLogger("lcca.reviewer")


class ReviewerAgent:
    NAME = "reviewer"

    def __init__(
        self,
        bus: A2ALocalBus,
        validator: Optional[SpecValidatorService] = None,
        error_analyzer: Optional[ErrorAnalyzer] = None,
    ):
        self._bus = bus
        self._validator = validator or SpecValidatorService()
        self._error_analyzer = error_analyzer or ErrorAnalyzer()

    def run_once(self, timeout_sec: int = 30) -> bool:
        msg = self._bus.receive(self.NAME, timeout_sec=timeout_sec)
        if msg is None:
            return False

        log.info("reviewer.run_once task_id=%s", msg.task_id)
        payload = msg.payload
        code = payload.get("code", "")

        # 1. Validation statique (compilabilité)
        static_ok, static_issues = self._check_syntax(code)

        # 2. Analyse des erreurs connues
        error_ctx = ""
        if not static_ok:
            error_ctx = self._error_analyzer.analyze(
                error_type="SyntaxError",
                error_msg="; ".join(static_issues),
                code=code,
            ).get("suggestion", "")

        # 3. Décision
        if static_ok:
            # Forward au Tester
            self._bus.send(
                to="tester",
                from_=self.NAME,
                task_id=msg.task_id,
                payload={**payload, "reviewer_ok": True, "review_notes": []},
                receipt_hash=msg.receipt_hash,
            )
            log.info("reviewer → tester task_id=%s", msg.task_id)
        else:
            # Reject → Architect (Règle 19 : réflexion partielle ici)
            reflection = f"Reviewer: {'; '.join(static_issues)}. Suggestion: {error_ctx}"
            self._bus.send(
                to="architect",
                from_=self.NAME,
                task_id=msg.task_id,
                payload={
                    "rejected": True,
                    "reviewer_ok": False,
                    "reflection": reflection,
                    "original_intent": payload.get("contract", {}).get("intent", ""),
                },
            )
            log.warning("reviewer → architect (rejected) task_id=%s", msg.task_id)

        return True

    def _check_syntax(self, code: str):
        """Compilation Python. Retourne (ok, [issues])."""
        if not code or not code.strip():
            return False, ["Code vide"]
        try:
            compile(code, "<review>", "exec")
            return True, []
        except SyntaxError as exc:
            return False, [f"SyntaxError ligne {exc.lineno}: {exc.msg}"]
        except Exception as exc:
            return False, [str(exc)]
```

---

## Spécification : `core/agents/tester.py`

```python
# core/agents/tester.py
"""
TesterAgent — Sandbox + métriques + receipts.
Pattern cognitif : Verifiable execution.
Tools MCP autorisés : sandbox_run, evaluate_quality
V8-Règle-17 : Aucun skill stocké sans ExecutionReceipt validé.
V8-Règle-18 : KarpathyLoop arrête après 3 stagnations (délégué au loop).
"""
import hashlib
import logging
from typing import Optional, TYPE_CHECKING

from core.agents.a2a_bus import A2ALocalBus, TaskContract
from core.agents.agent_card import TESTER_POLICY
from core.sandbox_engine import SandboxEngine
from core.code_evaluator import CodeEvaluator
from core.receipt_store import ExecutionReceipt, sign_receipt, store_receipt, verify_receipt

if TYPE_CHECKING:
    from core.skill_library import SkillLibrary
    from core.reflexion_engine import ReflexionEngine

log = logging.getLogger("lcca.tester")


class TesterAgent:
    NAME = "tester"

    def __init__(
        self,
        bus: A2ALocalBus,
        sandbox: Optional[SandboxEngine] = None,
        evaluator: Optional[CodeEvaluator] = None,
        skill_library=None,        # SkillLibrary (injection — évite import circulaire)
        reflexion_engine=None,     # ReflexionEngine
    ):
        self._bus = bus
        self._sandbox = sandbox or SandboxEngine(mode="soft")
        self._evaluator = evaluator or CodeEvaluator()
        self._skill_lib = skill_library
        self._reflexion = reflexion_engine

    def run_once(self, timeout_sec: int = 30) -> bool:
        msg = self._bus.receive(self.NAME, timeout_sec=timeout_sec)
        if msg is None:
            return False

        log.info("tester.run_once task_id=%s", msg.task_id)
        payload = msg.payload
        code = payload.get("code", "")
        contract_dict = payload.get("contract", {})

        # 1. Sandbox
        sandbox_result = self._run_sandbox(code)
        sandbox_ok = sandbox_result.get("success", False)

        # 2. Évaluation qualité
        eval_result = self._evaluator.evaluate(code, filename="<agent_output>")
        quality_score = getattr(eval_result, "score", 0)

        # 3. Construire et signer le receipt final
        output_hash = hashlib.md5(code.encode()).hexdigest()
        receipt = ExecutionReceipt(
            task_id=msg.task_id,
            agent=self.NAME,
            input_hash=payload.get("output_hash", ""),  # sortie du Coder = entrée du Tester
            output_hash=output_hash,
            sandbox_passed=sandbox_ok,
            tests_passed=sandbox_result.get("tests_passed", 0),
            tests_failed=sandbox_result.get("tests_failed", 0),
            tx_id=payload.get("tx_id"),
            signature="",
        )
        receipt.signature = sign_receipt(msg.task_id, output_hash)

        # 4. Vérifier l'intégrité (anti-tamper)
        assert verify_receipt(receipt), "Receipt HMAC invalide — possible tampering"
        store_receipt(receipt)

        if sandbox_ok and quality_score >= 70:
            # 5a. Succès → tenter stockage skill (V8-Règle-17)
            self._maybe_store_skill(code, receipt, contract_dict, quality_score)
            log.info("tester OK task_id=%s quality=%d", msg.task_id, quality_score)
        else:
            # 5b. Échec → réflexion → Architect
            reflection = self._generate_reflection(code, sandbox_result, receipt)
            self._bus.send(
                to="architect",
                from_=self.NAME,
                task_id=msg.task_id,
                payload={
                    "rejected": True,
                    "tester_ok": False,
                    "sandbox_passed": sandbox_ok,
                    "quality_score": quality_score,
                    "reflection": reflection,
                    "original_intent": contract_dict.get("intent", ""),
                },
            )
            log.warning("tester → architect (rejected) task_id=%s quality=%d sandbox=%s",
                        msg.task_id, quality_score, sandbox_ok)

        return True

    def _run_sandbox(self, code: str) -> dict:
        try:
            result = self._sandbox.run_code(code)
            return {
                "success": result.get("success", False),
                "tests_passed": result.get("tests_passed", 0),
                "tests_failed": result.get("tests_failed", 0),
                "output": result.get("output", ""),
            }
        except Exception as exc:
            log.debug("tester._run_sandbox error: %s", exc)
            return {"success": False, "tests_passed": 0, "tests_failed": 1}

    def _maybe_store_skill(self, code: str, receipt: ExecutionReceipt,
                           contract: dict, quality_score: int):
        """V8-Règle-17 : stockage uniquement si receipt valide."""
        if self._skill_lib is None:
            return
        try:
            self._skill_lib.extract_and_store(
                code=code,
                receipt=receipt,
                source_intent=contract.get("intent", ""),
                quality_score=quality_score,
            )
        except Exception as exc:
            log.debug("tester._maybe_store_skill failed: %s", exc)

    def _generate_reflection(self, code: str, sandbox_result: dict,
                              receipt: ExecutionReceipt) -> str:
        """Réflexion partielle du Tester. Combinée avec celle du Reviewer par Règle 19."""
        if self._reflexion is None:
            # Réflexion minimale sans LLM
            return (f"Tester: sandbox_passed={receipt.sandbox_passed}, "
                    f"tests_failed={receipt.tests_failed}")
        try:
            return self._reflexion.reflect_on_failure(
                code=code,
                error_output=sandbox_result.get("output", ""),
                agent=self.NAME,
            )
        except Exception:
            return f"Tester: échec sandbox (tests_failed={receipt.tests_failed})"
```

---

## Checklist des tests

### `tests/test_reviewer_agent.py`
- [ ] `test_run_once_false_if_no_message` — bus vide → False
- [ ] `test_valid_code_forwarded_to_tester` — code valid → bus.peek("tester") == 1
- [ ] `test_invalid_code_rejected_to_architect` — code SyntaxError → bus.peek("architect") == 1
- [ ] `test_empty_code_rejected` — code="" → rejected=True
- [ ] `test_reviewer_ok_flag_in_payload` — reviewer_ok: True dans le message vers tester
- [ ] `test_reflection_present_on_reject` — "reflection" dans le payload vers architect
- [ ] `test_receipt_hash_propagated` — receipt_hash du coder transmis au tester
- [ ] `test_run_once_true_if_message` — message traité → True

### `tests/test_tester_agent.py`
- [ ] `test_run_once_false_if_no_message` — bus vide → False
- [ ] `test_receipt_stored_on_success` — receipt .json créé après run_once
- [ ] `test_receipt_signature_valid` — verify_receipt(receipt) == True
- [ ] `test_low_quality_rejected` — quality_score < 70 → bus.peek("architect") == 1
- [ ] `test_sandbox_failure_rejected` — sandbox retourne success=False → rejected=True
- [ ] `test_skill_stored_on_success` — skill_lib.extract_and_store appelé si success + quality >= 70
- [ ] `test_skill_not_stored_without_receipt` — si receipt invalide → AssertionError
- [ ] `test_reflection_generated_on_failure` — reflection != "" dans payload rejected

---

## Notes importantes

- **V8-Règle-19** : Reviewer et Tester produisent chacun une réflexion. AgentOrchestrator (Sprint V8-08) les combine avant stockage.
- **Seuil qualité** : `quality_score >= 70` (70% du CodeEvaluator). Ajustable dans `config.py` comme `AGENT_MIN_QUALITY_SCORE = 70`.
- **Import conditionnel** `TYPE_CHECKING` : évite les imports circulaires entre agents et skill_library/reflexion_engine — injectés depuis l'orchestrateur.
