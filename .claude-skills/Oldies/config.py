"""
Configuration centralisee LCCA V5 Fusion.
Tous les paths et constantes en un seul endroit.
Importer avec : from config import BASE_DIR, WORKSPACE_DIR, ...
"""
import os as _os
from pathlib import Path

# ── Paths principaux ──────────────────────────────────────────────────────────
BASE_DIR         = Path("D:/LLMCodeAgent")
CORE_DIR         = BASE_DIR / "core"
WORKSPACE_DIR    = BASE_DIR / "workspace"
TRANSACTIONS_DIR = BASE_DIR / "transactions"
TESTS_DIR        = BASE_DIR / "tests"
UTILS_DIR        = BASE_DIR / "utils"
LOGS_DIR         = BASE_DIR / "logs"
DOCS_DIR         = BASE_DIR / "Docs"
SKILLS_DIR       = BASE_DIR / ".claude-skills"

# ── WAL (Write-Ahead Log) ─────────────────────────────────────────────────────
WAL_PATH = TRANSACTIONS_DIR / "wal.jsonl"

# ── Limites transactionnelles ─────────────────────────────────────────────────
MAX_FILES_PER_TX    = 3        # Max fichiers modifiables par transaction
MAX_CONTEXT_TOKENS  = 8_000   # Limite fenetre contexte LLM
MAX_LOG_SIZE_MB     = 10       # Seuil rotation logs

# ── Encodage Windows ──────────────────────────────────────────────────────────
FILE_ENCODING = "utf-8-sig"    # BOM pour compatibilite Windows

# ── LLM / Ollama ──────────────────────────────────────────────────────────────
OLLAMA_URL         = "http://localhost:11434"
OLLAMA_MODEL       = "qwen2.5-coder:3b"      # Benchmark 21/04/2026 -- 10.87 tok/s full VRAM (Quadro M2000M 4GB)
OLLAMA_MODEL_LIGHT = "qwen2.5-coder:3b"      # V9-01-B -- tier low (<24 Go RAM) -> full GPU
OLLAMA_MODEL_HEAVY = "qwen2.5-coder:14b"     # Sprint CTX-01 -- pour generate_spec + edit_batch (~10 GB RAM)
NL_MODEL           = "qwen2.5-coder:3b"      # meme modele pour NL
# Budget temps (P50, GPU Quadro M2000M 4 GB VRAM) :
#   Benchmark 21/04/2026 :
#     qwen2.5-coder:3b  (2.0 GB, full VRAM) : 10.87 tok/s  <- MODELE RETENU
#     qwen2.5-coder:7b  (4.7 GB, hybride)   :  4.01 tok/s  <- ECARTE (-63%)
#     llama3.2:3b GPU   (1.9 GB, full VRAM) : 11.34 tok/s  <- baseline
#     llama3.2:3b CPU                        :  8.03 tok/s  <- baseline CPU
#   qwen2.5-coder:14b : generation ~120-240s (hybride CPU+GPU)
#   web_search        : 3 fetch x 30s + synthese Ollama
#   generate_spec     : 1 appel LLM fusionne SPEC-01
#
# NOTE VRAM : Quadro M2000M = 4 GB VRAM
#   Modeles <= 3.5 GB (ex: qwen2.5-coder:3b 2.0 GB) -> 100% GPU -> ~11 tok/s
#   Modeles >  4 GB (ex: qwen2.5-coder:7b 4.7 GB) -> debordement CPU -> ~4 tok/s
#
# POLITIQUE TIMEOUT (Sprint NO-TIMEOUT) :
#   - OLLAMA_TIMEOUT  = None  -> urllib laisse le socket ouvert indefiniment
#     Justification : stream:True maintient le socket actif token par token.
#     Un timeout horloge ne protege pas contre un LLM lent -- il le tue.
#     Seul cas de coupure legitime : Ollama plante (plus aucun token -> EOF).
#   - SPEC_TIMEOUT    = None  -> meme raison, specs longues
OLLAMA_TIMEOUT    = None                      # Pas de timeout : le LLM prend le temps qu'il faut
SPEC_TIMEOUT      = None                      # Pas de timeout : idem pour la generation de specs
OLLAMA_MAX_TOKENS = 800                       # augmente : synthese web necessite ~600 tokens
SPEC_MAX_TOKENS   = 1500                      # spec complete 8 sections = 1200-1800 tokens
NL_MAX_TOKENS     = 256
LLM_CACHE_DIR     = TRANSACTIONS_DIR / ".llm_cache"
WEB_CACHE_DIR     = TRANSACTIONS_DIR / ".web_cache"  # WEB-02 + Audit 005 -- chemin centralise

