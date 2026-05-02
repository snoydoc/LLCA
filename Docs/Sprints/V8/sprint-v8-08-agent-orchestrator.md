# Sprint V8-08 — AgentOrchestrator + main --mode=agentic + Tests E2E
<!-- AI-READY | Sprint V8 | Phase rc | 2026-04-20 -->

## Objectif

**Sprint de clôture V8.0** : assembler tous les composants en un système cohérent.

- `AgentOrchestrator` : boot des agents, routing, gestion des rejets, consensus de réflexions
- `main.py --mode=agentic` : point d'entrée unique pour le mode agentique
- `NLOrchestratorV8Adapter` : rétrocompatibilité V7 → V8 avec `DeprecationWarning`
- `ObserverAgent` : maintenance mémoire périodique
- Tests E2E : pipeline complet Architect → Coder → Reviewer → Tester

---

## Fichiers à créer / modifier

| # | Fichier | Opération |
|---|---------|-----------|
| 1 | `core/agent_orchestrator.py` | CREATE |
| 2 | `core/agents/observer.py` | CREATE |
| 3 | `core/nl_orchestrator_v8_adapter.py` | CREATE |
| 4 | `main.py` | PATCH — `--mode=agentic` argument |
| 5 | `core/__init__.py` | PATCH — version `8.0.0`, exporter nouveaux modules |
| 6 | `.claude-skills/003-project-context.md` | PATCH — arborescence V8 |
| 7 | `.claude-skills/004-sprint-context.md` | PATCH — sprint context mis à jour |
| 8 | `tests/test_agent_orchestrator.py` | CREATE — 10 tests |
| 9 | `tests/test_agents_e2e.py` | CREATE — 6 tests E2E |
| 10 | `tests/test_nl_adapter.py` | CREATE — 4 tests |
| 11 | `tests/test_agentic_mode.py` | CREATE — 3 tests |

---

## Spécification : `core/agent_orchestrator.py`

