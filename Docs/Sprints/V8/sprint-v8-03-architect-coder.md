# Sprint V8-03 — ArchitectAgent + CoderAgent
<!-- AI-READY | Sprint V8 | Phase alpha | 2026-04-20 -->

## Objectif

Implémenter les deux premiers agents du pipeline V8 :

- **ArchitectAgent** : reçoit une demande utilisateur, cherche les skills existants, génère une spec, décompose en `TaskContracts`, les envoie au Coder.
- **CoderAgent** : reçoit un `TaskContract`, cherche les skills pertinents, génère/applique le code via `edit_batch` ACID, émet un receipt partiel.

---

## Fichiers à créer / modifier

| # | Fichier | Opération |
|---|---------|-----------|
| 1 | `core/agents/architect.py` | CREATE |
| 2 | `core/agents/coder.py` | CREATE |
| 3 | `core/agents/__init__.py` | PATCH — exporter les deux agents |
| 4 | `tests/test_architect_agent.py` | CREATE — 8 tests |
| 5 | `tests/test_coder_agent.py` | CREATE — 8 tests |

---

## Spécification : `core/agents/architect.py`

```python
# core/agents/architect.py
"""
ArchitectAgent — Planning et décomposition.
Reçoit un intent utilisateur, produit des TaskContracts pour le Coder.

Tools MCP autorisés : memory_search, project_search, generate_spec (interne)
V8-Règle-20 : Ne modifie jamais core/ directement.
"""
import hashlib
import logging
from typing import List, Optional

from core.agents.a2a_bus import A2ALocalBus, TaskContract
from core.agents.agent_card import AgentRegistry
from core.memory_engine import MemoryEngine
from core.spec_generator import SpecGeneratorService
from core.spec_entry import SpecEntry
import config

log = logging.getLogger("lcca.architect")


class ArchitectAgent:
    """
    Pattern cognitif : Deep reasoning.
    1. Cherche skills + specs existants (RAG)
    2. Si skill complet trouvé → délégation directe au Coder
    3. Sinon → génère spec interne → décompose → TaskContracts
    """
    NAME = "architect"

    def __init__(
        self,
        bus: A2ALocalBus,
        memory: Optional[MemoryEngine] = None,
        spec_generator: Optional[SpecGeneratorService] = None,
        registry: Optional[AgentRegistry] = None,
    ):
        self._bus = bus
        self._memory = memory or MemoryEngine()
        self._spec_gen = spec_generator or SpecGeneratorService()
        self._registry = registry or AgentRegistry.default()

    # ── Interface publique ────────────────────────────────────────────

    def handle(self, intent: str, domain: str = "global") -> List[str]:
        """
        Traite un intent. Retourne la liste des task_ids émis.
        Appelé par AgentOrchestrator.
        """
        log.info("architect.handle intent=%r domain=%s", intent, domain)

        # 1. Chercher skills existants
        skills_ctx = self._search_skills(intent)

        # 2. Générer spec interne (privée — Addendum 3.2)
        spec = self._generate_spec(intent, domain, extra_context=skills_ctx)

        # 3. Décomposer en sous-tâches
        contracts = self._decompose(intent, domain, spec, reuse_skills=bool(skills_ctx))

        # 4. Émettre les TaskContracts vers le Coder
        task_ids = []
        for contract in contracts:
            self._bus.send(
                to="coder",
                from_=self.NAME,
                task_id=contract.task_id,
                payload=contract.to_dict(),
            )
            log.info("architect → coder task_id=%s", contract.task_id)
            task_ids.append(contract.task_id)

        return task_ids

    # ── Méthodes internes ─────────────────────────────────────────────

    def _search_skills(self, intent: str) -> str:
        """RAG mémoire : skills + specs similaires."""
        try:
            results = self._memory.search(intent, n=3)
            snippets = []
            for entry in results.get("solutions", []) + results.get("specs", []):
                content = getattr(entry, "content", "") or ""
                snippets.append(content[:400])
            return "\n".join(snippets)
        except Exception:
            return ""

    def _generate_spec(self, intent: str, domain: str, extra_context: str = "") -> Optional[SpecEntry]:
        """Génère une spec interne. Non exposée au MCP (Addendum 3.2)."""
        try:
            result = self._spec_gen.generate(
                intent=intent,
                domain=domain,
                context=extra_context,
            )
            if isinstance(result, dict) and result.get("validated"):
                return SpecEntry.from_dict(result)
        except Exception as exc:
            log.debug("architect._generate_spec failed: %s", exc)
        return None

    def _decompose(
        self,
        intent: str,
        domain: str,
        spec: Optional[SpecEntry],
        reuse_skills: bool,
    ) -> List[TaskContract]:
        """
        Décompose l'intent en 1-3 TaskContracts.
        V1 simplifiée : un seul contrat pour la tâche complète.
        V8.1 : décomposition LLM-driven multi-tâches.
        """
        task_id = self._bus.make_task_id(intent)
        contract = TaskContract(
            task_id=task_id,
            intent=intent,
            domain=domain,
            source_agent=self.NAME,
            target_agent="coder",
            context={"reuse_skills": reuse_skills},
            spec_id=spec.spec_id if spec else None,
        )
        return [contract]

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()[:12]
```