# ── MIG-04 -- MemPalace local LLCA ────────────────────────────────────────────────────────────
PALACE_DIR        = BASE_DIR / "mempalace" / "palace"  # Palace autonome LLCA -- 0 dependance MediBot

# ── V7 -- MCP Server ──────────────────────────────────────────────────────────
MCP_SERVER_STDIO     = True
MCP_PROTOCOL_VERSION = "2024-11-05"

# ── V7 -- Sandbox ─────────────────────────────────────────────────────────────
SANDBOX_MODE         = _os.getenv("LCCA_SANDBOX_MODE", "auto")
SANDBOX_TIMEOUT      = int(_os.getenv("LCCA_SANDBOX_TIMEOUT", "30"))
SANDBOX_MEMORY_LIMIT = "512m"
SANDBOX_CPU_LIMIT    = 1.0

# ── V7 -- Memory collections ───────────────────────────────────────────────────
MCP_MEMORY_COLLECTIONS: dict = {
    "solutions": "lcca_solutions",
    "failures":  "lcca_failures",
    "context":   "lcca_context",
    "patches":   "lcca_patches",
}

# ── V7 -- Audit trail ─────────────────────────────────────────────────────────
MCP_AUDIT_LOG = TRANSACTIONS_DIR / "mcp_audit.jsonl"

# ── Sprint 14 -- Spec Layer ────────────────────────────────────────────────────
ADAPTIVE_SPEC_ENABLED        = True
SPEC_COMPLEXITY_THRESHOLD    = 60   # Score 0-100 : >= 60 -> spec obligatoire (Sprint 19 -- Dette 14)
SPEC_AUTO_FIX_MAX_ITERATIONS = 3
SPEC_RETRY_ON_FAIL           = True   # V9-09 -- generate_with_retry() : tente auto_fix si spec non usable
SPEC_MEMORY_COLLECTION       = "lcca_specs"
SPEC_STORAGE_DIR             = WORKSPACE_DIR / "specs"

# ── Sprint 20 -- Spec Layer V7.2 ───────────────────────────────────────────────
SPEC_DEFAULT_VERSION: str = "7.2.0"
SPEC_VALIDATOR_RULES: list = [
    "rule_1_smartpatcher_str",
    "rule_2_ast_read_libcst_write",
    "rule_3_max_files",
    "rule_4_snapshot_md5",
    "rule_5_wal_append_only",
    "rule_6_llm_fallback",
    "rule_7_dependency_injection",
    "rule_8_sys_executable",
    "rule_9_module_level_imports",
    "rule_10_utf8_sig",
    "rule_11_no_code_if_invalid_spec",
    "rule_12_complexity_first",
    "rule_13_spec_versioned",
    "rule_14_invalid_spec_stops",
    "rule_15_patterns_configurable",
]

# ── V8 -- Agents & A2A Bus ────────────────────────────────────────────────────
A2A_DB_PATH          = TRANSACTIONS_DIR / "a2a_bus.sqlite"
A2A_RECEIPTS_DIR     = BASE_DIR / "memory" / "receipts"
SECRET_DIR           = BASE_DIR / ".secret"

# ── V8 -- Agents comportement ─────────────────────────────────────────────────
AGENT_MIN_QUALITY_SCORE  = 70    # Seuil qualite pour stockage skill (TesterAgent)
AGENT_PIPELINE_TIMEOUT   = 3600  # 1h -- laisse le LLM terminer (modeles > 4 GB debordent sur CPU)
SKILL_MAX_BODY_LINES     = 20    # Max lignes affichees dans le prompt skill
SKILL_MAX_PER_PROMPT     = 3     # Max skills injectes par prompt

# ── V8 -- KarpathyLoop ────────────────────────────────────────────────────────
KARPATHY_MAX_ITERATIONS  = 20
KARPATHY_MAX_STAGNATION  = 3     # V8-Regle-18 : arret apres 3 iterations sans amelioration

# ═══════════════════════════════════════════════════════════════════════════
# V9 -- Performance LLM
# Benchmark 21/04/2026 : GPU Quadro M2000M (4 GB VRAM)
#   CPU  :  8.03 tok/s | GPU : 11.34 tok/s | Gain : +41%
#   Mode optimal : GPU (OLLAMA_NUM_GPU=99, CUDA_VISIBLE_DEVICES=0)
#   Script de demarrage : start-ollama.ps1 (mis a jour)
# ═══════════════════════════════════════════════════════════════════════════
OLLAMA_KEEP_ALIVE            = "30m"
OLLAMA_QUANTIZED             = True
OLLAMA_QUANT_LEVEL           = "Q4_K_M"       # "Q4_K_M" | "Q5_K_M"
OLLAMA_QUANT_LEVEL_HEAVY     = "Q4_K_M"       # Passer "Q5_K_M" si 32 Go
OLLAMA_THREADS               = 4
OLLAMA_NUM_GPU               = 99             # Benchmark : GPU +41% vs CPU -- Quadro M2000M 4 GB VRAM
OLLAMA_MMAP                  = True
LLM_POOL_MAX_LOADED          = 3              # 2 si < 24 Go
STREAM_BUFFER_SIZE           = 10
STREAM_THROTTLE_MS           = 50

