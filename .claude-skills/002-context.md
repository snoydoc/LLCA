# LCCA — TECH + PROJECT CONTEXT (mis à jour 2026-04-25)

## ENVIRONNEMENT
- Python 3.11+ | venv `D:\LLMCodeAgent\venv\`
- OS Windows | paths absolus `D:\LLMCodeAgent`
- 100% offline/local (Ollama) — aucune API cloud
- RAM : 24 GB (Lenovo P50, upgrade 32 GB prévu) | GPU : Quadro M2000M 4 GB VRAM

## STACK DÉPENDANCES
- `libcst>=1.1.0` — AST modif (OBLIGATOIRE)
- `chromadb>=0.4.0` — Vector DB (optionnel, skip Python 3.14+)
- `pytest>=7.0` | `pyyaml>=6.0` | `black>=23.0`

## MODÈLE ACTIF
**`qwen2.5-coder:3b`** (~2.0 GB VRAM, ~10 tok/s full-GPU)
- 7b ecarté : débordement RAM → GPU 23-44% seulement → 3.70 tok/s
- `hardware_profile.py` tier `low` → sélectionne automatiquement le 3b
- deepseek-coder:6.7b : 4.18 tok/s (mieux que 7b, GPU 37-39%) — candidat alternatif

| Modèle | VRAM | tok/s | GPU% | Statut |
|---|---|---|---|---|
| qwen2.5-coder:3b    | ~2.0 GB full  | 9.70  | 84-87% | ✅ retenu LCCA |
| qwen2.5-coder:7b    | ~4.7 GB hybr. | 3.70  | 23-44% | écarté |
| deepseek-coder:6.7b | ~3.8 GB hybr. | 4.18  | 37-39% | candidat alt. |
| qwen3:8b            | ~5.5 GB full  | 3.23  | 28-30% | écarté (lent vs 3b) |
| qwen3:14b           | ~9 GB RAM CPU | 1.79  | 15%    | ❌ écarté (RAM insuffisante, disque supprimé) |
| deepseek-r1:14b     | ~9 GB RAM CPU | 1.66  | 15%    | ❌ écarté (RAM insuffisante, disque supprimé) |
| qwen3:30b-a3b       | ~18 GB hybr.  | 5.31  | 24-36% | ⚠️ MoE (3B actifs/tok) — ref MoE, disque supprimé |
| qwen3:4b                    | ~2.7 GB hybr. | 6.38  | CPU    | ✅ testé 25/04 — bon candidat |
| gemma4:e4b                  | ~3.2 GB full  | 5.44  | CPU    | ⚠️ décevant vs e2b |
| gemma4:e2b                  | ~1.5 GB full  | 9.77  | CPU    | 🌟 challenger sérieux du 3b |
| phi4-mini                   | ~3.0 GB full  | 7.23  | CPU    | ⚠️ variance élevée (+27%) à confirmer |
| phi4-mini-reasoning         | ~3.0 GB full  | 5.78  | CPU    | ✅ stable, reasoning overhead |
| deepseek-r1:8b              | ~5.5 GB hybr. | 3.50  | CPU    | ❌ hybride lent (< 3b actuel) |
| qwen3-coder:30b-a3b-q4_K_M | ~18 GB MoE    | 7.05  | CPU    | 🌟 coding overnight candidat |
| qwen3:30b-a3b               | ~18 GB MoE    | 8.01  | CPU    | 🌟 surprise — MoE 3B actifs/tok |

Baseline 21/04 : 3b=10.87, 7b=4.01.
Benchmark 2026-04-24 Quick (2 prompts, 1 run) : qwen3:8b=3.23 tok/s | qwen3:14b=timeout.
Benchmark 2026-04-25 00h10 GPU (2 prompts, 1 run) : qwen3:14b=1.79 tok/s | VRAM 2935 MB | GPU 15% → hybride swap lent.
Benchmark 2026-04-25 00h23 GPU (2 prompts, 1 run) : deepseek-r1:14b=1.66 tok/s | VRAM 3005 MB | GPU 15% → même pattern.
Benchmark 2026-04-25 01h31 GPU (2 prompts, 1 run) : qwen3:30b-a3b=5.31 tok/s | MoE 3B actifs/tok | GPU 24-36% → meilleur gros modèle testé.
Conclusion session overnight : 14B chargés partiellement en VRAM (2.9-3 GB sur 4 GB), reste en RAM → swap trop lent.

**Benchmark 2026-04-25 journée — campagne complète (2 prompts × 1-2 runs, 12 modèles)**
> ⚠️ gpu_avg=0.0 pour tous les modèles : supervision pynvml non fonctionnelle dans le script. Débits calculés côté Ollama, valides.

| Modèle | Run 1 tok/s | Run 2 tok/s | Moy. tok/s | RAM avg MB | Verdict |
|---|---|---|---|---|---|
| gemma4:e2b | 10.28 | 9.25 | **9.77** | ~15 350 | 🌟 Meilleur Tier 1 |
| phi4-mini | 6.38 | 8.07 | **7.23** | ~13 970 | ⚠️ Variance +27% |
| qwen3:30b-a3b | 8.29 | 7.72 | **8.01** | ~23 250 | 🌟 Surprise MoE |
| qwen3-coder:30b-a3b-q4_K_M | 6.68* | 7.05 | **7.05** | ~22 660 | 🌟 Coding overnight |
| gemma3:4b | 6.76 | 6.14 | **6.45** | ~16 460 | ✅ Stable |
| qwen3:4b | 6.14 | 6.62 | **6.38** | ~17 700 | ✅ Candidat |
| phi4-mini-reasoning | 5.67 | 5.88 | **5.78** | ~14 250 | ✅ Très stable |
| gemma4:e4b | 5.21 | 5.66 | **5.44** | ~20 360 | ⚠️ RAM élevée |
| qwen3:8b | 3.79 | 3.66 | **3.73** | ~16 120 | ❌ Hybride lent |
| deepseek-r1:8b | 3.68 | 3.31 | **3.50** | ~14 430 | ❌ Hybride lent |
| deepseek-r1:14b | 1.99 | — | **1.99** | ~16 590 | ❌ CPU pur |
| qwen3:14b | 1.97 | — | **1.97** | ~17 030 | ❌ CPU pur |
*Run 1 qwen3-coder partiel (HTTP 500 sur code_simple, ttft=40s sur debug = chargement à froid).

**qwen2.5-coder:3b reste le modèle de prod LCCA** (10.87 tok/s baseline — non re-testé le 25/04).
Prochaine étape : re-tester gemma4:e2b et phi4-mini dans les mêmes conditions que le baseline 3b pour comparaison équitable.

### Pulls benchmarkés le 25/04/2026 ✅ TERMINÉ
Tous les modèles listés ci-dessus ont été testés. Campagne complète — voir tableau consolidé.
Rapport détaillé : `D:\LLMCodeAgent\CPUVsGPU\results\benchmark_ollama_lcca_20260425.md` (soumis à validation IA externe).

**Questions ouvertes post-benchmark :**
- Monitoring GPU non fonctionnel (pynvml) → investiguer avant prochaine campagne
- phi4-mini : variance +27% entre sessions → re-tester 3× pour confirmer
- gemma4:e2b : `response: ""` dans JSON (bug capture ou troncature script ?)
- qwen3:30b-a3b : RAM ~23-24 GB (~96%) → risque si OS + LCCA en parallèle

### Mapping rôles cible (mis à jour 25/04/2026 — chiffres réels)
- **Production LCCA (journée)** : `qwen2.5-coder:3b` (10.87 tok/s baseline) — challenger immédiat : `gemma4:e2b` (9.77 tok/s, ~15 GB RAM) → re-tester à conditions égales
- **Candidat prod confirmé** : `gemma4:e2b` si re-test ≥ 9 tok/s | `phi4-mini` si variance résolue (7.23 tok/s moy.)
- **DEBUG/reasoning** : `phi4-mini-reasoning` (5.78 tok/s, très stable) — `deepseek-r1:8b` écarté (3.50 tok/s)
- **Tâches overnight complexes** : `qwen3:30b-a3b` (8.01 tok/s, MoE) — surveiller RAM ≤ 20 GB
- **Coding overnight** : `qwen3-coder:30b-a3b-q4_K_M` (7.05 tok/s, spécialisé coding)
- **Écarté définitivement** : `qwen3:8b`, `deepseek-r1:8b`, `qwen3:14b`, `deepseek-r1:14b`, `gemma4:e4b`

## POLITIQUE TIMEOUT (INVARIANT)
- `OLLAMA_TIMEOUT = None` | `SPEC_TIMEOUT = None` → attente infinie
- `AGENT_PIPELINE_TIMEOUT = 3600` (1h)
- `is_available()` et `list_models()` : timeout=3 (ping rapide uniquement)
- **NE JAMAIS** mettre une valeur entière dans OLLAMA_TIMEOUT ou SPEC_TIMEOUT

## PALACE LOCAL LLCA (MIG-04/MIG-05)
- Racine : `D:\LLMCodeAgent\mempalace\palace\` (créé MIG-04)
- Config : `D:\LLMCodeAgent\mempalace\config.json`
- `PALACE_DIR` défini dans `config.py` — créé automatiquement au démarrage
- `MemPalaceClient()` sans args pointe sur PALACE_DIR (plus sur `~/.mempalace/palace`)
- Tests mempalace : `tmp_palace` fixture passe `palace_path` explicitement → non impactés
- 0 dépendance vers D:\MediBot ou le MCP palace partagé
- Peuplement : `python mempalace/migration/migrate_palace.py` (skills LLCA + sp03 historique)
- MCP audit MIG-05 : 3116 drawers MCP = 99.97% MediBot, 1 drawer LLCA (sp03 diary) exporté

---

## ARBORESCENCE CORE (D:\LLMCodeAgent)

### core/agents/ — 24 fichiers (état post-REFACTO-09 + whitelist refacto)
```
a2a_bus.py              V8-01 — A2ALocalBus, A2AMessage, TaskContract (SQLite3 :memory:)
agent_card.py           V8-02/FIX — AgentCard, RecoveryPolicy, AgentRegistry (+llm_review capability)
base_agent.py           V8-03 — BaseAgent ABC, AgentResult, _call_mcp (allowlist)
architect_agent.py      REFACTO-06 — orchestration légère (6.16 KB)
architect_decomposer.py REFACTO-06 — _detect_domain, _decompose_intent, ArchitectDecomposer
coder_agent.py          REFACTO-07 — orchestration légère (8.32 KB)
coder_builder.py        REFACTO-07 — CODER_SYSTEM, build_coder_prompt, format_skills_context, build_patch
reviewer_agent.py       REFACTO-09 — orchestration légère (~7.1 KB)
reviewer_validator.py   REFACTO-09 — _check_syntax, _build_reflection (module-level)
reviewer_analyzer.py    REFACTO-09 — ReviewerLlmAnalyzer, prompts LLM
tester_agent.py         REFACTO-05 — orchestration légère (10.28 KB)
tester_runner.py        REFACTO-05 — _hash, _run_sandbox_safe, TesterReceiptBuilder
agent_orchestrator.py   V9-07 — KarpathyLoop + OrchestratorResult (~8.5 KB)
orchestrator_loop.py    REFACTO-04 — KarpathyLoop + LoopResult + _detect_stagnation
observer_agent.py       REFACTO-08 — dédup skills, archivage (~10.37 KB)
observer_analyzer.py    REFACTO-03 — ObserverAnalyzer : find_low_quality, find_duplicates
observer_reporter.py    REFACTO-08 — make_report_id, should_archive, ObserverReporter
educator_agent.py       ED-04/REFACTO-08 — EducatorAgent V9.1 (16.64 KB)
educator_github.py      REFACTO-02 — EducatorGitHub : couche réseau GitHub
educator_filter.py      REFACTO-02 — EducatorFilter : 7 règles LCCA
educator_ingester.py    REFACTO-08 — EducatorIngester : process_repo, ingest, _extract_symbols
educator_curator.py     REFACTO-08 — EducatorCurator : run_curation, run_diff, sandbox_check
educator_whitelist.py   — Loader JSON whitelist : load_whitelist(), save_whitelist(), load_skip_set()
educator_whitelist.json — SOURCE DE VÉRITÉ whitelist 24 repos (JSON, modifiable sans toucher au code)
```

### core/ — modules principaux
```
receipt_store.py           V8-01 — HMAC sign/verify/store/load/rotate (3.2 KB)
skill_library.py           V8-05/ED-03 — SkillEntry (+source_type, +commit_hash), SkillLibrary (10.8 KB)
hardware_profile.py        V9-00 — detect_ram_gb(), get_profile(), apply_hardware_profile() (4.1 KB)
model_router.py            ROUTER-01 — ModelRouter + ModelDecision : routing LLM local↔online (~7 KB)
                                        Interface : get_model(task_type, complexity_score, api_key) → ModelDecision
                                        Config : online_models.json (racine projet) | routing.enabled=False par défaut
                                        Invariants : 0 exception levée, fallback silencieux si JSON absent/invalide
                                        Tests : tests/test_model_router.py (13 classes, ~55 tests) ✅ ROUTER-01
