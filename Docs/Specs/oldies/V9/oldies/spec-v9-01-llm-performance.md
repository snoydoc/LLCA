# Spec V9-01 — Optimisation des performances LLM (Qwen)
<!-- AI-READY | LCCA V9 | Performance LLM | Version 9.0.0-draft | 2026-04-20 -->

## Abstract

Réduire la latence perçue des appels Ollama de 40 à 70% sans perte de qualité, en exploitant
la quantification AWQ/GGUF Q4_K_M, un routage tri-modèle adaptatif (3b/7b/14b),
le streaming temps réel sur toutes les réponses, et le paramètre `keep_alive` Ollama.
Toutes les modifications sont dans `config.py`, `llm_generator.py` et `mcp_tool_handlers.py`.
Aucune interface publique n'est cassée.

---

## Sprint V9-01-A — Quantification Q4_K_M + keep_alive

### Contexte et motivations

`OllamaClient.generate()` appelle le modèle `qwen2.5-coder:7b` (~4GB RAM, ~4.5GB sur disque).
Sur P50 (CPU uniquement), une génération prend 60 secondes.
Deux optimisations orthogonales peuvent réduire ce temps :

1. **Quantification Q4_K_M** — le modèle GGUF quantifié 4-bit tient en ~2.5GB RAM,
   s'exécute 1.2-1.4x plus vite sur CPU (matrices plus petites → meilleur cache L2/L3).
   La perte de qualité sur HumanEval est < 1% selon les benchmarks Qwen2.5.

2. **`keep_alive`** — Ollama décharge le modèle de RAM après 5 minutes d'inactivité par défaut.
   Chaque rechargement prend 5-15s. En fixant `keep_alive=30m`, le modèle reste chaud.

### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `config.py` | PATCH — 3 nouvelles constantes |
| `core/llm_generator.py` | PATCH — `OllamaClient.generate()`, `chat()`, `chat_stream()`, `generate_stream()` |
| `tests/test_llm_generator.py` | PATCH — 2 nouveaux tests |

### Spécification : `config.py`

```python
# Après OLLAMA_MAX_TOKENS = 800 (ligne ~55)

# V9 — Quantification + keep_alive
OLLAMA_MODEL_LIGHT = "qwen2.5-coder:3b"          # V9-01-B
OLLAMA_KEEP_ALIVE  = "30m"                        # V9-01-A : modèle reste en RAM 30 min
OLLAMA_QUANTIZED   = True                         # V9-01-A : utiliser le modèle Q4_K_M si dispo
# NOTE : qwen2.5-coder:7b-q4_K_M doit être pullé manuellement :
#   ollama pull qwen2.5-coder:7b-q4_K_M
#   ollama pull qwen2.5-coder:14b-q4_K_M
```

### Spécification : `OllamaClient` — ajout `keep_alive`

Chaque méthode publique (`generate`, `chat`, `chat_stream`, `generate_stream`) doit inclure
le champ `"keep_alive"` dans son payload JSON.

```python
# Dans OllamaClient.__init__ — ajouter le paramètre
def __init__(self, base_url: str, model: str, timeout: int, max_tokens: int,
             keep_alive: str = "5m") -> None:
    ...
    self.keep_alive = keep_alive

# Dans generate() — ajouter au payload
payload = {
    "model":      self.model,
    "prompt":     prompt,
    "stream":     True,
    "keep_alive": self.keep_alive,          # V9-01-A
    "options":    {"num_predict": self.max_tokens},
}

# Identique pour chat(), chat_stream(), generate_stream()
```

### Spécification : `LLMGenerator.__init__` — propagation keep_alive

```python
def __init__(
    self,
    ollama_url:  Optional[str]  = None,
    model:       Optional[str]  = None,
    timeout:     Optional[int]  = None,
    max_tokens:  Optional[int]  = None,
    cache_dir:   Optional[Path] = None,
    keep_alive:  Optional[str]  = None,   # V9-01-A — nouveau paramètre
) -> None:
    cfg = _load_config(model_override=model)
    _keep_alive = keep_alive or getattr(config, "OLLAMA_KEEP_ALIVE", "5m")
    self.ollama = OllamaClient(
        base_url   = ollama_url or cfg["url"],
        model      = cfg["model"],
        timeout    = timeout    or cfg["timeout"],
        max_tokens = max_tokens or cfg["max_tokens"],
        keep_alive = _keep_alive,          # V9-01-A
    )
    ...
```

