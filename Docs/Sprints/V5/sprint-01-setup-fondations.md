# 🚀 Sprint 01 — Setup & Fondations

> **Durée estimée** : 5 jours  
> **Statut** : 🟡 EN COURS  
> **Priorité** : 🔴 Critique  
> **Objectif** : Mettre en place l'environnement, la structure de dossiers, le venv Python et les utilitaires de base.

---

## 🎯 Objectifs du Sprint

Ce sprint pose les bases sur lesquelles tous les autres sprints s'appuient. Rien ne peut être codé correctement sans un environnement stable et une arborescence conforme à la spec.

---

## 📋 Tâches

### TASK-01-01 — Création de la structure de dossiers
**Priorité** : 🔴 Critique  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Créer l'arborescence complète du projet conformément à la spec V5 Fusion.

**Critères d'acceptation** :
- [ ] `D:\LLMCodeAgent\core\` existe
- [ ] `D:\LLMCodeAgent\workspace\` existe
- [ ] `D:\LLMCodeAgent\transactions\` existe
- [ ] `D:\LLMCodeAgent\tests\` existe
- [ ] `D:\LLMCodeAgent\utils\` existe
- [ ] `D:\LLMCodeAgent\Docs\` existe avec `Specs\` et `Sprints\`

**Commande** :
```powershell
New-Item -ItemType Directory -Force -Path D:\LLMCodeAgent\core
New-Item -ItemType Directory -Force -Path D:\LLMCodeAgent\workspace
New-Item -ItemType Directory -Force -Path D:\LLMCodeAgent\transactions
New-Item -ItemType Directory -Force -Path D:\LLMCodeAgent\tests
New-Item -ItemType Directory -Force -Path D:\LLMCodeAgent\utils
```

---

### TASK-01-02 — Environnement Python (venv)
**Priorité** : 🔴 Critique  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Créer et configurer le venv Python 3.11+ avec toutes les dépendances.

**Critères d'acceptation** :
- [ ] Venv créé dans `D:\LLMCodeAgent\venv\`
- [ ] Python 3.11+ détecté dans le venv
- [ ] `requirements.txt` créé et validé
- [ ] Toutes les dépendances installables sans erreur

**Commandes** :
```powershell
# Créer le venv
python -m venv D:\LLMCodeAgent\venv

# Activer
D:\LLMCodeAgent\venv\Scripts\Activate.ps1

# Vérifier version
python --version  # doit afficher 3.11+
```

**Contenu `requirements.txt`** :
```
libcst>=1.1.0
chromadb>=0.4.0
pyyaml>=6.0
pytest>=7.0
black>=23.0
```

**Commande installation** :
```powershell
pip install -r requirements.txt
```

**Vérification** :
```powershell
python -c "import libcst; print('libcst OK:', libcst.__version__)"
python -c "import chromadb; print('chromadb OK:', chromadb.__version__)"
```

---

### TASK-01-03 — Fichiers `__init__.py`
**Priorité** : 🔴 Critique  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Créer tous les `__init__.py` qui font de `core/` et `utils/` des packages Python importables.

**Critères d'acceptation** :
- [ ] `D:\LLMCodeAgent\core\__init__.py` créé
- [ ] `D:\LLMCodeAgent\utils\__init__.py` créé
- [ ] `D:\LLMCodeAgent\tests\__init__.py` créé
- [ ] `from core.transaction_manager import TransactionManager` fonctionne (après Sprint 02)

**Contenu `core/__init__.py`** :
```python
"""
LCCA V5 Fusion - Core Package
Local Cognitive Coding Agency
"""

__version__ = "5.0.0"
__author__ = "LCCA"
```

---

### TASK-01-04 — Logger structuré (`utils/logger.py`)
**Priorité** : 🟠 Haute  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Créer un logger structuré centralisé utilisé par tous les modules core. Supporte les niveaux DEBUG, INFO, WARNING, ERROR, CRITICAL avec formatage coloré en console et fichier rotatif.

**Critères d'acceptation** :
- [ ] `utils/logger.py` créé et importable
- [ ] Sortie console colorée (DEBUG=cyan, INFO=vert, WARNING=jaune, ERROR=rouge)
- [ ] Sortie fichier dans `D:\LLMCodeAgent\logs\lcca.log`
- [ ] Rotation automatique à 10MB, 5 backups max
- [ ] Chaque log contient: timestamp ISO, niveau, module source, message
- [ ] Test unitaire `tests/test_logger.py` passe

**Fichier cible** : `utils/logger.py`

**Interface publique** :
```python
from utils.logger import get_logger

log = get_logger("transaction_manager")
log.info("Transaction BEGIN tx_abc123")
log.error("Rollback déclenché", extra={"tx_id": "abc123", "op": "write_file"})
log.debug("Snapshot MD5: a3f2b8")
```

**Implémentation** :
```python
"""
Logger structuré LCCA V5.
Centralisé, coloré, rotatif.
"""
import logging
import logging.handlers
from pathlib import Path
from datetime import datetime

LOG_DIR = Path("D:/LLMCodeAgent/logs")
LOG_DIR.mkdir(exist_ok=True)

COLORS = {
    "DEBUG": "\033[36m",     # Cyan
    "INFO": "\033[32m",      # Vert
    "WARNING": "\033[33m",   # Jaune
    "ERROR": "\033[31m",     # Rouge
    "CRITICAL": "\033[35m",  # Magenta
    "RESET": "\033[0m"
}


class ColoredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        color = COLORS.get(record.levelname, COLORS["RESET"])
        reset = COLORS["RESET"]
        msg = super().format(record)
        return f"{color}{msg}{reset}"


def get_logger(name: str) -> logging.Logger:
    """Retourne un logger nommé, configuré et prêt à l'emploi."""
    logger = logging.getLogger(f"lcca.{name}")

    if logger.handlers:
        return logger  # Déjà configuré

    logger.setLevel(logging.DEBUG)

    # Handler console coloré
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(ColoredFormatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S"
    ))

    # Handler fichier rotatif
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "lcca.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    ))

    logger.addHandler(console)
    logger.addHandler(file_handler)
    return logger
```

---

### TASK-01-05 — Configuration du projet (`config.py`)
**Priorité** : 🟠 Haute  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Créer un fichier de configuration centralisé pour tous les paths et constantes du projet. Évite les magic strings dispersées.

**Critères d'acceptation** :
- [ ] `D:\LLMCodeAgent\config.py` créé
- [ ] Tous les paths définis via `pathlib.Path`
- [ ] Lisible depuis n'importe quel module avec `from config import WORKSPACE_DIR`

**Contenu cible** :
```python
"""
Configuration centralisée LCCA V5 Fusion.
Tous les paths et constantes en un seul endroit.
"""
from pathlib import Path

# --- Paths principaux ---
BASE_DIR = Path("D:/LLMCodeAgent")
CORE_DIR = BASE_DIR / "core"
WORKSPACE_DIR = BASE_DIR / "workspace"
TRANSACTIONS_DIR = BASE_DIR / "transactions"
TESTS_DIR = BASE_DIR / "tests"
LOGS_DIR = BASE_DIR / "logs"
DOCS_DIR = BASE_DIR / "Docs"
SKILLS_DIR = BASE_DIR / ".claude-skills"

# --- WAL (Write-Ahead Log) ---
WAL_PATH = TRANSACTIONS_DIR / "wal.jsonl"

# --- MemPalace ---
MEMPALACE_PATH = Path("D:/MediBot/Mempalace")

# --- Limites ---
MAX_FILES_PER_TX = 3        # Max fichiers modifiables par transaction
MAX_CONTEXT_TOKENS = 8000   # Limite fenêtre contexte LLM
MAX_LOG_SIZE_MB = 10        # Rotation logs

# --- Encodage ---
FILE_ENCODING = "utf-8-sig"  # BOM pour Windows

# --- Assure l'existence des dossiers critiques ---
for _dir in [WORKSPACE_DIR, TRANSACTIONS_DIR, LOGS_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)
```

---

### TASK-01-06 — Test de smoke global
**Priorité** : 🟠 Haute  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Créer un script de smoke test qui valide que l'environnement est opérationnel avant de coder.

**Critères d'acceptation** :
- [ ] `tests/test_smoke.py` créé
- [ ] `pytest tests/test_smoke.py` passe avec 0 erreur
- [ ] Vérifie: version Python, imports, arborescence, encodage

**Contenu** :
```python
"""Smoke tests Sprint 01 — Validation environnement."""
import sys
import pytest
from pathlib import Path


def test_python_version():
    assert sys.version_info >= (3, 11), f"Python 3.11+ requis, trouvé {sys.version}"


def test_libcst_importable():
    import libcst
    assert libcst.__version__ >= "1.1.0"


def test_chromadb_importable():
    import chromadb
    assert chromadb is not None


def test_pyyaml_importable():
    import yaml
    assert yaml is not None


def test_directory_structure():
    base = Path("D:/LLMCodeAgent")
    dirs = ["core", "workspace", "transactions", "tests", "utils", "logs"]
    for d in dirs:
        assert (base / d).exists(), f"Dossier manquant: {base / d}"


def test_config_importable():
    from config import BASE_DIR, WORKSPACE_DIR, WAL_PATH
    assert BASE_DIR.exists()
    assert WORKSPACE_DIR.exists()


def test_logger_importable():
    from utils.logger import get_logger
    log = get_logger("test")
    log.info("Smoke test logger OK")
    assert log is not None
```

---

## 📊 Récapitulatif Sprint 01

| Task | Description | Effort | Statut |
|------|------------|--------|--------|
| TASK-01-01 | Structure dossiers | 0.5j | ⚪ |
| TASK-01-02 | Venv Python 3.11+ | 0.5j | ⚪ |
| TASK-01-03 | `__init__.py` packages | 0.5j | ⚪ |
| TASK-01-04 | Logger structuré | 1j | ⚪ |
| TASK-01-05 | Config centralisée | 0.5j | ⚪ |
| TASK-01-06 | Smoke tests | 0.5j | ⚪ |
| **TOTAL** | | **3.5j** | |

---

## ✅ Définition of Done (Sprint 01)

- [ ] `pytest tests/test_smoke.py` → 0 erreur
- [ ] `python -c "from utils.logger import get_logger"` → pas d'erreur
- [ ] `python -c "from config import WORKSPACE_DIR"` → pas d'erreur
- [ ] Tous les dossiers de l'arborescence existent
- [ ] `requirements.txt` committé et installable
- [ ] `004-sprint-context.md` mis à jour avec ce qui a été fait

---

## 🔗 Sprint suivant

➡️ [Sprint 02 — Transaction Manager ACID](sprint-02-transaction-manager.md)