transaction_manager.py     Sprint 02/07/V7/REFACTO-01/REFACTO-20 — façade ACID : begin/log_operation/commit/rollback + _snapshot + _backup (~9 KB)
transaction_wal.py         REFACTO-20 — TransactionWalMixin : _read_wal_for_tx, _get_tx_completion_timestamp, cleanup_old_snapshots, archive_old_wal_entries (~5 KB)
transaction_types.py       — Dataclasses TX (OpType, etc.) (2.2 KB)
transaction_legacy.py      — Alias legacy rétrocompat TX (4.2 KB)
ast_indexer.py             — ASTIndexer, index_repository(), symbols_table (10.6 KB)
smart_patcher.py           — SmartPatcher.apply_patch() → str uniquement (7.8 KB)
smart_patcher_transformers.py — Transformers libcst (9.4 KB)
llm_generator.py           Sprint 18/UI-07/V9-05 — generate()+generate_text()+generate_stream()+telemetry tok/s (9.09 KB)
mcp_tool_handlers.py       — Façade 13 tools MCP, dispatch vers handlers_core/spec/llm/extras (2.36 KB)
mcp_server.py              — McpServer JSON-RPC 2.0 stdio (13.5 KB) ⚠️ WARN >10KB
mcp_tools_schema.py        — Schémas 13 tools MCP (9.2 KB)
mcp_edit_batch.py          Sprint 12 — McpEditBatch : façade TX atomique pour outil edit_batch (12.9 KB) ⚠️ WARN >10KB
mcp_types.py               — Dataclasses MCP (0.6 KB)
nl_parser.py               — NLParser : parse intentions NL (8.5 KB)
nl_orchestrator.py         — NLOrchestrator : pipeline NL→TX (9.2 KB)
nl_intent.py               — Intent dataclass (3.8 KB)
nl_intent_builder.py       — NLIntentBuilder (7.6 KB)
nl_types.py                — Types NL partagés (3.3 KB)
nl_repl.py                 — REPL interactif NL (5.5 KB)
spec_entry.py              V7.2/V9-09 — SpecEntry + SpecDiff + diff() (11.2 KB)
spec_validator.py          — SpecValidatorService (6.5 KB)
spec_validator_rules.py    — RULE_REGISTRY R01-R15 (13.8 KB) ⚠️ WARN >10KB
spec_generator.py          REFACTO-16/V9-09 — Façade SpecGeneratorService + réexports rétrocompat (~8.8 KB)
spec_complexity.py         Sprint 15/18 — SpecComplexityEstimator, _infer_domain(), score 0-100 (4.3 KB)
spec_promoter.py           Sprint 15/16/19 — SpecPromoter : promotion Layer 2→1→0 (3.4 KB)
cognitive_patterns.py      REFACTO-12 — CognitivePattern ABC + 4 classes (prompts extraits) (8.4 KB)
cognitive_prompts.py       REFACTO-12 — 4 prompts système LLM source de vérité (8.0 KB)
error_analyzer.py          REFACTO-13 — Orchestration légère (5.8 KB) — importe error_classifier + error_recovery_hints
error_classifier.py        REFACTO-13 — Classification SyntaxError/ImportError/AttributeError/NameError (9.3 KB)
error_recovery_hints.py    REFACTO-13 — requirements.txt + build_fix_prompt + try_auto_fix (5.6 KB)
memory_engine.py           REFACTO-15/V7 — Façade orchestration légère (~6.6 KB) — délègue store+search + aliases rétrocompat
memory_engine_store.py    REFACTO-15 — MemoryStoreService : check_threshold, enrich_payload, store_via_adapter, StoreResult (7.7 KB)
memory_engine_search.py   REFACTO-15 — MemorySearchService : chromadb_query, normalize_entry, MemoryEntry (5.3 KB)
spec_generator.py          REFACTO-16/V9-09 — Façade SpecGeneratorService + réexports rétrocompat (~8.8 KB)
spec_generator_helpers.py  REFACTO-16 — _extract_title, _extract_abstract, _compute_complexity (2.4 KB)
spec_generator_context.py  REFACTO-16 — _DOMAIN_FILES, _KEYWORD_FILES, _build_technical_context SPEC-02 (4.1 KB)
llm_config.py              REFACTO-11 — constantes Ollama, timeouts, num_gpu (2.95 KB)
ollama_client.py           REFACTO-11/17 — OllamaClient HTTP, 3 helpers module-level : _build_request, _stream_lines, _capture_tps (10.27 KB)
llm_prompt_builder.py      REFACTO-11 — build_prompt(), PROMPT_TEMPLATES (3.3 KB)
llm_code_utils.py          REFACTO-11 — extract_code_block(), clean_generated_code() (2.95 KB)
mcp_context_builders.py    REFACTO-10 — _build_*_context() pour les tools MCP (7.59 KB)
mcp_handlers_core.py       REFACTO-10 — Handlers create/run/evaluate (6.85 KB)
mcp_handlers_spec.py       REFACTO-10 — Handlers spec_* (5.54 KB)
mcp_handlers_llm.py        REFACTO-10 — Handlers llm_* (5.05 KB)
mcp_handlers_extras.py     REFACTO-10 — Handlers web_cache_stats + divers (4.68 KB)
sandbox_engine.py          V7 — soft|docker|auto (8.2 KB)
code_evaluator.py          — CodeEvaluator, EvalResult.to_dict() (9.5 KB)
code_evaluator_criteria.py — Critères qualité (9.4 KB)
context_assembler.py       — ContextAssembler : assemblage contexte LLM (8.8 KB)
dependency_graph.py        — DependencyGraph.build() (5.8 KB)
file_selector.py           — FileSelector : sélection fichiers cibles (5.5 KB)
planner.py                 — MultiFilePlanner : planification multi-fichiers (11.5 KB) ⚠️ WARN >10KB
recovery_service.py        — RecoveryService : boot_check + auto_recover (8.9 KB)
executor.py                — Executor : exécution TX (6.3 KB)
dsl_parser.py              — DSLParser : parse commandes DSL (7.2 KB)
orchestrator.py            — LCCAV5Fusion : façade légère REFACTO-18 (~6 KB) ⚠️ WARN >10KB → résolu
orchestrator_pipeline.py   REFACTO-18 — OrchestratorPipeline : run_pipeline() + _validate_changes() (phases 3-9) (~5 KB)
orchestrator_helpers.py    REFACTO-18 — update_sprint_log() + dry_run() helper pur (~2.5 KB)
orchestrator_compat.py     — Orchestrator = alias legacy LCCAV5Fusion (1.1 KB)
orchestrator_spec.py       REFACTO-01 — OrchestratorSpecMixin : _run_spec_layer() extrait de orchestrator.py (5.2 KB)
mempalace_client.py        REFACTO-14/MIG-04 — MemPalaceClient orchestration légère (6.1 KB) — délègue layers + fs | default palace = PALACE_DIR
mempalace_layers.py        REFACTO-14 — PalaceLayers : 4 collections ChromaDB + MemoryEntry (10.6 KB)
mempalace_fs.py            REFACTO-14 — PalaceFilesystem : wings/rooms hiérarchie JSON (2.6 KB)
mempalace_adapter.py       FIX-MCP-CRASH-01 — ExistingMemPalaceAdapter : pont MemoryEngine ↔ ChromaDB lcca_* (créé 2026-04-23)
project_health_checker.py   PROJ-10 — ProjectHealthChecker : scans santé projet (fichiers manquants, WAL, history, skills)
project_contributor.py      PROJ-11 — ProjectContributor : pipeline contribution skills locales → project_global_skills
                                        _strip_frontmatter() : retire lignes quality_score/score avant Jaccard global
