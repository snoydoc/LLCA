# Sprint V9-01-B — Tri-modèle adaptatif + LLMGeneratorPool
<!-- AI-READY | LCCA V9 | Sprint V9-01-B | Priorité P0 | Effort 1j -->

## Objectif

Créer un pool LRU de `LLMGenerator` (max 3 sur 24 Go) et router automatiquement
chaque tool MCP vers le modèle optimal (3b/7b/14b).

**Gain attendu** : `llm_chat` en ~20s (vs 60s), sans perte de qualité sur `generate_spec`.

## Prérequis

- V9-00 et V9-01-A terminés
- `qwen2.5-coder:3b` disponible dans Ollama

## Fichiers cibles

| # | Fichier | Opération |
|---|---------|-----------|
| 1 | `core/llm_generator_pool.py` | CREATE |
| 2 | `core/mcp_tool_handlers.py` | PATCH — `_get_generator(tool_name)` |
| 3 | `core/nl_parser.py` | PATCH — utiliser OLLAMA_MODEL_LIGHT |
| 4 | `tests/test_llm_generator_pool.py` | CREATE |
| 5 | `tests/test_mcp_tool_handlers.py` | PATCH — 3 tests |

## Spécification : `core/llm_generator_pool.py`

```python
# -*- coding: utf-8-sig -*-
"""
llm_generator_pool.py — Pool singleton LRU de LLMGenerator par modèle.
Garantit max LLM_POOL_MAX_LOADED modèles simultanément en RAM.
Silencieux : toute erreur → log.debug uniquement.
"""
from __future__ import annotations
import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.llm_generator import LLMGenerator

log = logging.getLogger("lcca.llm_pool")


class LLMGeneratorPool:
    """
    Pool singleton thread-safe de LLMGenerator.

    Politique d'éviction :
        LRU (Least Recently Used) — le modèle le moins récemment utilisé
        est déchargé quand on atteint MAX_LOADED.

    Usage :
        gen = LLMGeneratorPool.get("qwen2.5-coder:3b", timeout=90, max_tokens=512)
    """
    _instances : dict[str, "LLMGenerator"] = {}
    _last_used : dict[str, float]          = {}
    _lock      = threading.Lock()

    @classmethod
    def _max_loaded(cls) -> int:
        try:
            import config
            return getattr(config, "LLM_POOL_MAX_LOADED", 3)
        except ImportError:
            return 3

    @classmethod
    def get(
        cls,
        model      : str,
        timeout    : int = 90,
        max_tokens : int = 512,
    ) -> "LLMGenerator":
        """
        Retourne un LLMGenerator pour le modèle demandé.
        Crée une nouvelle instance si absente (avec éviction LRU si nécessaire).
        Thread-safe.
        """
        from core.llm_generator import LLMGenerator
        key = f"{model}:{timeout}:{max_tokens}"
        with cls._lock:
            if key not in cls._instances:
                cls._evict_if_needed()
                log.debug("LLMPool: loading model=%s", model)
                cls._instances[key] = LLMGenerator(
                    model=model, timeout=timeout, max_tokens=max_tokens
                )
            cls._last_used[key] = time.monotonic()
            return cls._instances[key]

    @classmethod
    def _evict_if_needed(cls) -> None:
        """Décharge le modèle LRU si on atteint la limite."""
        if len(cls._instances) < cls._max_loaded():
            return
        oldest = min(cls._last_used, key=cls._last_used.get)
        log.debug("LLMPool: evicting LRU=%s", oldest)
        cls._instances.pop(oldest, None)
        cls._last_used.pop(oldest, None)

    @classmethod
    def unload(cls, model: str) -> None:
        """Déchargement explicite d'un modèle (libère la référence Python)."""
        with cls._lock:
            keys = [k for k in cls._instances if k.startswith(f"{model}:")]
            for k in keys:
                cls._instances.pop(k, None)
                cls._last_used.pop(k, None)
                log.debug("LLMPool: unloaded model=%s key=%s", model, k)

    @classmethod
    def clear(cls) -> None:
        """Vide le pool entier."""
        with cls._lock:
            cls._instances.clear()
            cls._last_used.clear()

    @classmethod
    def status(cls) -> dict:
        """Retourne l'état du pool (debug/monitoring)."""
        with cls._lock:
            return {
                "loaded":     len(cls._instances),
                "max":        cls._max_loaded(),
                "models":     list(cls._instances.keys()),
                "last_used":  {k: time.monotonic() - v
                               for k, v in cls._last_used.items()},
            }

    @classmethod
    def health_check(cls) -> dict:
        """Teste la disponibilité d'Ollama."""
        try:
            loaded = list(cls._instances.values())
            if loaded:
                # Tester le modèle déjà chargé
                gen = loaded[0]
            else:
                import config
                model = getattr(config, "OLLAMA_MODEL_LIGHT", "qwen2.5-coder:3b")
                gen = cls.get(model, timeout=10, max_tokens=1)
            avail = getattr(gen.ollama, "is_available", lambda: True)()
            return {"healthy": bool(avail), "loaded": len(cls._instances)}
        except Exception as exc:
            return {"healthy": False, "error": str(exc), "loaded": len(cls._instances)}
```