---

## Spécification : `core/agents/coder.py`

```python
# core/agents/coder.py
"""
CoderAgent — Génération et application de code.
Reçoit un TaskContract depuis l'Architect, génère le code, applique via edit_batch ACID.

Tools MCP autorisés : edit_batch, memory_search
V8-Règle-20 : utilise TransactionManager via MCP edit_batch, jamais d'écriture directe.
"""
import hashlib
import logging
from typing import Optional

from core.agents.a2a_bus import A2ALocalBus, A2AMessage, TaskContract
from core.agents.agent_card import CODER_POLICY
from core.llm_generator import LLMGenerator
from core.mcp_edit_batch import McpEditBatch
from core.memory_engine import MemoryEngine
from core.receipt_store import ExecutionReceipt, sign_receipt
import config

log = logging.getLogger("lcca.coder")


class CoderAgent:
    """
    Pattern cognitif : Spec formatter.
    1. Lit le TaskContract depuis le bus
    2. Cherche skills réutilisables
    3. Génère le code (LLM ou injection skill)
    4. Applique via edit_batch ACID
    5. Émet vers le Reviewer avec receipt partiel
    """
    NAME = "coder"

    def __init__(
        self,
        bus: A2ALocalBus,
        memory: Optional[MemoryEngine] = None,
        generator: Optional[LLMGenerator] = None,
        edit_batch: Optional[McpEditBatch] = None,
    ):
        self._bus = bus
        self._memory = memory or MemoryEngine()
        self._generator = generator or LLMGenerator()
        self._edit_batch = edit_batch or McpEditBatch()

    # ── Interface publique ────────────────────────────────────────────

    def run_once(self, timeout_sec: int = 30) -> bool:
        """
        Consomme un message depuis le bus et le traite.
        Retourne True si un message a été traité, False si timeout.
        Appelé en boucle par AgentOrchestrator.
        """
        msg = self._bus.receive(self.NAME, timeout_sec=timeout_sec)
        if msg is None:
            return False

        log.info("coder.run_once task_id=%s from=%s", msg.task_id, msg.from_agent)
        try:
            contract = TaskContract.from_dict(msg.payload)
            result_payload, receipt = self._process(contract)

            # Émettre vers le Reviewer
            self._bus.send(
                to="reviewer",
                from_=self.NAME,
                task_id=msg.task_id,
                payload=result_payload,
                receipt_hash=receipt.signature,
            )
            log.info("coder → reviewer task_id=%s success=%s", msg.task_id, result_payload.get("success"))
            return True

        except Exception as exc:
            log.error("coder.run_once failed task_id=%s: %s", msg.task_id, exc)
            self._handle_failure(msg, str(exc))
            return True

    # ── Méthodes internes ─────────────────────────────────────────────

    def _process(self, contract: TaskContract):
        """Génère + applique le code. Retourne (payload, receipt)."""
        # 1. Chercher skills réutilisables
        skill_prompt = self._search_skills(contract.intent)

        # 2. Générer le code
        gen_result = self._generator.generate(
            operation="implement",
            intent=contract.intent,
            context=skill_prompt or contract.context.get("extra_context", ""),
        )

        code = gen_result.code if hasattr(gen_result, "code") else str(gen_result)
        input_hash = hashlib.md5(contract.intent.encode()).hexdigest()
        output_hash = hashlib.md5(code.encode()).hexdigest()

        # 3. Appliquer via edit_batch (ACID — Règle 1)
        success = False
        tx_id = None
        try:
            batch_result = self._edit_batch.apply(
                [{"operation": "create_or_patch", "content": code}]
            )
            success = batch_result.get("success", False)
            tx_id = batch_result.get("tx_id")
        except Exception as exc:
            log.warning("coder.edit_batch failed: %s", exc)

        # 4. Construire receipt partiel
        receipt = ExecutionReceipt(
            task_id=contract.task_id,
            agent=self.NAME,
            input_hash=input_hash,
            output_hash=output_hash,
            sandbox_passed=False,   # Le Tester va compléter
            tests_passed=0,
            tests_failed=0,
            tx_id=tx_id,
            signature="",
        )
        receipt.signature = sign_receipt(contract.task_id, output_hash)

        payload = {
            "success": success,
            "task_id": contract.task_id,
            "code": code,
            "tx_id": tx_id,
            "output_hash": output_hash,
            "contract": contract.to_dict(),
        }
        return payload, receipt

    def _search_skills(self, intent: str) -> str:
        try:
            results = self._memory.search(intent, n=2)
            snippets = [
                getattr(e, "content", "")[:300]
                for e in results.get("solutions", [])
            ]
            return "\n".join(filter(None, snippets))
        except Exception:
            return ""

    def _handle_failure(self, msg: A2AMessage, error: str):
        """Politique CODER_POLICY : rollback. Émet erreur vers Architect."""
        if CODER_POLICY.fallback_agent:
            self._bus.send(
                to=CODER_POLICY.fallback_agent,
                from_=self.NAME,
                task_id=msg.task_id,
                payload={"error": error, "original": msg.payload},
            )
```

