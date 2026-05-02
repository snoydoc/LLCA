# Sprint V9-01-A — keep_alive + Quantification Q4_K_M
<!-- AI-READY | LCCA V9 | Sprint V9-01-A | Priorité P0 | Effort 0.5j -->

## Objectif

Réduire la latence Ollama de 30-40% sans perte de qualité en activant :
1. **`keep_alive=30m`** — modèle reste chaud en RAM entre les appels
2. **Q4_K_M GGUF** — matrices 4-bit → meilleur cache L2/L3 CPU → 1.3x plus rapide

## Prérequis

- Sprint V9-00 terminé (`config.py` patché)
- Modèles quantifiés disponibles localement :
  ```
  ollama pull qwen2.5-coder:3b
  ollama pull qwen2.5-coder:7b-q4_K_M
  ollama pull qwen2.5-coder:14b-q4_K_M
  ```

## Fichiers cibles

| # | Fichier | Opération |
|---|---------|-----------|
| 1 | `core/llm_generator.py` | PATCH — OllamaClient.__init__ + generate/chat/stream |
| 2 | `core/llm_generator.py` | PATCH — LLMGenerator.__init__ propagation keep_alive |
| 3 | `core/llm_generator.py` | PATCH — _load_config() sélection modèle quantifié |
| 4 | `tests/test_llm_generator.py` | PATCH — 2 nouveaux tests (classe TestKeepAlive) |

## Spécification détaillée

### Patch 1 : `OllamaClient.__init__`

Ajouter `keep_alive: str = "5m"` en paramètre, stocker dans `self.keep_alive`.

```python
# AVANT
def __init__(self, base_url: str, model: str, timeout: int, max_tokens: int) -> None:

# APRÈS
def __init__(
    self, base_url: str, model: str,
    timeout: int, max_tokens: int,
    keep_alive: str = "5m",
) -> None:
    ...
    self.keep_alive = keep_alive
```

### Patch 2 : Méthodes `generate`, `chat`, `chat_stream`, `generate_stream`

Dans chaque payload JSON, remplacer la section `"options"` :

```python
# AVANT
"options": {"num_predict": self.max_tokens},

# APRÈS
"keep_alive": self.keep_alive,
"options": {
    "num_predict": self.max_tokens,
    "num_thread":  getattr(config, "OLLAMA_THREADS", 4),
    "num_gpu":     getattr(config, "OLLAMA_NUM_GPU", 0),
    "use_mmap":    getattr(config, "OLLAMA_MMAP", True),
},
```

### Patch 3 : `LLMGenerator.__init__` — propagation

```python
def __init__(
    self,
    ollama_url : Optional[str]  = None,
    model      : Optional[str]  = None,
    timeout    : Optional[int]  = None,
    max_tokens : Optional[int]  = None,
    cache_dir  : Optional[Path] = None,
    keep_alive : Optional[str]  = None,  # V9-01-A
) -> None:
    cfg = _load_config(model_override=model)
    _keep = keep_alive or getattr(config, "OLLAMA_KEEP_ALIVE", "5m")
    self.ollama = OllamaClient(
        base_url   = ollama_url or cfg["url"],
        model      = cfg["model"],
        timeout    = timeout    or cfg["timeout"],
        max_tokens = max_tokens or cfg["max_tokens"],
        keep_alive = _keep,  # V9-01-A
    )
```

### Patch 4 : `_load_config` — sélection modèle quantifié

```python
def _load_config(model_override=None) -> dict:
    try:
        import config
        base = model_override or getattr(config, "OLLAMA_MODEL", _DEFAULT_MODEL)
        quantized = getattr(config, "OLLAMA_QUANTIZED", False)
        if quantized and not model_override and "_K_M" not in base:
            level = getattr(config, "OLLAMA_QUANT_LEVEL", "Q4_K_M")
            model = base.replace(":7b", f":7b-{level}").replace(":14b", f":14b-{level}")
        else:
            model = base
        return {
            "url":        getattr(config, "OLLAMA_URL",        _DEFAULT_OLLAMA_URL),
            "model":      model,
            "timeout":    getattr(config, "OLLAMA_TIMEOUT",    _DEFAULT_TIMEOUT),
            "max_tokens": getattr(config, "OLLAMA_MAX_TOKENS", _DEFAULT_MAX_TOKENS),
            "cache_dir":  getattr(config, "LLM_CACHE_DIR",     _CACHE_DIR_FALLBACK),
        }
    except ImportError:
        return { ... }  # fallback identique à l'existant
```

### Tests à ajouter : `class TestKeepAlive`

```python
class TestKeepAlive:
    def test_keep_alive_in_payload(self, mocker):
        """keep_alive est transmis dans le payload Ollama."""
        client = OllamaClient(
            "http://localhost:11434", "qwen", 60, 512, keep_alive="30m"
        )
        mock_urlopen = mocker.patch("urllib.request.urlopen")
        # ... setup mock context manager ...
        client.generate("sys", "user")
        call_args = mock_urlopen.call_args[0][0]
        body = json.loads(call_args.data)
        assert body["keep_alive"] == "30m"

    def test_default_keep_alive_from_config(self, monkeypatch):
        """keep_alive = OLLAMA_KEEP_ALIVE si non spécifié."""
        import config
        monkeypatch.setattr(config, "OLLAMA_KEEP_ALIVE", "15m")
        gen = LLMGenerator()
        assert gen.ollama.keep_alive == "15m"
```

## Critères d'acceptation

- [ ] `OllamaClient("...", "qwen", 60, 512, keep_alive="30m").keep_alive == "30m"`
- [ ] `LLMGenerator()` lit `OLLAMA_KEEP_ALIVE` depuis config
- [ ] `_load_config()` retourne `qwen2.5-coder:7b-q4_K_M` si `OLLAMA_QUANTIZED=True`
- [ ] `_load_config(model_override="custom")` ignore la quantification
- [ ] Payload JSON de `generate()` contient `"keep_alive"` et `"num_thread"`
- [ ] Tous les tests V8 existants toujours verts (0 régression)

## Protocole d'exécution

```
1. filesystem:read_text_file core/llm_generator.py  → repérer OllamaClient.__init__
2. filesystem:edit_file core/llm_generator.py       → patch __init__ (keep_alive param)
3. filesystem:edit_file core/llm_generator.py       → patch generate() options
4. filesystem:edit_file core/llm_generator.py       → patch chat() options
5. filesystem:edit_file core/llm_generator.py       → patch _load_config()
6. filesystem:edit_file core/llm_generator.py       → patch LLMGenerator.__init__
7. filesystem:read_text_file tests/test_llm_generator.py → repérer fin du fichier
8. filesystem:edit_file tests/test_llm_generator.py → ajouter TestKeepAlive
9. bash: python -c "from core.llm_generator import LLMGenerator; print('OK')"
10. bash: python -m pytest tests/test_llm_generator.py -v -k "TestKeepAlive"
11. bash: python -m pytest tests/ -x -q
```

## ⚠️ Points d'attention

- `generate_stream()` et `chat_stream()` ont leur propre payload → patcher les DEUX
- Ne pas casser `generate_text()` (interface CognitivePatterns, sans `op`/`intent`)
- `_load_config` : le remplacement `:7b` → `:7b-q4_K_M` ne doit pas affecter les modèles `:7b-instruct`
  → ajouter garde `if ":7b-instruct" not in base`

## Mise à jour skills

- **001** : pattern "V9-01-A — keep_alive dans payload + QUANT_LEVEL"
- **004** : V9-01-A TERMINÉ
