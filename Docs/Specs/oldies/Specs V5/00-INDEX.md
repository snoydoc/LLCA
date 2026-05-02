# LCCA V5 Fusion — Index des Spécifications Techniques
<!-- AI-READY | Mis à jour le 2026-04-17 | Version 5.0.0 | Sprint 11 -->

## Vue d'ensemble

**LCCA** (Local Cognitive Coding Agency) est un agent de codage local transactionnel.
Il modifie du code Python via AST (libcst) avec garantie ACID (rollback atomique) et génération de code via LLM local (Ollama).

---

## Documents de spécification

| Fichier | Modules couverts | Sprint | Statut |
|---------|-----------------|--------|--------|
| [01-transaction-manager.md](01-transaction-manager.md) | `core/transaction_manager.py` | 02 | ✅ VALIDÉ |
| [02-ast-indexer.md](02-ast-indexer.md) | `core/ast_indexer.py` | 03 | ✅ VALIDÉ |
| [03-dependency-graph.md](03-dependency-graph.md) | `core/dependency_graph.py` | 03 | ✅ VALIDÉ |
| [04-smart-patcher.md](04-smart-patcher.md) | `core/smart_patcher.py` | 03 | ✅ VALIDÉ |
| [05-dsl-parser.md](05-dsl-parser.md) | `core/dsl_parser.py` | 04 | ✅ VALIDÉ |
| [06-file-selector.md](06-file-selector.md) | `core/file_selector.py` | 04 | ✅ VALIDÉ |
| [07-planner.md](07-planner.md) | `core/planner.py` | 04 | ✅ VALIDÉ |
| [08-orchestrator.md](08-orchestrator.md) | `core/orchestrator.py` | 04+09 | ✅ VALIDÉ |
| [09-mempalace.md](09-mempalace.md) | `core/mempalace_client.py` + `core/context_assembler.py` + `core/mempalace_adapter.py` | 05+08 | ✅ VALIDÉ |
| [10-recovery-executor-error.md](10-recovery-executor-error.md) | `core/recovery_service.py` + `core/executor.py` + `core/error_analyzer.py` | 06 | ✅ VALIDÉ |
| [11-llm-generator.md](11-llm-generator.md) | `core/llm_generator.py` | 09 | ✅ VALIDÉ |
| [12-nl-interface.md](12-nl-interface.md) | `core/nl_parser.py` + `core/nl_orchestrator.py` | 10 | ✅ VALIDÉ |
| [13-code-evaluator.md](13-code-evaluator.md) | `core/code_evaluator.py` | 11 | ✅ VALIDÉ |
| [14-medibot-orchestrator.md](14-medibot-orchestrator.md) | `core/orchestrator_medi.py` | 08 | ✅ VALIDÉ |
| [15-clis.md](15-clis.md) | `main.py` + `main_medi.py` + `main_nl.py` | 07+08+10 | ✅ VALIDÉ |
| [16-config-utils.md](16-config-utils.md) | `config.py` + `utils/logger.py` | 01–11 | ✅ VALIDÉ |
| [17-architecture-globale.md](17-architecture-globale.md) | Système complet — synthèse | Tous | ✅ VALIDÉ |

---

## Tests — État global (Sprint 11)

```
pytest tests/ -v
→ ≥ 237 PASSED, 0 FAILED, 0 SKIPPED  (Sprint 11 — 2026-04-17)
```

| Suite de tests | Fichier | Nb tests |
|---------------|---------|----------|
| Smoke | `test_smoke.py` | 11 |
| TransactionManager | `test_transaction_manager.py` | 9 |
| ASTIndexer | `test_ast_indexer.py` | 6 |
| SmartPatcher | `test_smart_patcher.py` | 6 |
| Orchestrateur | `test_orchestrator.py` | 13 |
| MemPalace | `test_mempalace_client.py` | 20 |
| Recovery | `test_recovery_service.py` | 12 |
| Executor | `test_executor.py` | 22 |
| Intégration | `test_integration.py` | 9 |
| MediBotAdapter | `test_medibot_adapter.py` | 7 |
| LLMGenerator | `test_llm_generator.py` | 26 |
| NLParser | `test_nl_parser.py` | ~25 |
| NLOrchestrator | `test_nl_orchestrator.py` | 25 |
| CodeEvaluator | `test_code_evaluator.py` | 46 |

---

## Stack technique

- **Python** : 3.11+
- **AST Modification** : `libcst` ≥ 1.1.0
- **AST Indexation** : `ast` stdlib (lecture seule)
- **Base vectorielle** : `chromadb` ≥ 0.4.0 (MemPalace)
- **LLM** : Ollama local (`qwen2.5-coder:14b`) via `urllib.request`
- **Tests** : `pytest` ≥ 7.0
- **OS** : Windows 11 (D:\, UTF-8-BOM)

---

## 10 Règles architecturales invariantes

1. **SmartPatcher retourne `str`** — jamais d'écriture disque directe
2. **`ast` pour lire, `libcst` pour écrire** — libcst préserve le formatage
3. **Max 3 fichiers par TX** (`config.MAX_FILES_PER_TX = 3`)
4. **Snapshot MD5 + WAL avant chaque write** — rollback byte-perfect
5. **WAL JSONL append-only** — crash-safe
6. **LLMGenerator a toujours un FallbackGenerator** — jamais de crash si Ollama HS
7. **Injection de dépendances dans LCCAV5Fusion** — tous les composants mockables
8. **`sys.executable` toujours** — jamais `"python"` hardcodé en subprocess
9. **Imports module-level pour les classes patchées** — requis pour `unittest.mock.patch()`
10. **Encodage `utf-8-sig`** — BOM obligatoire sur Windows