### Spécification : `_load_config` — modèle quantifié

```python
def _load_config(model_override: str | None = None) -> dict:
    try:
        import config
        base_model = model_override or getattr(config, "OLLAMA_MODEL", _DEFAULT_MODEL)
        quantized  = getattr(config, "OLLAMA_QUANTIZED", False)
        if quantized and not model_override and not base_model.endswith("_K_M"):
            # Tenter le modèle quantifié, fallback sur base si absent
            model = base_model.replace(":7b", ":7b-q4_K_M").replace(":14b", ":14b-q4_K_M")
        else:
            model = base_model
        return {
            "url":        getattr(config, "OLLAMA_URL",        _DEFAULT_OLLAMA_URL),
            "model":      model,
            "timeout":    getattr(config, "OLLAMA_TIMEOUT",    _DEFAULT_TIMEOUT),
            "max_tokens": getattr(config, "OLLAMA_MAX_TOKENS", _DEFAULT_MAX_TOKENS),
            "cache_dir":  getattr(config, "LLM_CACHE_DIR",     _CACHE_DIR_FALLBACK),
        }
    except ImportError:
        ...
```

### Tests attendus

```python
class TestKeepAlive:
    def test_keep_alive_in_payload(self, mocker):
        """keep_alive est transmis dans le payload Ollama."""
        client = OllamaClient("http://localhost:11434", "qwen", 60, 512, keep_alive="30m")
        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value.__iter__ = lambda s: iter([
            json.dumps({"response": "ok", "done": True}).encode()
        ])
        client.generate("sys", "user")
        call_args = mock_urlopen.call_args[0][0]
        body = json.loads(call_args.data)
        assert body["keep_alive"] == "30m"

    def test_default_keep_alive_from_config(self, monkeypatch):
        """keep_alive = OLLAMA_KEEP_ALIVE si non spécifié."""
        monkeypatch.setattr(config, "OLLAMA_KEEP_ALIVE", "15m")
        gen = LLMGenerator()
        assert gen.ollama.keep_alive == "15m"
```

---

## Sprint V9-01-B — Tri-modèle adaptatif (3b / 7b / 14b)

### Contexte et motivations

`config.py` expose déjà `OLLAMA_MODEL` (7b) et `OLLAMA_MODEL_HEAVY` (14b) mais tous les appels
utilisent systématiquement 7b. L'analyse des tools MCP montre trois niveaux de complexité :

| Niveau | Tools | Modèle optimal |
|--------|-------|----------------|
| Léger | `llm_chat`, `memory_search`, NL parser | 3b (~20s CPU) |
| Moyen | `edit_batch`, `evaluate_quality`, `analyze_error`, `web_search` | 7b (~60s CPU) |
| Lourd | `generate_spec`, `validate_spec` | 14b (~180s CPU) |

### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `config.py` | PATCH — `OLLAMA_MODEL_LIGHT = "qwen2.5-coder:3b"` |
| `core/mcp_tool_handlers.py` | PATCH — `_get_generator(complexity)` helper |
| `core/nl_parser.py` | PATCH — utiliser `OLLAMA_MODEL_LIGHT` |
| `tests/test_mcp_tool_handlers.py` | PATCH — 3 nouveaux tests |

### Spécification : `mcp_tool_handlers.py` — helper `_get_generator`

