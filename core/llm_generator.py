# -*- coding: utf-8-sig -*-
"""
llm_generator.py — LCCA V5 Fusion — orchestration légère REFACTO-11

REFACTO-11 : 28.3 KB → < 10 KB
Avant : classe monolithique avec OllamaClient + PromptBuilder + CodeExtractor
        + FallbackGenerator + LLMGenerator + helpers config dans un seul fichier.
Après : chaque responsabilité dans son module, réexports rétrocompat ici.

Modules extraits :
  core.llm_config        — _load_config, _cfg_read, _cfg_available, constantes
  core.ollama_client     — OllamaClient (HTTP, generate, chat, stream, warmup)
  core.llm_prompt_builder — PromptBuilder
  core.llm_code_utils    — CodeExtractor + FallbackGenerator

Ce fichier conserve :
  - GenerationResult (dataclass)
  - LLMGenerator (cache + orchestration)
  - Réexports rétrocompat de tous les symboles publics

Interface inchangée — aucun import existant ne doit être modifié.

Sprint 09 — TASK-09-01
Sprint V7  — Cache versionné par modèle
Sprint 18  — generate_text() + documentation interface duale
UI-06      — /api/generate au lieu de /api/chat
NO-TIMEOUT — OLLAMA_TIMEOUT=None : attente infinie.
"""
from __future__ import annotations

import hashlib
import json
import logging
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Imports depuis les modules REFACTO-11 ─────────────────────────────────────
from core.llm_config import (
    load_config      as _load_config,
    cfg_read         as _cfg_read,
    cfg_available    as _cfg_available,
    DEFAULT_OLLAMA_URL  as _DEFAULT_OLLAMA_URL,
    DEFAULT_MODEL       as _DEFAULT_MODEL,
    DEFAULT_TIMEOUT     as _DEFAULT_TIMEOUT,
    DEFAULT_MAX_TOKENS  as _DEFAULT_MAX_TOKENS,
    CACHE_DIR_FALLBACK  as _CACHE_DIR_FALLBACK,
)
from core.ollama_client     import OllamaClient
from core.llm_prompt_builder import PromptBuilder
from core.llm_code_utils     import CodeExtractor, FallbackGenerator

log = logging.getLogger("lcca.llm_generator")

__all__ = [
    # Symboles propres
    "GenerationResult",
    "LLMGenerator",
    # Réexports rétrocompat
    "OllamaClient",
    "PromptBuilder",
    "CodeExtractor",
    "FallbackGenerator",
    "_load_config",
    "_cfg_read",
    "_cfg_available",
    "_DEFAULT_OLLAMA_URL",
    "_DEFAULT_MODEL",
    "_DEFAULT_TIMEOUT",
    "_DEFAULT_MAX_TOKENS",
    "_CACHE_DIR_FALLBACK",
]


@dataclass
class GenerationResult:
    code:          str
    model:         str
    from_cache:    bool
    from_fallback: bool
    prompt_tokens: int
    duration_ms:   int


