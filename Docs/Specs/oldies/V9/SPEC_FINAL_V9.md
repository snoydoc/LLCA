# LCCA V9 — Spécification Technique Finale Consolidée
<!-- AI-READY | LCCA V9 SPEC FINAL | Version 9.0.0-final | 2026-04-20 -->
<!-- Statut : VALIDÉE — Fusion Spec V9 Draft + Review Final + Addendum Hardware -->

**Auteur** : Synthèse automatique (Specs_LLCAV9.MD + Specs_LLCA_V9_Review_Final.md)
**Date** : 2026-04-20
**Machine cible** : Lenovo P50, 24 Go actuels → 32 Go prochainement, CPU uniquement, Windows 11
**Base V8** : 525 tests passing, 0 failed, architecture multi-agent KarpathyLoop opérationnelle

---

## Table des matières

1. [Contexte & État V8](#1-contexte--état-v8)
2. [Principes directeurs V9](#2-principes-directeurs-v9)
3. [Décisions architecturales consolidées](#3-décisions-architecturales-consolidées)
4. [Axe 1 — Performance LLM (V9-01)](#4-axe-1--performance-llm-v9-01)
5. [Axe 2 — Qualité des réponses (V9-02)](#5-axe-2--qualité-des-réponses-v9-02)
6. [Axe 3 — Agentic RAG (V9-03)](#6-axe-3--agentic-rag-v9-03)
7. [Axe 4 — Pipeline d'entraînement (V9-04)](#7-axe-4--pipeline-dentraînement-v9-04)
8. [Axe 5 — Agents créatifs (V9-05)](#8-axe-5--agents-créatifs-v9-05)
9. [Nouveaux fichiers à créer](#9-nouveaux-fichiers-à-créer)
10. [Patches config.py consolidés](#10-patches-configpy-consolidés)
11. [Tests requis V9](#11-tests-requis-v9)
12. [Priorités & roadmap](#12-priorités--roadmap)
13. [Checklist de validation finale](#13-checklist-de-validation-finale)

---

## 1. Contexte & État V8

### Architecture en place (ne pas casser)

```
core/
├── agents/
│   ├── a2a_bus.py          — A2ALocalBus SQLite3 ACID
│   ├── agent_card.py       — AgentCard + RecoveryPolicy
│   ├── base_agent.py       — BaseAgent ABC + AgentResult
│   ├── architect_agent.py  — Décomposition intent → TaskContracts
│   ├── coder_agent.py      — build_patch + edit_batch MCP
│   ├── reviewer_agent.py   — _check_syntax + forward tester/reject architect
│   ├── tester_agent.py     — sandbox + CodeEvaluator + HMAC receipt
│   ├── agent_orchestrator.py — KarpathyLoop (max 20 iter, stagnation=3)
│   └── observer_agent.py   — Déduplication skills + archivage receipts
├── memory_engine.py        — 6 collections ChromaDB (+ lcca_skills)
├── llm_generator.py        — LLMGenerator + OllamaClient + FallbackGenerator
├── web_search.py           — WebSearchEngine multi-moteurs
├── skill_library.py        — SkillLibrary (extraction + retrieval + format)
├── spec_generator.py       — SpecGeneratorService + SpecDirectPattern
├── spec_validator.py       — RULE_REGISTRY R01-R15
├── mcp_server.py           — JSON-RPC 2.0 stdio, 12 tools
└── ... (50 fichiers total)
```

### Stack LLM actuelle
- **Léger** : `qwen2.5-coder:7b` (~4.5 GB RAM, ~60s/gen CPU)
- **Lourd** : `qwen2.5-coder:14b` (~9 GB RAM, ~180s/gen CPU)
- **Nouveau V9** : `qwen2.5-coder:3b` (~2 GB RAM, ~20s/gen CPU)

### Contraintes matérielles confirmées
- **RAM actuelle** : 24 Go → 32 Go prochainement
- **CPU** : Lenovo P50, pas de GPU dédié
- **Ollama** : modèles chargés en RAM, déchargement après `keep_alive`
- **Windows 11** : encodage `utf-8-sig`, `sys.executable`, `pathlib.Path`

---

## 2. Principes directeurs V9

| # | Principe | Détail |
|---|----------|--------|
| P1 | **Pas de rupture de contrat** | Toute modification préserve les interfaces existantes |
| P2 | **Silencieux en cas d'échec** | Tout nouveau composant : `try/except Exception` global |
| P3 | **Testable dès la conception** | Chaque spec inclut fixtures et assertions |
| P4 | **CPU-first ajusté 24 Go** | 3 modèles simultanés, pas de fine-tuning local continu |
| P5 | **Incrémental** | Chaque sprint déployable indépendamment |
| P6 | **Safe Mode** | `LCCA_SAFE_MODE=True` désactive les features lourdes |
| P7 | **Opt-in pour les features coûteuses** | Boucle de correction, TTS, HyDE, GRPO |

---

## 3. Décisions architecturales consolidées

### 3.1 Tableau de décision final (après review + addendum hardware)

| Sous-sprint | Décision | Modifications vs. spec initiale |
|-------------|----------|---------------------------------|
| **V9-01-A** keep_alive + Q4_K_M | ✅ Implémenter tel quel | — |
| **V9-01-B** Tri-modèle + Pool | ✅ Implémenter avec LLMGeneratorPool LRU max **3** | max 2→3 (24 Go confortables) |
| **V9-01-C** Streaming universel | ✅ Implémenter + buffer/throttle optionnel | Ajout STREAM_BUFFER_SIZE + STREAM_THROTTLE_MS |
| **V9-02-A** Few-shot SkillLibrary | ✅ Implémenter tel quel | — |
| **V9-02-B** Boucle de correction | ✅ Implémenter, **CORRECTION_LOOP_ENABLED=False** par défaut | Flag opt-in + timeout global 120s |
| **V9-02-C** AST context SpecGenerator | ✅ Implémenter tel quel | — |
| **V9-02-D** JSON mode Ollama | ✅ Implémenter tel quel | — |
| **V9-03-A** Repository-RAG CoderAgent | ✅ Implémenter avec cache AST TTL **3600s** | TTL 5min→1h (index 10 Mo, 24 Go) |
| **V9-03-B** Web search auto ArchitectAgent | ✅ Implémenter tel quel | — |
| **V9-03-C** HyDE MemoryEngine | ✅ Implémenter, injection générateur obligatoire | Pas de LLMGenerator interne |
| **V9-03-D** Doc retrieval erreur API | ✅ Implémenter + recherche lcca_failures avant web | — |
| **V9-04-A** Collecteur SFT | ✅ Implémenter tel quel | — |
| **V9-04-B** GRPO Unsloth | ❌ **Reporté V10** | CPU trop lent (heures/epoch). Flag expérimental V9.1 |
| **V9-04-C** Pipeline continu | ❌ **Reporté V10** | Dépend V9-04-B |
| **V9-04-D** PromptTuner (remplacement GRPO) | ✅ **Nouveau** | In-context learning, pas de fine-tuning |
| **V9-05-A** QAAgent | ✅ Implémenter tel quel | — |
| **V9-05-B** DocAgent | ✅ Implémenter, DOCAGENT_AUTO_CONFIRM=False | — |
| **V9-05-C** Pair Programmer HITL | ✅ Implémenter tel quel | — |
| **V9-05-D** Dashboard Analytics | ✅ Implémenter tel quel | — |
| **V9-05-E** Mémoire épisodique | ✅ Implémenter avec **SQLite FTS5** (pas DuckDB) | DuckDB→SQLite (stdlib, pas de dépendance compilée) |
| **V9-05-F** TTS local | ✅ Implémenter, **Kokoro par défaut** + pyttsx3 fallback | pyttsx3→Kokoro (200 Mo viable sur 24 Go) |
| **Hardware** HardwareProfile | ✅ **Nouveau** | Détection RAM auto + adaptation paramètres |

---

## 4. Axe 1 — Performance LLM (V9-01)

### 4.1 Sprint V9-01-A — Quantification Q4_K_M + keep_alive

**Objectif** : Réduire la latence de 30-40% et maintenir le modèle chaud en RAM.

#### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `config.py` | PATCH — 5 constantes V9 |
| `core/llm_generator.py` | PATCH — OllamaClient + LLMGenerator |
| `tests/test_llm_generator.py` | PATCH — 2 tests |

#### Spécification `config.py`

```python
# V9-01-A — Quantification + keep_alive
OLLAMA_MODEL_LIGHT   = "qwen2.5-coder:3b"      # V9-01-B
OLLAMA_KEEP_ALIVE    = "30m"                    # Modèle en RAM 30 min
OLLAMA_QUANTIZED     = True                     # Utiliser Q4_K_M si disponible
OLLAMA_QUANT_LEVEL   = "Q4_K_M"                # "Q4_K_M" | "Q5_K_M"
OLLAMA_QUANT_LEVEL_HEAVY = "Q4_K_M"            # Sur 32 Go : passer à "Q5_K_M"
OLLAMA_THREADS       = 4                        # 0 = auto
OLLAMA_NUM_GPU       = 0                        # Force CPU
OLLAMA_MMAP          = True                     # Réduction RAM via mmap
```

#### Spécification `OllamaClient.__init__`

```python
def __init__(
    self, base_url: str, model: str,
    timeout: int, max_tokens: int,
    keep_alive: str = "5m",
) -> None:
    ...
    self.keep_alive = keep_alive
```

Chaque méthode publique (`generate`, `chat`, `chat_stream`, `generate_stream`) ajoute :
```python
"keep_alive": self.keep_alive,
"options": {
    "num_predict": self.max_tokens,
    "num_thread":  getattr(config, "OLLAMA_THREADS", 4),
    "num_gpu":     getattr(config, "OLLAMA_NUM_GPU", 0),
    "use_mmap":    getattr(config, "OLLAMA_MMAP", True),
},
```

#### Spécification `_load_config` — modèle quantifié

```python
def _load_config(model_override=None):
    base_model = model_override or getattr(config, "OLLAMA_MODEL", _DEFAULT_MODEL)
    quantized  = getattr(config, "OLLAMA_QUANTIZED", False)
    if quantized and not model_override and "_K_M" not in base_model:
        level = getattr(config, "OLLAMA_QUANT_LEVEL", "Q4_K_M")
        model = base_model.replace(":7b", f":7b-{level}").replace(":14b", f":14b-{level}")
    else:
        model = base_model
    return {"url": ..., "model": model, "timeout": ..., ...}
```

> **Note opérationnelle** : Avant activation, exécuter :
> ```
> ollama pull qwen2.5-coder:3b
> ollama pull qwen2.5-coder:7b-q4_K_M
> ollama pull qwen2.5-coder:14b-q4_K_M
> ```

---

### 4.2 Sprint V9-01-B — Tri-modèle adaptatif via LLMGeneratorPool

**Objectif** : Routage automatique 3b/7b/14b selon la complexité du tool MCP, avec pool LRU (max 3 sur 24 Go).

#### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `core/llm_generator_pool.py` | CREATE — nouveau |
| `config.py` | PATCH — LLM_POOL_MAX_LOADED = 3 |
| `core/mcp_tool_handlers.py` | PATCH — `_get_generator(tool_name)` |
| `core/nl_parser.py` | PATCH — utiliser OLLAMA_MODEL_LIGHT |
| `tests/test_llm_generator_pool.py` | CREATE — 6 tests |
| `tests/test_mcp_tool_handlers.py` | PATCH — 3 tests |

#### Spécification `core/llm_generator_pool.py`

```python
# -*- coding: utf-8-sig -*-
"""
llm_generator_pool.py — Pool singleton de LLMGenerator avec éviction LRU.
Garantit max MAX_LOADED modèles en RAM simultanément.

Usage :
    gen = LLMGeneratorPool.get("qwen2.5-coder:3b", timeout=90, max_tokens=512)
    result = gen.generate_text(system, user)
"""
from __future__ import annotations
import threading
import time
from typing import Optional

class LLMGeneratorPool:
    _instances: dict[str, "LLMGenerator"] = {}
    _last_used: dict[str, float]          = {}
    _lock = threading.Lock()

    @classmethod
    def _max_loaded(cls) -> int:
        try:
            import config
            return getattr(config, "LLM_POOL_MAX_LOADED", 3)
        except ImportError:
            return 3

    @classmethod
    def get(cls, model: str, timeout: int = 90, max_tokens: int = 512) -> "LLMGenerator":
        from core.llm_generator import LLMGenerator
        key = f"{model}:{timeout}:{max_tokens}"
        with cls._lock:
            if key not in cls._instances:
                cls._evict_if_needed()
                cls._instances[key] = LLMGenerator(model=model, timeout=timeout, max_tokens=max_tokens)
            cls._last_used[key] = time.monotonic()
            return cls._instances[key]

    @classmethod
    def _evict_if_needed(cls):
        if len(cls._instances) < cls._max_loaded():
            return
        oldest = min(cls._last_used, key=cls._last_used.get)
        cls._instances.pop(oldest)
        cls._last_used.pop(oldest)

    @classmethod
    def unload(cls, model: str) -> None:
        with cls._lock:
            keys = [k for k in cls._instances if k.startswith(f"{model}:")]
            for k in keys:
                cls._instances.pop(k, None)
                cls._last_used.pop(k, None)

    @classmethod
    def clear(cls):
        with cls._lock:
            cls._instances.clear()
            cls._last_used.clear()

    @classmethod
    def health_check(cls) -> dict:
        """Vérifie disponibilité Ollama via un appel léger."""
        try:
            gen = cls.get(list(cls._instances.values())[0].ollama.model
                         if cls._instances else "qwen2.5-coder:3b",
                         timeout=10, max_tokens=1)
            return {"healthy": True, "loaded": len(cls._instances)}
        except Exception as exc:
            return {"healthy": False, "error": str(exc), "loaded": len(cls._instances)}
```

#### Spécification `_get_generator` dans `mcp_tool_handlers.py`

```python
_COMPLEXITY_LIGHT  = "light"
_COMPLEXITY_MEDIUM = "medium"
_COMPLEXITY_HEAVY  = "heavy"

_TOOL_COMPLEXITY: dict[str, str] = {
    "llm_chat":        _COMPLEXITY_LIGHT,
    "memory_search":   _COMPLEXITY_LIGHT,
    "memory_store":    _COMPLEXITY_LIGHT,
    "project_search":  _COMPLEXITY_LIGHT,
    "web_cache_stats": _COMPLEXITY_LIGHT,
    "analyze_error":   _COMPLEXITY_MEDIUM,
    "evaluate_quality":_COMPLEXITY_MEDIUM,
    "sandbox_run":     _COMPLEXITY_MEDIUM,
    "edit_batch":      _COMPLEXITY_MEDIUM,
    "web_search":      _COMPLEXITY_MEDIUM,
    "get_analytics":   _COMPLEXITY_LIGHT,
    "generate_spec":   _COMPLEXITY_HEAVY,
    "validate_spec":   _COMPLEXITY_HEAVY,
}

def _get_generator(tool_name: str = "llm_chat") -> "LLMGenerator":
    import config
    from core.llm_generator_pool import LLMGeneratorPool
    complexity = _TOOL_COMPLEXITY.get(tool_name, _COMPLEXITY_MEDIUM)
    if complexity == _COMPLEXITY_LIGHT:
        model      = getattr(config, "OLLAMA_MODEL_LIGHT", config.OLLAMA_MODEL)
        timeout    = 90
        max_tokens = getattr(config, "NL_MAX_TOKENS", 512)
    elif complexity == _COMPLEXITY_HEAVY:
        model      = config.OLLAMA_MODEL_HEAVY
        timeout    = config.SPEC_TIMEOUT
        max_tokens = config.SPEC_MAX_TOKENS
    else:
        model      = config.OLLAMA_MODEL
        timeout    = config.OLLAMA_TIMEOUT
        max_tokens = config.OLLAMA_MAX_TOKENS
    return LLMGeneratorPool.get(model, timeout=timeout, max_tokens=max_tokens)
```

---

### 4.3 Sprint V9-01-C — Streaming universel

**Objectif** : Étendre le streaming temps réel à tous les tools LLM (actuellement limité à `llm_chat`).

#### Spécification `CognitivePattern._call_llm_stream`

```python
def _call_llm_stream(
    self,
    system: str,
    user: str,
    on_token: "Callable[[str], None] | None" = None,
    timeout_override: "int | None" = None,
) -> str:
    if on_token is None:
        return self._call_llm(system, user, timeout_override)
    ollama = self._generator.ollama
    if timeout_override is not None:
        orig = ollama.timeout
        ollama.timeout = timeout_override
    try:
        result = ollama.generate_stream(system, user, on_token)
        return result if isinstance(result, str) else ""
    except Exception:
        return self._call_llm(system, user, timeout_override)   # fallback bloquant
    finally:
        if timeout_override is not None:
            ollama.timeout = orig
```

Ajout dans `config.py` :
```python
STREAM_BUFFER_SIZE = 10       # Tokens bufferisés avant flush UI
STREAM_THROTTLE_MS = 50       # Délai minimal entre flushes (ms)
```

---

## 5. Axe 2 — Qualité des réponses (V9-02)

### 5.1 Sprint V9-02-A — Few-shot SkillLibrary dans PromptBuilder

**Objectif** : Connecter `SkillLibrary.retrieve()` à `PromptBuilder.build()` pour injecter des exemples de code LCCA réels dans chaque prompt de génération.

#### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `core/llm_generator.py` | PATCH — `PromptBuilder.build()` + `LLMGenerator.generate()` |
| `core/agents/coder_agent.py` | PATCH — extraction `skill_context` depuis `contract.context` |
| `tests/test_llm_generator.py` | PATCH — 3 tests |

#### Spécification `PromptBuilder.build` (signature complète)

```python
def build(
    self,
    op,
    intent,
    context: str = "",
    skill_context: str = "",   # V9-02-A — snippets few-shot
) -> tuple[str, str]:
    # ... construction user prompt existante ...
    if skill_context:
        user = (
            "## Exemples de code LCCA existants (style à imiter)\n\n"
            + skill_context
            + "\n\n## Votre tâche\n\n"
            + user
        )
    return self._SYSTEM, user
```

#### Spécification `CoderAgent.run_task` — extraction

```python
skill_context = contract.context.get("available_skills", "")
result = self._generator.generate(
    op=patch, intent=intent,
    context=file_context, skill_context=skill_context,
)
```

---

### 5.2 Sprint V9-02-B — Boucle de correction post-génération (opt-in)

**Objectif** : Retenter la génération avec feedback si score CodeEvaluator < 70, max 2 fois.
**Critique** : Opt-in strict (`CORRECTION_LOOP_ENABLED=False`) + timeout global 120s pour éviter 9 min de blocage sur 14b.

#### Config

```python
CORRECTION_LOOP_ENABLED        = False   # Opt-in obligatoire
LLM_MAX_CORRECTION_RETRIES     = 2
LLM_GENERATION_MAX_TOTAL_SEC   = 120     # Timeout dur global
```

#### Spécification `LLMGenerator.generate` (boucle)

```python
_MIN_QUALITY_SCORE = 70

def generate(self, op, intent, context="", skill_context="") -> GenerationResult:
    import time, config
    from core.code_evaluator import CodeEvaluator

    if not getattr(config, "CORRECTION_LOOP_ENABLED", False):
        return self._generate_single(op, intent, context, skill_context)

    max_retries  = getattr(config, "LLM_MAX_CORRECTION_RETRIES", 2)
    max_total_s  = getattr(config, "LLM_GENERATION_MAX_TOTAL_SEC", 120)
    deadline     = time.monotonic() + max_total_s
    evaluator    = CodeEvaluator()
    system, user_orig = self.builder.build(op, intent, context, skill_context=skill_context)
    prompt_key   = self._cache_key(system, user_orig, self.ollama.model)
    cached = self._cache_get(prompt_key)
    if cached:
        return GenerationResult(code=cached, model=self.ollama.model, from_cache=True,
                                from_fallback=False, prompt_tokens=len(user_orig)//4, duration_ms=0)
    t0, user, last_code = time.monotonic(), user_orig, ""
    for attempt in range(max_retries + 1):
        if time.monotonic() > deadline:
            log.warning("generate: timeout global %ds — fallback", max_total_s)
            break
        try:
            raw  = self.ollama.generate(system, user)
            code = self.extractor.extract(raw)
            code = self.extractor.sanitize(code)
            if not self.extractor.is_valid_python(code):
                feedback = "SyntaxError : code non valide."
            else:
                ev = evaluator.evaluate(code)
                if ev.score >= _MIN_QUALITY_SCORE:
                    ms = int((time.monotonic() - t0) * 1000)
                    self._cache_set(prompt_key, code)
                    return GenerationResult(code=code, model=self.ollama.model,
                                           from_cache=False, from_fallback=False,
                                           prompt_tokens=len(user)//4, duration_ms=ms)
                feedback = (f"Score {ev.score}/100 < {_MIN_QUALITY_SCORE}.\n"
                            f"Problèmes : {'; '.join(ev.issues[:3])}. Corrige.")
            last_code = code
            if attempt < max_retries:
                user = (user_orig
                        + f"\n\n## Correction (tentative {attempt+1}/{max_retries})\n"
                        + feedback
                        + f"\n\nCode à corriger :\n```python\n{code[:1000]}\n```\n")
        except (ConnectionError, RuntimeError) as exc:
            code = self.fallback.generate(op, intent)
            return GenerationResult(code=code, model="fallback", from_cache=False,
                                    from_fallback=True,
                                    prompt_tokens=len(user)//4,
                                    duration_ms=int((time.monotonic()-t0)*1000))
    ms = int((time.monotonic() - t0) * 1000)
    if last_code and self.extractor.is_valid_python(last_code):
        return GenerationResult(code=last_code, model=self.ollama.model, from_cache=False,
                                from_fallback=False, prompt_tokens=len(user)//4, duration_ms=ms)
    code = self.fallback.generate(op, intent)
    return GenerationResult(code=code, model="fallback", from_cache=False,
                            from_fallback=True, prompt_tokens=len(user)//4, duration_ms=ms)
```

---

### 5.3 Sprint V9-02-C — Contexte AST complet dans SpecGenerator

**Objectif** : Injecter les signatures réelles des modules LCCA dans les prompts SpecDirectPattern.

#### Spécification `SpecGeneratorService._build_ast_context`

```python
def _build_ast_context(self, query: str) -> str:
    import config
    max_symbols = getattr(config, "SPEC_AST_MAX_SYMBOLS", 20)
    query_words = set(query.lower().split())
    try:
        index = self._indexer.index_repository()
    except Exception as exc:
        log.debug("_build_ast_context: %s", exc)
        return ""
    relevant = []
    for fp, symbols in index.items():
        fp_lower = fp.lower()
        for sym in symbols:
            score = sum(1 for w in query_words if w in sym.get("name","").lower() or w in fp_lower)
            if score > 0:
                relevant.append({**sym, "_score": score, "_file": fp})
    relevant.sort(key=lambda s: s["_score"], reverse=True)
    top = relevant[:max_symbols]
    if not top:
        return ""
    lines = ["## Symboles LCCA pertinents (AST)\n"]
    for s in top:
        lines.append(f"### `{s.get('name','?')}` ({s.get('type','fn')}) — `{s.get('_file','?')}`\n"
                     f"```python\n{s.get('signature', '')}\n```\n")
    return "\n".join(lines)
```

Intégration dans `generate()` :
```python
tech_context = self._build_technical_context()
ast_context  = self._build_ast_context(intent)      # V9-02-C
spec_context = "\n\n".join(filter(None, [tech_context, ast_context, rag_context]))
```

---

### 5.4 Sprint V9-02-D — JSON mode Ollama

**Objectif** : Forcer `"format": "json"` pour `SpecValidatorPattern` et `analyze_error`.

#### Spécification `OllamaClient.generate` (ajout paramètre)

```python
def generate(self, system: str, user: str,
             response_format: "str | None" = None) -> str:
    payload = {...}
    if response_format == "json":
        payload["format"] = "json"
    ...
```

---

## 6. Axe 3 — Agentic RAG (V9-03)

### 6.1 Sprint V9-03-A — Repository-RAG dans CoderAgent (avec cache AST)

**Objectif** : Injecter les fichiers LCCA les plus pertinents dans le contexte CoderAgent, avec cache TTL 1h sur 24 Go.

#### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `core/agents/coder_agent.py` | PATCH — `_retrieve_repo_context` + cache |
| `config.py` | PATCH — REPO_RAG_MAX_FILES, REPO_RAG_MAX_LINES, AST_INDEX_CACHE_TTL |
| `tests/test_coder_agent.py` | PATCH — 4 tests |

#### Config

```python
REPO_RAG_MAX_FILES    = 5
REPO_RAG_MAX_LINES    = 80
AST_INDEX_CACHE_TTL   = 3600   # 1 heure (24 Go confortables)
SPEC_AST_MAX_SYMBOLS  = 20
```

#### Spécification `CoderAgent` — cache AST + BM25

```python
class CoderAgent(BaseAgent):
    def __init__(self, ...):
        ...
        self._ast_index_cache: Optional[dict]  = None
        self._ast_index_cache_ts: float        = 0
        self._last_git_head: Optional[str]     = None

    def _get_ast_index(self) -> dict:
        import subprocess, time, config
        from core.ast_indexer import ASTIndexer
        ttl = getattr(config, "AST_INDEX_CACHE_TTL", 3600)
        try:
            current_head = subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True,
                text=True, cwd=str(config.WORKSPACE_DIR), timeout=5
            ).stdout.strip()
        except Exception:
            current_head = None
        now = time.monotonic()
        if (self._ast_index_cache is not None
                and (now - self._ast_index_cache_ts) < ttl
                and (current_head is None or current_head == self._last_git_head)):
            return self._ast_index_cache
        self._ast_index_cache    = ASTIndexer(workspace=config.WORKSPACE_DIR).index_repository()
        self._ast_index_cache_ts = now
        self._last_git_head      = current_head
        return self._ast_index_cache

    def _retrieve_repo_context(self, intent: str) -> str:
        import config
        max_files = getattr(config, "REPO_RAG_MAX_FILES", 5)
        max_lines = getattr(config, "REPO_RAG_MAX_LINES", 80)
        try:
            tokens = {w.lower() for w in intent.split()
                      if w.lower() not in _REPO_RAG_STOPWORDS and len(w) > 2}
            if not tokens:
                return ""
            index = self._get_ast_index()
            scores = {fp: len(tokens & {t for s in syms
                              for t in s.get("name","").lower().split("_")})
                      for fp, syms in index.items()}
            top = sorted((fp for fp, s in scores.items() if s > 0),
                         key=lambda fp: scores[fp], reverse=True)[:max_files]
            if not top:
                return ""
            parts = ["## Fichiers LCCA pertinents (Repository-RAG)\n"]
            for fp in top:
                try:
                    from pathlib import Path
                    lines = Path(fp).read_text(encoding="utf-8-sig", errors="replace"
                                               ).splitlines()[:max_lines]
                    parts.append(f"### `{Path(fp).name}` (score={scores[fp]})\n"
                                 f"```python\n" + "\n".join(lines) + "\n```\n")
                except Exception:
                    continue
            return "\n".join(parts)
        except Exception as exc:
            log.debug("_retrieve_repo_context: %s", exc)
            return ""
```

---

### 6.2 Sprint V9-03-B — Web search auto dans ArchitectAgent

**Objectif** : Détecter les libs externes dans l'intent et enrichir les sous-contrats avec leur documentation.

#### Spécification `ArchitectAgent._detect_external_libs`

```python
_LCCA_INTERNAL_KEYWORDS = frozenset({
    "transaction", "ast", "mcp", "sandbox", "memory", "spec", "orchestrator",
    "agent", "skill", "llm", "ollama", "chromadb", "libcst", "nlp",
    "patch", "commit", "rollback", "wal", "receipt", "bus",
})

def _detect_external_libs(self, intent: str) -> list[str]:
    import re
    candidates = re.findall(r'\b([a-z][a-z0-9_-]{2,})\b', intent.lower())
    external = [c for c in candidates
                if c not in _LCCA_INTERNAL_KEYWORDS
                and not any(c in kw for kw in _LCCA_INTERNAL_KEYWORDS)
                and len(c) > 3]
    seen, result = set(), []
    for e in external:
        if e not in seen:
            seen.add(e); result.append(e)
    return result[:3]
```

Intégration (silencieuse) :
```python
if getattr(config, "ARCHITECT_WEB_SEARCH_ENABLED", True):
    libs = self._detect_external_libs(contract.intent)
    if libs:
        try:
            from core.web_search import WebSearchEngine
            result = WebSearchEngine().search(f"{libs[0]} python usage examples")
            if result.synthesis:
                for sub in sub_contracts:
                    sub.context["web_documentation"] = result.synthesis[:1500]
        except Exception as exc:
            log.debug("[architect] web_search: %s", exc)
```

---

### 6.3 Sprint V9-03-C — HyDE (Hypothetical Document Embedding)

**Objectif** : Améliorer le recall ChromaDB de 25-30% via un document hypothétique intermédiaire.
**Correction critique** : Pas d'instanciation interne de LLMGenerator.

#### Spécification `MemoryEngine.search_hyde`

```python
def search_hyde(self, query, wing="lcca", n=5,
                generator=None) -> dict:
    import config
    if not getattr(config, "MEMORY_HYDE_ENABLED", False):
        return self.search(query, wing, n)
    if not self._available:
        return self.search(query, wing, n)
    if generator is None:   # Jamais instancier en interne
        log.debug("HyDE: aucun générateur fourni → fallback standard")
        return self.search(query, wing, n)
    try:
        hyde_doc = generator.generate_text(_HYDE_SYSTEM, f"Requête : {query}")
        if not hyde_doc or len(hyde_doc) < 20:
            return self.search(query, wing, n)
    except Exception as exc:
        log.debug("HyDE: %s → fallback", exc)
        return self.search(query, wing, n)
    return self.search(hyde_doc, wing, n)
```

Config :
```python
MEMORY_HYDE_ENABLED = False   # Opt-in (coûteux : +1 appel LLM léger par recherche)
```

---

### 6.4 Sprint V9-03-D — Récupération doc officielle sur erreur d'API

**Objectif** : Quand le ReviewerAgent détecte une erreur de signature d'API, enrichir la réflexion avec la doc officielle (d'abord `lcca_failures`, puis web en fallback).

#### Spécification `ReviewerAgent._enrich_reflection_with_docs`

```python
_API_ERROR_PATTERNS = [
    r"AttributeError: (?:module '(\w+)'|'(\w+)' object) has no attribute '(\w+)'",
    r"TypeError: (\w+)\(\) got an unexpected keyword argument '(\w+)'",
    r"ImportError: cannot import name '(\w+)' from '(\w+)'",
    r"ModuleNotFoundError: No module named '(\w+)'",
]

def _enrich_reflection_with_docs(self, reflection: str, code: str) -> str:
    import re
    for pattern in _API_ERROR_PATTERNS:
        match = re.search(pattern, reflection)
        if match:
            lib_name = next((g for g in match.groups() if g), None)
            if not lib_name:
                continue
            # 1. Chercher d'abord dans lcca_failures
            try:
                from core.memory_engine import MemoryEngine
                mem = MemoryEngine()
                local = mem.search(f"{lib_name} error", n=3)
                failures = local.get("failures", [])
                if failures:
                    doc = failures[0].content[:600]
                    return reflection + f"\n\n## Erreur similaire connue : `{lib_name}`\n\n{doc}"
            except Exception:
                pass
            # 2. Fallback web
            try:
                from core.web_search import WebSearchEngine
                result = WebSearchEngine().search(f"{lib_name} python official documentation API")
                if result.synthesis and len(result.synthesis) > 50:
                    return (reflection
                            + f"\n\n## Documentation officielle : `{lib_name}`\n\n"
                            + result.synthesis[:800]
                            + "\n\nCorrige le code avec la bonne API.")
            except Exception as exc:
                log.debug("[reviewer] doc enrichment: %s", exc)
            break
    return reflection
```

---

## 7. Axe 4 — Pipeline d'entraînement (V9-04)

### 7.1 Sprint V9-04-A — Collecteur SFT (TrainingDataCollector)

**Objectif** : Collecter les paires (instruction, code) validées et les exporter au format ShareGPT/Alpaca.
**Périmètre V9.0** : Collecte + export uniquement. Pas de fine-tuning local.

#### Fichiers à créer

| Fichier | Opération |
|---------|-----------|
| `core/training_types.py` | CREATE — SFTPair + GRPOSample |
| `core/training_collector.py` | CREATE — TrainingDataCollector |
| `config.py` | PATCH — TRAINING_OUTPUT_DIR, TRAINING_MIN_SCORE=70, TRAINING_MIN_PAIRS=50 |
| `tests/test_training_collector.py` | CREATE — 10 tests |

#### Spécification `SFTPair`

```python
@dataclass
class SFTPair:
    instruction : str
    output      : str
    source      : str = "lcca_patches"
    quality     : int = 0
    tx_id       : str = ""
    created_at  : str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_sharegpt(self) -> dict: ...
    def to_alpaca(self) -> dict: ...
    def is_usable(self, min_quality: int = 70) -> bool:
        return bool(self.instruction) and bool(self.output) \
               and self.quality >= min_quality and len(self.output) >= 20
```

#### Sources de collecte

1. **`lcca_solutions`** — code validé + score ≥ min_quality
2. **`receipts/*.json`** — `code_snapshot`, `quality_score`, `intent`

#### Export

```
training_data/v9/
    train.jsonl   (80%)
    eval.jsonl    (20%)
    stats.json    {total, train, eval, skipped, avg_quality}
```

---

### 7.2 Sprint V9-04-D — PromptTuner (remplacement GRPO V9.0)

**Objectif** : Améliorer la qualité des prompts via in-context learning, sans fine-tuning de poids.
**Principe** : Injecter les top-3 skills les plus pertinents et récents dans le prompt système.

#### Fichier à créer

| Fichier | Opération |
|---------|-----------|
| `core/prompt_tuner.py` | CREATE |
| `tests/test_prompt_tuner.py` | CREATE — 5 tests |

#### Spécification `PromptTuner`

```python
class PromptTuner:
    """
    Améliore dynamiquement les prompts système via les skills récents.
    Aucune modification de poids — pure ingénierie de prompt.
    """
    def __init__(self, skill_library=None):
        self._skills = skill_library

    def tune(self, base_system: str, query: str, top_n: int = 3) -> str:
        if self._skills is None:
            return base_system
        try:
            entries = self._skills.retrieve(query, max_results=top_n)
            if not entries:
                return base_system
            examples = self._skills.format_for_prompt(entries)
            return base_system + "\n\n## Patterns LCCA récents\n\n" + examples
        except Exception as exc:
            log.debug("PromptTuner.tune: %s", exc)
            return base_system
```

> **Note V9.1** : Si `GRPO_EXPERIMENTAL_ENABLED=True` (32 Go + GPU futur), `TrainingPipeline.run()` déclenche un micro-fine-tune LoRA nocturne. Désactivé par défaut.

---

## 8. Axe 5 — Agents créatifs (V9-05)

### 8.1 Sprint V9-05-A — QAAgent

**Objectif** : Audit autonome continu du codebase, publication de `TaskContract` A2A pour les CRITIQUE.

#### Fichiers à créer

| Fichier | Opération |
|---------|-----------|
| `core/agents/qa_agent.py` | CREATE |
| `core/agents/__init__.py` | PATCH — export QAAgent + QAReport |
| `config.py` | PATCH — QA_SCAN_INTERVAL_HOURS=24, QA_DEBT_THRESHOLD_WARN=7, QA_DEBT_THRESHOLD_CRIT=10 |
| `tests/test_qa_agent.py` | CREATE — 12 tests |

#### Règles d'audit (QA_RULES)

| Règle | Sévérité | Détection |
|-------|----------|-----------|
| `_rule_file_too_large` | CRITIQUE si >20KB, WARN si >10KB | `size_kb` |
| `_rule_hardcoded_python` | CRITIQUE | `re.search(r'["\']python["\']', content)` hors tests |
| `_rule_direct_file_write` | CRITIQUE | `write_text()` sans snapshot hors tests |
| `_rule_hardcoded_path` | WARN | `D:\\` dans le code source |
| `_rule_bare_except` | WARN | `except:` sans type |
| `_rule_print_in_production` | INFO | `print()` hors tests |
| `_rule_fstring_in_log` | INFO | `log.info(f"...")` |
| `_rule_missing_docstring` | INFO | Classe/fonction publique sans docstring |
| `_rule_duplicate_constant` | WARN | Même constante dans 2+ fichiers |

#### Contraintes QAAgent

- **Lecture seule** — jamais de modification de fichier
- Publie `TaskContract(target_agent="architect")` pour les CRITIQUE
- Stocke le rapport dans `lcca_context` via `memory_store`
- `schedule(interval_hours=24)` → thread daemon silencieux

---

### 8.2 Sprint V9-05-B — DocAgent

**Objectif** : Auto-documentation des modules (docstrings) et mise à jour des skills `.md`.

#### Contraintes

- Modèle léger uniquement (`OLLAMA_MODEL_LIGHT = 3b`)
- Max 5 fichiers par session
- Ne touche jamais `core/` directement → utilise `edit_batch` MCP
- `DOCAGENT_AUTO_CONFIRM = False` par défaut

#### Spécification `DocAgent`

```python
class DocAgent(BaseAgent):
    def document_file(self, filepath: Path) -> dict:
        """Ajoute docstrings manquantes. Returns {added, skipped, errors}."""
        ...

    def update_skill(self, skill_path: Path, new_pattern: str) -> bool:
        """Ajoute pattern dans skill .md. Demande confirmation si DOCAGENT_AUTO_CONFIRM=False."""
        ...
```

Script `scripts/post-commit.ps1` déclenche `DocAgent` après chaque commit.

---

### 8.3 Sprint V9-05-C — Mode Pair Programmer (HITL)

**Objectif** : Pause de la KarpathyLoop après chaque itération Reviewer, avec validation humaine.

#### Spécification `AgentOrchestrator`

```python
def __init__(self, ..., hitl_callback: "Callable | None" = None):
    self._hitl = hitl_callback

# Dans KarpathyLoop, après ReviewerAgent :
if self._hitl and not reviewer_result.success:
    decision = self._hitl(generated_code, reflection, iteration)
    if decision == "accept":
        success = True; break
    elif decision.startswith("modify:"):
        intent = decision[7:]
    # "continue" → boucle normale
```

Config :
```python
HITL_ENABLED = False   # Opt-in
```

Nouveau composant UI : `HITLPanel.tsx` (diff coloré + 3 boutons : Continuer / Accepter / Modifier).

---

### 8.4 Sprint V9-05-D — Dashboard Analytics

**Objectif** : Dashboard React (recharts) alimenté par un nouveau tool MCP `get_analytics`.

#### Nouveau tool MCP `get_analytics` (13ème)

```python
def _tool_get_analytics(params: dict) -> dict:
    return {
        "period_days":           int,
        "total_transactions":    int,
        "success_rate":          float,
        "avg_quality_score":     float,
        "avg_latency_ms":        float,
        "models_used":           dict,
        "tools_usage":           dict,
        "quality_trend":         list,   # 30 derniers jours
        "karpathy_stats":        dict,   # avg_iterations, stagnation_rate, success_rate
    }
```

UI : `AnalyticsPanel.tsx` avec LineChart, BarChart, PieChart, stat cards (recharts).

---

### 8.5 Sprint V9-05-E — Mémoire épisodique (SQLite FTS5)

**Objectif** : Graphe de décisions architecturales requêtable en langage naturel.
**Backend** : SQLite FTS5 (stdlib Python 3.11+) — pas DuckDB (dépendance compilée lourde).

#### Fichiers à créer

| Fichier | Opération |
|---------|-----------|
| `core/episodic_memory.py` | CREATE — EpisodicMemory + SQLite FTS5 |
| `core/episodic_types.py` | CREATE — Node, Edge, EpisodicQuery |
| `config.py` | PATCH — EPISODIC_DB_PATH |
| `tests/test_episodic_memory.py` | CREATE — 6 tests |

#### Schéma SQLite FTS5

```sql
CREATE TABLE sessions (id TEXT PRIMARY KEY, date TEXT, sprint_name TEXT, engineer TEXT);
CREATE TABLE decisions (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, rationale TEXT,
    alternatives TEXT, session_id TEXT, created_at TEXT,
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);
CREATE VIRTUAL TABLE decisions_fts USING fts5(
    title, rationale, alternatives, session_id,
    content='decisions', content_rowid='rowid'
);
CREATE TRIGGER decisions_ai AFTER INSERT ON decisions BEGIN
    INSERT INTO decisions_fts(rowid, title, rationale, alternatives, session_id)
    VALUES (new.rowid, new.title, new.rationale, new.alternatives, new.session_id);
END;
```

---

### 8.6 Sprint V9-05-F — Synthèse vocale locale (TTS)

**Objectif** : Notifications vocales de fin de tâche. Kokoro par défaut sur 24 Go, pyttsx3 en fallback.

#### Fichiers à créer

| Fichier | Opération |
|---------|-----------|
| `core/tts_engine.py` | CREATE — TTSEngine (pyttsx3 + Kokoro) |
| `ui/electron/main.ts` | PATCH — handler `tts:speak` |
| `ui/electron/preload.ts` | PATCH — `window.lcca.ttsSay()` |
| `ui/src/hooks/useTts.ts` | CREATE — hook React |
| `scripts/start-tts.ps1` | CREATE — démarre Kokoro |

#### Spécification `TTSEngine`

```python
class TTSEngine:
    def say(self, text: str):
        if not self._enabled: return
        if self._provider == "kokoro":
            try: self._say_kokoro(text)
            except Exception:
                log.warning("Kokoro indisponible → pyttsx3")
                self._say_pyttsx3(text)
        else:
            self._say_pyttsx3(text)

    def _say_pyttsx3(self, text):
        try:
            import pyttsx3
            if self._engine is None: self._engine = pyttsx3.init()
            self._engine.say(text); self._engine.runAndWait()
        except Exception as exc:
            log.debug("TTS pyttsx3: %s", exc)
```

Config :
```python
TTS_ENABLED = False
TTS_ENGINE  = "kokoro"   # "kokoro" | "pyttsx3"
TTS_VOICE   = "fr_f"
```

Points de notification : `AgentOrchestrator.run()`, `SpecGenerator.generate()`, `QAAgent.run_scan()`, `TrainingPipeline.run()`.

---

## 9. Nouveaux fichiers à créer

| Fichier | Sprint | Description |
|---------|--------|-------------|
| `core/llm_generator_pool.py` | V9-01-B | Pool LRU de LLMGenerator |
| `core/hardware_profile.py` | Transversal | Détection RAM + profil auto |
| `core/training_types.py` | V9-04-A | SFTPair + GRPOSample |
| `core/training_collector.py` | V9-04-A | TrainingDataCollector |
| `core/training_reward.py` | V9-04-A | lcca_code_reward (prêt pour V9.1 GRPO) |
| `core/prompt_tuner.py` | V9-04-D | PromptTuner (in-context learning) |
| `core/tts_engine.py` | V9-05-F | TTSEngine Kokoro + pyttsx3 |
| `core/agents/qa_agent.py` | V9-05-A | QAAgent + QAReport |
| `core/agents/doc_agent.py` | V9-05-B | DocAgent |
| `core/episodic_memory.py` | V9-05-E | EpisodicMemory SQLite FTS5 |
| `core/episodic_types.py` | V9-05-E | Types graphe épisodique |
| `ui/src/components/HITLPanel.tsx` | V9-05-C | Pair Programmer UI |
| `ui/src/components/AnalyticsPanel.tsx` | V9-05-D | Dashboard Analytics |
| `ui/src/stores/analyticsStore.ts` | V9-05-D | Zustand store analytics |
| `ui/src/hooks/useTts.ts` | V9-05-F | Hook TTS |
| `scripts/start-tts.ps1` | V9-05-F | Script démarrage Kokoro |
| `scripts/post-commit.ps1` | V9-05-B | Git hook DocAgent |
| `tests/test_llm_generator_pool.py` | V9-01-B | 6 tests pool |
| `tests/test_hardware_profile.py` | Transversal | 4 tests profil |
| `tests/test_training_collector.py` | V9-04-A | 10 tests |
| `tests/test_prompt_tuner.py` | V9-04-D | 5 tests |
| `tests/test_qa_agent.py` | V9-05-A | 12 tests |
| `tests/test_doc_agent.py` | V9-05-B | 8 tests |
| `tests/test_episodic_memory.py` | V9-05-E | 6 tests |
| `tests/test_tts_engine.py` | V9-05-F | 5 tests |

---

## 10. Patches `config.py` consolidés

```python
# ─── V9-01-A Quantification + keep_alive ───────────────────────────────────
OLLAMA_MODEL_LIGHT        = "qwen2.5-coder:3b"
OLLAMA_KEEP_ALIVE         = "30m"
OLLAMA_QUANTIZED          = True
OLLAMA_QUANT_LEVEL        = "Q4_K_M"          # "Q4_K_M" | "Q5_K_M"
OLLAMA_QUANT_LEVEL_HEAVY  = "Q4_K_M"          # Passer à "Q5_K_M" sur 32 Go
OLLAMA_THREADS            = 4
OLLAMA_NUM_GPU            = 0
OLLAMA_MMAP               = True

# ─── V9-01-B Pool LRU ──────────────────────────────────────────────────────
LLM_POOL_MAX_LOADED       = 3                  # 2 si < 24 Go (hardware_profile)

# ─── V9-01-C Streaming ─────────────────────────────────────────────────────
STREAM_BUFFER_SIZE        = 10
STREAM_THROTTLE_MS        = 50

# ─── V9-02-B Boucle de correction (opt-in) ────────────────────────────────
CORRECTION_LOOP_ENABLED   = False
LLM_MAX_CORRECTION_RETRIES = 2
LLM_GENERATION_MAX_TOTAL_SEC = 120

# ─── V9-02-C AST context ───────────────────────────────────────────────────
SPEC_AST_MAX_SYMBOLS      = 20

# ─── V9-03-A Repository-RAG ────────────────────────────────────────────────
REPO_RAG_MAX_FILES        = 5
REPO_RAG_MAX_LINES        = 80
AST_INDEX_CACHE_TTL       = 3600              # 300 si < 24 Go (hardware_profile)

# ─── V9-03-B Web search auto ───────────────────────────────────────────────
ARCHITECT_WEB_SEARCH_ENABLED = True

# ─── V9-03-C HyDE ──────────────────────────────────────────────────────────
MEMORY_HYDE_ENABLED       = False

# ─── V9-04-A Training ──────────────────────────────────────────────────────
TRAINING_OUTPUT_DIR       = "training_data"
TRAINING_MIN_SCORE        = 70
TRAINING_MIN_PAIRS        = 50

# ─── V9-04-B GRPO (expérimental V9.1 uniquement) ──────────────────────────
GRPO_EXPERIMENTAL_ENABLED = False             # Nécessite 32 Go + nuitée CPU

# ─── V9-05-A QAAgent ───────────────────────────────────────────────────────
QA_SCAN_INTERVAL_HOURS    = 24
QA_DEBT_THRESHOLD_WARN    = 7
QA_DEBT_THRESHOLD_CRIT    = 10

# ─── V9-05-B DocAgent ──────────────────────────────────────────────────────
DOCAGENT_AUTO_CONFIRM     = False

# ─── V9-05-C HITL ──────────────────────────────────────────────────────────
HITL_ENABLED              = False

# ─── V9-05-E Mémoire épisodique ────────────────────────────────────────────
EPISODIC_DB_PATH          = "memory/episodic.sqlite"

# ─── V9-05-F TTS ───────────────────────────────────────────────────────────
TTS_ENABLED               = False
TTS_ENGINE                = "kokoro"           # "pyttsx3" si < 24 Go
TTS_VOICE                 = "fr_f"

# ─── Transversal Safe Mode ─────────────────────────────────────────────────
LCCA_SAFE_MODE            = True              # Désactive features lourdes au démarrage
```

---

## 11. Tests requis V9

| Suite | Fichier | Cas critiques | Priorité |
|-------|---------|---------------|----------|
| Pool | `test_llm_generator_pool.py` | `test_pool_limits_max_3_models` / `test_evict_lru` / `test_unload` | CRITIQUE |
| Boucle | `test_llm_generator.py` | `test_correction_loop_disabled_by_default` / `test_timeout_global_120s` | CRITIQUE |
| RAG | `test_coder_agent.py` | `test_ast_cache_ttl` / `test_ast_cache_invalidated_on_commit` / `test_retrieve_empty_stopwords` | HAUTE |
| HyDE | `test_memory_engine.py` | `test_hyde_requires_generator` / `test_hyde_fallback_if_disabled` | HAUTE |
| SFT | `test_training_collector.py` | `test_collect_empty_memory` / `test_export_creates_files` / `test_is_usable_quality_threshold` | HAUTE |
| QA | `test_qa_agent.py` | `test_rule_hardcoded_python_critique` / `test_rule_file_too_large` / `test_schedule_no_crash` | HAUTE |
| TTS | `test_tts_engine.py` | `test_disabled_no_call` / `test_pyttsx3_fallback_silent` | MOYENNE |
| Episodic | `test_episodic_memory.py` | `test_add_and_query` / `test_fts_search` | MOYENNE |
| Hardware | `test_hardware_profile.py` | `test_profile_24gb` / `test_profile_below_16gb` | MOYENNE |
| Régressions | tous V8 | 525 tests V8 toujours green | BLOQUANT |

---

## 12. Priorités & roadmap

| Priorité | Sprint | Titre | Effort | Valeur |
|----------|--------|-------|--------|--------|
| **P0** | V9-01-A | keep_alive + Q4_K_M | 0.5j | -40% latence |
| **P0** | V9-01-B | Tri-modèle + Pool LRU | 1j | -67% latence llm_chat |
| **P0** | V9-02-A | Few-shot SkillLibrary | 1j | +30% conformité code |
| **P0** | V9-02-B | Boucle de correction (opt-in) | 1j | +20% qualité (opt) |
| **P1** | V9-03-A | Repository-RAG CoderAgent | 1j | -imports manquants |
| **P1** | V9-02-C | AST context SpecGenerator | 1j | Specs avec vraies signatures |
| **P1** | V9-03-B | Web search auto ArchitectAgent | 1.5j | Libs externes correctes |
| **P1** | V9-02-D | JSON mode Ollama | 0.5j | +fiabilité validation |
| **P2** | V9-04-A | Collecteur SFT | 1.5j | Base données fine-tuning |
| **P2** | V9-04-D | PromptTuner | 0.5j | +qualité via ICL |
| **P2** | V9-05-A | QAAgent autonome | 2j | Dette détectée auto |
| **P2** | V9-05-B | DocAgent | 1.5j | Doc auto post-commit |
| **P3** | V9-05-C | Pair Programmer HITL | 2j | Contrôle humain |
| **P3** | V9-05-D | Dashboard Analytics | 2j | Observabilité |
| **P3** | V9-03-C | HyDE | 1j | +recall ChromaDB |
| **P3** | V9-03-D | Doc retrieval erreur API | 1j | -erreurs API |
| **P4** | V9-05-E | Mémoire épisodique (SQLite) | 2j | Historique décisions |
| **P4** | V9-05-F | TTS Kokoro | 1j | Notifs vocales |
| **P4** | V9-01-C | Streaming universel | 1j | UX LLM lent |
| **P4** | Hardware | HardwareProfile auto | 0.5j | Adaptabilité |

---

## 13. Checklist de validation finale

### Bloquants techniques

- [ ] `LLMGeneratorPool` : LRU max 3, `unload()`, `clear()`, `health_check()`
- [ ] `CORRECTION_LOOP_ENABLED = False` par défaut, `LLM_GENERATION_MAX_TOTAL_SEC = 120`
- [ ] `generate()` respecte le flag et le timeout (arrêt dur)
- [ ] `CoderAgent._get_ast_index()` : cache TTL configurable, invalidation git
- [ ] `search_hyde()` : jamais d'instanciation LLMGenerator interne
- [ ] `TrainingDataCollector` : silencieux si MemoryEngine indisponible
- [ ] `PromptTuner` : aucun import `torch` ni `unsloth`
- [ ] `EpisodicMemory` : `sqlite3` stdlib uniquement (pas duckdb)
- [ ] `TTSEngine` : `pyttsx3` fallback silencieux si Kokoro absent
- [ ] `LCCA_SAFE_MODE = True` désactive : boucle correction, web auto, DocAgent, TTS

### Qualité

- [ ] 525 tests V8 restent verts (0 régression)
- [ ] Tous les nouveaux modules : `try/except Exception` global sur les opérations réseau
- [ ] Tous les nouveaux modules : `from __future__ import annotations`
- [ ] Tous les fichiers Python : encodage `utf-8-sig`
- [ ] `sys.executable` partout (jamais `"python"` hardcodé)
- [ ] `safe_path()` avant toute opération disque MCP
- [ ] Docstrings en français technique sur toutes les classes et méthodes publiques

### Hardware

- [ ] `hardware_profile.py` : détection RAM auto via `psutil`
- [ ] `LLM_POOL_MAX_LOADED = 2` si < 24 Go
- [ ] `AST_INDEX_CACHE_TTL = 300` si < 24 Go
- [ ] `TTS_ENGINE = "pyttsx3"` si < 24 Go
- [ ] `OLLAMA_QUANT_LEVEL_HEAVY = "Q5_K_M"` documenté (option manuelle 32 Go)

### Opérationnel

- [ ] Commandes `ollama pull` documentées pour 3b + Q4_K_M + Q5_K_M
- [ ] `scripts/start-tts.ps1` présent si TTS activé
- [ ] `scripts/post-commit.ps1` : ASCII pur (pas d'accent, PowerShell CP1252)
- [ ] Nouveau tool MCP `get_analytics` dans `mcp_tools_schema.py` + `mcp_server.py` handler_map

---

*Document généré par analyse automatique — LCCA V9 SPEC FINAL — 2026-04-20*
<!-- AI-READY END -->