```python
# Niveaux de complexité
_COMPLEXITY_LIGHT  = "light"
_COMPLEXITY_MEDIUM = "medium"
_COMPLEXITY_HEAVY  = "heavy"

# Mapping tool → complexité
_TOOL_COMPLEXITY: dict[str, str] = {
    "llm_chat":          _COMPLEXITY_LIGHT,
    "memory_search":     _COMPLEXITY_LIGHT,
    "memory_store":      _COMPLEXITY_LIGHT,
    "project_search":    _COMPLEXITY_LIGHT,
    "analyze_error":     _COMPLEXITY_MEDIUM,
    "evaluate_quality":  _COMPLEXITY_MEDIUM,
    "sandbox_run":       _COMPLEXITY_MEDIUM,
    "edit_batch":        _COMPLEXITY_MEDIUM,
    "web_search":        _COMPLEXITY_MEDIUM,
    "web_cache_stats":   _COMPLEXITY_LIGHT,
    "generate_spec":     _COMPLEXITY_HEAVY,
    "validate_spec":     _COMPLEXITY_HEAVY,
}

def _get_generator(tool_name: str = "llm_chat") -> "LLMGenerator":
    """
    Retourne un LLMGenerator avec le bon modèle selon la complexité du tool.
    Silencieux : si OLLAMA_MODEL_LIGHT absent, fallback sur OLLAMA_MODEL.
    """
    from core.llm_generator import LLMGenerator
    import config

    complexity = _TOOL_COMPLEXITY.get(tool_name, _COMPLEXITY_MEDIUM)

    if complexity == _COMPLEXITY_LIGHT:
        model = getattr(config, "OLLAMA_MODEL_LIGHT", config.OLLAMA_MODEL)
        timeout = 90
        max_tokens = config.NL_MAX_TOKENS
    elif complexity == _COMPLEXITY_HEAVY:
        model = config.OLLAMA_MODEL_HEAVY
        timeout = config.SPEC_TIMEOUT
        max_tokens = config.SPEC_MAX_TOKENS
    else:
        model = config.OLLAMA_MODEL
        timeout = config.OLLAMA_TIMEOUT
        max_tokens = config.OLLAMA_MAX_TOKENS

    return LLMGenerator(model=model, timeout=timeout, max_tokens=max_tokens)
```

### Préconditions et postconditions

- **Précondition** : `ollama pull qwen2.5-coder:3b` doit avoir été exécuté.
  Si le modèle est absent, Ollama retourne une erreur HTTP 404 → `ConnectionError` →
  `FallbackGenerator` prend le relais (comportement déjà en place).
- **Postcondition** : `llm_chat` répond en ~20s, `generate_spec` conserve son timeout 360s.

### Tests attendus

```python
class TestGetGenerator:
    def test_light_tool_uses_light_model(self):
        gen = _get_generator("llm_chat")
        assert gen.ollama.model == config.OLLAMA_MODEL_LIGHT or \
               gen.ollama.model == config.OLLAMA_MODEL  # fallback OK

    def test_heavy_tool_uses_heavy_model(self):
        gen = _get_generator("generate_spec")
        assert gen.ollama.model == config.OLLAMA_MODEL_HEAVY

    def test_unknown_tool_uses_medium_model(self):
        gen = _get_generator("unknown_tool_xyz")
        assert gen.ollama.model == config.OLLAMA_MODEL
```

---

## Sprint V9-01-C — Streaming universel (tous les tools LLM)

### Contexte et motivations

`OllamaClient.chat_stream()` et `generate_stream()` existent depuis UI-07 mais ne sont utilisés
que pour `llm_chat`. Tous les tools LLM qui prennent > 5s devraient streamer leurs tokens
pour éliminer le "loading spinner" statique.

### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `core/mcp_server.py` | PATCH — `_emit_token(token)` helper (déjà partiellement en place) |
| `core/cognitive_patterns.py` | PATCH — `_call_llm_stream(system, user, on_token)` |
| `core/spec_generator.py` | PATCH — passer `on_token` à `SpecDirectPattern.run()` |
| `ui/electron/mcp-bridge.ts` | VÉRIF — streaming déjà géré via `onToken` |

### Spécification : `CognitivePattern._call_llm_stream`

```python
def _call_llm_stream(
    self,
    system: str,
    user: str,
    on_token: "Callable[[str], None] | None" = None,
    timeout_override: "int | None" = None,
) -> str:
    """
    Variante streamée de _call_llm().
    Si on_token est None, se comporte comme _call_llm() (bloquant).
    Garantit toujours un retour str.
    """
    if on_token is None:
        return self._call_llm(system, user, timeout_override)

    if callable(getattr(self._generator, "ollama", None)):
        return ""  # safety

    ollama = self._generator.ollama
    if timeout_override is not None:
        orig = ollama.timeout
        ollama.timeout = timeout_override
    try:
        result = ollama.generate_stream(system, user, on_token)
        return result if isinstance(result, str) else ""
    except Exception:
        return self._call_llm(system, user, timeout_override)  # fallback bloquant
    finally:
        if timeout_override is not None:
            ollama.timeout = orig
```

### Règles invariantes concernées

- **Règle streaming** : `on_token` ne lève jamais — wrappé dans `try/except` dans `OllamaClient`
- **Règle fallback** : si `generate_stream` échoue, repli sur `generate` bloquant
- **Règle test** : les tests mockent `on_token` avec un `list.append` — pas de side effects