## Spécification : `mcp_tool_handlers.py` — `_get_generator`

Remplacer toutes les instanciations directes `LLMGenerator()` par `_get_generator(tool_name)` :

```python
# Ajouter en tête du fichier (après les imports existants)
from core.llm_generator_pool import LLMGeneratorPool

_COMPLEXITY_LIGHT  = "light"
_COMPLEXITY_MEDIUM = "medium"
_COMPLEXITY_HEAVY  = "heavy"

_TOOL_COMPLEXITY: dict[str, str] = {
    "llm_chat":          _COMPLEXITY_LIGHT,
    "memory_search":     _COMPLEXITY_LIGHT,
    "memory_store":      _COMPLEXITY_LIGHT,
    "project_search":    _COMPLEXITY_LIGHT,
    "web_cache_stats":   _COMPLEXITY_LIGHT,
    "get_analytics":     _COMPLEXITY_LIGHT,
    "analyze_error":     _COMPLEXITY_MEDIUM,
    "evaluate_quality":  _COMPLEXITY_MEDIUM,
    "sandbox_run":       _COMPLEXITY_MEDIUM,
    "edit_batch":        _COMPLEXITY_MEDIUM,
    "web_search":        _COMPLEXITY_MEDIUM,
    "generate_spec":     _COMPLEXITY_HEAVY,
    "validate_spec":     _COMPLEXITY_HEAVY,
}

def _get_generator(tool_name: str = "llm_chat") -> "LLMGenerator":
    """
    Retourne un LLMGenerator du pool avec le bon modèle selon la complexité.
    Silencieux : fallback sur modèle moyen si OLLAMA_MODEL_LIGHT absent.
    """
    import config
    complexity = _TOOL_COMPLEXITY.get(tool_name, _COMPLEXITY_MEDIUM)
    if complexity == _COMPLEXITY_LIGHT:
        model      = getattr(config, "OLLAMA_MODEL_LIGHT", config.OLLAMA_MODEL)
        timeout    = 90
        max_tokens = getattr(config, "NL_MAX_TOKENS", 512)
    elif complexity == _COMPLEXITY_HEAVY:
        model      = config.OLLAMA_MODEL_HEAVY
        timeout    = getattr(config, "SPEC_TIMEOUT", 360)
        max_tokens = getattr(config, "SPEC_MAX_TOKENS", 1500)
    else:
        model      = config.OLLAMA_MODEL
        timeout    = config.OLLAMA_TIMEOUT
        max_tokens = config.OLLAMA_MAX_TOKENS
    return LLMGeneratorPool.get(model, timeout=timeout, max_tokens=max_tokens)
```

**Remplacer dans chaque handler** :
- `LLMGenerator()` → `_get_generator("llm_chat")`
- `_get_spec_generator()` → conserver pour rétrocompat, le faire utiliser `_get_generator("generate_spec")`

## Tests `tests/test_llm_generator_pool.py`

