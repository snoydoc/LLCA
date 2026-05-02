# Spec 11 — LLMGenerator (Ollama + Cache + Fallback)
> **Module** : `core/llm_generator.py` | **Sprint** : 09 | **Statut** : ✅ VALIDÉ

---

## 1. Vue d'ensemble

`llm_generator.py` est la **couche de génération de code IA** de LCCA. Il remplace l'ancien `_generate_stub()` par une vraie génération via Ollama, avec cache disque et fallback garanti.

**Architecture en 5 composants :**

```
LLMGenerator (interface publique + cache disque)
    ├── PromptBuilder       — Construit les prompts (4 templates)
    ├── OllamaClient        — HTTP vers /api/chat (stdlib uniquement)
    ├── CodeExtractor       — Extrait + valide le code Python brut
    └── FallbackGenerator   — Stub minimal si Ollama indisponible
```

---

## 2. GenerationResult (dataclass)

```python
@dataclass
class GenerationResult:
    code:          str     # Code Python généré ou stub
    model:         str     # Modèle utilisé (ex: "qwen2.5-coder:14b" ou "fallback")
    from_cache:    bool    # True = répondu depuis cache disque
    from_fallback: bool    # True = Ollama indisponible → stub
    prompt_tokens: int     # Estimation tokens du prompt (len(user) // 4)
    duration_ms:   int     # Durée en ms (0 si cache hit)
```

---

## 3. PromptBuilder

### Templates disponibles
| `patch_type` / `action` | Template |
|-------------------------|----------|
| `action="create"` | Module complet (header utf-8-sig, docstring, imports, stub) |
| `patch_type="add_function"` | Définition de fonction seule |
| `patch_type="modify_function"` | Corps de fonction (sans def line) |
| `patch_type="add_import"` | Ligne d'import uniquement |

### Prompt système (invariant)
```
"You are LCCA, an expert Python code generator.
Generate ONLY valid Python code. No explanations, no markdown fences,
no comments except inline docstrings.
Follow PEP 8. Use type hints. Raise NotImplementedError if logic is unknown."
```

### `build(op, intent, context) → Tuple[str, str]`
Retourne `(system_prompt, user_prompt)`.

---

## 4. OllamaClient

```python
class OllamaClient:
    def __init__(self, base_url, model, timeout, max_tokens)
    def is_available(self) → bool   # GET /api/tags, timeout=3s
    def generate(system, user) → str   # POST /api/chat
```

**Format payload `/api/chat` :**
```json
{
    "model": "qwen2.5-coder:14b",
    "stream": false,
    "options": {"num_predict": 512, "temperature": 0.2, "top_p": 0.9},
    "messages": [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "..."}
    ]
}
```

**Règle absolue** : `urllib.request` uniquement. Jamais `requests` ou `httpx` dans `core/`.

**Exceptions levées :**
- `ConnectionError` : Ollama inaccessible
- `RuntimeError` : Réponse JSON malformée

---

## 5. CodeExtractor

### `extract(raw) → str`
Stratégie en cascade :
1. Cherche un bloc ` ```python ... ``` ` ou ` ``` ... ``` ` (regex `_FENCE_RE`)
2. Sinon : filtre les lignes commençant par `def`, `class`, `import`, `from`, `#`, `@`, etc.
3. Fallback : retourne le texte brut nettoyé

### `is_valid_python(code) → bool`
```python
compile(code, "<generated>", "exec")   # compile uniquement, sans exécution
```

### `sanitize(code) → str`
Supprime les balises résiduelles (` ``` `) et normalise les fins de ligne CRLF → LF.

---

## 6. FallbackGenerator

Génère un stub Python minimal **sans LLM**. Comportement identique à l'ancien `_generate_stub()` de Sprint 08.

| `action` / `patch_type` | Stub généré |
|------------------------|-------------|
| `"create"` | Module complet avec docstring + `def {symbol}(): raise NotImplementedError` |
| `"add_function"` | `def {symbol}(): raise NotImplementedError` |
| `"modify_function"` | Corps : `raise NotImplementedError('{symbol} — à modifier')` |
| `"add_import"` | `import {module}` |

---

## 7. LLMGenerator — Pipeline complet

```python
def generate(op, intent, context="") → GenerationResult:
    system, user = builder.build(op, intent, context)
    key = MD5(system + "\n" + user)

    # 1. Cache hit ?
    if cache_dir / f"{key}.py" existe:
        return GenerationResult(code=cached, from_cache=True, duration_ms=0)

    # 2. Appel Ollama
    try:
        raw = ollama.generate(system, user)
        code = extractor.extract(raw)
        code = extractor.sanitize(code)

        if not extractor.is_valid_python(code):
            return GenerationResult(code=fallback.generate(op, intent), from_fallback=True)

        cache_set(key, code)
        return GenerationResult(code=code, from_cache=False, from_fallback=False)

    except (ConnectionError, RuntimeError):
        return GenerationResult(code=fallback.generate(op, intent), from_fallback=True, model="fallback")
```

---

## 8. Cache disque

```
transactions/.llm_cache/
    {md5_hash}.py   # Code Python généré
```

| Méthode | Description |
|---------|-------------|
| `_cache_key(system, user) → str` | `MD5(system + "\n" + user).hexdigest()` |
| `_cache_get(key) → Optional[str]` | Lit `{key}.py` si existant |
| `_cache_set(key, code) → None` | Écrit `{key}.py` (silencieux si erreur) |
| `clear_cache() → int` | Supprime tous les `.py` du cache, retourne le nombre |

**Idempotence garantie** : même prompt → même hash → même fichier cache.

---

## 9. Configuration via `config.py`

```python
OLLAMA_URL        = "http://localhost:11434"
OLLAMA_MODEL      = "qwen2.5-coder:14b"    # Sprint 10
OLLAMA_TIMEOUT    = 90                      # 14B est plus lent
OLLAMA_MAX_TOKENS = 512
LLM_CACHE_DIR     = TRANSACTIONS_DIR / ".llm_cache"
```

`_load_config(model_override=None)` permet de surcharger le modèle programmatiquement.

---

## 10. Méthodes additionnelles

```python
def is_available(self) → bool          # Délègue à ollama.is_available()
def list_models(self) → list[str]      # GET /api/tags → liste des modèles
def clear_cache(self) → int            # Vide le cache
```

---

## 11. Règles AI-Ready

- **Jamais de crash** : `FallbackGenerator` garantit toujours un retour valide
- **Cache idempotent** : même entrée = même sortie (déterministe)
- **`_generate_stub()` deprecated** depuis Sprint 09 — délègue à `self.llm.fallback.generate()`
- **Injection LLM** : `LCCAV5Fusion.__init__(llm=None)` → si None, crée LLMGenerator par défaut
- **Tests** : toujours injecter `lcca.llm = MagicMock()` pour mocker Ollama (pas `_generate_stub`)
