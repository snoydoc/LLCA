# Spec 16 — Configuration & Utilitaires
> **Modules** : `config.py`, `utils/logger.py` | **Sprints** : 01–11 | **Statut** : ✅ VALIDÉ

---

## 1. config.py

### Rôle
Centralise tous les **paths absolus** et **constantes** du projet. Tout module qui a besoin d'un chemin doit l'importer depuis `config`, jamais le hardcoder.

### Contenu complet

```python
from pathlib import Path

# ── Paths principaux ──────────────────────────────────────────────────────
BASE_DIR         = Path("D:/LLMCodeAgent")
CORE_DIR         = BASE_DIR / "core"
WORKSPACE_DIR    = BASE_DIR / "workspace"
TRANSACTIONS_DIR = BASE_DIR / "transactions"
TESTS_DIR        = BASE_DIR / "tests"
UTILS_DIR        = BASE_DIR / "utils"
LOGS_DIR         = BASE_DIR / "logs"
DOCS_DIR         = BASE_DIR / "Docs"
SKILLS_DIR       = BASE_DIR / ".claude-skills"

# ── WAL ───────────────────────────────────────────────────────────────────
WAL_PATH = TRANSACTIONS_DIR / "wal.jsonl"

# ── Limites transactionnelles ─────────────────────────────────────────────
MAX_FILES_PER_TX    = 3        # Hard limit fichiers par TX
MAX_CONTEXT_TOKENS  = 8_000   # Budget fenêtre contexte LLM
MAX_LOG_SIZE_MB     = 10       # Seuil rotation logs

# ── Encodage Windows ──────────────────────────────────────────────────────
FILE_ENCODING = "utf-8-sig"    # BOM pour compatibilité Windows

# ── LLM / Ollama ──────────────────────────────────────────────────────────
OLLAMA_URL        = "http://localhost:11434"
OLLAMA_MODEL      = "qwen2.5-coder:14b"
NL_MODEL          = "qwen2.5-coder:14b"    # Analyse NL
OLLAMA_TIMEOUT    = 90                      # secondes (14B lent)
OLLAMA_MAX_TOKENS = 512                     # Génération code
NL_MAX_TOKENS     = 256                     # Analyse NL (JSON court)
LLM_CACHE_DIR     = TRANSACTIONS_DIR / ".llm_cache"

# ── Auto-création des dossiers critiques au démarrage ─────────────────────
for _dir in [WORKSPACE_DIR, TRANSACTIONS_DIR, LOGS_DIR, LLM_CACHE_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)
```

### Règles d'utilisation

| Règle | Détail |
|-------|--------|
| Import toujours `from config import X` | Jamais `import config; config.X` |
| Import tardif dans les méthodes | Pour éviter les imports circulaires (ex: `FileSelector.select()`) |
| `MAX_FILES_PER_TX` | Contrainte hard — ne jamais hardcoder `3` ailleurs |
| Paths Windows | Toujours `Path("D:/...")` (slashes forward) ou `Path(r"D:\...")` |
| Auto-création dossiers | Se fait à l'import de `config` → garanti avant tout usage |

---

## 2. utils/logger.py

### Rôle
Logger centralisé, coloré en console, rotatif sur fichier.

### `get_logger(name: str) → logging.Logger`

Retourne `logging.getLogger(f"lcca.{name}")` configuré une seule fois (idempotent via `if logger.handlers: return logger`).

### Configuration des handlers

| Handler | Niveau | Format | Destination |
|---------|--------|--------|-------------|
| Console (ColoredFormatter) | INFO+ | `HH:MM:SS [LEVEL] lcca.nom — message` | stdout |
| RotatingFileHandler | DEBUG+ | `YYYY-MM-DDTHH:MM:SS [LEVEL] lcca.nom — message` | `logs/lcca.log` |

### Rotation fichier
- `maxBytes = 10 MB`
- `backupCount = 5` (→ lcca.log, lcca.log.1, ..., lcca.log.5)
- Encoding: `utf-8`

### Couleurs console (ANSI)
```python
COLORS = {
    "DEBUG":    "\033[36m",   # Cyan
    "INFO":     "\033[32m",   # Vert
    "WARNING":  "\033[33m",   # Jaune
    "ERROR":    "\033[31m",   # Rouge
    "CRITICAL": "\033[35m",   # Magenta
}
```

### Usage dans les modules `core/`
```python
import logging
log = logging.getLogger("lcca.mon_module")
# Les handlers sont configurés par utils/logger.py ou par logging.basicConfig()
```

Les modules `core/` utilisent `logging.getLogger()` directement. `get_logger()` est pour les scripts CLI qui veulent les handlers complets (console + fichier).

---

## 3. Structure des logs

```
logs/
└── lcca.log          # Log principal (rotation auto à 10 MB)
    lcca.log.1        # Archives rotatives
    ...
    lcca.log.5
```

### Namespace des loggers

| Logger | Module |
|--------|--------|
| `lcca.transaction_manager` | `transaction_manager.py` |
| `lcca.ast_indexer` | `ast_indexer.py` |
| `lcca.orchestrator` | `orchestrator.py` |
| `lcca.llm_generator` | `llm_generator.py` |
| `lcca.nl_parser` | `nl_parser.py` |
| ... | ... |

---

## 4. Contraintes AI-Ready

- `config.py` créé les dossiers à l'import → aucun `mkdir()` dans les modules
- `utils/logger.py` idempotent → pas de handlers dupliqués si appelé plusieurs fois
- Tous les paths dans `config.py` utilisent `pathlib.Path` (jamais des strings)
- `FILE_ENCODING = "utf-8-sig"` : BOM obligatoire sur Windows pour les accents
- Niveau console = `INFO` (pas de DEBUG en prod, sauf `--verbose`)