```

### core/ — module web_search (Sprint WEB-01→03)
```
web_search.py          WEB-02/03 — WebSearchEngine orchestrateur (DDG+Brave+Wikipedia+Ollama) (12.8 KB) ⚠️ WARN >10KB
web_search_types.py    WEB-02 — Dataclasses SearchHit, FetchedPage, SearchResult (2.5 KB)
web_search_clients.py  REFACTO-19 — BaseSearchClient ABC + _DdgLiteClient + _BraveSearchClient + _WikipediaClient (~9 KB)
web_search_engines.py  REFACTO-19 — Façade MultiEngineSearchClient + réexports rétrocompat (~3.5 KB)
web_search_fetcher.py  WEB-02 — _PageFetcher : fetch parallèle + scoring qualité 0.0-1.0 (8.5 KB)
web_search_cache.py    WEB-02 — SearchCache TTL adaptatif (5.8 KB)
```
Règles web_search :
- urllib.request stdlib uniquement (pas de requests)
- Timeout 30s fetch / 15s moteur | fetch EN PARALLÈLE (ThreadPoolExecutor)
- Troncature à la phrase, 3000 chars/page max pour synthèse
- Score qualité < 0.3 → exclu de la synthèse Ollama
- re-exports rétrocompat : `from core.web_search import SearchHit, FetchedPage, SearchResult`

### ui/ — Electron + React (TypeScript)
```
electron/
  main.ts         IPC handlers + fs:writeWorkspaceFile
  preload.ts      contextBridge (window.lcca.*)
  mcp-bridge.ts   IPC→MCP stdio + TOOL_TIMEOUTS
  mcp-timeouts.ts SOURCE DE VÉRITÉ timeouts MCP
src/
  components/  TitleBar (TpsIndicator + EducatorBadge), ChatPanel, Sidebar, InputZone,
               MessageBubble, SpecBadge, TxBadge, StreamingIndicator, ContextPanel,
               CommandPalette, WelcomeScreen, TelemetryPanel (V9-09), SelfImprovePanel (SI-06)
  stores/      chatStore, contextStore (polling MCP 3s + tps 10s + educator 30s),
               settingsStore, telemetryStore (V9-09 — polling history 10s, découplé)
  styles/      themes.css (SOURCE DE VÉRITÉ vars), globals.css, ui05-enhancements.css
