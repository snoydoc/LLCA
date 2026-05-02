# 📋 LCCA V5 Fusion — Planning des Sprints

> **Projet** : Local Cognitive Coding Agency V5 Fusion  
> **Créé le** : 2026-04-16  
> **Mis à jour** : 2026-04-16  
> **Stack** : Python 3.11+, libcst, ChromaDB, WAL (JSONL)  
> **Workspace** : `D:\LLMCodeAgent`

---

## 🗺️ Vue d'ensemble

| Sprint | Titre | Durée | Statut | Priorité |
|--------|-------|--------|--------|----------|
| [Sprint 01](sprint-01-setup-fondations.md) | Setup & Fondations | 3.5j | 🟡 EN COURS | 🔴 Critique |
| [Sprint 02](sprint-02-transaction-manager.md) | Transaction Manager ACID | 5.5j | ⚪ À FAIRE | 🔴 Critique |
| [Sprint 03](sprint-03-ast-indexer.md) | AST Indexer & Smart Patcher | 6j | ⚪ À FAIRE | 🔴 Critique |
| [Sprint 04](sprint-04-planner-orchestrator.md) | Planner, DSL & Orchestrateur | 5j | ⚪ À FAIRE | 🟠 Haute |
| [Sprint 05](sprint-05-mempalace-integration.md) | MemPalace Integration | 4.5j | ⚪ À FAIRE | 🟠 Haute |
| [Sprint 06](sprint-06-recovery-validation.md) | Recovery Service & Validation | 4j | ⚪ À FAIRE | 🟠 Haute |
| [Sprint 07](sprint-07-cli-tests.md) | CLI, Tests & Polish | 3.5j | ⚪ À FAIRE | 🟡 Normale |
| [Sprint 08](sprint-08-medibot-adapter.md) | MediBot Adapter (Bonus) | 3j | ⚪ À FAIRE | 🟢 Basse |

**Total estimé : ~35 jours** (sans Sprint 08 bonus : ~32 jours)

---

## 🏗️ Architecture cible (Fichier → Sprint)

```
D:\LLMCodeAgent
├── core\
│   ├── __init__.py                ← Sprint 01
│   ├── mempalace_client.py        ← Sprint 05
│   ├── mempalace_adapter.py       ← Sprint 08 (MediBot bonus)
│   ├── transaction_manager.py     ← Sprint 02
│   ├── recovery_service.py        ← Sprint 06
│   ├── dsl_parser.py              ← Sprint 04
│   ├── ast_indexer.py             ← Sprint 03
│   ├── dependency_graph.py        ← Sprint 03
│   ├── smart_patcher.py           ← Sprint 03
│   ├── context_assembler.py       ← Sprint 05
│   ├── planner.py                 ← Sprint 04
│   ├── file_selector.py           ← Sprint 04
│   ├── executor.py                ← Sprint 06
│   ├── error_analyzer.py          ← Sprint 06
│   ├── orchestrator.py            ← Sprint 04
│   └── orchestrator_medi.py       ← Sprint 08 (MediBot bonus)
├── utils\
│   └── logger.py                  ← Sprint 01
├── config.py                      ← Sprint 01
├── main.py                        ← Sprint 07
├── main_medi.py                   ← Sprint 08 (MediBot bonus)
├── workspace\                     ← Code cible (rempli à l'usage)
├── transactions\                  ← Auto-généré (WAL + backups)
├── tests\
│   ├── test_smoke.py              ← Sprint 01
│   ├── test_transaction_manager.py← Sprint 02
│   ├── test_ast_indexer.py        ← Sprint 03
│   ├── test_smart_patcher.py      ← Sprint 03
│   ├── test_mempalace_client.py   ← Sprint 05
│   ├── test_recovery_service.py   ← Sprint 06
│   ├── test_executor.py           ← Sprint 06
│   ├── test_integration.py        ← Sprint 07
│   └── test_medibot_adapter.py    ← Sprint 08 (bonus)
└── Docs\
    ├── Specs\
    │   └── LLMCoderPlateformV5.md
    └── Sprints\
        ├── README.md (ce fichier)
        ├── sprint-01-setup-fondations.md
        ├── sprint-02-transaction-manager.md
        ├── sprint-03-ast-indexer.md
        ├── sprint-04-planner-orchestrator.md
        ├── sprint-05-mempalace-integration.md
        ├── sprint-06-recovery-validation.md
        ├── sprint-07-cli-tests.md
        └── sprint-08-medibot-adapter.md
```

---

## 📌 Règles transversales (tous sprints)

- **Jamais** écrire directement dans un fichier sans snapshot WAL
- **Jamais** utiliser regex pour modifier du code Python → libcst obligatoire
- **Toujours** `pathlib.Path`, jamais strings avec `\`
- **Toujours** `encoding='utf-8-sig'` pour les writes sur Windows
- **Toujours** typer les fonctions avec retours complexes
- Nommage: `PascalCase` classes, `snake_case` fonctions/fichiers, `tx_{hash12}` IDs
- Max **3 fichiers** modifiables par transaction (contrainte hard)
- **ChromaDB ≥ 0.4** : utiliser `PersistentClient(path=...)` — pas `Settings(chroma_db_impl=...)`

---

## 🔗 Documents de référence

- `D:\LLMCodeAgent\.claude-skills\001-skill-coding-agent-master.md` — Règles LCCA
- `D:\LLMCodeAgent\.claude-skills\002-tech-context.md` — Stack technique
- `D:\LLMCodeAgent\.claude-skills\003-project-context.md` — Structure projet
- `D:\LLMCodeAgent\Docs\Specs\LLMCoderPlateformV5.md` — Spécification complète V5

---

## 🚀 Ordre d'exécution recommandé

```
Sprint 01 → Sprint 02 → Sprint 03 ─┐
                                    ├→ Sprint 04 → Sprint 05 → Sprint 06 → Sprint 07
                                   (peuvent être menés en parallèle si 2 devs)
                                                                            ↓
                                                                       Sprint 08 (bonus)
```
