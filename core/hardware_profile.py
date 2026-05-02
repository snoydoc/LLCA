# -*- coding: utf-8-sig -*-
"""
hardware_profile.py -- Detection RAM et adaptation automatique des parametres V9.

Usage au demarrage de McpServer ou main.py :
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
    ollama_model      : str    # V9-01-B : modele principal selon tier VRAM


def detect_ram_gb() -> int:
    """Retourne la RAM disponible en Go. Retourne 16 si psutil absent."""
    try:
        import psutil
        return psutil.virtual_memory().total // (1024 ** 3)
    except Exception:
        return 16


def get_profile(ram_gb: int | None = None) -> HardwareProfile:
    """
    Retourne le profil materiel selon la RAM.

    Tiers :
        high : >= 32 Go -- pool 3 modeles, Q5_K_M, Kokoro, TTL 1h, GRPO opt
        mid  : >= 24 Go -- pool 3 modeles, Q4_K_M, Kokoro, TTL 1h
        low  : < 24 Go  -- pool 2 modeles, Q4_K_M, pyttsx3, TTL 5min
    """
    if ram_gb is None:
        ram_gb = detect_ram_gb()

    # V9-01-B : modele principal selon VRAM disponible
    # Quadro M2000M = 4 GB VRAM :
    #   qwen2.5-coder:3b  (~2.0 GB) -> 100% GPU, ~15 tok/s
    #   qwen2.5-coder:7b  (~4.4 GB) -> debordement CPU, ~11 tok/s
    # Seuil RAM ici = RAM systeme (pas VRAM), mais tier "low" = P50 16 Go
    # -> on assume 4 GB VRAM et on prefere le 3b pour full-GPU.
    _model_light = _cfg_read_safe("OLLAMA_MODEL_LIGHT", "qwen2.5-coder:3b")
    _model_main  = _cfg_read_safe("OLLAMA_MODEL",       "qwen2.5-coder:7b")

    if ram_gb >= 32:
        return HardwareProfile(
            ram_gb=ram_gb, tier="high",
            pool_max_loaded=3, quant_heavy="Q5_K_M",
            tts_default="kokoro", ast_cache_ttl=3600,
            grpo_experimental=True,
            ollama_model=_model_main,
        )
    elif ram_gb >= 24:
        return HardwareProfile(
            ram_gb=ram_gb, tier="mid",
            pool_max_loaded=3, quant_heavy="Q4_K_M",
            tts_default="kokoro", ast_cache_ttl=3600,
            grpo_experimental=False,
            ollama_model=_model_main,
        )
    else:
        # low : <= 16 Go RAM (Lenovo P50) -> 4 GB VRAM -> 3b full-GPU
        return HardwareProfile(
            ram_gb=ram_gb, tier="low",
            pool_max_loaded=2, quant_heavy="Q4_K_M",
            tts_default="pyttsx3", ast_cache_ttl=300,
            grpo_experimental=False,
            ollama_model=_model_light,
        )


def _cfg_read_safe(key: str, default: str) -> str:
    """Lit une cle config sans lever d'erreur si config absent."""
    try:
        import config  # type: ignore
        return getattr(config, key, default)
    except Exception:
        return default


def apply_hardware_profile(ram_gb: int | None = None) -> HardwareProfile:
    """
    Detecte le profil et applique les overrides dans config.py au runtime.
    Silencieux : toute erreur -> profil non modifie.

    Returns:
        HardwareProfile applique.
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
        config.OLLAMA_MODEL              = profile["ollama_model"]  # V9-01-B
        config.NL_MODEL                  = profile["ollama_model"]  # V9-01-B
    except Exception as exc:
        log.debug("apply_hardware_profile: config patch failed: %s", exc)
    return profile
