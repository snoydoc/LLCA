# INDEX — Sprints V7 (Sprints 12 à 16)
<!-- AI-READY | Index Sprints V7 | LCCA V7.0.0 | 2026-04-17 -->

## Vue d'ensemble V7

LCCA V7 expose le cœur transactionnel V5 (237 tests, inchangé) via un serveur **MCP JSON-RPC 2.0 stdio**, compatible Goose et Claude Desktop.

> **Principe fondateur** : La V7 n'est pas une réécriture. C'est un wrapper MCP + un moteur sandbox qui s'interfacent avec le cœur V5 éprouvé.

---

## Tableau de bord des sprints

| Sprint | Fichier | Thème | Nouveaux fichiers | Tests cible | Statut |
|--------|---------|-------|------------------|-------------|--------|
| **12** | `sprint-12-v7-fondations-mcp.md` | Fondations : config, safe_path, telemetry, OpType | 2 (`utils/`) + 2 (tests) | +24 → 261 | 🔲 À FAIRE |
| **13** | `sprint-13-v7-mcp-edit-memory.md` | McpEditBatch + MemoryEngine + Cache LLM v7 | 2 (`core/`) + 2 (tests) | +34 → 295 | 🔲 À FAIRE |
| **14** | `sprint-14-v7-sandbox-engine.md` | SandboxEngine (soft + Docker) | 1 (`core/`) + 1 (test) | +22 → 317 | 🔲 À FAIRE |
| **15** | `sprint-15-v7-mcp-server.md` | MCP Server JSON-RPC + CLI + Goose recipe | 3 (racine) + 2 (tests) | +30 → 347 | 🔲 À FAIRE |
| **16** | `sprint-16-v7-integration-finale.md` | E2E + Documentation + Validation | 3 (scripts/docs) + 1 (test) | +20 → 367 | 🔲 À FAIRE |

---

## Arborescence cible post-V7

```
D:\LLMCodeAgent
├── core\
│   ├── [... V5 : 19 fichiers inchangés ...]
│   ├── mcp_edit_batch.py       [Sprint 13 — Façade TX V5]
│   ├── memory_engine.py        [Sprint 13 — 4 collections MemPalace]
│   └── sandbox_engine.py       [Sprint 14 — soft + Docker]
│
├── utils\
│   ├── logger.py               [V5]
│   ├── safe_path.py            [Sprint 12 — anti path traversal]
│   └── telemetry.py            [Sprint 12 — JSONL rotatif]
│
├── scripts\
│   ├── migrate_cache_v6_to_v7.py  [Sprint 13 — migration one-shot]
│   └── validate_v7.py             [Sprint 16 — validation install]
│
├── .goose\
│   └── recipes\
│       └── lcca-dev.yaml          [Sprint 15 — Recipe Goose]
│
├── tests\
│   ├── [... V5 : 14 fichiers inchangés ...]
│   ├── test_safe_path.py          [Sprint 12 — 12 tests]
│   ├── test_telemetry.py          [Sprint 12 — 8 tests]
│   ├── test_mcp_edit_batch.py     [Sprint 13 — 18 tests]
│   ├── test_memory_engine.py      [Sprint 13 — 12 tests]
│   ├── test_sandbox_engine.py     [Sprint 14 — 22 tests]
│   ├── test_mcp_server.py         [Sprint 15 — 20 tests]
│   ├── test_mcp_security.py       [Sprint 15 — 10 tests]
│   └── test_mcp_integration.py    [Sprint 16 — 11 tests]
│
├── config.py                   [EXTENDED Sprint 12 — constantes V7]
├── mcp_server.py               [Sprint 15 — MCP JSON-RPC 2.0]
├── main_mcp.py                 [Sprint 15 — CLI + REPL MCP]
└── requirements.txt            [EXTENDED Sprint 14 — docker optionnel]
```

---

## Graphe de dépendances (ordre d'exécution)

```
Sprint 12 (Fondations)
    │
    ├── utils/safe_path.py
    ├── utils/telemetry.py
    ├── config.py (V7 additions)
    └── transaction_manager.py (OpType.CREATE_FILE + cleanup)
         │
Sprint 13 (McpEditBatch + MemoryEngine)
         │
         ├── core/mcp_edit_batch.py  ← dépend: safe_path, TX, SmartPatcher
         ├── core/memory_engine.py   ← dépend: MemPalaceAdapter V5
         └── core/llm_generator.py  ← patch: cache versionné modèle
              │
Sprint 14 (SandboxEngine)
              │
              └── core/sandbox_engine.py ← dépend: safe_path, config V7
                   │
Sprint 15 (MCP Server)
                   │
                   ├── mcp_server.py    ← dépend: TOUT (sprint 12-14 + V5)
                   └── main_mcp.py     ← entrée CLI
                        │
Sprint 16 (E2E + Docs)
                        │
                        └── Intégration + Validation
```

---

## Règles invariantes V7 (rappel)

| # | Règle | Application V7 |
|---|-------|----------------|
| 1 | SmartPatcher retourne `str` | `McpEditBatch` respecte : `apply_patch()` → `str`, `log_operation()` écrit |
| 2 | `ast` pour lire, `libcst` pour écrire | Conservé V5 |
| 3 | Max 3 fichiers par TX | `McpEditBatch.apply()` valide `MAX_FILES_PER_TX` |
| 4 | Snapshot MD5 + WAL avant chaque write | `TransactionManager.log_operation()` conservé |
| 5 | WAL JSONL append-only | Conservé V5 |
| 6 | LLMGenerator toujours Fallback | V7 : cache versionné par modèle + fallback inchangé |
| 7 | Injection de dépendances | `McpEditBatch`, `MemoryEngine`, `SandboxEngine` injectables |
| 8 | `sys.executable` toujours | `SandboxEngine._run_subprocess()` + commandes Docker |
| 9 | Imports module-level pour `patch()` | Maintenu pour tests |
| 10 | Encodage `utf-8-sig` | Tous fichiers écrits sur disque |
| **11** | `safe_path()` sur tout path MCP | Nouveau V7 — obligatoire |
| **12** | Logs MCP sur `stderr` uniquement | `stdout` = canal JSON-RPC pur |
| **13** | Docker SDK Python, jamais f-string shell | `SandboxEngine._run_docker()` |
| **14** | Container Docker `.remove(force=True)` dans `finally` | Pas de containers zombies |
| **15** | Cache LLM inclut le modèle dans la clé | `_cache_key(system, user)` → `{model}\n{system}\n{user}` |

---

## Checklist de validation finale V7

```powershell
# 1. Tous les tests passent (V5 + V7)
pytest tests/ -v --tb=short

# 2. Script de validation
python scripts/validate_v7.py

# 3. Test lifecycle MCP
python main_mcp.py --call "initialize" --args "{}"
python main_mcp.py --call "tools/list"
python main_mcp.py --status

# 4. Migration cache
python scripts/migrate_cache_v6_to_v7.py
```

**Critère de release V7.0** :
- ✅ ≥ 367 tests PASSED, 0 FAILED
- ✅ `validate_v7.py` 100% PASSED
- ✅ MCP Server répond au lifecycle initialize → tools/list
- ✅ 0 régression sur les 237 tests V5

<!-- Index Sprints V7 | LCCA V7.0.0 | 2026-04-17 -->