```python
# core/agent_orchestrator.py
"""
AgentOrchestrator V8 — Chef d'orchestre du système multi-agent.
Boot les 5 agents, route les demandes, gère les rejets et le consensus réflexion.

Ne modifie jamais core/ directement (V8-Règle-20).
"""
import logging
import threading
from typing import Optional

from core.agents.a2a_bus import A2ALocalBus
from core.agents.agent_card import AgentRegistry
from core.agents.architect import ArchitectAgent
from core.agents.coder import CoderAgent
from core.agents.reviewer import ReviewerAgent
from core.agents.tester import TesterAgent
from core.agents.observer import ObserverAgent
from core.memory_engine import MemoryEngine
from core.reflexion_engine import ReflexionEngine, Reflexion
from core.skill_library import SkillLibrary
from core.llm_generator import LLMGenerator
import config

log = logging.getLogger("lcca.orchestrator_v8")

# Timeout de traitement d'un pipeline complet (secondes)
_PIPELINE_TIMEOUT = getattr(config, "AGENT_PIPELINE_TIMEOUT", 120)


class AgentOrchestrator:
    """
    Orchestre le pipeline multi-agent V8.

    Architecture :
        handle(intent) → architect.handle() → [bus] → coder → [bus] → reviewer → [bus] → tester
        En cas de rejet : tester/reviewer → [bus] → architect (max 2 retry)
    """
    MAX_RETRIES = 2   # Rejets max avant abandon (1 init + 2 retry = 3 tentatives total)

    def __init__(
        self,
        bus: Optional[A2ALocalBus] = None,
        memory: Optional[MemoryEngine] = None,
        registry: Optional[AgentRegistry] = None,
    ):
        self._bus = bus or A2ALocalBus()
        self._memory = memory or MemoryEngine()
        self._registry = registry or AgentRegistry.default()
        self._skill_lib = SkillLibrary(self._memory)
        self._reflexion = ReflexionEngine(self._memory)
        self._generator = LLMGenerator()

        # Instanciation des agents
        self._architect = ArchitectAgent(self._bus, self._memory)
        self._coder = CoderAgent(self._bus, self._memory, self._generator)
        self._reviewer = ReviewerAgent(self._bus)
        self._tester = TesterAgent(
            self._bus, skill_library=self._skill_lib,
            reflexion_engine=self._reflexion
        )
        self._observer = ObserverAgent(self._bus, self._memory, self._skill_lib)

        self._running = False
        self._threads: list = []

    # ── API publique ──────────────────────────────────────────────────

    def handle(self, intent: str, domain: str = "global") -> dict:
        """
        Traite un intent utilisateur en mode synchrone.
        Attend la complétion du pipeline (timeout = _PIPELINE_TIMEOUT).
        Retourne un dict de résultat.
        """
        log.info("orchestrator.handle intent=%r", intent)

        # Purger les éventuels messages résiduels de la session précédente
        # (uniquement en mode synchrone/test — pas en mode daemon)
        if not self._running:
            self._bus.purge()

        # Démarrer les agents consommateurs en threads courts
        result = self._run_pipeline_sync(intent, domain)
        return result

    def boot(self):
        """
        Lance les agents en mode daemon (boucle infinie).
        Utilisé par main.py --mode=agentic.
        """
        self._running = True

        def worker(agent, name):
            while self._running:
                try:
                    agent.run_once(timeout_sec=5)
                except Exception as exc:
                    log.error("agent %s crashed: %s", name, exc)

        for agent, name in [
            (self._coder, "coder"),
            (self._reviewer, "reviewer"),
            (self._tester, "tester"),
        ]:
            t = threading.Thread(target=worker, args=(agent, name), daemon=True)
            t.start()
            self._threads.append(t)

        log.info("orchestrator.boot: coder/reviewer/tester daemons started")

    def stop(self):
        self._running = False

    def repl(self):
        """REPL interactif agentique."""
        print("LCCA V8 — Mode agentique. 'exit' pour quitter.")
        while True:
            try:
                intent = input("lcca> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if intent.lower() in ("exit", "quit", "q"):
                break
            if not intent:
                continue
            result = self.handle(intent)
            status = "✅" if result.get("success") else "❌"
            print(f"{status} {result.get('message', result)}")
        self.stop()

    # ── Pipeline synchrone (mode handle()) ───────────────────────────

    def _run_pipeline_sync(self, intent: str, domain: str) -> dict:
        """
        Exécute le pipeline complet de façon synchrone.
        Utilisé en mode test/direct — pas le mode daemon.
        """
        import time
        start = time.monotonic()

        for attempt in range(self.MAX_RETRIES + 1):
            task_ids = self._architect.handle(intent, domain)
            if not task_ids:
                return {"success": False, "message": "Architect n'a émis aucune tâche"}

            task_id = task_ids[0]

            # Déroulement séquentiel : coder → reviewer → tester
            if not self._coder.run_once(timeout_sec=30):
                return {"success": False, "message": "Coder timeout"}

            if not self._reviewer.run_once(timeout_sec=15):
                return {"success": False, "message": "Reviewer timeout"}

            tester_result = self._try_tester(timeout_sec=30)
            if tester_result.get("success"):
                return {
                    "success": True,
                    "task_id": task_id,
                    "message": f"Pipeline OK — {attempt} retry",
                    "quality_score": tester_result.get("quality_score", 0),
                }

            # Rejet → vérifier si reflections en attente
            rejection = self._bus.receive("architect", timeout_sec=2)
            if rejection is None:
                break

            # V8-Règle-19 : tenter de merger les réflexions
            self._handle_rejection_reflexions(rejection.payload)

            if time.monotonic() - start > _PIPELINE_TIMEOUT:
                break

        return {"success": False, "message": "Pipeline échec après retries"}

    def _try_tester(self, timeout_sec: int) -> dict:
        self._tester.run_once(timeout_sec=timeout_sec)
        # Vérifier si un rejection a été émis vers architect
        pending_rejection = self._bus.peek("architect") > 0
        return {"success": not pending_rejection}

    def _handle_rejection_reflexions(self, rejection_payload: dict):
        """
        V8-Règle-19 : combine les réflexions Reviewer + Tester avant stockage.
        """
        reviewer_reflection = rejection_payload.get("reflection", "")
        tester_reflection = rejection_payload.get("reflection", "")  # Peut venir des deux

        if not reviewer_reflection and not tester_reflection:
            return

        # Créer des réflexions minimales pour le merge
        reflexions = []
        if reviewer_reflection:
            reflexions.append(Reflexion(
                task_hash="", failure_type="ValidationError",
                context="", reflection=reviewer_reflection,
                fix="", verified=False, agents=["reviewer"]
            ))
        if tester_reflection and tester_reflection != reviewer_reflection:
            reflexions.append(Reflexion(
                task_hash="", failure_type="SandboxError",
                context="", reflection=tester_reflection,
                fix="", verified=False, agents=["tester"]
            ))

        merged = self._reflexion.merge_agent_reflexions(reflexions)
        if merged:
            self._reflexion.store(merged)
```