---

## Checklist des tests

### `tests/test_architect_agent.py`
- [ ] `test_handle_returns_task_ids` — handle() retourne au moins un task_id
- [ ] `test_task_contract_sent_to_coder` — après handle(), bus.peek("coder") == 1
- [ ] `test_handle_with_no_memory_ok` — MemoryEngine mocké sans résultats = pas d'erreur
- [ ] `test_spec_generation_failure_doesnt_crash` — spec_gen lève → handle() continue
- [ ] `test_task_id_is_stable` — même intent → même task_id
- [ ] `test_domain_propagated_in_contract` — domain="ast" dans le contract
- [ ] `test_skill_context_injected` — mémoire retourne un skill → reuse_skills=True dans contract
- [ ] `test_decompose_returns_single_contract_v1` — V1 : toujours 1 contrat

### `tests/test_coder_agent.py`
- [ ] `test_run_once_returns_false_if_no_message` — bus vide → False
- [ ] `test_run_once_returns_true_if_message` — message présent → True
- [ ] `test_message_forwarded_to_reviewer` — après run_once, bus.peek("reviewer") == 1
- [ ] `test_edit_batch_failure_doesnt_crash` — edit_batch lève → success=False mais message émis
- [ ] `test_failure_escalates_to_architect` — erreur critique → message vers "architect"
- [ ] `test_receipt_signature_present` — receipt_hash dans le message vers reviewer
- [ ] `test_no_direct_file_write` — CoderAgent n'importe pas pathlib.write_text
- [ ] `test_skill_search_failure_ok` — MemoryEngine lève → _search_skills retourne ""

---

## Patterns clés

- **AgentOrchestrator** (Sprint V8-08) appellera `architect.handle()` depuis le REPL
- **CoderAgent** tourne en boucle via `run_once()` — jamais de `while True` dans le run (géré par orchestrateur)
- **Règle atomicité** : CoderAgent ne fait jamais de `write_text()` direct — passe toujours par `McpEditBatch`
- **Receipt partiel** : le Coder signe la sortie, mais `sandbox_passed=False` — le Tester complètera