class LLMGenerator:
    """
    Générateur de code Python via Ollama avec cache sur disque (V7).

    Interface HAUTE : generate(op, intent, context) -> GenerationResult
    Interface BASSE : generate_text(system, user) -> str

    NO-TIMEOUT : timeout=None transmis à OllamaClient -> urllib attend indéfiniment.
    """

    def __init__(
        self,
        ollama_url: Optional[str]  = None,
        model:      Optional[str]  = None,
        timeout:    Optional[int]  = None,
        max_tokens: Optional[int]  = None,
        cache_dir:  Optional[Path] = None,
        keep_alive: Optional[str]  = None,
    ) -> None:
        cfg = _load_config(model_override=model)
        resolved_timeout = timeout if timeout is not None else cfg["timeout"]
        _keep = keep_alive or (_cfg_read("OLLAMA_KEEP_ALIVE") or "5m")
        self.ollama    = OllamaClient(
            base_url   = ollama_url or cfg["url"],
            model      = cfg["model"],
            timeout    = resolved_timeout,
            max_tokens = max_tokens or cfg["max_tokens"],
            keep_alive = _keep,
        )
        self.builder   = PromptBuilder()
        self.extractor = CodeExtractor()
        self.fallback  = FallbackGenerator()
        self.cache_dir = Path(cache_dir or cfg["cache_dir"])
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        log.info(
            "LLMGenerator init -- model=%s url=%s timeout=%s cache=%s",
            self.ollama.model, self.ollama.base_url,
            "infini" if resolved_timeout is None else f"{resolved_timeout}s",
            self.cache_dir,
        )
        if _cfg_read("OLLAMA_WARMUP", False):
            self.ollama.warmup()

    def generate(
        self,
        op,
        intent,
        context: str = "",
        skill_context: str = "",
    ) -> GenerationResult:
        import time
        system, user = self.builder.build(op, intent, context, skill_context=skill_context)
        prompt_key   = self._cache_key(system, user, self.ollama.model)

        cached = self._cache_get(prompt_key)
        if cached is not None:
            log.debug("Cache hit: %s", prompt_key[:8])
            return GenerationResult(
                code=cached, model=self.ollama.model, from_cache=True,
                from_fallback=False, prompt_tokens=len(user) // 4, duration_ms=0,
            )

        t0 = time.monotonic()
        try:
            raw   = self.ollama.generate(system, user)
            code  = self.extractor.extract(raw)
            code  = self.extractor.sanitize(code)
            valid = self.extractor.is_valid_python(code)
            ms    = int((time.monotonic() - t0) * 1000)

            if not valid:
                log.warning("Code genere invalide — fallback stub")
                code = self.fallback.generate(op, intent)
                return GenerationResult(
                    code=code, model=self.ollama.model, from_cache=False,
                    from_fallback=True, prompt_tokens=len(user) // 4, duration_ms=ms,
                )

            self._cache_set(prompt_key, code)
            log.info("Code genere OK — model=%s ms=%d", self.ollama.model, ms)
            return GenerationResult(
                code=code, model=self.ollama.model, from_cache=False,
                from_fallback=False, prompt_tokens=len(user) // 4, duration_ms=ms,
            )

        except (ConnectionError, RuntimeError) as exc:
            ms   = int((time.monotonic() - t0) * 1000)
            log.warning("Ollama indisponible (%s) — fallback stub", exc)
            code = self.fallback.generate(op, intent)
            return GenerationResult(
                code=code, model="fallback", from_cache=False,
                from_fallback=True, prompt_tokens=len(user) // 4, duration_ms=ms,
            )

    def generate_text(self, system: str, user: str, model_override: Optional[str] = None) -> str:
        """
        Interface basse : appel direct Ollama sans cache.
        FL-02 : model_override optionnel — transmis a OllamaClient.generate(),
                local a l'appel, ne mute pas self.ollama.model.
        """
        try:
            return self.ollama.generate(system, user, model_override=model_override)
        except (ConnectionError, RuntimeError) as exc:
            log.warning("generate_text: Ollama indisponible (%s)", exc)
            return ""

    def is_available(self) -> bool:
        return self.ollama.is_available()

    def list_models(self) -> list[str]:
        try:
            url = f"{self.ollama.base_url}/api/tags"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    def _cache_key(self, system: str, user: str, model: str) -> str:
        payload = f"{model}\n{system}\n{user}"
        return hashlib.md5(payload.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.py"

    def _meta_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _cache_get(self, key: str) -> Optional[str]:
        cache_file = self._cache_path(key)
        meta_file  = self._meta_path(key)
        if not cache_file.exists():
            return None
        if meta_file.exists():
            try:
                meta         = json.loads(meta_file.read_text(encoding="utf-8"))
                cached_model = meta.get("model", "unknown")
                current      = self.ollama.model
                if cached_model == "unknown" and current != "unknown":
                    return None
                if cached_model != current:
                    return None
            except Exception:
                pass
        try:
            return cache_file.read_text(encoding="utf-8")
        except Exception:
            return None

    def _cache_set(self, key: str, code: str) -> None:
        try:
            self._cache_path(key).write_text(code, encoding="utf-8")
            meta = {
                "model":     self.ollama.model,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version":   "7.0",
            }
            self._meta_path(key).write_text(
                json.dumps(meta, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            log.warning("Cache write failed: %s", exc)

    def clear_cache(self) -> int:
        deleted = 0
        for pattern in ("*.py", "*.json"):
            for f in self.cache_dir.glob(pattern):
                try:
                    f.unlink()
                    deleted += 1
                except Exception:
                    pass
        log.info("Cache vide: %d fichier(s)", deleted)
        return deleted