# ═══════════════════════════════════════════════════════════════════════════
# V9 -- Qualite LLM
# ═══════════════════════════════════════════════════════════════════════════
CORRECTION_LOOP_ENABLED      = True           # Active : GPU rend les retries moins couteux
LLM_MAX_CORRECTION_RETRIES   = 2
LLM_GENERATION_MAX_TOTAL_SEC = 120
SPEC_AST_MAX_SYMBOLS         = 20

# ═══════════════════════════════════════════════════════════════════════════
# V9 -- Agentic RAG
# ═══════════════════════════════════════════════════════════════════════════
REPO_RAG_MAX_FILES           = 5
REPO_RAG_MAX_LINES           = 80
AST_INDEX_CACHE_TTL          = 3600           # 300 si < 24 Go
ARCHITECT_WEB_SEARCH_ENABLED = True
MEMORY_HYDE_ENABLED          = False          # Opt-in

# ═══════════════════════════════════════════════════════════════════════════
# V9 -- Training
# ═══════════════════════════════════════════════════════════════════════════
TRAINING_OUTPUT_DIR          = "training_data"
TRAINING_MIN_SCORE           = 70
TRAINING_MIN_PAIRS           = 50
GRPO_EXPERIMENTAL_ENABLED    = False          # V9.1 -- necessite 32 Go + nuit

# ═══════════════════════════════════════════════════════════════════════════
# V9 -- Agents creatifs
# ═══════════════════════════════════════════════════════════════════════════
QA_SCAN_INTERVAL_HOURS       = 24
QA_DEBT_THRESHOLD_WARN       = 7
QA_DEBT_THRESHOLD_CRIT       = 10
DOCAGENT_AUTO_CONFIRM        = False
HITL_ENABLED                 = False
EPISODIC_DB_PATH             = "memory/episodic.sqlite"
TTS_ENABLED                  = False
TTS_ENGINE                   = "kokoro"       # "pyttsx3" si < 24 Go
TTS_VOICE                    = "fr_f"

# ═══════════════════════════════════════════════════════════════════════════
# V9 -- Transversal
# ═══════════════════════════════════════════════════════════════════════════
LCCA_SAFE_MODE               = True           # Desactive features lourdes
OLLAMA_WARMUP                = True           # V9-06 : pre-charge le modele au demarrage (elimine cold start)

# ═══════════════════════════════════════════════════════════════════════════
# V9.1 -- EDUCATOR AGENT
# ═══════════════════════════════════════════════════════════════════════════
EDUCATOR_ENABLED              = False          # Opt-in explicite
EDUCATOR_DRY_RUN              = True           # Par defaut : ne pas ecrire en memoire
EDUCATOR_MAX_FILES_PER_REPO   = 30
EDUCATOR_MAX_SKILLS_PER_REPO  = 20
EDUCATOR_MIN_SCORE            = 70             # Score CodeEvaluator minimum
EDUCATOR_MIN_FILTER_SCORE     = 5              # Sur 7 regles LCCA
EDUCATOR_SLEEP_BETWEEN_REPOS  = 1.0            # Secondes -- rate limiting GitHub
EDUCATOR_FETCH_TIMEOUT        = 300            # Timeout global fetch (secondes)
EDUCATOR_CACHE_TTL_HOURS      = 24             # Cache licences et metadonnees
EDUCATOR_SKILL_DEPRECATION_DAYS = 30           # Jours sans usage -> deprecated
EDUCATOR_GITHUB_TOKEN         = ""             # Optionnel -- depasse 60 req/h si renseigne
EDUCATOR_STARS_THRESHOLD      = 1000           # Repos avec moins d'etoiles ignores
EDUCATOR_RETRY_MAX            = 3              # ED-02 -- Nombre de tentatives reseau avant abandon
EDUCATOR_HASH_PERSIST_PATH    = TRANSACTIONS_DIR / "educator_hashes.json"  # ED-02 -- Persistance dedup cross-session

# ── Assure l'existence des dossiers critiques au demarrage ────────────────────
for _dir in [WORKSPACE_DIR, TRANSACTIONS_DIR, LOGS_DIR, LLM_CACHE_DIR, PALACE_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)