```python
# -*- coding: utf-8-sig -*-
"""Tests pour LLMGeneratorPool — Sprint V9-01-B."""
from unittest.mock import MagicMock, patch
import pytest
from core.llm_generator_pool import LLMGeneratorPool


@pytest.fixture(autouse=True)
def clear_pool():
    LLMGeneratorPool.clear()
    yield
    LLMGeneratorPool.clear()


class TestPoolEviction:
    def test_pool_limit_max_3(self, monkeypatch):
        """3 modèles chargés → le 4ème évince le LRU."""
        import config
        monkeypatch.setattr(config, "LLM_POOL_MAX_LOADED", 3)
        with patch("core.llm_generator_pool.LLMGenerator") as MockGen:
            MockGen.side_effect = lambda **kw: MagicMock()
            LLMGeneratorPool.get("model-a", 60, 512)
            LLMGeneratorPool.get("model-b", 60, 512)
            LLMGeneratorPool.get("model-c", 60, 512)
            assert len(LLMGeneratorPool._instances) == 3
            LLMGeneratorPool.get("model-d", 60, 512)
            assert len(LLMGeneratorPool._instances) == 3
            # model-a (LRU) a été évincé
            assert not any("model-a" in k for k in LLMGeneratorPool._instances)

    def test_lru_order_respected(self, monkeypatch):
        """Le modèle le moins récemment utilisé est évincé."""
        import config, time
        monkeypatch.setattr(config, "LLM_POOL_MAX_LOADED", 2)
        with patch("core.llm_generator_pool.LLMGenerator") as MockGen:
            MockGen.side_effect = lambda **kw: MagicMock()
            LLMGeneratorPool.get("model-a", 60, 512)
            time.sleep(0.01)
            LLMGeneratorPool.get("model-b", 60, 512)
            time.sleep(0.01)
            LLMGeneratorPool.get("model-a", 60, 512)   # rafraîchit model-a
            time.sleep(0.01)
            LLMGeneratorPool.get("model-c", 60, 512)   # évince model-b (LRU)
            keys = list(LLMGeneratorPool._instances.keys())
            assert any("model-a" in k for k in keys)
            assert not any("model-b" in k for k in keys)


class TestPoolUnload:
    def test_unload_removes_model(self):
        with patch("core.llm_generator_pool.LLMGenerator") as MockGen:
            MockGen.side_effect = lambda **kw: MagicMock()
            LLMGeneratorPool.get("model-x", 60, 512)
            LLMGeneratorPool.unload("model-x")
            assert not any("model-x" in k for k in LLMGeneratorPool._instances)

    def test_unload_nonexistent_silent(self):
        LLMGeneratorPool.unload("does-not-exist")   # pas de raise


class TestGetGenerator:
    def test_light_tool_uses_light_model(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "OLLAMA_MODEL_LIGHT", "qwen:3b")
        with patch("core.llm_generator_pool.LLMGenerator") as MockGen:
            MockGen.side_effect = lambda **kw: MagicMock()
            from core.mcp_tool_handlers import _get_generator
            gen = _get_generator("llm_chat")
            call_kwargs = MockGen.call_args[1]
            assert call_kwargs.get("model") == "qwen:3b"

    def test_heavy_tool_uses_heavy_model(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "OLLAMA_MODEL_HEAVY", "qwen:14b")
        with patch("core.llm_generator_pool.LLMGenerator") as MockGen:
            MockGen.side_effect = lambda **kw: MagicMock()
            from core.mcp_tool_handlers import _get_generator
            _get_generator("generate_spec")
            call_kwargs = MockGen.call_args[1]
            assert call_kwargs.get("model") == "qwen:14b"

    def test_unknown_tool_uses_medium_model(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "OLLAMA_MODEL", "qwen:7b")
        with patch("core.llm_generator_pool.LLMGenerator") as MockGen:
            MockGen.side_effect = lambda **kw: MagicMock()
            from core.mcp_tool_handlers import _get_generator
            _get_generator("unknown_tool")
            call_kwargs = MockGen.call_args[1]
            assert call_kwargs.get("model") == "qwen:7b"
```

## Critères d'acceptation

- [ ] `LLMGeneratorPool.get("model", 60, 512)` retourne un `LLMGenerator`
- [ ] Le 4ème modèle évince le LRU si `LLM_POOL_MAX_LOADED=3`
- [ ] `unload("model")` silencieux si modèle absent
- [ ] `clear()` vide le pool sans erreur
- [ ] `_get_generator("llm_chat")` utilise OLLAMA_MODEL_LIGHT
- [ ] `_get_generator("generate_spec")` utilise OLLAMA_MODEL_HEAVY
- [ ] `_get_generator("unknown")` utilise OLLAMA_MODEL (medium)
- [ ] 0 régression sur tests V8

## Protocole d'exécution

```
1. filesystem:write_file core/llm_generator_pool.py
2. filesystem:read_text_file core/mcp_tool_handlers.py   → repérer les LLMGenerator()
3. filesystem:edit_file core/mcp_tool_handlers.py        → ajouter _TOOL_COMPLEXITY + _get_generator
4. filesystem:edit_file core/mcp_tool_handlers.py        → remplacer chaque LLMGenerator() par _get_generator(tool)
5. filesystem:read_text_file core/nl_parser.py           → repérer OLLAMA_MODEL usage
6. filesystem:edit_file core/nl_parser.py                → utiliser OLLAMA_MODEL_LIGHT
7. filesystem:write_file tests/test_llm_generator_pool.py
8. bash: python -c "from core.llm_generator_pool import LLMGeneratorPool; print('OK')"
9. bash: python -m pytest tests/test_llm_generator_pool.py -v
10. bash: python -m pytest tests/ -x -q
```

## Mise à jour skills

- **001** : pattern "LLMGeneratorPool LRU — _evict_if_needed, max 3 sur 24 Go"
- **003** : `core/llm_generator_pool.py` + `tests/test_llm_generator_pool.py`
- **004** : V9-01-B TERMINÉ