---

## Spécification : `core/agents/observer.py`

```python
# core/agents/observer.py
"""
ObserverAgent V8 — Maintenance mémoire.
Agent passif. S'exécute périodiquement (sur demande ou en cron).
"""
import logging
from typing import Optional

from core.agents.a2a_bus import A2ALocalBus
from core.memory_engine import MemoryEngine

log = logging.getLogger("lcca.observer")


class ObserverAgent:
    NAME = "observer"

    def __init__(
        self,
        bus: A2ALocalBus,
        memory: Optional[MemoryEngine] = None,
        skill_library=None,
    ):
        self._bus = bus
        self._memory = memory
        self._skill_lib = skill_library

    def run_once(self, timeout_sec: int = 5) -> bool:
        """Consomme une tâche de maintenance depuis le bus."""
        msg = self._bus.receive(self.NAME, timeout_sec=timeout_sec)
        if msg is None:
            return False

        action = msg.payload.get("action", "")
        log.info("observer.run_once action=%s", action)

        if action == "deduplicate_skills" and self._skill_lib:
            removed = self._skill_lib.deduplicate()
            log.info("observer.deduplicate_skills removed=%d", removed)

        elif action == "archive_old_receipts":
            days = msg.payload.get("days", 30)
            self._archive_old_receipts(days)

        return True

    def _archive_old_receipts(self, days: int):
        """Déplace les receipts anciens dans receipts_archive/."""
        try:
            import config
            from datetime import datetime, timezone, timedelta
            receipts_dir = config.A2A_RECEIPTS_DIR if hasattr(config, "A2A_RECEIPTS_DIR") else None
            if receipts_dir is None:
                return
            archive_dir = receipts_dir.parent / "receipts_archive"
            archive_dir.mkdir(parents=True, exist_ok=True)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            moved = 0
            for f in receipts_dir.glob("*.json"):
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    f.rename(archive_dir / f.name)
                    moved += 1
            log.info("observer.archive_old_receipts days=%d moved=%d", days, moved)
        except Exception as exc:
            log.debug("observer._archive_old_receipts error: %s", exc)
```

---

## Spécification : `core/nl_orchestrator_v8_adapter.py`

```python
# core/nl_orchestrator_v8_adapter.py
"""
Adaptateur rétrocompatible V7 → V8.
Émet un DeprecationWarning et redirige les requêtes NL vers AgentOrchestrator.

À supprimer en V8.1 (après migration complète).
"""
import warnings
import logging

log = logging.getLogger("lcca.nl_adapter")


class NLOrchestratorV8Adapter:
    """
    Remplaçant rétrocompat de NLOrchestrator pour la V8.
    Utilisez AgentOrchestrator directement en V8.
    """
    def __init__(self):
        warnings.warn(
            "NLOrchestrator est déprécié en V8. Utilisez AgentOrchestrator.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Import lazy pour éviter boot complet si juste un test de compatibilité
        from core.agent_orchestrator import AgentOrchestrator
        self._orch = AgentOrchestrator()

    def run(self, command: str) -> dict:
        """Interface V7. Délègue à AgentOrchestrator.handle()."""
        log.info("nl_adapter.run (deprecated): %r", command)
        return self._orch.handle(intent=command, domain="global")

    def execute(self, command: str) -> dict:
        """Alias de run() — interface legacy."""
        return self.run(command)
```

---

## Patch `main.py`

