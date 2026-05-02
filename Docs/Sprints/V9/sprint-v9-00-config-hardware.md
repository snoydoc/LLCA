# Sprint V9-00 — Config + Hardware Profile
<!-- AI-READY | LCCA V9 | Sprint V9-00 | Priorité P0 | Effort 0.5j -->

## Objectif

Poser toutes les nouvelles constantes V9 dans `config.py` et créer `core/hardware_profile.py`
pour une adaptation automatique selon la RAM disponible.
Ce sprint est un **prérequis bloquant** pour tous les autres sprints V9.

## Contexte

- `config.py` : 50+ constantes déjà présentes. Ajouter 25 nouvelles sans casser l'existant.
- `hardware_profile.py` : détection RAM via `psutil` → profil (low/mid/high) appliqué au démarrage.
- Aucune interface publique modifiée.

## Fichiers cibles

| # | Fichier | Opération | Lignes estimées |
|---|---------|-----------|-----------------|
| 1 | `config.py` | PATCH — 25 nouvelles constantes V9 | +40 lignes |
| 2 | `core/hardware_profile.py` | CREATE | ~80 lignes |
| 3 | `tests/test_hardware_profile.py` | CREATE | ~50 lignes |

## Spécification détaillée

### 1. `config.py` — nouvelles constantes

Ajouter à la fin de `config.py`, dans des sections commentées :

```python
# ═══════════════════════════════════════════════════════════════════════════
# V9 — Performance LLM
# ═══════════════════════════════════════════════════════════════════════════
OLLAMA_MODEL_LIGHT           = "qwen2.5-coder:3b"
OLLAMA_KEEP_ALIVE            = "30m"
OLLAMA_QUANTIZED             = True
OLLAMA_QUANT_LEVEL           = "Q4_K_M"       # "Q4_K_M" | "Q5_K_M"
OLLAMA_QUANT_LEVEL_HEAVY     = "Q4_K_M"       # Passer "Q5_K_M" si 32 Go
OLLAMA_THREADS               = 4
OLLAMA_NUM_GPU               = 0
OLLAMA_MMAP                  = True
LLM_POOL_MAX_LOADED          = 3              # 2 si < 24 Go
STREAM_BUFFER_SIZE           = 10
STREAM_THROTTLE_MS           = 50

# ═══════════════════════════════════════════════════════════════════════════
# V9 — Qualité LLM
# ═══════════════════════════════════════════════════════════════════════════
CORRECTION_LOOP_ENABLED      = False          # Opt-in — coûteux sur CPU
LLM_MAX_CORRECTION_RETRIES   = 2
LLM_GENERATION_MAX_TOTAL_SEC = 120
SPEC_AST_MAX_SYMBOLS         = 20

# ═══════════════════════════════════════════════════════════════════════════
# V9 — Agentic RAG
# ═══════════════════════════════════════════════════════════════════════════
REPO_RAG_MAX_FILES           = 5
REPO_RAG_MAX_LINES           = 80
AST_INDEX_CACHE_TTL          = 3600           # 300 si < 24 Go
ARCHITECT_WEB_SEARCH_ENABLED = True
MEMORY_HYDE_ENABLED          = False          # Opt-in

# ═══════════════════════════════════════════════════════════════════════════
# V9 — Training
# ═══════════════════════════════════════════════════════════════════════════
TRAINING_OUTPUT_DIR          = "training_data"
TRAINING_MIN_SCORE           = 70
TRAINING_MIN_PAIRS           = 50
GRPO_EXPERIMENTAL_ENABLED    = False          # V9.1 — nécessite 32 Go + nuit

# ═══════════════════════════════════════════════════════════════════════════
# V9 — Agents créatifs
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
# V9 — Transversal
# ═══════════════════════════════════════════════════════════════════════════
LCCA_SAFE_MODE               = True           # Désactive features lourdes
```

### 2. `core/hardware_profile.py` — CREATE

