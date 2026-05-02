# -*- coding: utf-8-sig -*-
"""
llm_config.py — REFACTO-11
Extrait de llm_generator.py : configuration Ollama + telemetrie.

Responsabilité unique : lecture de config, constantes par défaut, log_metric.
Importé par ollama_client, llm_generator et les helpers.
"""
from __future__ import annotations

from pathlib import Path

try:
    from utils.telemetry import log_metric as _log_metric
except Exception:
    def _log_metric(name, value, labels=None):  # type: ignore
        pass

# ── Valeurs par défaut ────────────────────────────────────────────────────────

DEFAULT_OLLAMA_URL  = "http://localhost:11434"
DEFAULT_MODEL       = "codellama"
DEFAULT_TIMEOUT     = None   # NO-TIMEOUT : None = urllib attend indéfiniment
DEFAULT_MAX_TOKENS  = 512
CACHE_DIR_FALLBACK  = Path(__file__).resolve().parent.parent / "transactions" / ".llm_cache"

# Alias privés préservés pour imports legacy (test_llm_generator.py)
_DEFAULT_OLLAMA_URL = DEFAULT_OLLAMA_URL
_DEFAULT_MODEL      = DEFAULT_MODEL
_DEFAULT_TIMEOUT    = DEFAULT_TIMEOUT
_DEFAULT_MAX_TOKENS = DEFAULT_MAX_TOKENS
_CACHE_DIR_FALLBACK = CACHE_DIR_FALLBACK


def cfg_available() -> bool:
    """Retourne True si le module config est importable."""
    try:
        import config  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


# Alias privé préservé pour imports legacy
_cfg_available = cfg_available


def cfg_read(key: str, default=None):
    """Lit une clé de config sans lever d'erreur si config absent."""
    try:
        import config  # type: ignore
        return getattr(config, key, default)
    except ImportError:
        return default


# Alias privé préservé pour imports legacy
_cfg_read = cfg_read


def load_config(model_override: str | None = None) -> dict:
    """
    Charge la configuration Ollama depuis config.py.
    V9-01-A : le modèle est utilisé tel quel (Ollama gère la quantification
    en interne via Modelfile — pas de renommage :7b -> :7b-Q4_K_M).
    """
    try:
        import config  # type: ignore
        model = model_override or getattr(config, "OLLAMA_MODEL", DEFAULT_MODEL)
        return {
            "url":        getattr(config, "OLLAMA_URL",        DEFAULT_OLLAMA_URL),
            "model":      model,
            "timeout":    getattr(config, "OLLAMA_TIMEOUT",    DEFAULT_TIMEOUT),
            "max_tokens": getattr(config, "OLLAMA_MAX_TOKENS", DEFAULT_MAX_TOKENS),
            "cache_dir":  getattr(config, "LLM_CACHE_DIR",     CACHE_DIR_FALLBACK),
        }
    except ImportError:
        return {
            "url":        DEFAULT_OLLAMA_URL,
            "model":      model_override or DEFAULT_MODEL,
            "timeout":    DEFAULT_TIMEOUT,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "cache_dir":  CACHE_DIR_FALLBACK,
        }


# Alias privé préservé pour imports legacy
_load_config = load_config
