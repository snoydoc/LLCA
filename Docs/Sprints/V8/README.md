# Sprints V8 — Cognitive Fabric
<!-- AI-READY | Index sprints V8 | Version 8.0.0 | 2026-04-20 -->

## Contexte

La V7.2 (Sprints 20-22 + Audits 007-012) est complète et propre.  
La V8 transforme LCCA d'un outil piloté par l'utilisateur en un **système d'agents cognitifs autonomiques**.

> **Invariant absolu** : les 525+ tests V5/V7 doivent rester verts à chaque sprint.

---

## Architecture cible

```
Utilisateur
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  AgentOrchestrator (main.py --mode=agentic)        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │Architect │ │  Coder   │ │ Reviewer │ │ Tester │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘ │
│       └────────────┴────────────┴────────────┘      │
│                 A2ALocalBus (SQLite3 ACID)           │
└─────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  Memory Fabric                                      │
│  lcca_skills · lcca_specs · lcca_failures           │
│  lcca_receipts · lcca_solutions · lcca_context      │
└─────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  LCCA V7.2 Core (conservé intégralement)            │
│  TransactionManager · SmartPatcher · SandboxEngine  │
│  ASTIndexer · LLMGenerator · MemoryEngine           │
└─────────────────────────────────────────────────────┘
```

---

## Roadmap

| Sprint | Nom | Phase | Durée | Statut |
|--------|-----|-------|-------|--------|
| [V8-01](sprint-v8-01-a2a-bus.md) | A2A Bus SQLite3 + TaskContract | V8.0-alpha | ~3h | 🔮 À FAIRE |
| [V8-02](sprint-v8-02-agent-cards.md) | AgentCard + RecoveryPolicy + Registry | V8.0-alpha | ~2h | 🔮 À FAIRE |
| [V8-03](sprint-v8-03-architect-coder.md) | ArchitectAgent + CoderAgent | V8.0-alpha | ~4h | 🔮 À FAIRE |
| [V8-04](sprint-v8-04-reviewer-tester.md) | ReviewerAgent + TesterAgent + Receipts | V8.0-beta | ~4h | 🔮 À FAIRE |
| [V8-05](sprint-v8-05-skill-library.md) | SkillLibrary + SkillExtractor | V8.0-beta | ~3h | 🔮 À FAIRE |
| [V8-06](sprint-v8-06-reflexion-engine.md) | ReflexionEngine + lcca_failures enrichi | V8.0-beta | ~3h | 🔮 À FAIRE |
| [V8-07](sprint-v8-07-karpathy-loop.md) | KarpathyLoop + métriques composites | V8.0-rc | ~3h | 🔮 À FAIRE |
| [V8-08](sprint-v8-08-agent-orchestrator.md) | AgentOrchestrator + main --mode=agentic + tests E2E | V8.0-rc | ~4h | 🔮 À FAIRE |

**Total estimé** : ~26h de développement.

---

## Nouvelles règles invariantes V8

| # | Règle | Raison |
|---|-------|--------|
| 16 | Un agent ne modifie jamais la mémoire d'un autre agent | Isolation A2A |
| 17 | Aucun skill n'est stocké sans ExecutionReceipt validé | Verifiable execution |
| 18 | KarpathyLoop s'arrête si 3 itérations sans amélioration | Anti-reward hacking |
| 19 | Les réflexions sont produites par ≥ 2 agents (consensus) | Multi-Agent Reflexion |
| 20 | Aucun agent ne peut modifier `core/` directement | Safety constraint |
| 21 | Toute communication inter-agent passe par A2ALocalBus | Bus isolation |

---

## Nouveaux modules à créer

```
core/
├── agents/
│   ├── __init__.py
│   ├── agent_card.py          # AgentCard + RecoveryPolicy + Registry
│   ├── architect.py           # Planning + décomposition + spec interne
│   ├── coder.py               # Génération code + edit_batch ACID
│   ├── reviewer.py            # Validation + critique + réflexion
│   ├── tester.py              # Sandbox + métriques + receipt
│   ├── observer.py            # Maintenance mémoire (dédoublonnage)
│   └── a2a_bus.py             # Bus local SQLite3
├── skill_library.py           # Extraction + stockage + injection
├── reflexion_engine.py        # Génération + RAG réflexions
├── karpathy_loop.py           # Boucle auto-expérimentation
├── receipt_store.py           # HMAC + audit trail
├── agent_orchestrator.py      # Boot agents + routing + REPL agentique
└── nl_orchestrator_v8_adapter.py  # Rétrocompat NLOrchestrator V7

memory/
└── a2a_bus.sqlite             # Créé automatiquement par A2ALocalBus
```

---

## Nouvelles collections MemoryEngine

| Collection | Layer | Contenu |
|------------|-------|---------|
| `lcca_skills` | L1 | Fonctions validées + signature + résumé |
| `lcca_receipts` | L3 | Audit trail A2A (tâches exécutées) |

> `lcca_failures` est enrichi avec un champ `reflection` (pas de nouvelle collection).

---

## Conventions V8

- `core/agents/` = module Python standard (pas de sous-package séparé)
- `A2AMessage.task_id` = format `a2a_{hash12}` (cohérent avec TX IDs)
- Tests : `tests/test_a2a_bus.py`, `tests/test_skill_library.py`, etc.
- Fichiers `.secret/` dans `.gitignore` (clé HMAC)
- Logging agents sur `sys.stderr` (cohérent avec MCP server)
