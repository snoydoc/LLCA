# Sprint 09 — LLM Code Generator (Ollama)

> **Statut** : ✅ IMPLÉMENTÉ — 2026-04-17  
> **Objectif** : Remplacer `_generate_stub()` (raise NotImplementedError) par un vrai générateur de code via Ollama local.

---

## 🎯 Motivation

Le cœur de LCCA V5 était complet sauf un point : la génération de code réel. `_generate_stub()` dans l'orchestrateur retournait `raise NotImplementedError`. Sprint 09 comble ce manque en branchant Ollama comme moteur LLM local, avec fallback stub si Ollama est indisponible.

---

## 📦 Fichiers modifiés

| Fichier | Action | Description |
|---------|--------|-------------|
| `core/llm_generator.py` | 🆕 CRÉÉ | LLMGenerator + OllamaClient + PromptBuilder + CodeExtractor + FallbackGenerator + cache disque |
| `core/orchestrator.py` | 🔧 MODIFIÉ | `_generate_stub()` → délègue à `LLMGenerator`, `execute()` lit le contexte existant |
| `core/__init__.py` | 🔧 MODIFIÉ | Exports Sprint 09 ajoutés |
| `config.py` | 🔧 MODIFIÉ | Constantes Ollama : `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT`, `OLLAMA_MAX_TOKENS`, `LLM_CACHE_DIR` |
| `tests/test_llm_generator.py` | 🆕 CRÉÉ | 26 tests mockés (Ollama non requis) |

---

## 🏗️ Architecture `LLMGenerator`

```
LLMGenerator.generate(op, intent, context)
    │
    ├─ PromptBuilder.build()      → (system, user) selon action/patch_type
    │       create          → _prompt_create()
    │       add_function    → _prompt_add_function()
    │       modify_function → _prompt_modify()
    │       add_import      → _prompt_import()
    │
    ├─ Cache disque (MD5 prompt → .py file)
    │       hit  → GenerationResult(from_cache=True)
    │       miss → OllamaClient.generate()
    │
    ├─ OllamaClient.generate()   → HTTP POST /api/chat (urllib stdlib, pas requests)
    │       OK   → CodeExtractor.extract() + sanitize() + is_valid_python()
    │       FAIL → FallbackGenerator.generate()
    │
    └─ GenerationResult(code, model, from_cache, from_fallback, prompt_tokens, duration_ms)
```

---

## ⚙️ Configuration (config.py)

```python
OLLAMA_URL        = "http://localhost:11434"
OLLAMA_MODEL      = "codellama"    # ou "qwen2.5-coder", "deepseek-coder"
OLLAMA_TIMEOUT    = 60             # secondes
OLLAMA_MAX_TOKENS = 512
LLM_CACHE_DIR     = TRANSACTIONS_DIR / ".llm_cache"
```

---

## 🔌 Installation Ollama (manuelle)

```powershell
# 1. Télécharger depuis https://ollama.ai
# 2. Installer et démarrer
ollama serve

# 3. Télécharger un modèle code
ollama pull codellama
# ou
ollama pull qwen2.5-coder:7b

# 4. Vérifier
curl http://localhost:11434/api/tags
```

---

## 🧪 Tests (26 tests, 0 Ollama requis)

```
TestCodeExtractor     (6)  : extract markdown/plain, is_valid_python, sanitize
TestPromptBuilder     (5)  : build create/add/modify/import, system prompt
TestFallbackGenerator (4)  : generate create/add_function/modify/import
TestOllamaClient      (4)  : is_available true/false, generate ok/bad_response
TestLLMGenerator      (5)  : fallback_unavailable, ollama_ok, cache_hit, invalid_python, clear_cache
```

---

## 🔄 Comportement runtime

| Situation | Résultat |
|-----------|----------|
| Ollama disponible, code valide | `GenerationResult(from_fallback=False, from_cache=False)` |
| Prompt déjà en cache | `GenerationResult(from_cache=True, duration_ms=0)` |
| Ollama indisponible | `GenerationResult(from_fallback=True, model="fallback")` |
| Code généré syntaxiquement invalide | `GenerationResult(from_fallback=True)` |

---

## 📝 Notes

- **Pas de dépendance externe** : `OllamaClient` utilise uniquement `urllib.request` (stdlib)
- **Cache idempotent** : même prompt → même fichier cache (MD5)
- **Rétrocompatibilité** : `_generate_stub()` existe toujours dans l'orchestrateur (délègue à `FallbackGenerator`)
- **`dry_run()` enrichi** : retourne `llm_available` en plus du plan