```python
# Ajout de l'argument --mode
import argparse

def main():
    parser = argparse.ArgumentParser(description="LCCA V8")
    parser.add_argument("--mode", choices=["direct", "agentic", "mcp"],
                        default="direct",
                        help="Mode de démarrage (default: direct)")
    args, remaining = parser.parse_known_args()

    if args.mode == "agentic":
        from core.agent_orchestrator import AgentOrchestrator
        orch = AgentOrchestrator()
        orch.boot()
        orch.repl()
    elif args.mode == "mcp":
        from core.mcp_server import McpServer
        McpServer().serve_stdio()
    else:
        # Mode direct V5/V7 (comportement inchangé)
        from core.orchestrator import LCCAV5Fusion
        # ... reste du code existant ...
        pass
```

---

## Checklist des tests

### `tests/test_agent_orchestrator.py`
- [ ] `test_handle_returns_dict` — handle() retourne toujours un dict
- [ ] `test_handle_success_key_present` — clé "success" dans le résultat
- [ ] `test_boot_starts_daemon_threads` — boot() → threads non-None
- [ ] `test_stop_sets_running_false` — stop() → _running=False
- [ ] `test_bus_purged_before_sync_pipeline` — handle() purge le bus avant de démarrer
- [ ] `test_max_retries_respected` — échec répété → MAX_RETRIES tentatives max
- [ ] `test_reflexion_merged_on_rejection` — rejection payload → reflexion.merge appelé
- [ ] `test_architect_task_ids_empty` — architect retourne [] → success=False
- [ ] `test_coder_timeout` — coder ne répond pas → success=False
- [ ] `test_pipeline_success_returns_task_id` — pipeline OK → task_id dans le résultat

### `tests/test_agents_e2e.py`
- [ ] `test_architect_to_coder_to_reviewer_to_tester_flow` — pipeline complet avec mocks
- [ ] `test_rejection_triggers_retry` — reviewer reject → architect reçoit rejection
- [ ] `test_skill_stored_after_success` — succès complet → skill_lib.extract_and_store appelé
- [ ] `test_reflexion_stored_after_rejection` — échec → reflexion dans lcca_failures
- [ ] `test_observer_deduplicates_skills` — observer reçoit action → deduplicate appelé
- [ ] `test_pipeline_respects_pipeline_timeout` — timeout global respecté

### `tests/test_nl_adapter.py`
- [ ] `test_nlorchestrator_v8_emits_deprecation_warning` — DeprecationWarning levé
- [ ] `test_nlorchestrator_v8_redirect` — run() → orch.handle() appelé
- [ ] `test_execute_alias` — execute() = run()
- [ ] `test_adapter_returns_dict` — résultat est un dict

### `tests/test_agentic_mode.py`
- [ ] `test_main_agentic_boots_agents` — --mode=agentic → boot() appelé (mocké)
- [ ] `test_main_mcp_starts_server` — --mode=mcp → McpServer.serve_stdio() appelé
- [ ] `test_main_direct_unchanged` — --mode=direct → comportement V7 inchangé

---

## Mise à jour skills (fin de sprint obligatoire)

```markdown
# Mises à jour à faire en fin de Sprint V8-08 :

1. `.claude-skills/001-skill-coding-agent-master.md`
   → Ajouter patterns Session V8 (A2A, agents, Karpathy, réflexions)

2. `.claude-skills/003-project-context.md`
   → Ajouter core/agents/ et nouveaux modules à l'arborescence

3. `.claude-skills/004-sprint-context.md`
   → Marquer Sprint V8-08 TERMINÉ, prochains sprints possibles

4. `core/__init__.py`
   → version = "8.0.0"
   → Exporter : AgentOrchestrator, A2ALocalBus, SkillLibrary,
                ReflexionEngine, KarpathyLoop
```

---

## Règles applicables à ce sprint

- V8-Règle-21 : AgentOrchestrator coordonne via A2ALocalBus uniquement
- V8-Règle-19 : Réflexions combinées Reviewer+Tester dans `_handle_rejection_reflexions()`
- V8-Règle-20 : AgentOrchestrator et ObserverAgent ne font jamais de `write_text()` direct sur `core/`
- Règle legacy : les 525+ tests V5/V7 restent verts après ce sprint

## Anti-patterns interdits

- ❌ `while True` dans les agents sans `self._running` guard (risque de thread zombie)
- ❌ Import de `AgentOrchestrator` dans les agents (dépendance circulaire)
- ❌ Bus partagé entre tests sans `bus.purge()` (contamination d'état)
