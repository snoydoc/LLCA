# Spec 17 — Architecture Globale LCCA V5 Fusion
> **Document de synthèse** | **Sprints** : 01–11 | **Statut** : ✅ COMPLET

---

## 1. Vision

**LCCA V5 Fusion** (Local Cognitive Coding Agency) est un agent de codage local transactionnel. Sa philosophie :

> Ne jamais modifier du code en texte brut. Chaque modification est un **patch AST atomique** avec snapshot, rollback possible, et génération de code via LLM local.

---

## 2. Stack technique

| Composant | Technologie | Version |
|-----------|-------------|---------|
| Python | CPython | 3.11+ |
| AST modification | `libcst` | ≥ 1.1.0 |
| AST lecture | `ast` stdlib | — |
| Base vectorielle | `chromadb` | ≥ 0.4.0 |
| LLM local | Ollama + qwen2.5-coder:14b | Sprint 10 |
| Tests | `pytest` | ≥ 7.0 |
| Formatage | `black` | ≥ 23.0 |
| OS | Windows 11 | D:\ |
| HTTP LLM | `urllib.request` stdlib | (pas de requests) |

---

## 3. Architecture en couches

```
┌─────────────────────────────────────────────────────────────────┐
│                    INTERFACES UTILISATEUR (Layer 4)              │
│  main.py (CLI DSL)  │  main_medi.py (REPL MediBot)  │  main_nl  │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                  ORCHESTRATION (Layer 3)                         │
│  LCCAV5Fusion  │  MediBotOrchestrator  │  NLOrchestrator        │
└─────────────────────────────────────────────────────────────────┘
          │                  │                    │
┌─────────┴──────────────────┴────────────────────┴───────────────┐
│                  INTELLIGENCE (Layer 2)                          │
│  NLParser  │  LLMGenerator  │  CodeEvaluator  │  ErrorAnalyzer  │
│  DSLParser │  ContextAssembler  │  MemPalaceClient               │
└─────────────────────────────────────────────────────────────────┘
          │
┌─────────┴───────────────────────────────────────────────────────┐
│                  MOTEUR TRANSACTIONNEL (Layer 1)                 │
│  TransactionManager  │  ASTIndexer  │  SmartPatcher              │
│  DependencyGraph  │  FileSelector  │  MultiFilePlanner           │
│  RecoveryService  │  Executor                                    │
└─────────────────────────────────────────────────────────────────┘
          │
┌─────────┴───────────────────────────────────────────────────────┐
│                  INFRASTRUCTURE (Layer 0)                        │
│  config.py  │  utils/logger.py  │  WAL JSONL  │  .llm_cache     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Pipeline d'exécution complet (DSL)

```
Commande utilisateur: "DashV1 - Auth - Ajoute validate_email()"
            │
            ▼
    DSLParser.parse()
    → Intent { project="DashV1", target="Auth",
               action="ajoute", details="validate_email()", confidence=1.0 }
            │
            ▼
    FileSelector.select(intent)
    → ["auth.py"]   (stratégie 1: symbole, ou 2: nom fichier)
            │
            ▼
    MultiFilePlanner.create_plan()
    → [PlannedOperation { file="auth.py", action="modify",
                          patch_type="add_function", symbol="validate_email" }]
    + validate_plan_consistency() → (True, [])
            │
            ▼
    TransactionManager.begin()
    → tx_id = "tx_a3f2b8d9e1c4"
    → WAL: {"type":"BEGIN", "tx_id":"...", "dsl_input":"...", ...}
            │
            ▼
    LLMGenerator.generate(op, intent, context=existing_code)
    → GenerationResult { code="def validate_email(...): ...",
                         from_cache=False, from_fallback=False }
            │
            ▼
    SmartPatcher.apply_patch("auth.py", "add_function", code=..., name=...)
    → new_source: str   (retourne str, N'ÉCRIT PAS sur disque)
            │
            ▼
    TransactionManager.log_operation(path, PATCH_FILE, lambda: patcher...)
    → snapshot MD5 avant + exécution _do_patch + write_text
    → WAL: {"type":"OP_START"} puis {"type":"OP_SUCCESS"}
            │
            ▼
    _validate_changes()
    → Executor.check_syntax("auth.py")  (compile() uniquement)
            │
        ┌───┴────┐
        │ OK     │ ERREUR
        ▼        ▼
    commit()   rollback()
    WAL COMMIT WAL ROLLBACK + restore .bak
        │
        ▼
    index_repository() + dep_graph.build()  (re-indexation)
    _update_sprint_log()
        │
        ▼
    return True
```

---

## 5. Pipeline langage naturel (NL)

```
"Ajoute une fonction validate_phone dans core/utils.py"
            │
            ▼
    NLParser.parse(command, project_files)
    → Ollama /api/chat (qwen2.5-coder:14b)
    → NLIntent { action="add_function", target_file="core/utils.py",
                 symbol="validate_phone", confidence=0.95 }
            │
            ▼
    NLOrchestrator._validate_intent()
    → confidence >= 0.4 ✅
            │
            ▼
    NLIntent.to_dsl()
    → "LCCA - utils - validate_phone - Ajoute validate_phone"
            │
            ▼
    LCCAV5Fusion.execute(dsl_command)
    → [pipeline DSL complet ci-dessus]
            │
            ▼
    NLResult { success=True, dsl_command="...", duration_s=2.4 }
```

---

## 6. Carte des modules

| Module | Classes clés | Rôle |
|--------|-------------|------|
| `transaction_manager.py` | `TransactionManager` | WAL, snapshots MD5, ACID |
| `ast_indexer.py` | `ASTIndexer`, `Symbol`, `FileIndex` | Indexation lecture (ast stdlib) |
| `dependency_graph.py` | `DependencyGraph` | Graphe dépendances inter-fichiers, BFS |
| `smart_patcher.py` | `SmartPatcher` | Patches libcst (AddFunction, Modify, AddImport) |
| `dsl_parser.py` | `DSLParser`, `Intent` | Parse commandes structurées DSL |
| `file_selector.py` | `FileSelector` | Sélection fichiers cibles (3 stratégies) |
| `planner.py` | `MultiFilePlanner`, `PlannedOperation` | Ordonnancement opérations |
| `orchestrator.py` | `LCCAV5Fusion`, `Orchestrator` | Pipeline complet + TX |
| `mempalace_client.py` | `MemPalaceClient`, `MemoryEntry` | Mémoire vectorielle ChromaDB |
| `context_assembler.py` | `ContextAssembler` | Budget tokens pour prompt LLM |
| `mempalace_adapter.py` | `ExistingMemPalaceAdapter` | Connexion palace MediBot |
| `recovery_service.py` | `RecoveryService` | Boot-check + repair WAL orphelins |
| `executor.py` | `Executor`, `ValidationResult` | Syntaxe + pytest |
| `error_analyzer.py` | `ErrorAnalyzer`, `ErrorReport` | Suggestions LLM < 200 tokens |
| `llm_generator.py` | `LLMGenerator`, `OllamaClient`, `PromptBuilder` | Génération code Ollama |
| `nl_parser.py` | `NLParser`, `NLIntent` | NL → Intent via Qwen |
| `nl_orchestrator.py` | `NLOrchestrator`, `NLResult`, `NLSession` | NL → LCCAV5Fusion |
| `code_evaluator.py` | `CodeEvaluator`, `EvaluationResult` | Score qualité 0-100 |
| `orchestrator_medi.py` | `MediBotOrchestrator` | Orchestrateur spécialisé MediBot |

---

## 7. Règles architecturales invariantes

| # | Règle | Justification |
|---|-------|---------------|
| 1 | **SmartPatcher retourne `str`**, jamais n'écrit | Séparation responsabilités : seul l'orchestrateur écrit |
| 2 | **`ast` pour lire, `libcst` pour écrire** | `libcst` préserve le formatage ; `ast` est plus rapide |
| 3 | **Max 3 fichiers par TX** (`MAX_FILES_PER_TX`) | Limite l'explosion de l'espace d'états à rollback |
| 4 | **Snapshot MD5 avant chaque write** | Rollback byte-perfect possible |
| 5 | **WAL JSONL append-only** | Crash-safe : chaque ligne = état cohérent |
| 6 | **LLMGenerator a toujours un fallback** | Jamais de crash si Ollama est HS |
| 7 | **Injection de dépendances dans LCCAV5Fusion** | Testabilité : chaque composant mockable |
| 8 | **Jamais `subprocess.run("python")` → `sys.executable`** | Pointe sur le venv actif |
| 9 | **Imports module-level pour les classes patchées** | `patch("module.Classe")` requiert l'attribut module-level |
| 10 | **Encodage `utf-8-sig`** sur Windows | Compatibilité BOM pour fichiers avec accents |

---

## 8. État des tests (Sprint 11)

| Suite | Fichier | Tests |
|-------|---------|-------|
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
| **TOTAL** | — | **≥ 237 PASSED, 0 SKIPPED** |

---

## 9. Structure du dossier projet

```
D:\LLMCodeAgent\
├── .claude-skills\          SKILLS session LCCA (lire en premier)
├── core\                    Moteur transactionnel (19 modules)
├── utils\                   Logger structuré
├── tests\                   Suite pytest complète
├── workspace\               Zone de code cible (modifiable)
├── transactions\            WAL + snapshots + cache LLM
├── logs\                    Logs rotatifs
├── Docs\
│   ├── Specs\               Ces spécifications (00-17)
│   └── Sprints\             Planning + journal de sessions
├── config.py                Tous les paths + constantes
├── main.py                  CLI généraliste (6 sous-commandes)
├── main_medi.py             CLI MediBot + REPL
├── main_nl.py               CLI NL + REPL
└── requirements.txt         Dépendances Python
```

---

## 10. Roadmap non implémentée (V2+)

- [ ] Sandbox Docker pour exécution du code généré
- [ ] GUI Tkinter
- [ ] Support multi-langage (JS, TS)
- [ ] RAG sur le codebase (ChromaDB + embeddings)
- [ ] Streaming Ollama (réponses progressives)
- [ ] Évaluation qualité intégrée au pipeline (CodeEvaluator bloquant si score < seuil)
- [ ] Upgrade modèle : `qwen3:30b-a3b` (MoE, 3B actifs, ~20 GB RAM)