```python
# -*- coding: utf-8-sig -*-
"""
hardware_profile.py — Détection RAM et adaptation automatique des paramètres V9.

Usage au démarrage de McpServer ou main.py :
    from core.hardware_profile import apply_hardware_profile
    apply_hardware_profile()
"""
from __future__ import annotations
import logging
from typing import TypedDict

log = logging.getLogger("lcca.hardware_profile")


class HardwareProfile(TypedDict):
    ram_gb            : int
    tier              : str    # "low" | "mid" | "high"
    pool_max_loaded   : int
    quant_heavy       : str
    tts_default       : str
    ast_cache_ttl     : int
    grpo_experimental : bool


def detect_ram_gb() -> int:
    """Retourne la RAM disponible en Go. Retourne 16 si psutil absent."""
    try:
        import psutil
        return psutil.virtual_memory().total // (1024 ** 3)
    except Exception:
        return 16


def get_profile(ram_gb: int | None = None) -> HardwareProfile:
    """
    Retourne le profil matériel selon la RAM.

    Tiers :
        high : >= 32 Go — pool 3 modèles, Q5_K_M, Kokoro, TTL 1h, GRPO opt
        mid  : >= 24 Go — pool 3 modèles, Q4_K_M, Kokoro, TTL 1h
        low  : < 24 Go  — pool 2 modèles, Q4_K_M, pyttsx3, TTL 5min
    """
    if ram_gb is None:
        ram_gb = detect_ram_gb()

    if ram_gb >= 32:
        return HardwareProfile(
            ram_gb=ram_gb, tier="high",
            pool_max_loaded=3, quant_heavy="Q5_K_M",
            tts_default="kokoro", ast_cache_ttl=3600,
            grpo_experimental=True,
        )
    elif ram_gb >= 24:
        return HardwareProfile(
            ram_gb=ram_gb, tier="mid",
            pool_max_loaded=3, quant_heavy="Q4_K_M",
            tts_default="kokoro", ast_cache_ttl=3600,
            grpo_experimental=False,
        )
    else:
        return HardwareProfile(
            ram_gb=ram_gb, tier="low",
            pool_max_loaded=2, quant_heavy="Q4_K_M",
            tts_default="pyttsx3", ast_cache_ttl=300,
            grpo_experimental=False,
        )


def apply_hardware_profile(ram_gb: int | None = None) -> HardwareProfile:
    """
    Détecte le profil et applique les overrides dans config.py au runtime.
    Silencieux : toute erreur → profil non modifié.

    Returns:
        HardwareProfile appliqué.
    """
    profile = get_profile(ram_gb)
    log.info(
        "Hardware profile: tier=%s, ram=%dGo, pool_max=%d, tts=%s, cache_ttl=%ds",
        profile["tier"], profile["ram_gb"], profile["pool_max_loaded"],
        profile["tts_default"], profile["ast_cache_ttl"],
    )
    try:
        import config
        config.LLM_POOL_MAX_LOADED       = profile["pool_max_loaded"]
        config.OLLAMA_QUANT_LEVEL_HEAVY  = profile["quant_heavy"]
        config.TTS_ENGINE                = profile["tts_default"]
        config.AST_INDEX_CACHE_TTL       = profile["ast_cache_ttl"]
        config.GRPO_EXPERIMENTAL_ENABLED = profile["grpo_experimental"]
    except Exception as exc:
        log.debug("apply_hardware_profile: config patch failed: %s", exc)
    return profile
```

### 3. `tests/test_hardware_profile.py` — CREATE

```python
# -*- coding: utf-8-sig -*-
"""Tests test_hardware_profile.py — Sprint V9-00."""
import pytest
from core.hardware_profile import get_profile, apply_hardware_profile


class TestGetProfile:
    def test_high_tier_32gb(self):
        p = get_profile(32)
        assert p["tier"] == "high"
        assert p["pool_max_loaded"] == 3
        assert p["quant_heavy"] == "Q5_K_M"
        assert p["grpo_experimental"] is True

    def test_mid_tier_24gb(self):
        p = get_profile(24)
        assert p["tier"] == "mid"
        assert p["pool_max_loaded"] == 3
        assert p["tts_default"] == "kokoro"
        assert p["grpo_experimental"] is False

    def test_low_tier_16gb(self):
        p = get_profile(16)
        assert p["tier"] == "low"
        assert p["pool_max_loaded"] == 2
        assert p["tts_default"] == "pyttsx3"
        assert p["ast_cache_ttl"] == 300

    def test_apply_patches_config(self, monkeypatch):
        import config
        apply_hardware_profile(ram_gb=16)
        assert config.LLM_POOL_MAX_LOADED == 2
        # Restaurer
        apply_hardware_profile(ram_gb=24)
        assert config.LLM_POOL_MAX_LOADED == 3
```

## Critères d'acceptation

- [ ] `config.py` importe sans erreur après patch
- [ ] `get_profile(16)` → tier="low", pool=2, tts="pyttsx3"
- [ ] `get_profile(24)` → tier="mid", pool=3, tts="kokoro"
- [ ] `get_profile(32)` → tier="high", quant="Q5_K_M", grpo=True
- [ ] `apply_hardware_profile()` silencieux si `import config` échoue
- [ ] Tous les tests V8 existants toujours verts

## Protocole d'exécution

```
1. filesystem:read_text_file config.py  → vérifier fin du fichier
2. filesystem:edit_file config.py       → appender les constantes V9
3. filesystem:write_file core/hardware_profile.py
4. filesystem:write_file tests/test_hardware_profile.py
5. bash: python -c "import config; print('OK')"
6. bash: python -m pytest tests/test_hardware_profile.py -v
7. bash: python -m pytest tests/ -x -q  (régression globale)
```

## Dépendances à installer

```bash
pip install psutil --break-system-packages
```

## Mise à jour skills requise

En fin de sprint :
- **001** : pattern "Hardware profile V9-00 — get_profile(), apply_hardware_profile()"
- **003** : arborescence `core/hardware_profile.py` + `tests/test_hardware_profile.py`
- **004** : sprint V9-00 marqué TERMINÉ