```

---

## ÉTAT DES TESTS (2026-04-30 post-PROJ-09)
- **~2089 passed** (cumul 2026-04-30 — PROJ-11 validé : 38 passed in 1.14s)
- PROJ-00 à PROJ-11 : tous DONE
- FL-01/02/03/04 : tous DONE
- VOICE-00→06 : tous DONE (35+35+34+31+34+37+56 tests)
- ROUTER-01 : `test_model_router.py` (13 classes, ~55 tests) créé 2026-04-25
- PROJ-04 : `test_proj_04.py` (20 tests) + `test_mcp_server.py` mis à jour (count 13→23)
- Run session-11 : SI-07 créé — `test_si_integration.py` (11 tests) + `test_si_guardrails.py` (19 tests) créés
- Run session-9 : SI-05 audit — `educator.py` + `test_si_05_educator.py` existaient déjà (8 tests) ✅ **8 passed in 0.15s**
- Run session-8 : SI-04 audit — `auto_fix.py` + `test_si_04_autofix.py` existaient déjà (14 tests)
- Run session-2 validé : `test_refacto_15.py test_refacto_16.py test_memory_engine.py test_spec_layer.py test_spec_retry.py test_smoke.py` — **143 passed in 2.63s** ✅
- Run session-3 validé : `test_planner.py test_refacto_11.py test_v9_05.py test_v9_06.py` — **77 passed in 1.30s** ✅
- test_planner.py : +18 tests (audit coverage B — planner.py)
- REFACTO-15 : +18 tests (test_refacto_15.py)
- REFACTO-16 : +18 tests (test_refacto_16.py)
- V9-09 : +48 tests
  - REFACTO-13 : +18 tests (test_refacto_13.py)
  - REFACTO-14 : +18 tests (test_refacto_14.py)
  - Spec Diff  : +6 tests  (test_spec_diff.py)
  - Spec Retry : +6 tests  (test_spec_retry.py)
- REFACTO-12 : +18 tests (test_refacto_12.py)
- FIX-NETWORK : conftest.py créé + test_educator_agent.py + test_ed_02.py corrigés
- FIX-REFACTO11 : 13 tests corrigés (test_v9_01_a, test_v9_05, test_v9_06) — mocks déplacés vers `core.ollama_client`
- Correction V9-08 : `llm_review` ajouté à VALID_CAPABILITIES dans agent_card.py
- Derniers sprints ajoutant des tests :
  - REFACTO-09 : +18 tests (test_refacto_09.py)
  - REFACTO-08 : +28 tests (test_refacto_08.py)
  - REFACTO-07 : +18 tests (test_refacto_07.py)
  - REFACTO-06 : +18 tests (test_refacto_06.py)
  - V9-08 : +12 tests (test_v9_08.py)
  - V9-07 : +12 tests (test_v9_07.py)

### Audit coverage Option B (2026-04-22) — résultats

**B1 — mcp_tool_handlers.py / mcp_server.py** ✅ Couverture satisfaisante
- test_mcp_server.py : 40 tests unitaires (mocks), 13 tools vérifiés
- test_mcp_integration.py : 38 tests intégration end-to-end (deps réelles)
- Pipelines complets : create→run→evaluate testés
- Sécurité : path traversal, absolu, tool inconnu — tous couverts
- ⚠️ mcp_tool_handlers.py à 28.9 KB : candidat REFACTO-10 (handlers à découper)

**B2 — orchestrator_spec.py / spec_promoter.py** ✅ Couverture satisfaisante
- test_spec_promoter.py : 6 tests (promotion Layer 2→1→0, idempotence, config)
- test_spec_complexity.py : 10 tests (score, mots-clés, domain, search normalisé)
- orchestrator_spec.py : couvert indirectement via test_spec_layer.py + test_orchestrator.py
- orchestrator_medi.py : RETIRÉ (MIG-02) — archivé dans _archive_medibot/
- test_medibot_adapter.py : RETIRÉ (MIG-02) — archivé dans _archive_medibot/

**B3 — web_search (5 fichiers WEB-01→03)** ✅ Couverture satisfaisante
- test_web_search.py : ~35 tests couvrant :
  - SearchHit/FetchedPage/SearchResult (types + to_dict)
  - SearchCache : miss/set/get/expired/invalidate/stats/TTL adaptatif
  - _PageFetcher : troncature phrase, scoring qualité, extraction sémantique/fallback
  - MultiEngineSearchClient : dédup URL, engines_used, Wikipedia encyclopédique
  - WebSearchEngine : ranking post-fetch WEB-03, exclusion qualité < 0.3
  - DDG fallback : filtrage trackers/titres courts
  - Tool MCP web_cache_stats : stats/clear_expired/invalidate/erreurs

### Lacunes identifiées (mineures)
- orchestrator_spec.py : `_run_spec_layer()` testé via orchestrateur principal, pas de test isolé
- llm_generator.py : 9.09 KB (post-REFACTO-11) — coverage via test_llm_generator.py (non audité en détail)

## SPRINTS TERMINÉS (liste complète condensée)
Sprints 01→22 (core V7.2) | Sprint 05 (MemPalaceClient 4 layers) | Sprint 08 (RETIRÉ — passerelles MediBot archivées MIG-02)
Sprint 12 (TransactionManager + McpEditBatch) | Sprint 15 (SpecComplexityEstimator + SpecPromoter)
Sprint 16 (SpecPromoter Règle 19) | Sprint 18 (LLMGenerator + dette spec_complexity) | Sprint 19 (SpecPromoter memory_layer)
V8-01→V8-09 | UI-01→UI-08 | UI-DS | UI-CHARTE
WEB-01→WEB-03 | CTX-01→CTX-05 | V9-00→V9-08 | ED-01→ED-04 | V9-02-A
REFACTO-01 (OrchestratorSpecMixin extrait) | REFACTO-02→REFACTO-09
REFACTO-10 (mcp_tool_handlers.py découpé : context_builders + handlers_core/spec/llm/extras)
REFACTO-11 (llm_generator.py découpé : llm_config + ollama_client + prompt_builder + llm_code_utils)
REFACTO-15 (memory_engine.py 17.16 KB → 6.6 KB) : store → memory_engine_store.py | search → memory_engine_search.py | +18 tests
REFACTO-16 (spec_generator.py 16.75 KB → 8.8 KB) : helpers → spec_generator_helpers.py | context → spec_generator_context.py | +18 tests
REFACTO-12 (cognitive_patterns.py : prompts extraits dans cognitive_prompts.py | +18 tests)
FIX-V9-08 : agent_card.py — ajout llm_review dans VALID_CAPABILITIES
SI-V10.5 Phase 1 (2026-04-23 session 5) : squelette SelfImprove créé
  lcca_si.py (CLI racine) | SelfImprove/si_config.py | SelfImprove/si_utils.py | engines/__init__.py
  config.toml | orchestrator_rules.json | auto_fix_whitelist.json | observer_patterns.json
  pending_actions.json | borgnes_map.json | actions.log | structure dossiers complète
  Specs : Docs/Specs/SelfImprovement/ (5 fichiers) | Sprints : Docs/Sprints/SelfImprovement/ (7 sprints)

## MODE PROJETS — SPRINTS PROJ-00 à PROJ-03 (état 2026-04-23)

**Statut : 0% — AUCUN sprint commencé, AUCUN fichier créé.**

Les 4 sprints sont des specs uniquement. Aucun code ni test n'existe dans `core/` ou `tests/`.
Fichiers attendus absents : `migration_manager.py`, `project_manager.py`, `project_lock.py`,
`project_orchestrator.py`, `project_loader.py`, `project_context_assembler.py`, `project_checkpoint.py`.
Tests attendus absents : `test_proj_00.py`, `test_proj_01.py`, `test_proj_02.py`, `test_proj_03.py`.

| Sprint | Fichier | Statut | Dépendances |
|--------|---------|--------|-------------|
| PROJ-00 | `core/migration_manager.py` + `test_proj_00.py` (15 tests) | ✅ FAIT | Aucune |
| PROJ-01 | `core/project_manager.py` + `test_proj_01.py` (23 tests) | ✅ FAIT | PROJ-00 |
| PROJ-02 | `core/project_lock.py` + `test_proj_02.py` (14 tests) | ✅ FAIT | PROJ-01 |
| PROJ-03 | 4 fichiers core + `test_proj_03.py` (19 tests) | ✅ FAIT | PROJ-01, PROJ-02 |
| PROJ-04 | `core/mcp_handlers_projects.py` + `test_proj_04.py` (20 tests) | ✅ FAIT | PROJ-03 ✅ |
| PROJ-05 | UI Electron Mode Projets (0 tests Python) | ✅ FAIT | PROJ-04 |
| PROJ-06 | `core/project_wal.py` + `test_proj_06.py` (35 tests) | ✅ FAIT | PROJ-01 |
| PROJ-07 | `core/user_context_injector.py` + `test_proj_07.py` | ✅ FAIT | PROJ-06 |
| PROJ-08 | `core/user_context_learner.py` + `tests/test_proj_08.py` | ✅ FAIT | PROJ-06, PROJ-07 |
| PROJ-09 | `core/project_history_compactor.py` + `test_proj_09.py` (21 tests) | ✅ FAIT | PROJ-01 |
| PROJ-10 | `core/project_health_checker.py` + patch `_tool_project_healthcheck` + `test_proj_10.py` (20 tests) | ✅ FAIT | PROJ-01 |
| PROJ-11 | `core/project_contributor.py` + `tests/test_proj_11.py` (38 tests) | ✅ FAIT | PROJ-01, palace |

Règles Mode Projets (à appliquer dès PROJ-00) :
- Structure racine : `D:\LLMCodeAgent\projects\{slug}\` (créée par MigrationManager)
- Source de vérité : scan filesystem `projects/*/.llca/project.json` (jamais `index.cache.json`)
- `index.cache.json` = cache performance uniquement, reconstruit au boot (< 50 ms)
- Lock : `.lock` minimal dans projet + payload heartbeat dans `%TEMP%` (évite Defender)
- Thread heartbeat : daemon, join timeout=1.0s à la fermeture, intervalle 30s
- `psutil` optionnel : `callable(getattr(psutil, "pid_exists", None))` avant appel
- Double namespace legacy : `project_legacy_*` (écriture) + `lcca_*` (lecture fallback)
- **Aucun rename ChromaDB** — non supporté nativement, on fait du fallback lecture
- `_rewrite_paths()` : 3 passes (double backslash, simple backslash, forward slash)
- Chaque worker PROJ-03 < 8 KB (règle REFACTO LLCA)
- `save_project()` release le lock dans un `try/finally` (même si checkpoint.save() lève)
- PROJ-03 worker 5 (`user_context_injector.py`) créé dans PROJ-07 (dépend de PROJ-06 WAL)

## FIX-UI-ONLINE-MODELS (2026-04-24)
- Cause root : classes CSS `.om-*` absentes de tous les fichiers styles → éléments invisibles/chevauchés
- Fix : 2 sections ajoutées dans `ui05-enhancements.css` (sections §21 et §22)
  - §21 : `.settings-modal` max-height 88vh + `.settings-body` overflow-y + scrollbar webkit visible (width 5px)
  - §22 : CSS complet `.om-panel`, `.om-card`, `.om-card-header`, `.om-card-controls`, `.om-badge`, `.om-toggle`, `.om-btn-test`, `.om-key-row`, `.om-btn-sm` — tous les variants (--active, --off, --warn, --ready, --testing, --ok, --error, --cancel)
- 0 modification de `OnlineModelsPanel.tsx` (logique correcte, bouton 'Ajouter' existait déjà)
- Règle ajoutée : tout nouveau composant avec classes CSS propres → vérifier que ces classes existent dans ui05-enhancements.css avant de déclarer le sprint TERMINÉ

## UI-CTX-01 — MENU CONTEXTUEL (2026-04-24) ✅
Fichiers créés/modifiés :
- `ui/src/components/ContextMenu.tsx` (nouveau) — 3 exports : `ContextMenu` composant + `useContextMenu` hook + helpers (`copyToClipboard`, `extractFirstCodeBlock`, `formatAsQuote`)
- `ui/src/components/MessageBubble.tsx` — +`onContextMenu` sur la bulle, +bouton `⋯` discret (`.ctx-trigger`), +`ContextMenu` monté en `fixed`, +toast de confirmation
- `ui/src/components/ChatPanel.tsx` — +prop `onQuote` passé aux bulles (pré-remplit `setInputValue`)
- `ui/src/styles/ui05-enhancements.css` — +section §23 : styles `.ctx-menu`, `.ctx-item`, `.ctx-icon`, `.ctx-label`, `.ctx-shortcut`, `.ctx-divider`, `.ctx-toast`, `.ctx-trigger`
Actions disponibles dans le menu :
- **Copier le texte** (plain text, sans blocs code) — Ctrl+C
- **Copier le Markdown** (raw)
- **Copier le code** (premier bloc ``` uniquement — apparaît seulement si code détecté) — Ctrl+Shift+C
- **Citer dans l'InputZone** (formatAsQuote → > lignes, max 400 chars injecte dans input existant)
- **Exporter en .md** (téléchargement fichier, assistants uniquement)
Invariants :
- Menu désactivé pendant le streaming (guard `isStreaming`)
- Fermeture : Escape / clic extérieur / scroll (3 listeners document)
- Position clampée dans le viewport (ajustement post-mount)
- Toast auto-effacé après 1800ms
- `copyToClipboard` : navigator.clipboard avec fallback execCommand
- Messages système : aucun menu contextuel (guard `isSystem`)
- Pas de menu pendant pré-streaming (guard `!message.content`)

## UI-MODEL-01 — BADGE MODÈLE PAR MESSAGE (2026-04-24) ✅
Fichiers modifiés :
- `ui/src/types/chat.ts` — +`modelName?: string` sur `Message`
- `ui/src/components/ChatPanel.tsx` — +`tpsData` depuis contextStore, injecté dans `appendMessage` assistant (`modelName: tpsData?.model ?? undefined`)
- `ui/src/components/MessageBubble.tsx` — +`.bubble-model-badge` rendu sous chaque bulle assistant (guard : `!isStreaming && role==='assistant' && modelName`)
- `ui/src/styles/ui05-enhancements.css` — +section §24 : `.bubble-model-badge`, `.bubble-model-icon` (losange ambre, glow), `.bubble-model-name` (mono 10px)
Comportement :
- Badge discret (opacité 0.6 au repos, 0.85 au survol de la bulle, 1.0 au survol direct)
- Affiche le modèle tel que retourné par `tpsData.model` (ex: `qwen2.5-coder:3b`)
- Absent si `modelName` non défini (messages chargés depuis une session antérieure sans le champ)
- Source de données : `contextStore.tpsData.model` pollé toutes les 10s (déjà existant)
- Persistance : `modelName` sérialisé avec le message dans `saveSessionMessages`

## PROCHAIN SPRINT SUGGÉRÉ
PROJ-11 TERMINÉ (2026-04-30) — `core/project_contributor.py` + `tests/test_proj_11.py` (38 tests). Pipeline contribution skills → MemPalace. `_strip_frontmatter()` ajouté.
PROJ-00→PROJ-11 : tous DONE. Prochains candidats :
- **PROJ-UI-01** : `ProjectWelcomeScreen` Electron (spec v3 §1) — UI Mode Projets, 0 tests Python
- **EvalLoop V3 live** : test manuel Ollama réel (`lcca_eval.py probe`) quand Ollama disponible
- **FL-04** : `skill_metrics.py` — `record_usage/record_outcome` déjà dans skill_library.py — à vérifier avant de coder
- **VOICE-11** : `install.bat` + `requirements.txt` Voice (fin pipeline Voice)
V9-09 TERMINÉ (2026-04-23) — spec_diff, spec_retry, TelemetryPanel, REFACTO-13, REFACTO-14.
REFACTO-15 TERMINÉ (2026-04-23) — `memory_engine.py` découpé + 18 tests ✅ validés (test_refacto_15.py + test_memory_engine.py)
REFACTO-16 TERMINÉ (2026-04-23) — `spec_generator.py` découpé + 18 tests ✅ validés (test_refacto_16.py + test_spec_layer.py + test_spec_retry.py)
DETTE-01/02/03 TERMINÉS (2026-04-23 session 4) — `orchestrator.py` dead code supprimé, `web_search_engines.py` R9 corrigé, `002-context.md` tailles + arbo à jour.
FIX-MCP-CRASH-01 (2026-04-23) — `core/mempalace_adapter.py` créé : module manquant causant crash MCP Server au démarrage.
MIG-05 TERMINÉ (2026-04-23) — palace local peuple : 75 drawers (3 skills + 2 historiques MCP), 192 KB ChromaDB.
SI-V10.5 SPECS + SQUELETTE TERMINÉS (2026-04-23 session 5) — specs complètes + squelette Phase 1 créés.
SI-02 — ObserverDaemon TERMINÉ (2026-04-23 session 6) — observer_daemon.py existait déjà, tests créés (test_si_02_observer.py, 22 tests).
SI-03 — OrchestratorLight TERMINÉ (2026-04-23 session 7) — orchestrator.py + test_si_03_orchestrator.py existaient déjà (même pattern que SI-02). `get_coupling_mode()` conforme, `si_utils.py` exports complets.
SI-04 — AutoFix TERMINÉ (2026-04-23 session 8) — auto_fix.py + test_si_04_autofix.py existaient déjà (même pattern que SI-02/SI-03). 8 guards, rollback automatique, 14 tests.
SI-05 — EducatorSI TERMINÉ (2026-04-23 session 9) — educator.py + test_si_05_educator.py existaient déjà (même pattern). 8 tests. Invariant : jamais de modification system files. Prochain sprint : **SI-07 — Tests** (`Docs/Sprints/SelfImprovement/sprint-si-07-tests.md`).
SI-06 — SelfImprovePanel TERMINÉ (2026-04-23 session 10) — 5 fichiers (mcp-timeouts.ts + main.ts + preload.ts + SelfImprovePanel.tsx + Sidebar.tsx). Composant complet avec ModeSection, SystemStateSection, MiniLogSection, FullLogModal, badge pending. 0 couleur hardcodée.
SI-07 — Tests intégration + guardrails TERMINÉ (2026-04-23 session 11) — `test_si_integration.py` (11 tests pipeline) + `test_si_guardrails.py` (19 tests garde-fous). Sprint SI complet.
PROJ-00 — MigrationManager TERMINÉ (2026-04-23) — `core/migration_manager.py` + `test_proj_00.py` (15 tests). Structure projects/.llca/ + projet legacy + _rewrite_paths() + idempotence.
PROJ-03 — ProjectOrchestrator TERMINÉ (2026-04-23) — 4 fichiers créés : `project_loader.py`, `project_context_assembler.py`, `project_checkpoint.py`, `project_orchestrator.py` + `test_proj_03.py` (18 tests). Pipeline load/save complet.
PROJ-04 — MCP tools Mode Projets TERMINÉ (2026-04-23) — `core/mcp_handlers_projects.py` (10 handlers) + `test_proj_04.py` (20 tests). MCP passe de 13 → 23 tools. `mcp_tools_schema.py`, `mcp_tool_handlers.py`, `mcp_server.py`, `test_mcp_server.py` mis à jour.
PROJ-02 — ProjectLock TERMINÉ (2026-04-23) — `core/project_lock.py` + `test_proj_02.py` (14 tests). Lock fichier + heartbeat %TEMP + thread daemon + stale detection.
PROJ-01 — ProjectManager TERMINÉ (2026-04-23) — `core/project_manager.py` + `test_proj_01.py` (23 tests). CRUD projets, scan filesystem source de vérité, slug ASCII, cache reconstruit.
REFACTO-18 TERMINÉ (2026-04-23) — `orchestrator.py` (15.6 KB → ~6 KB façade) : pipeline TX/LLM/Patch → `orchestrator_pipeline.py` (OrchestratorPipeline) | helpers → `orchestrator_helpers.py` | aliases rétrocompat maintenus | +18 tests (test_refacto_18.py).
REFACTO-19 TERMINÉ (2026-04-23) — `web_search_engines.py` (13.2 KB → ~3.5 KB façade) : `web_search_clients.py` existait déjà (9.03 KB) | réexports rétrocompat `_DdgLiteClient/_BraveSearchClient/_WikipediaClient` | 0 nouveau test (test_web_search.py couvre déjà tout).
REFACTO-20 TERMINÉ (2026-04-23) — `transaction_manager.py` (16.7 KB → ~9 KB façade) : maintenance WAL/cleanup → `transaction_wal.py` (TransactionWalMixin) | héritage `TransactionManager(TransactionWalMixin, TransactionLegacyMixin)` | réexport rétrocompat | +18 tests (test_refacto_20.py).

## WHITELIST EDUCATOR (état 2026-04-23) — 22 repos
Source de vérité : `core/agents/educator_whitelist.json` (JSON direct, pas educator_agent.py)
Loader : `educator_whitelist.py` — expose WHITELIST, load_whitelist(), save_whitelist(), load_skip_set()
Patch `educator_github.py` : list_py_files() lit `.endswith((".py", ".pyi"))` — typeshed débloqué

Ajouts 2026-04-23 (+6 repos) :
- `PyCQA/flake8`           P0 — pattern RuleChecker + plugin registry (spec_validator_rules.py) | skip_license_check
- `lidatong/dataclasses-json` P0 — to_dict/from_dict SpecEntry, sérialisation dataclass JSON
- `python-attrs/cattrs`    P1 — conversion dataclass ↔ dict typée stricte
- `sqlalchemy/sqlalchemy`  P1 — vocabulaire ACID/WAL/rollback/session (domaine transaction)
- `python/typeshed`        P0 — stubs PEP 484 stdlib, skip_license_check=true
- `astral-sh/ruff`         P1 — 500+ règles nommées avec codes/sévérités

Retirés 2026-04-23 (licences non conformes) :
- `PyCQA/astroid`          LGPL-2.1 — copyleft, skip interdit
- `HypothesisWorks/hypothesis` MPL-2.0 — hors ACCEPTED_SPDX

Fix skip_license_check 2026-04-23 :
- `numpy/numpy`            BSD-3 confirmé mais API GitHub retourne spdx_id=null (faux positif)

P2 différés (non urgents) : `microsoft/promptflow`, `sphinx-doc/sphinx`
Tests : 0 mise à jour requise — aucun test ne pinne count whitelist ni extension list_py_files

### Run Educator 2026-04-23_00-13 — résultats
- 9 repos traités / 24 | 240 fichiers | 118 skills | 80 hashes persistés | 0 erreur | ~2min22
- `PyCQA/flake8` rejeté (licence non conforme) → FIX : skip_license_check=true ajouté au JSON
- 15 repos restants à traiter (dont typeshed + ruff) — rate limit GitHub 60 req/h anonyme
- `python/typeshed` et `astral-sh/ruff` pas encore exercés (prochain run)

### Run Educator 2026-04-23_00-19 — résultats
- 24 repos traités (tous) | 630 fichiers | 410 skills | 193 hashes persistés | 0 erreur | ~6min
- `PyCQA/flake8` inguré (fix skip appliqué) ✔
- `python/typeshed` + `astral-sh/ruff` traités — patch .pyi exercé pour la première fois ✔
- Rejetés : astroid (LGPL), hypothesis (MPL-2.0), numpy (faux positif BSD-3)
- FIX appliqué post-run : astroid+hypothesis retirés | numpy skip_license_check=true

## EDUCATOR RUNNER (2026-04-22)
Lanceur autonome créé dans D:\LLMCodeAgent\Educator\ :
- educator_runner.py  (10 KB) — script Python, args --mode all|update|dry
- lcca_educator.bat   (6.4 KB) — menu interactif Windows (Continuer / MAJ / Nouvelle source / Voir sources)
- sources.json        — sources custom (initialement vide [])
- logs/               — rapports de session YYYY-MM-DD_HH-MM.log

Règles :
- sources.json contient UNIQUEMENT les repos ajoutés par l'utilisateur (format [{owner, repo, description}])
- La whitelist interne (24 repos) est dans educator_whitelist.json — PAS dans educator_agent.py
- Le runner injecte les sources custom dans curator._whitelist au runtime
- dry_run=False sur [1] Continuer | dry_run=True sur [2] MAJ
- Pas de token GitHub (repos publics, 60 req/h anonyme suffisent)
- Rapport de fin affiché console ET écrit dans logs/

## FIX-NETWORK (2026-04-22) — fichiers modifiés
| Fichier | Action |
|---|---|
| tests/conftest.py | CRÉÉ — autouse fixture bloque urllib.request.urlopen dans tous les tests |
| tests/test_educator_agent.py | FIX — test_run_task_dry_run_from_context mocke run_curation |
| tests/test_ed_02.py | FIX — test_persist_* mockent agent._ingester.process_repo (bon niveau post-REFACTO) |

## DETTE TECHNIQUE
Aucune dette ouverte (toutes résolues avant le 2026-04-21).
Seuils de surveillance :
- > 7 KB + 2 responsabilités → INFO
- > 10 KB → WARN (candidat REFACTO)
- Constante dupliquée entre 2 fichiers → WARN

### Nouveaux modules SelfImprove (2026-04-23 session 5)
```
D:\LLMCodeAgent\
├── lcca_si.py                   CLI point d'entrée SelfImprove (racine projet)
SelfImprove\
├── si_config.py                 Loader config.toml + fallback défauts
├── si_utils.py                  atomic_write_json, log_action, cooldown tracker, pending_actions
├── config.toml                  Configuration (coupling_mode, intervals, paths)
├── orchestrator_rules.json      Règles déterministes (grammaire unifiée {field,operator,value,filters})
├── auto_fix_whitelist.json      Patterns auto-fix autorisés (SmartPatcher / template string)
├── observer_patterns.json       Patterns détection extensibles
├── pending_actions.json         Actions en attente d'ACK humain
├── borgnes_map.json             Carte angles morts V10 (clustering WAL ChromaDB)
├── actions.log                  Write-ahead CSV toutes actions
├── engines/
│   ├── observer_daemon.py       ✅ SI-02 TERMINÉ — ObserverDaemon (collecte WAL/logs/telemetry/tests)
│   ├── orchestrator.py          ✅ SI-03 TERMINÉ — OrchestratorLight (règles JSON, cooldown, write-ahead)
│   ├── auto_fix.py              ✅ SI-04 TERMINÉ — AutoFixEngine (8 guards, rollback, missing_import + coroutine_never_awaited STUB)
│   └── educator.py              ✅ SI-05 TERMINÉ — EducatorSI (auto-fix/borgnes/manual, dédup sha256, suggestions .md)
├── observations/                Fichiers JSON horodatés (écriture atomique .tmp→rename)
├── auto_fixes/                  Patches + logs auto-fix
└── patterns/                    Suggestions Educator (.md)
```
Règles SelfImprove :
- Import TelemetryStore en **lazy** dans ObserverDaemon (évite import circulaire)
- `SmartPatcher.apply_patch()` retourne `str` — AutoFixEngine écrit disque via `filesystem:write_file`
- `min_coupling_mode` dans chaque règle JSON — vérifié avant exécution
- `auto_push = false` codé en dur (jamais de push git automatique)
- Mode 3 : A2ALocalBus import lazy dans `_action_retry_coder_once` (Mode 3 uniquement)

### Fichiers > 10 KB surveillés (état 2026-04-23 post-session-3)
| Fichier | Taille | Statut |
|---|---|---|
| transaction_manager.py | 12.25 KB | ✅ REFACTO-20 (maintenance WAL/cleanup → transaction_wal.py) — cœur ACID inséparable (begin/log_op/commit/rollback/_snapshot/_backup/_write_wal) |
| transaction_wal.py | ~5 KB | ✅ REFACTO-20 nouveau module |
| llm_generator.py | 9.09 KB | ✅ REFACTO-11 (llm_config + ollama_client + prompt_builder + llm_code_utils) |
| ollama_client.py | 10.27 KB | ✅ REFACTO-17 (nettoyage interne, 3 helpers module-level extractés) |
| memory_engine.py | ~7 KB | ✅ REFACTO-15 (store → memory_engine_store.py, search → memory_engine_search.py) |
| spec_generator.py | ~7 KB | ✅ REFACTO-16 (helpers → spec_generator_helpers.py, context → spec_generator_context.py) |
| orchestrator.py | 15.6 KB | ✅ REFACTO-18 (façade + orchestrator_pipeline.py + orchestrator_helpers.py) |
| cognitive_patterns.py | 7.4 KB | ✅ REFACTO-12 (prompts extraits dans cognitive_prompts.py) |
| cognitive_prompts.py | 7.2 KB | ✅ REFACTO-12 nouveau module |
| mempalace_client.py | 6.4 KB | ✅ REFACTO-14 (layers + fs extraits) |
| error_analyzer.py | 5.8 KB | ✅ REFACTO-13 (classifier + recovery_hints extraits) |
| spec_validator_rules.py | 13.8 KB | ⚠️ Surveiller |
| web_search_clients.py | 9.03 KB | ✅ REFACTO-19 (clients extraits de web_search_engines.py) |
| web_search_engines.py | ~3.5 KB | ✅ REFACTO-19 (façade + réexports rétrocompat) |
| mcp_server.py | 13.5 KB | ⚠️ Surveiller |
| mcp_edit_batch.py | 12.9 KB | OK (1 responsabilité claire) |
| web_search.py | 12.8 KB | OK (orchestrateur léger) |
| planner.py | 11.5 KB | ⚠️ Surveiller — test_planner.py couverture ajoutée (audit-B) |

## EVALLOOP — SPECS V1 (2026-04-24)
- `Spec_EvalLoop_V1.md` créée : `D:\LLMCodeAgent\Docs\Specs\EvalLoop\Spec_EvalLoop_V1.md`
- Remplace V0 (ClaudeV0) + Addendum (Kimi) — 7 sprints EVAL-01→07, ~125 tests
- PROCHAIN SPRINT EVALLOOP : **EvalLoop V3 TERMINÉ** — test manuel Ollama réel quand Ollama disponible

### INT-01 — TERMINÉ (2026-04-24) ✅ 5 passed
Fichier créé :
- `tests/test_eval_integration.py` — 5 tests bout-en-bout (pipeline probe→scores, distill claude, curriculum update, dedup cross-session, invariant local jamais injecté)
Patterns importants :
- `StoreResult` importé depuis `core.memory_engine_store` (pas core.memory_engine)
- Scores < 0.70 en moyenne dans test_3 → palier reste 0 (pas de montée involontaire)
- Dedup cross-session : même `DistillEngine` instance entre les deux sessions (index chargé une fois, sauvé une fois)

### EVAL-05 — TERMINÉ (2026-04-24) ✅ 5 passed
Fichiers créés :
- `lcca_eval.py` (racine) — CLI 5 commandes : probe/run/distill/report/review-bench, sys.path.insert en premier, imports locaux dans cmd_*
- `EvalLoop/engines/judge_engine.py` — JudgeEngine : gatekeeper JudgeLocal + dispatch JudgeClaude, guard VIG-03 mélange juges
- `EvalLoop/engines/session_reporter.py` — SessionReporter : session_report.md + métriques santé Ollama (4 seuils), écriture atomique T-14
- `tests/test_eval_05_cli.py` — 5 tests smoke ✅
Patterns importants :
- cmd_* importent les moteurs LOCALEMENT (pas d'import module-level) → patch via modules sources, pas `lcca_eval.ProbeEngine`
- `_new_session_dir()` crée dossier YYYY-MM-DD_HH-MM sous _SESSIONS_DIR (constante patchable via monkeypatch)
- Test 4 : monkeypatch sur `lcca_eval._SESSIONS_DIR` APRÈS import du module

### EVAL-04 — TERMINÉ (2026-04-24) ✅ 10 passed
Fichiers créés :
- `EvalLoop/engines/distill_engine.py` — DistillEngine : filtre strict judge=claude+inject=True+score>=0.70, payload strict "content" uniquement, dedup charge-une-fois/écrit-une-fois, écriture atomique T-14
- `EvalLoop/judges/judge_claude.py` — JudgeClaude stub V3 : retourne improved_answer hardcodé, final_score=0.74, inject_recommended=True
- `tests/test_eval_04_distill.py` — 10 tests ✅
Patterns importants :
- `DistillEngine.__init__` instancie `MemoryEngine()` → patcher `EvalLoop.engines.distill_engine.MemoryEngine` (binding local) dans `_make_engine()`
- Import DIRECT (pas lazy) dans distill_engine — pas de circulaire car EvalLoop n'est pas importé par core/
- Payload interdit : "code", "snippet", "error", "text" (extract_content() les prendrait en priorité sur "content")
- `_save_dedup_index()` appelé UNE SEULE FOIS après la boucle (anti-O-01)

### EVAL-03 — TERMINÉ (2026-04-24) ✅ 10 passed
Fichiers créés :
- `EvalLoop/benchmarks/__init__.py` — package vide
- `EvalLoop/benchmarks/python_core/palier_0.json` — 10 questions actives palier 0
- `EvalLoop/benchmarks/python_core/palier_1.json` — 10 questions actives palier 1
- `EvalLoop/engines/curriculum_tracker.py` — CurriculumTracker : get_state/update_state/is_unlocked/load_questions, atomic write T-14, SYS-02 désactivé
- `tests/test_eval_03_curriculum.py` — 10 tests ✅

### EVAL-02 — TERMINÉ (2026-04-24) ✅ 15 passed
Fichiers créés :
- `EvalLoop/engines/__init__.py` — package vide
- `EvalLoop/engines/probe_engine.py` — ProbeEngine : appel OllamaClient, probe()/probe_batch(), timeout=None invariant
- `EvalLoop/judges/__init__.py` — package vide
- `EvalLoop/judges/judge_base.py` — JudgeBase ABC
- `EvalLoop/judges/judge_local.py` — JudgeLocal : scoring tokenisé (concept 60% + coherence 20% + structure 20%), invariants inject=False/answer=""
- `tests/test_eval_02_judge.py` — 15 tests ✅

### EVAL-01 — TERMINÉ (2026-04-24) ✅ 15 passed
Fichiers créés :
- `EvalLoop/__init__.py` — package Python vide
- `EvalLoop/evalloop_types.py` — 5 dataclasses + to_dict/from_dict (BenchQuestion, ProbeResponse, JudgeScore, DistilledSkill, PalierState)
- `EvalLoop/eval_config.toml` — config globale (scoring, sessions, storage, flags SYS-02/03/04)
- `EvalLoop/eval_state.json` — `{}` état initial
- `EvalLoop/eval_dedup_index.json` — `[]` index dedup initial
- `EvalLoop/README_EvalLoop.md` — limitations V3 (SYS-01/02/04 documentées, règle payload strict)
- `tests/test_eval_01_types.py` — 15 tests ✅

**Corrections majeures V0 → V1 après analyse code réel :**
- `SkillLibrary.add_skill()` inexistant → injection via `MemoryEngine.store("evalloop_skills", ...)`
- `JudgeLocal` (matching expected_concepts, 100% offline) = juge par défaut, pas Claude
- `judge_openai.py` stub supprimé → remplacé par `judge_local.py`
- `BenchQuestion.status` ajouté : "active" | "draft" (questions LLM non revues)
- `JudgeScore.sub_scores` ajouté : concept_coverage + length_bonus
- Palier 0/1 : écriture manuelle uniquement — CLI refuse `gen-bench --palier 0/1`
- Prompt probe : "Tu es LCCA" supprimé (incorrect conceptuellement)
- `min_inject_score = 0.70` (non 0.75 — JudgeLocal moins précis)
- Commande `run` ajoutée au CLI (pipeline complet probe→judge→distill→report)
- Import MemoryEngine **DIRECT** dans DistillEngine (pas de circulaire — EvalLoop non importé par core/)

## PIPELINE VOICE — SPRINTS (état 2026-04-25)

Spec : `D:\LLMCodeAgent\Docs\Specs\Voice\Spec_Voice_V1.md`
Isolation totale : `Voice/` n'importe JAMAIS depuis `core/`
venv séparé : `Voice/venv/` distinct du venv LCCA
Communication Electron ↔ services : WebSocket uniquement (ports 8765 STT, 8766 TTS)
0 nouveau tool MCP en V1

### Décisions validées (2026-04-25)
- Langue : fixe `fr` (pas d'auto-détection en V1)
- Push-to-talk par défaut, continu opt-in (`continuous_mode = false`)
- TTS streaming phrase par phrase pendant génération Ollama
- Raccourci `Alt+V` local uniquement (pas d'iohook global)
- Voix FR : Piper `fr_FR-mls-medium` | Voix EN : Kokoro `af_heart`
- venv séparé (`Voice/venv/`)
- `auto_submit = false` — utilisateur lit/édite avant envoi
- Volume TTS indépendant système (sounddevice amplitude multiplier)
- Interruption TTS : `Alt+V` ou bouton micro → `sounddevice.stop()` + vide queue
- Texte partiel visible en italique grisé dans InputZone
- Bips : 440Hz/80ms (activation) + 220Hz/60ms (désactivation), numpy+sounddevice
- Ollama occupé → transcription en queue InputZone, submit grisé le temps qu'Ollama libère

### Arborescence Voice/
```
D:\LLMCodeAgent\Voice\
├── voice_types.py       ✅ VOICE-00 — Enums + dataclasses + config loader + VRAM helpers + BeepSpec
├── voice_capture.py     ✅ VOICE-01 — VoiceCapture VAD + buffer PCM + CaptureResult
├── voice_config.toml    ✅ VOICE-00 — Config toml (langue fr, push_to_talk, auto_submit=false)
├── voice_transcriber.py VOICE-02 — faster-whisper wrapper, device auto-detect, INT8
├── voice_service.py     VOICE-03 — Serveur WebSocket STT port 8765
├── tts_engine_piper.py  VOICE-04 — Piper ONNX wrapper
├── tts_engine_kokoro.py VOICE-05 — Kokoro wrapper fallback CPU
├── tts_sentence.py      VOICE-06 — split_sentences/iter_sentences/flush_partial (streaming phrase-par-phrase)
├── tts_service.py       VOICE-06 — TTSService WebSocket TTS port 8766 (_ws_factory + _engine_factory injectables)
├── models/stt/          faster-whisper small ctranslate2
├── models/tts/piper/    fichiers .onnx Piper
├── models/tts/kokoro/   Kokoro weights
├── venv/                venv Python isolé (PAS le venv LCCA)
├── requirements.txt     à créer VOICE-02
└── install.bat          à créer VOICE-11
```

### Règles Voice invariantes
- `VoiceCapture._vad_factory` injectable pour tests sans webrtcvad installé
- `_DummyVad` fallback si webrtcvad absent : retourne toujours False
- `make_silent_chunk()` / `make_speech_chunk()` : helpers test dans voice_capture.py
- `sys.path.insert(0, _VOICE_DIR)` dans chaque test Voice (pas de package __init__)
- `pytest.skip()` si sounddevice sans périphérique audio (CI)
- Mocks `sounddevice.play` dans tous les tests TTS
- `webrtcvad.Vad.is_speech` mocké via `_vad_factory` injectable
- `WhisperModel` mocké via `patch("Voice.voice_transcriber.WhisperModel")`
- `resolve_stt_device()` / `resolve_tts_engine()` : seuil VRAM_MIN_MB_FOR_CUDA = 1500 MB libre

### Tests Voice (état 2026-04-30)
- `test_voice_00.py` : ✅ VOICE-00 — 9 classes, ~35 tests (enums, messages WS, configs, VRAM helpers, BeepSpec)
- `test_voice_01.py` : ✅ VOICE-01 — 10 classes, ~35 tests (constantes, DummyVad, lifecycle, VAD states, bad chunks, max utterance, stop flush, callback, stats, CaptureResult)
- `test_voice_02.py` : ✅ VOICE-02 — 34 tests (VoiceTranscriber, WAV temp, logprob→conf, TranscriptionResult)
- `test_voice_03.py` : ✅ VOICE-03 — 31 tests (VoiceService STT, clients WS, commandes, transcription broadcast)
- `test_voice_04.py` : ✅ VOICE-04 — 34 tests (PiperTTSEngine, SynthesisResult, _apply_volume, _pcm_duration_ms)
- `test_voice_05.py` : ✅ VOICE-05 — 37 tests (KokoroTTSEngine, _float32_to_int16, load/synthesize)
- `test_voice_06.py` : ✅ VOICE-06 — 56 tests (split_sentences, iter_sentences, flush_partial, TTSService)
- VOICE-07/08/09/10 : UI Electron uniquement — pas de tests Python associés

### VOICE-10 — TERMINÉ (2026-04-30)
Fichiers modifiés :
- `ui/src/components/SettingsModal.tsx` : section `🎤 Voix` était **déjà présente** depuis VOICE-09 (diagnostic préliminaire vérifié)
- `ui/src/components/ChatPanel.tsx` : `useEffect` raccourci `Alt+V` ajouté — guard `sttEnabled`, dep `[sttEnabled, toggleListening]`, cleanup `removeEventListener`


### VOICE-00 — TERMINÉ (2026-04-25)
Fichiers créés :
- `Voice/voice_types.py` (15.3 KB) — 7 enums, 3 messages WS, 6 dataclasses config hiérarchiques, `load_voice_config()` (tomllib 3.11 stdlib), `VRAMInfo` + `query_vram()` + `resolve_stt_device()` + `resolve_tts_engine()`, `BeepSpec` + `BEEP_START`/`BEEP_STOP`
- `Voice/voice_config.toml` (1.2 KB) — config complète avec toutes décisions validées
- `Voice/models/stt/`, `Voice/models/tts/piper/`, `Voice/models/tts/kokoro/` — dossiers créés
- `tests/test_voice_00.py` — 9 classes, ~35 assertions

### VOICE-01 — TERMINÉ (2026-04-25)
Fichiers créés :
- `Voice/voice_capture.py` (11.3 KB) — `VoiceCapture` : VAD injectable, machine à états IDLE↔SPEECH, pre-speech buffer (ring deque), silence threshold 800ms, max utterance 30s, callback `on_utterance`, stats session, thread-safe via `_lock_instance` (instance, pas classe)
- `CaptureResult` : `pcm_bytes`, `duration_ms`, `num_samples`, `to_dict()`
- `_DummyVad` fallback si webrtcvad absent
- `make_silent_chunk()` / `make_speech_chunk()` helpers test
- `tests/test_voice_01.py` — 10 classes, ~35 tests

Patterns Voice-01 importants :
- `_vad_factory=lambda agg: _FakeVad(seq)` dans les tests (pas de patch global)
- `_FakeVad(sequence, default)` : rejoue le dernier `default` quand liste épuisée
- `_lock_instance` : `threading.Lock()` en attribut d'**instance** (règle LCCA)
- Import `webrtcvad` tardif dans `__init__` (pas au niveau module) → testable sans le package
- `stop()` flush l'utterance en cours si buffer non vide
- Chunks de mauvaise taille ignorés silencieusement (pas comptés dans `total_chunks`)

## ROUTER-01 — MODEL ROUTER (2026-04-25) ✅
Fichier existant documenté + tests créés :
- `core/model_router.py` (~7 KB) — `ModelRouter` + `ModelDecision` dataclass
  - `get_model(task_type, complexity_score, api_key)` → `ModelDecision`
  - Normalisation score 0-100 → 0-10 (accepte les deux ranges)
  - Routing : local_default → heavy_local (score≥5) → online (score≥6 + clé API)
  - Tâche `debug` : bypass vers OLLAMA_MODEL_DEBUG ou OLLAMA_MODEL_HEAVY
  - `list_available_online()` : providers avec online=True (sans clés)
  - `reload_config()` : hotreload online_models.json sans redémarrage
  - Fallback dégradé silencieux : JSON absent/invalide → routing.enabled=False
  - `_cfg_read(key)` : lit config.py sans lever d'exception
- `tests/test_model_router.py` (~55 tests, 13 classes) — créé 2026-04-25
  - TestModelDecision | TestLoadConfig | TestReloadConfig | TestListAvailableOnline
  - TestGetModelRoutingDisabled | TestGetModelDebugTask | TestScoreNormalization
  - TestGetModelHeavyLocal | TestGetModelOnline | TestOnlineFallback
  - TestLocalDefault | TestCfgRead | TestRealConfig (smoke avec online_models.json réel)

Invariants ModelRouter :
- Ne modifie jamais config.py ni online_models.json
- Les clés API arrivent en paramètre — jamais lues depuis le disque ici
- 0 exception levée (fallback silencieux dans tous les cas d'erreur)
- online=False dans le JSON → provider jamais appelé
- Pas de clé API → fallback local silencieux

## MEDIBOT — MODULE AMC (état 2026-05-02)

### Architecture AMC
```
D:\MediBot\AMC\                        # App ETL autonome
├── etl_amc.py                           # Orchestrateur (organismes | taux | medications | all)
├── config.py                            # DSN_MEDIBOT + DSN_MEDOCSDB
├── scrapers/
│   ├── scraper_acaps.py                 # AMC-MIG-00 ✅ -- 25 organismes seed statique
│   ├── scraper_anam.py                  # AMC-MIG-00 ✅ -- 13 taux TNR seed statique
│   ├── scraper_cnops.py                 # AMC-MIG-01 ✅ -- 3 taux legacy CNOPS
│   ├── scraper_medicament_ma.py         # AMC-MIG-01 ✅ -- 4 catégories médicaments
│   ├── scrapers_all.py                  # AMC-MIG-01 ✅ -- runner asyncio.gather (4 scrapers)
│   └── __init__.py                      # 9 exports
├── loaders/
│   ├── loader_organismes.py             # → medibot.amc_organismes
│   ├── loader_taux.py                   # → medibot.amc_taux
│   └── loader_medications.py            # → medocsdb.medications
D:\MediBot\backend\                    # FastAPI backend
├── models/amc.py                        # AMC-MIG-02 ✅ -- ORM 4 tables
└── services/amc_service.py              # AMC-MIG-02 ✅ -- service métier + calcul_ticket
```

### Tables AMC en DB (medibot port 5433)
| Table | Lignes | Statut |
|-------|--------|--------|
| `amc_organismes` | 25 (24 actifs + 1 CNOPS legacy) | ✅ |
| `amc_taux` | 13 | ✅ |
| `amc_reseau` | 0 | vide (AMC-MIG-03+) |
| `patient_couverture` | 0 | vide (AMC-MIG-03+) |

### Règles AMC invariantes (rappel)
- **AMC-04** : CNOPS actif=False, conserver jusqu'à 2027-06-01, ne jamais supprimer
- **AMC-11** : `remb_amo + remb_amc <= tarif_reel` — guard dans `calcul_ticket()`, plafonner silencieusement
- **AMC-12** : seuls les organismes agréés ACAPS dans `amc_organismes`
- **AMC-14** : AFMA jamais inséré (courtier, pas assureur)
- **AMC-16** : `base_amo = min(tarif_reel, tnr)` — toujours
- Formule AMC : `remb_amc = max(0, base_amc * taux% - remb_amo)` (AMC couvre le solde post-AMO)
- `calcul_ticket()` : 0 exception levée — toujours retourne un `TicketResult` (mode dégradé si pas de taux)

### Prochains sprints AMC
- **AMC-MIG-03** : intégration `amc_service` dans `consultation_billing` (calcul ticket en facturation)
  ou `chat.py` (collecte couverture AMC via WhatsApp)
- **AMC-MIG-04** : router REST `/amc` (GET organismes actifs, POST couverture patient, GET ticket)

---

## CONVENTIONS PROJET
1. SmartPatcher retourne `str`, jamais n'écrit disque
2. max 3 fichiers/TX (`config.MAX_FILES_PER_TX`)
3. `safe_path()` obligatoire avant toute op disque MCP
4. Telemetry silencieuse — jamais bloquer le flux
5. Logs MCP sur stderr, JSON-RPC sur stdout
6. Spec non validée → jamais de génération de code
7. CognitivePatterns : classes injectables, jamais fonctions libres
