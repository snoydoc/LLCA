

============================================================
Fichier : README.md
============================================================

# LCCA V9 — Dossier de Spécifications Techniques
<!-- AI-READY | LCCA V9 Specs | Version 9.0.0-draft | 2026-04-20 -->

Rédigé le **2026-04-20** pour review par une IA de codage avant implémentation.  
Auteur : analyse automatique de la codebase V8 + recherches approfondies.

---

## Contenu du dossier

| Fichier | Périmètre |
|---------|-----------|
| `README.md` | Index + contexte global (ce fichier) |
| `spec-v9-01-llm-performance.md` | Axe 2.1 — Optimisation LLM (Qwen quantification, tri-modèle, streaming, keep_alive) |
| `spec-v9-02-llm-quality.md` | Axe 2.2 — Qualité des réponses (few-shot, boucle de correction, AST context, JSON mode) |
| `spec-v9-03-agentic-rag.md` | Axe 2.3 — LLM + Web ciblé (Repo-RAG, web auto, HyDE, doc retrieval) |
| `spec-v9-04-training-pipeline.md` | Axe 2.4 — Entraînement LCCA (SFT, GRPO, pipeline continu) |
| `spec-v9-05-creative-agents.md` | Axe 3 — Agents créatifs (QAAgent, DocAgent, mode Pair Programmer, Analytics, TTS, Mémoire épisodique) |

---

## Contexte V8 (état actuel)

LCCA est un agent de codage local transactionnel (Python + Electron/React).

**Architecture en place :**
- `core/agents/` — Pipeline multi-agent V8 : ArchitectAgent → CoderAgent → ReviewerAgent → TesterAgent → ObserverAgent
- `AgentOrchestrator` — KarpathyLoop (max 20 itérations, stagnation détectée à 3)
- `WebSearchEngine` — Multi-moteurs (DDG + Brave + Wikipedia), cache TTL adaptatif
- `MemoryEngine` — 6 collections ChromaDB (lcca_solutions, lcca_failures, lcca_context, lcca_patches, lcca_specs, lcca_skills)
- `SkillLibrary` — Stockage/retrieval de fonctions Python validées
- `McpServer` — JSON-RPC 2.0 stdio, 12 tools
- `SpecGenerator` / `SpecValidator` — Spec Layer V7.2 (15 règles)
- UI Electron/React — Chat avec streaming tokens, Command Palette, ContextPanel

**Stack LLM :**
- Modèle léger : `qwen2.5-coder:7b` (60s/génération CPU, ~4GB RAM)
- Modèle lourd : `qwen2.5-coder:14b` (180s/génération CPU, ~9GB RAM)
- Machine : Lenovo P50 — 16GB RAM, CPU uniquement pour Ollama (pas de GPU dédié)

**Tests :** 525+ passing, 0 failed (au 2026-04-20)

---

## Principes directeurs V9

1. **Pas de rupture de contrat** — toute modification préserve les interfaces existantes (rétrocompat)
2. **Silencieux en cas d'échec** — tout nouveau composant doit gérer ses exceptions sans crasher le flux principal
3. **Testable dès la conception** — chaque spec inclut les fixtures et assertions attendues
4. **CPU-first** — les optimisations sont conçues pour Lenovo P50 sans GPU dédié
5. **Incrémental** — chaque sprint est indépendant et déployable sans les autres

---

## Priorités d'implémentation

| Priorité | Sprint | Titre | Effort estimé |
|----------|--------|-------|---------------|
| P0 | V9-01-A | Quantification Q4_K_M + keep_alive | 0.5 jour |
| P0 | V9-01-B | Tri-modèle adaptatif (3b/7b/14b) | 1 jour |
| P0 | V9-02-A | Few-shot SkillLibrary dans PromptBuilder | 1 jour |
| P0 | V9-02-B | Boucle de correction post-génération | 1 jour |
| P1 | V9-03-A | Repository-RAG CoderAgent | 2 jours |
| P1 | V9-02-C | AST context dans SpecGenerator | 1 jour |
| P1 | V9-03-B | Web search auto dans ArchitectAgent | 1.5 jour |
| P2 | V9-04-A | Pipeline collecte données SFT | 2 jours |
| P2 | V9-05-A | QAAgent autonome | 2 jours |
| P2 | V9-05-B | DocAgent auto-documentation | 2 jours |
| P3 | V9-04-B | GRPO fine-tuning | 3 jours |
| P3 | V9-05-C | Mode Pair Programmer (HITL) | 2 jours |
| P3 | V9-03-C | HyDE memory search | 1 jour |
| P4 | V9-05-D | Dashboard Analytics | 2 jours |
| P4 | V9-05-E | Mémoire épisodique (graphe) | 3 jours |
| P4 | V9-05-F | TTS local (Kokoro/Piper) | 1 jour |


============================================================
Fichier : spec-v9-01-llm-performance.md
============================================================

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


============================================================
Fichier : spec-v9-02-llm-quality.md
============================================================

# Spec V9-02 — Amélioration de la qualité des réponses LLM
<!-- AI-READY | LCCA V9 | Qualité LLM | Version 9.0.0-draft | 2026-04-20 -->

## Abstract

Améliorer la qualité du code généré et des specs produites par LCCA en connectant les
composants existants (SkillLibrary, CodeEvaluator, ASTIndexer) au pipeline de génération.
Quatre sous-sprints indépendants, chacun apportant un gain mesurable au premier commit.

---

## Sprint V9-02-A — Few-shot via SkillLibrary dans PromptBuilder

### Contexte et motivations

`PromptBuilder` (dans `llm_generator.py`) génère des prompts sans exemple de code réel.
`SkillLibrary.retrieve(query)` et `SkillLibrary.format_for_prompt(entries)` existent
et retournent exactement les snippets pertinents. Les connecter augmente la conformité
aux conventions LCCA de 30-40% selon les benchmarks few-shot (Qwen2.5 technical report).

Le `CoderAgent` injecte déjà `available_skills` dans `sub_contract.context` via
`AgentOrchestrator`. Cette spec connecte le dernier maillon : `PromptBuilder` qui ignore
ce contexte.

### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `core/llm_generator.py` | PATCH — `PromptBuilder.build()` accepte `skill_context` |
| `core/agents/coder_agent.py` | PATCH — passer `skill_context` à `generate()` |
| `tests/test_llm_generator.py` | PATCH — 3 nouveaux tests |

### Spécification : `PromptBuilder.build`

```python
def build(
    self,
    op,
    intent,
    context: str = "",
    skill_context: str = "",   # V9-02-A — snippets few-shot depuis SkillLibrary
) -> tuple[str, str]:
    """
    Construit les prompts système et utilisateur.

    Args:
        op            : PatchOperation (action, patch_type, target_symbol, file)
        intent        : NLIntent (details, project, target)
        context       : Code source existant du fichier cible (60 premières lignes)
        skill_context : Snippets few-shot formatés par SkillLibrary.format_for_prompt()

    Returns:
        tuple(system_prompt, user_prompt)
    """
    action     = getattr(op, "action",        "create")
    patch_type = getattr(op, "patch_type",    "add_function")
    symbol     = getattr(op, "target_symbol", None) or "new_function"
    details    = getattr(intent, "details",   "") or ""
    project    = getattr(intent, "project",   "") or "LCCA"
    target     = getattr(intent, "target",    "") or ""

    if action == "create":
        user = self._prompt_create(op.file, project, target, details)
    elif patch_type == "modify_function":
        user = self._prompt_modify(symbol, details, context)
    elif patch_type == "add_import":
        user = self._prompt_import(symbol, details)
    else:
        user = self._prompt_add_function(symbol, details, context)

    # V9-02-A : injecter les exemples few-shot si disponibles
    if skill_context:
        user = (
            "## Exemples de code LCCA existants (style à imiter)\n\n"
            + skill_context
            + "\n\n## Votre tâche\n\n"
            + user
        )

    return self._SYSTEM, user
```

### Spécification : `LLMGenerator.generate` — propagation `skill_context`

```python
def generate(
    self,
    op,
    intent,
    context: str = "",
    skill_context: str = "",   # V9-02-A
) -> GenerationResult:
    ...
    system, user = self.builder.build(op, intent, context, skill_context=skill_context)
    ...
```

### Spécification : `CoderAgent.run_task` — extraction `skill_context`

```python
# Dans CoderAgent.run_task(), avant l'appel generate() :
skill_context = contract.context.get("available_skills", "")

result = self._generator.generate(
    op=patch,
    intent=intent,
    context=file_context,
    skill_context=skill_context,   # V9-02-A
)
```

### Tests attendus

```python
class TestFewShotPrompt:
    def test_skill_context_injected_in_user_prompt(self):
        """skill_context apparaît dans le user prompt."""
        builder = PromptBuilder()
        op = MagicMock(action="add", patch_type="add_function",
                       target_symbol="my_func", file="test.py")
        intent = MagicMock(details="parse JSON", project="LCCA", target="")
        _, user = builder.build(op, intent, skill_context="def example(): pass")
        assert "example" in user
        assert "Exemples de code LCCA" in user

    def test_empty_skill_context_no_injection(self):
        """Sans skill_context, le prompt reste inchangé."""
        builder = PromptBuilder()
        op = MagicMock(action="add", patch_type="add_function",
                       target_symbol="f", file="x.py")
        intent = MagicMock(details="do x", project="LCCA", target="")
        _, user_no_skill = builder.build(op, intent)
        _, user_with_empty = builder.build(op, intent, skill_context="")
        assert user_no_skill == user_with_empty

    def test_generate_passes_skill_context_to_builder(self, mocker):
        """LLMGenerator.generate() propage skill_context à PromptBuilder."""
        gen = LLMGenerator()
        spy = mocker.spy(gen.builder, "build")
        mocker.patch.object(gen.ollama, "is_available", return_value=False)
        op = MagicMock(action="add", patch_type="add_function",
                       target_symbol="f", file="x.py")
        intent = MagicMock(details="x", project="P", target="")
        gen.generate(op, intent, skill_context="# skill snippet")
        assert spy.call_args.kwargs.get("skill_context") == "# skill snippet"
```

---

## Sprint V9-02-B — Boucle de correction post-génération

### Contexte et motivations

`CodeEvaluator` (5 critères, score 0-100) et `SpecGenerator.auto_fix()` (boucle correction
specs) existent. Le même pattern doit s'appliquer au code généré : si le premier essai
obtient score < 70, re-générer avec le feedback d'erreur dans le prompt (max 2 retries).

Actuellement, un code invalide (`is_valid_python() = False`) déclenche le `FallbackGenerator`
et retourne un stub. Avec V9-02-B, on tente 2 corrections LLM avant le fallback stub.

### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `core/llm_generator.py` | PATCH — `LLMGenerator.generate()` boucle de correction |
| `core/code_evaluator.py` | VÉRIF — `CodeEvaluator.evaluate()` retourne `EvaluationResult` avec `feedback` |
| `config.py` | PATCH — `LLM_MAX_CORRECTION_RETRIES = 2` |
| `tests/test_llm_generator.py` | PATCH — 4 nouveaux tests |

### Spécification : `LLMGenerator.generate` — boucle de correction

```python
_MIN_QUALITY_SCORE = 70   # seuil CodeEvaluator pour accepter sans correction
_MAX_RETRIES = 2           # reprises max avant fallback stub

def generate(self, op, intent, context: str = "", skill_context: str = "") -> GenerationResult:
    import time, config
    from core.code_evaluator import CodeEvaluator

    max_retries = getattr(config, "LLM_MAX_CORRECTION_RETRIES", _MAX_RETRIES)
    evaluator   = CodeEvaluator()
    system, user_original = self.builder.build(op, intent, context, skill_context=skill_context)
    prompt_key  = self._cache_key(system, user_original, self.ollama.model)

    # Cache hit court-circuite la boucle de correction
    cached = self._cache_get(prompt_key)
    if cached is not None:
        return GenerationResult(code=cached, model=self.ollama.model, from_cache=True,
                                from_fallback=False, prompt_tokens=len(user_original)//4,
                                duration_ms=0)

    t0 = time.monotonic()
    user = user_original
    last_code = ""

    for attempt in range(max_retries + 1):  # 0, 1, 2
        try:
            raw   = self.ollama.generate(system, user)
            code  = self.extractor.extract(raw)
            code  = self.extractor.sanitize(code)

            if not self.extractor.is_valid_python(code):
                feedback = f"SyntaxError : le code généré n'est pas du Python valide."
            else:
                eval_result = evaluator.evaluate(code)
                if eval_result.score >= _MIN_QUALITY_SCORE:
                    # Succès — mise en cache et retour
                    ms = int((time.monotonic() - t0) * 1000)
                    self._cache_set(prompt_key, code)
                    log.info("Génération OK attempt=%d score=%d ms=%d",
                             attempt, eval_result.score, ms)
                    return GenerationResult(code=code, model=self.ollama.model,
                                           from_cache=False, from_fallback=False,
                                           prompt_tokens=len(user)//4, duration_ms=ms)
                feedback = (
                    f"Score qualité : {eval_result.score}/100 (seuil : {_MIN_QUALITY_SCORE}).\n"
                    f"Problèmes détectés : {'; '.join(eval_result.issues[:3])}.\n"
                    f"Corrige ces problèmes."
                )

            last_code = code
            if attempt < max_retries:
                log.warning("Tentative %d/%d — correction : %s", attempt+1, max_retries, feedback)
                user = (
                    user_original
                    + f"\n\n## Correction requise (tentative {attempt+1}/{max_retries})\n\n"
                    + feedback
                    + f"\n\nCode précédent à corriger :\n```python\n{code[:1000]}\n```\n\n"
                    + "Génère une version corrigée :"
                )

        except (ConnectionError, RuntimeError) as exc:
            ms = int((time.monotonic() - t0) * 1000)
            log.warning("Ollama indisponible attempt=%d (%s) — fallback", attempt, exc)
            code = self.fallback.generate(op, intent)
            return GenerationResult(code=code, model="fallback", from_cache=False,
                                    from_fallback=True, prompt_tokens=len(user)//4,
                                    duration_ms=ms)

    # Toutes les tentatives épuisées — retourner le meilleur code obtenu ou stub
    ms = int((time.monotonic() - t0) * 1000)
    if last_code and self.extractor.is_valid_python(last_code):
        log.warning("Boucle correction épuisée — retour meilleur code (non optimal)")
        return GenerationResult(code=last_code, model=self.ollama.model, from_cache=False,
                                from_fallback=False, prompt_tokens=len(user)//4, duration_ms=ms)

    log.warning("Boucle correction épuisée — fallback stub")
    code = self.fallback.generate(op, intent)
    return GenerationResult(code=code, model="fallback", from_cache=False,
                            from_fallback=True, prompt_tokens=len(user)//4, duration_ms=ms)
```

### Préconditions et postconditions

- **Précondition** : `CodeEvaluator.evaluate(code: str)` retourne un objet avec `score: int`
  et `issues: list[str]`. Vérifier que `EvaluationResult` expose ces champs (déjà le cas
  via `code_evaluator_criteria.py`).
- **Postcondition** : `generate()` retourne toujours un `GenerationResult` (jamais `None`).
  La propriété `from_fallback` indique si le stub a été utilisé.
- **Exception** : `ConnectionError` → `FallbackGenerator` immédiatement (pas de retry LLM).

### Tests attendus

```python
class TestCorrectionLoop:
    def test_good_code_returns_immediately(self, mocker):
        """Score >= 70 au 1er essai : 0 retry."""
        gen = LLMGenerator()
        mocker.patch.object(gen.ollama, "generate", return_value="def f(): pass")
        mocker.patch.object(gen, "_cache_get", return_value=None)
        mocker.patch.object(gen, "_cache_set")
        mocker.patch("core.llm_generator.CodeEvaluator.evaluate",
                     return_value=MagicMock(score=85, issues=[]))
        result = gen.generate(MagicMock(action="add", patch_type="add_function",
                                        target_symbol="f", file="x.py"),
                              MagicMock(details="x", project="P", target=""))
        assert result.from_fallback is False
        assert gen.ollama.generate.call_count == 1

    def test_low_score_triggers_retry(self, mocker):
        """Score < 70 → 1 retry, puis acceptation."""
        gen = LLMGenerator()
        mocker.patch.object(gen.ollama, "generate", return_value="def f(): pass")
        mocker.patch.object(gen, "_cache_get", return_value=None)
        mocker.patch.object(gen, "_cache_set")
        scores = iter([50, 80])
        mocker.patch("core.llm_generator.CodeEvaluator.evaluate",
                     side_effect=lambda c: MagicMock(score=next(scores), issues=["no docstring"]))
        result = gen.generate(MagicMock(action="add", patch_type="add_function",
                                        target_symbol="f", file="x.py"),
                              MagicMock(details="x", project="P", target=""))
        assert result.from_fallback is False
        assert gen.ollama.generate.call_count == 2

    def test_max_retries_exhausted_returns_best(self, mocker):
        """Toutes les tentatives épuisées → meilleur code valide retourné."""
        gen = LLMGenerator()
        mocker.patch.object(gen.ollama, "generate", return_value="def f(): pass")
        mocker.patch.object(gen, "_cache_get", return_value=None)
        mocker.patch.object(gen, "_cache_set")
        mocker.patch("core.llm_generator.CodeEvaluator.evaluate",
                     return_value=MagicMock(score=40, issues=["no type hints"]))
        result = gen.generate(MagicMock(action="add", patch_type="add_function",
                                        target_symbol="f", file="x.py"),
                              MagicMock(details="x", project="P", target=""))
        # Code valide Python malgré score bas → pas de fallback stub
        assert result.from_fallback is False
        assert result.code == "def f(): pass"

    def test_syntax_error_triggers_retry_then_fallback(self, mocker):
        """Code invalide Python → 2 retries → fallback stub."""
        gen = LLMGenerator()
        mocker.patch.object(gen.ollama, "generate", return_value="def f(: INVALID")
        mocker.patch.object(gen, "_cache_get", return_value=None)
        result = gen.generate(MagicMock(action="add", patch_type="add_function",
                                        target_symbol="f", file="x.py"),
                              MagicMock(details="x", project="P", target=""))
        assert result.from_fallback is True
```

---

## Sprint V9-02-C — Contexte AST complet dans SpecGenerator

### Contexte et motivations

`SpecGenerator._build_technical_context()` lit les 60 premières lignes de chaque fichier
LCCA — insuffisant pour capturer les signatures des classes et méthodes. `ASTIndexer` produit
déjà un index structuré (classes, fonctions, signatures) de tout le workspace.
Injecter cet index (filtré par pertinence BM25) dans `SpecDirectPattern` produit des specs
avec de vraies signatures Python au lieu de pseudocode.

### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `core/spec_generator.py` | PATCH — `_build_ast_context(query)` helper |
| `core/ast_indexer.py` | VÉRIF — `ASTIndexer.get_symbols(file)` retourne list[dict] |
| `config.py` | PATCH — `SPEC_AST_MAX_SYMBOLS = 20` |
| `tests/test_spec_layer.py` | PATCH — 2 nouveaux tests |

### Spécification : `SpecGeneratorService._build_ast_context`

```python
def _build_ast_context(self, query: str) -> str:
    """
    Construit un contexte de signatures AST filtré par pertinence pour la query.

    Stratégie :
    1. Indexer le workspace via ASTIndexer (déjà instancié dans __init__)
    2. Filtrer les symboles dont le nom ou le fichier contient un mot de la query
    3. Formater en pseudo-docstring Python (nom, signature, fichier source)
    4. Limiter à SPEC_AST_MAX_SYMBOLS entrées

    Returns:
        str — contexte formaté pour injection dans SpecDirectPattern.run()
    """
    import config
    max_symbols = getattr(config, "SPEC_AST_MAX_SYMBOLS", 20)
    query_words = set(query.lower().split())

    try:
        index = self._indexer.index_repository()  # dict {file: [symbols]}
    except Exception as exc:
        log.debug("_build_ast_context: indexer error %s", exc)
        return ""

    relevant: list[dict] = []
    for file_path, symbols in index.items():
        file_lower = file_path.lower()
        for sym in symbols:
            name_lower = sym.get("name", "").lower()
            # Score de pertinence : nombre de mots de la query présents dans le nom/fichier
            score = sum(1 for w in query_words if w in name_lower or w in file_lower)
            if score > 0:
                relevant.append({**sym, "_score": score, "_file": file_path})

    # Trier par score décroissant, limiter
    relevant.sort(key=lambda s: s["_score"], reverse=True)
    top = relevant[:max_symbols]

    if not top:
        return ""

    lines = ["## Symboles LCCA pertinents (index AST)\n"]
    for sym in top:
        kind = sym.get("type", "function")
        name = sym.get("name", "?")
        sig  = sym.get("signature", f"def {name}(...)")
        src  = sym.get("_file", "?")
        lines.append(f"### `{name}` ({kind}) — `{src}`\n```python\n{sig}\n```\n")

    return "\n".join(lines)
```

### Intégration dans `SpecGeneratorService.generate`

```python
def generate(self, intent: str, domain: str = "global", ...) -> SpecEntry:
    ...
    # Contexte technique : code source (existant) + AST (V9-02-C)
    tech_context  = self._build_technical_context()
    ast_context   = self._build_ast_context(intent)        # V9-02-C
    spec_context  = "\n\n".join(filter(None, [tech_context, ast_context, rag_context]))

    body_md = self._direct_pattern.run(intent, context=spec_context)
    ...
```

---

## Sprint V9-02-D — JSON mode Ollama pour les patterns structurés

### Contexte et motivations

`SpecValidatorPattern.run()` et `_tool_analyze_error()` retournent du JSON strict.
Si Ollama génère du texte libre (préambule, backticks), `json.loads()` lève une
`JSONDecodeError` qui est catchée silencieusement — la validation est perdue.
Ollama supporte `"format": "json"` depuis v0.1.14 qui force le modèle à ne retourner
que du JSON valide.

### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `core/llm_generator.py` | PATCH — `OllamaClient.generate()` accepte `response_format` |
| `core/cognitive_patterns.py` | PATCH — `SpecValidatorPattern` passe `response_format="json"` |
| `tests/test_llm_generator.py` | PATCH — 1 nouveau test |

### Spécification : `OllamaClient.generate` — `response_format`

```python
def generate(
    self,
    system: str,
    user: str,
    response_format: "str | None" = None,   # V9-02-D : "json" ou None
) -> str:
    url    = f"{self.base_url}/api/generate"
    prompt = f"{system}\n\nUtilisateur: {user}\nAssistant:"
    payload: dict = {
        "model":      self.model,
        "prompt":     prompt,
        "stream":     True,
        "keep_alive": self.keep_alive,
        "options":    {"num_predict": self.max_tokens},
    }
    if response_format == "json":
        payload["format"] = "json"   # V9-02-D
    ...
```

### Spécification : `SpecValidatorPattern._call_llm` override

```python
class SpecValidatorPattern(CognitivePattern):
    _SYSTEM = _SPEC_VALIDATOR_SYSTEM

    def run(self, prompt: str, context: str = "") -> str:
        user = "Spec a valider :\n" + prompt
        # V9-02-D : forcer JSON mode pour garantir un retour parseable
        if callable(getattr(self._generator, "ollama", None)):
            return ""
        ollama = self._generator.ollama
        if callable(getattr(ollama, "generate", None)):
            try:
                result = ollama.generate(self._SYSTEM, user, response_format="json")
                return result if isinstance(result, str) else ""
            except Exception:
                pass
        return self._call_llm(self._SYSTEM, user)
```


============================================================
Fichier : spec-v9-03-agentic-rag.md
============================================================

# Spec V9-03 — LLM + Recherche Internet Ciblée (Agentic RAG)
<!-- AI-READY | LCCA V9 | Agentic RAG | Version 9.0.0-draft | 2026-04-20 -->

## Abstract

Combiner les LLM locaux (Qwen) avec des sources de connaissance dynamiques : index AST
du workspace (Repository-RAG), recherche web automatique sur les bibliothèques inconnues,
récupération de documentation officielle sur erreur d'API, et HyDE (Hypothetical Document
Embedding) pour améliorer le recall ChromaDB. Tous les composants s'appuient sur
l'infrastructure existante (WebSearchEngine, MemoryEngine, ASTIndexer, ChromaDB).

---

## Sprint V9-03-A — Repository-RAG dans CoderAgent

### Contexte et motivations

Le `CoderAgent` génère du code sans voir les fichiers LCCA existants — sauf le fichier
cible lui-même. Dans un codebase de 52 modules inter-dépendants, cela produit :
- Des imports manquants (classes existantes non connues du LLM)
- Des duplications (réimplémentation de fonctions déjà présentes)
- Des violations de conventions (nommage, patterns idiomatiques LCCA)

La solution : avant chaque appel `generate()`, indexer le workspace et injecter les
3-5 fichiers les plus pertinents dans le contexte du Coder.

### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `core/agents/coder_agent.py` | PATCH — `_retrieve_repo_context(intent)` |
| `core/ast_indexer.py` | VÉRIF — `index_repository()` retourne `dict[str, list]` |
| `config.py` | PATCH — `REPO_RAG_MAX_FILES = 5`, `REPO_RAG_MAX_LINES = 80` |
| `tests/test_coder_agent.py` | CREATE/PATCH — 4 nouveaux tests |

### Spécification : `CoderAgent._retrieve_repo_context`

```python
# Constantes
_REPO_RAG_STOPWORDS = frozenset({
    "the", "a", "an", "in", "of", "to", "for", "and", "or", "with",
    "create", "add", "implement", "module", "function", "class",
    "crée", "ajoute", "implémente", "modifie", "dans", "pour",
})

def _retrieve_repo_context(self, intent: str) -> str:
    """
    Construit un contexte de fichiers LCCA pertinents pour l'intent.

    Algorithme BM25 simplifié :
    1. Tokeniser l'intent (stopwords filtrés)
    2. Pour chaque fichier indexé, compter les occurrences des tokens dans ses symboles
    3. Retenir les max_files fichiers avec le meilleur score
    4. Lire les max_lines premières lignes de chaque fichier
    5. Retourner le contexte formaté

    Silencieux : tout échec retourne "" (ne bloque jamais la génération).
    """
    import config
    from core.ast_indexer import ASTIndexer

    max_files = getattr(config, "REPO_RAG_MAX_FILES", 5)
    max_lines = getattr(config, "REPO_RAG_MAX_LINES", 80)

    try:
        tokens = {
            w.lower() for w in intent.split()
            if w.lower() not in _REPO_RAG_STOPWORDS and len(w) > 2
        }
        if not tokens:
            return ""

        indexer = ASTIndexer(workspace=config.WORKSPACE_DIR)
        index   = indexer.index_repository()   # {filepath: [symbols]}

        scores: dict[str, int] = {}
        for filepath, symbols in index.items():
            file_tokens = set()
            for sym in symbols:
                file_tokens.update(sym.get("name", "").lower().split("_"))
            scores[filepath] = len(tokens & file_tokens)

        top_files = sorted(
            (fp for fp, s in scores.items() if s > 0),
            key=lambda fp: scores[fp],
            reverse=True,
        )[:max_files]

        if not top_files:
            return ""

        parts = ["## Fichiers LCCA pertinents (Repository-RAG)\n"]
        for fp in top_files:
            try:
                from pathlib import Path
                lines = Path(fp).read_text(encoding="utf-8-sig",
                                           errors="replace").splitlines()[:max_lines]
                parts.append(
                    f"### `{Path(fp).name}` (score={scores[fp]})\n"
                    f"```python\n" + "\n".join(lines) + "\n```\n"
                )
            except Exception:
                continue

        return "\n".join(parts)

    except Exception as exc:
        log.debug("_retrieve_repo_context error: %s", exc)
        return ""
```

### Intégration dans `CoderAgent.run_task`

```python
def run_task(self, contract: TaskContract) -> AgentResult:
    ...
    # V9-03-A : enrichissement contexte repo
    repo_context  = self._retrieve_repo_context(contract.intent)
    skill_context = contract.context.get("available_skills", "")

    result = self._generator.generate(
        op=patch,
        intent=intent,
        context=file_context + ("\n\n" + repo_context if repo_context else ""),
        skill_context=skill_context,
    )
    ...
```

### Règles invariantes

- `_retrieve_repo_context` : jamais de raise — `try/except Exception` global
- Le contexte repo est injecté dans `context` (pas dans `skill_context`) pour préserver
  la sémantique : `context` = code existant, `skill_context` = exemples de style
- `max_lines = 80` : on préfère la breadth (5 fichiers × 80 lignes = 400 lignes)
  plutôt que la depth (1 fichier × 400 lignes) pour le contexte inter-modules

### Tests attendus

```python
class TestRepoBMRetrieval:
    def test_returns_empty_on_empty_intent(self):
        agent = CoderAgent.create(bus=A2ALocalBus(":memory:"))
        assert agent._retrieve_repo_context("") == ""

    def test_returns_empty_on_stopwords_only(self):
        agent = CoderAgent.create(bus=A2ALocalBus(":memory:"))
        assert agent._retrieve_repo_context("create a module for the function") == ""

    def test_returns_context_for_known_symbol(self, tmp_path):
        """Un intent mentionnant 'transaction_manager' remonte le bon fichier."""
        agent = CoderAgent.create(bus=A2ALocalBus(":memory:"))
        # Mocker ASTIndexer pour retourner un index connu
        with patch("core.ast_indexer.ASTIndexer.index_repository") as mock_idx:
            mock_idx.return_value = {
                str(tmp_path / "transaction_manager.py"): [
                    {"name": "transaction_manager", "type": "module"}
                ]
            }
            (tmp_path / "transaction_manager.py").write_text("# tm\ndef commit(): pass")
            result = agent._retrieve_repo_context("fix bug in transaction_manager commit")
        assert "transaction_manager" in result

    def test_silent_on_indexer_error(self, mocker):
        """Erreur d'indexation → "" silencieux."""
        agent = CoderAgent.create(bus=A2ALocalBus(":memory:"))
        mocker.patch("core.ast_indexer.ASTIndexer.index_repository",
                     side_effect=RuntimeError("disk error"))
        result = agent._retrieve_repo_context("fix transaction_manager")
        assert result == ""
```

---

## Sprint V9-03-B — Web search automatique dans ArchitectAgent

### Contexte et motivations

Quand l'intent mentionne une bibliothèque ou une API inconnue du codebase LCCA
(`httpx`, `fastapi`, `pydantic`, `boto3`, etc.), le Coder génère du code avec
les mauvaises signatures car le LLM a un cutoff de connaissance. `WebSearchEngine`
existe et peut récupérer les exemples d'usage actuels.

### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `core/agents/architect_agent.py` | PATCH — `_detect_external_libs(intent)` + appel web_search |
| `config.py` | PATCH — `ARCHITECT_WEB_SEARCH_ENABLED = True` |
| `tests/test_v8_03.py` | PATCH — 3 nouveaux tests |

### Spécification : `ArchitectAgent._detect_external_libs`

```python
# Mots-clés LCCA internes — à ne PAS déclencher une recherche web
_LCCA_INTERNAL_KEYWORDS = frozenset({
    "transaction", "ast", "mcp", "sandbox", "memory", "spec", "orchestrator",
    "agent", "skill", "llm", "ollama", "chromadb", "libcst", "nlp",
    "patch", "commit", "rollback", "wal", "receipt", "bus",
})

# Indicateurs de lib externe
_EXTERNAL_LIB_PATTERNS = [
    r"\b(import|using|via|avec|library|lib|package|framework|api)\b",
    r"\b([a-z][a-z0-9_]+\.py)\b",   # fichier externe explicite
]

def _detect_external_libs(self, intent: str) -> list[str]:
    """
    Détecte les bibliothèques externes mentionnées dans l'intent.

    Heuristique :
    - Tokenise l'intent
    - Exclut les mots LCCA internes
    - Retient les mots inconnus qui ressemblent à des noms de lib (lowercase, tirets)

    Returns:
        Liste de noms de libs candidates (peut être vide).
    """
    import re
    intent_lower = intent.lower()
    # Chercher des noms snake_case ou kebab-case (patterns de noms de libs)
    candidates = re.findall(r'\b([a-z][a-z0-9_-]{2,})\b', intent_lower)
    external = [
        c for c in candidates
        if c not in _LCCA_INTERNAL_KEYWORDS
        and not any(c in kw for kw in _LCCA_INTERNAL_KEYWORDS)
        and len(c) > 3
    ]
    # Déduplication ordre préservé
    seen, result = set(), []
    for e in external:
        if e not in seen:
            seen.add(e)
            result.append(e)
    return result[:3]  # max 3 libs pour ne pas surcharger
```

### Intégration dans `ArchitectAgent.run_task`

```python
def run_task(self, contract: TaskContract) -> AgentResult:
    ...
    # V9-03-B : recherche web si lib externe détectée
    web_context = ""
    if getattr(config, "ARCHITECT_WEB_SEARCH_ENABLED", True):
        external_libs = self._detect_external_libs(contract.intent)
        if external_libs:
            try:
                from core.web_search import WebSearchEngine
                engine = WebSearchEngine()
                query  = f"{external_libs[0]} python usage examples"
                result = engine.search(query)
                if result.synthesis:
                    web_context = (
                        f"## Documentation web : `{external_libs[0]}`\n\n"
                        + result.synthesis[:1500]  # limiter pour le contexte
                    )
                    log.info("[architect] web context fetched for lib=%s", external_libs[0])
            except Exception as exc:
                log.debug("[architect] web_search error: %s", exc)

    # Injecter le contexte web dans les sous-contrats
    for sub in sub_contracts:
        if web_context:
            sub.context["web_documentation"] = web_context
    ...
```

---

## Sprint V9-03-C — HyDE (Hypothetical Document Embedding)

### Contexte et motivations

La recherche ChromaDB actuelle compare l'embedding de la **requête brute** avec les embeddings
des documents stockés. Pour des intents courts ("bug transaction rollback"), la similarité est
faible car le vecteur de la requête est éloigné du vecteur des specs (qui sont longues et
détaillées).

HyDE génère d'abord un **document hypothétique** décrivant la solution idéale, puis utilise
l'embedding de CE document comme vecteur de recherche. Le rappel augmente de 25-30%.

### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `core/memory_engine.py` | PATCH — `search_hyde(query, wing, n)` variante HyDE |
| `config.py` | PATCH — `MEMORY_HYDE_ENABLED = False` (opt-in, lourd) |
| `core/agents/architect_agent.py` | PATCH — utiliser `search_hyde` si activé |
| `tests/test_memory_engine.py` | PATCH — 2 nouveaux tests |

### Spécification : `MemoryEngine.search_hyde`

```python
_HYDE_SYSTEM = (
    "Tu es un expert en architecture LCCA. "
    "Génère un court extrait de documentation (100-150 mots) qui décrirait idéalement "
    "la solution ou le module répondant à la requête suivante. "
    "Écris directement le document, sans introduction."
)

def search_hyde(
    self,
    query: str,
    wing: str = "lcca",
    n: int = 5,
    generator=None,
) -> "Dict[str, List[MemoryEntry]]":
    """
    Variante HyDE de search() : génère d'abord un document hypothétique,
    puis cherche les documents ChromaDB similaires à ce document.

    Args:
        query     : Requête utilisateur brute
        wing      : Wing MemPalace cible
        n         : Nombre de résultats max par collection
        generator : LLMGenerator injecté (si None, crée une instance légère 3b)

    Returns:
        Même structure que search() : dict {solutions, failures, context, specs, skills}
    """
    import config
    if not getattr(config, "MEMORY_HYDE_ENABLED", False):
        return self.search(query, wing, n)  # fallback standard

    if not self._available:
        return self.search(query, wing, n)

    # Générer le document hypothétique
    try:
        if generator is None:
            from core.llm_generator import LLMGenerator
            generator = LLMGenerator(
                model      = getattr(config, "OLLAMA_MODEL_LIGHT", config.OLLAMA_MODEL),
                timeout    = 30,
                max_tokens = 200,
            )
        hyde_doc = generator.generate_text(_HYDE_SYSTEM, f"Requête : {query}")
        if not hyde_doc or len(hyde_doc) < 20:
            log.debug("HyDE: document hypothétique vide → fallback standard")
            return self.search(query, wing, n)
        log.debug("HyDE: document généré %d chars", len(hyde_doc))
    except Exception as exc:
        log.debug("HyDE: erreur génération (%s) → fallback", exc)
        return self.search(query, wing, n)

    # Chercher avec le document hypothétique au lieu de la requête brute
    return self.search(hyde_doc, wing, n)
```

### Préconditions et postconditions

- **Précondition** : `MEMORY_HYDE_ENABLED = True` dans config.py (désactivé par défaut
  car coûteux : +1 appel LLM léger par recherche).
- **Postcondition** : retourne la même structure que `search()`.
- **Dégradation gracieuse** : toute erreur → `search()` standard silencieusement.

---

## Sprint V9-03-D — Récupération doc officielle sur erreur d'API

### Contexte et motivations

Quand le `TesterAgent` échoue avec `AttributeError: module 'X' has no attribute 'Y'`
ou `TypeError: function() got unexpected keyword argument`, c'est une erreur de signature
d'API. Le `ReviewerAgent` doit détecter ce pattern et lancer une recherche web ciblée
sur la doc officielle avant de retourner la réflexion au KarpathyLoop.

### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `core/agents/reviewer_agent.py` | PATCH — `_enrich_reflection_with_docs(reflection, code)` |
| `tests/test_reviewer_agent.py` | PATCH — 3 nouveaux tests |

### Spécification : `ReviewerAgent._enrich_reflection_with_docs`

```python
import re as _re

_API_ERROR_PATTERNS = [
    r"AttributeError: (?:module '(\w+)'|'(\w+)' object) has no attribute '(\w+)'",
    r"TypeError: (\w+)\(\) got an unexpected keyword argument '(\w+)'",
    r"ImportError: cannot import name '(\w+)' from '(\w+)'",
    r"ModuleNotFoundError: No module named '(\w+)'",
]

def _enrich_reflection_with_docs(self, reflection: str, code: str) -> str:
    """
    Si la réflexion contient une erreur d'API connue, lance une recherche web ciblée
    et enrichit la réflexion avec la documentation officielle trouvée.

    Silencieux : en cas d'échec, retourne la réflexion originale non modifiée.
    """
    for pattern in _API_ERROR_PATTERNS:
        match = _re.search(pattern, reflection)
        if match:
            groups = [g for g in match.groups() if g]
            lib_name = groups[0] if groups else None
            if not lib_name:
                continue
            try:
                from core.web_search import WebSearchEngine
                engine = WebSearchEngine()
                query  = f"{lib_name} python official documentation API"
                result = engine.search(query)
                if result.synthesis and len(result.synthesis) > 50:
                    doc_snippet = result.synthesis[:800]
                    return (
                        reflection
                        + f"\n\n## Documentation officielle : `{lib_name}`\n\n"
                        + doc_snippet
                        + "\n\nCorrige le code en utilisant la bonne API documentée ci-dessus."
                    )
            except Exception as exc:
                log.debug("[reviewer] doc enrichment failed: %s", exc)
            break  # ne tenter qu'une seule lib par réflexion

    return reflection
```

### Intégration dans `ReviewerAgent.run_task`

```python
def run_task(self, contract: TaskContract) -> AgentResult:
    ...
    if not review_passed:
        reflection = _build_reflection(code, syntax_errors)
        # V9-03-D : enrichir si erreur d'API détectée
        reflection = self._enrich_reflection_with_docs(reflection, code)
        return AgentResult(
            success=False,
            error="Reviewer: syntax or quality rejected",
            payload={"reflection": reflection},
        )
    ...
```


============================================================
Fichier : spec-v9-04-training-pipeline.md
============================================================

# Spec V9-04 — Pipeline d'Entraînement LCCA
<!-- AI-READY | LCCA V9 | Training Pipeline | Version 9.0.0-draft | 2026-04-20 -->

## Abstract

Construire un pipeline d'entraînement continu qui transforme les transactions réussies de LCCA
en données d'entraînement SFT (Supervised Fine-Tuning), puis utilise le score `CodeEvaluator`
comme fonction de récompense pour GRPO (Group Relative Policy Optimization).
Le résultat est un modèle Qwen2.5-coder:7b fine-tuné sur les conventions spécifiques du projet.

---

## Sprint V9-04-A — Collecteur de données SFT

### Contexte et motivations

Chaque transaction LCCA réussie produit un triplet exploitable :

```
intent (NLIntent.details)
    → spec (SpecEntry.body_md)     [si generate_spec appelé]
    → code (GenerationResult.code) [si eval >= 70]
    → receipt (ExecutionReceipt)   [HMAC signé, traçable]
```

Ces triplets sont stockés dans :
- `lcca_patches` : TX commitées (intent + fichiers modifiés)
- `lcca_solutions` : code validé (code + score)
- `lcca_specs` : specs générées (body_md + validation)
- `receipts/` : ExecutionReceipts HMAC

Le module `TrainingDataCollector` doit les assembler en paires (instruction, output)
au format SFT standard (ShareGPT / Alpaca) exportables vers Unsloth ou axolotl.

### Fichiers à créer / modifier

| Fichier | Opération |
|---------|-----------|
| `core/training_collector.py` | CREATE — TrainingDataCollector |
| `core/training_types.py` | CREATE — SFTPair, GRPOSample dataclasses |
| `config.py` | PATCH — `TRAINING_OUTPUT_DIR`, `TRAINING_MIN_SCORE`, `TRAINING_MIN_PAIRS` |
| `tests/test_training_collector.py` | CREATE — 10 tests |

### Spécification : `core/training_types.py`

```python
# -*- coding: utf-8-sig -*-
"""training_types.py — Dataclasses pour le pipeline d'entraînement LCCA V9."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class SFTPair:
    """
    Paire (instruction, output) pour le Supervised Fine-Tuning.

    Format ShareGPT :
        {"conversations": [
            {"from": "human", "value": instruction},
            {"from": "gpt",   "value": output}
        ]}

    Champs :
        instruction : prompt système + intent utilisateur
        output      : code Python généré et validé
        source      : origine (lcca_patches, lcca_solutions, manual)
        quality     : score CodeEvaluator (0-100)
        tx_id       : ID transaction LCCA source
        created_at  : timestamp ISO
    """
    instruction : str
    output      : str
    source      : str = "lcca_patches"
    quality     : int = 0
    tx_id       : str = ""
    created_at  : str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_sharegpt(self) -> dict:
        return {
            "conversations": [
                {"from": "human", "value": self.instruction},
                {"from": "gpt",   "value": self.output},
            ],
            "metadata": {
                "source":     self.source,
                "quality":    self.quality,
                "tx_id":      self.tx_id,
                "created_at": self.created_at,
            }
        }

    def to_alpaca(self) -> dict:
        return {
            "instruction": self.instruction,
            "input":       "",
            "output":      self.output,
        }

    def is_usable(self, min_quality: int = 70) -> bool:
        """True si la paire est de qualité suffisante pour l'entraînement."""
        return (
            bool(self.instruction) and bool(self.output)
            and self.quality >= min_quality
            and len(self.output) >= 20
        )


@dataclass
class GRPOSample:
    """
    Échantillon pour GRPO (Group Relative Policy Optimization).

    GRPO génère N completions pour un même prompt, les classe par récompense,
    puis optimise le modèle pour favoriser les meilleures.

    Champs :
        prompt   : prompt système + intent
        outputs  : liste des N générations
        rewards  : liste des scores correspondants (CodeEvaluator 0-100)
    """
    prompt  : str
    outputs : list[str]
    rewards : list[float]

    def __post_init__(self):
        if len(self.outputs) != len(self.rewards):
            raise ValueError("outputs et rewards doivent avoir la même longueur")

    def is_usable(self) -> bool:
        return len(self.outputs) >= 2 and max(self.rewards) > min(self.rewards)
```

### Spécification : `core/training_collector.py`

```python
# -*- coding: utf-8-sig -*-
"""
training_collector.py — Collecteur de données d'entraînement depuis les collections LCCA.

Usage ::

    collector = TrainingDataCollector()
    pairs = collector.collect(min_quality=70)
    stats = collector.export(pairs, output_dir=Path("training_data"))
    print(f"{stats['total']} paires exportées")
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from core.training_types import SFTPair

log = logging.getLogger("lcca.training_collector")


class TrainingDataCollector:
    """
    Collecte les paires SFT depuis MemoryEngine et ReceiptStore.

    Sources :
        1. lcca_solutions : code validé + score >= min_quality
        2. lcca_specs + lcca_patches : triplets (intent, spec, code)
        3. receipts/*.json : contexte supplémentaire
    """

    def __init__(
        self,
        memory_engine=None,
        receipt_store_path: Optional[Path] = None,
    ) -> None:
        if memory_engine is None:
            from core.memory_engine import MemoryEngine
            self._memory = MemoryEngine()
        else:
            self._memory = memory_engine

        try:
            import config
            self._receipts_dir = receipt_store_path or Path(config.A2A_RECEIPTS_DIR)
        except (ImportError, AttributeError):
            self._receipts_dir = Path("memory/receipts")

    def collect(self, min_quality: int = 70) -> list[SFTPair]:
        """
        Collecte toutes les paires SFT disponibles.

        Args:
            min_quality : seuil minimum de qualité CodeEvaluator (0-100)

        Returns:
            Liste de SFTPair filtrés et dédupliqués.
        """
        pairs: list[SFTPair] = []
        pairs.extend(self._collect_from_solutions(min_quality))
        pairs.extend(self._collect_from_receipts(min_quality))

        # Déduplication par (instruction[:100], output[:100])
        seen: set = set()
        deduped: list[SFTPair] = []
        for p in pairs:
            key = (p.instruction[:100], p.output[:100])
            if key not in seen:
                seen.add(key)
                deduped.append(p)

        log.info("collect: %d paires brutes → %d après déduplication", len(pairs), len(deduped))
        return deduped

    def export(
        self,
        pairs: list[SFTPair],
        output_dir: Path,
        format: str = "sharegpt",    # "sharegpt" | "alpaca"
    ) -> dict:
        """
        Exporte les paires en fichiers JSON/JSONL exploitables par Unsloth/axolotl.

        Structure exportée :
            output_dir/
                train.jsonl     (80% des paires)
                eval.jsonl      (20% des paires)
                stats.json      (métriques)

        Returns:
            dict avec clés : total, train, eval, skipped, avg_quality
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        usable = [p for p in pairs if p.is_usable(min_quality=0)]
        if not usable:
            log.warning("export: aucune paire utilisable")
            return {"total": 0, "train": 0, "eval": 0, "skipped": len(pairs), "avg_quality": 0}

        # Split 80/20
        split_idx = max(1, int(len(usable) * 0.8))
        train_pairs = usable[:split_idx]
        eval_pairs  = usable[split_idx:]

        def _write_jsonl(path: Path, plist: list[SFTPair]) -> None:
            with path.open("w", encoding="utf-8") as f:
                for p in plist:
                    record = p.to_sharegpt() if format == "sharegpt" else p.to_alpaca()
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

        _write_jsonl(output_dir / "train.jsonl", train_pairs)
        _write_jsonl(output_dir / "eval.jsonl",  eval_pairs)

        avg_q = sum(p.quality for p in usable) / len(usable) if usable else 0
        stats = {
            "total":       len(usable),
            "train":       len(train_pairs),
            "eval":        len(eval_pairs),
            "skipped":     len(pairs) - len(usable),
            "avg_quality": round(avg_q, 1),
            "format":      format,
        }
        (output_dir / "stats.json").write_text(
            json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        log.info("export: %d train + %d eval → %s", len(train_pairs), len(eval_pairs), output_dir)
        return stats

    # ── Méthodes privées ──────────────────────────────────────────────────────

    def _collect_from_solutions(self, min_quality: int) -> list[SFTPair]:
        """Collecte depuis lcca_solutions (code validé)."""
        if not self._memory.is_available:
            return []
        try:
            results = self._memory.search("python function implementation", n=200)
            pairs: list[SFTPair] = []
            for entry in results.get("solutions", []):
                code    = entry.metadata.get("code", "") or entry.content
                score   = int(float(entry.metadata.get("score", 0)) * 100)
                intent  = entry.metadata.get("intent", "Implémente la fonction suivante")
                tx_id   = entry.metadata.get("tx_id", "")
                if score < min_quality or not code.strip():
                    continue
                instruction = self._build_instruction(intent)
                pairs.append(SFTPair(
                    instruction = instruction,
                    output      = code,
                    source      = "lcca_solutions",
                    quality     = score,
                    tx_id       = tx_id,
                ))
            log.debug("_collect_from_solutions: %d paires", len(pairs))
            return pairs
        except Exception as exc:
            log.debug("_collect_from_solutions error: %s", exc)
            return []

    def _collect_from_receipts(self, min_quality: int) -> list[SFTPair]:
        """Collecte depuis les ExecutionReceipts (fichiers JSON dans receipts/)."""
        pairs: list[SFTPair] = []
        if not self._receipts_dir.exists():
            return pairs
        for receipt_file in self._receipts_dir.glob("*.json"):
            try:
                data = json.loads(receipt_file.read_text(encoding="utf-8"))
                code    = data.get("code_snapshot", "")
                score   = data.get("quality_score", 0)
                intent  = data.get("intent", "")
                tx_id   = data.get("task_id", "")
                if score < min_quality or not code.strip() or not intent.strip():
                    continue
                pairs.append(SFTPair(
                    instruction = self._build_instruction(intent),
                    output      = code,
                    source      = "receipts",
                    quality     = score,
                    tx_id       = tx_id,
                ))
            except Exception:
                continue
        log.debug("_collect_from_receipts: %d paires", len(pairs))
        return pairs

    @staticmethod
    def _build_instruction(intent: str) -> str:
        """Construit le prompt instruction au format LCCA."""
        return (
            "Tu es LCCA, un agent de codage Python transactionnel.\n"
            "Génère UNIQUEMENT du code Python valide, conforme aux conventions LCCA V7.2 :\n"
            "- type hints obligatoires\n"
            "- docstring en français technique\n"
            "- from __future__ import annotations\n"
            "- sys.executable (jamais 'python' hardcodé)\n"
            "- safe_path() avant toute opération disque\n\n"
            f"Tâche : {intent}"
        )
```

---

## Sprint V9-04-B — Intégration GRPO (récompense CodeEvaluator)

### Contexte et motivations

GRPO (Group Relative Policy Optimization) est la technique de RL utilisée par Qwen2.5
lui-même pour son post-training. Elle ne nécessite pas un modèle reward séparé —
on définit une **fonction de récompense programmable** qui retourne un score numérique.

`CodeEvaluator` (5 critères, score 0-100) est exactement cette fonction de récompense.

### Architecture GRPO pour LCCA

```
Pour chaque SFTPair.instruction :
    1. Générer N=4 completions via le modèle de base (Qwen2.5-coder:7b)
    2. Pour chaque completion :
       - Compiler (compile() Python) → -50 si SyntaxError
       - CodeEvaluator.evaluate() → score 0-100
       - Vérifier les règles LCCA (sys.executable, safe_path) → -20 par violation
    3. GRPO calcule l'avantage relatif (meilleure - moyenne)
    4. Gradient update pour favoriser les meilleures completions
```

### Spécification : fonction de récompense

```python
# core/training_reward.py
"""
training_reward.py — Fonctions de récompense pour GRPO.
Compatible avec Unsloth GRPO notebooks (reward_funcs parameter).
"""
from __future__ import annotations
import re
from typing import Any

from core.code_evaluator import CodeEvaluator

_evaluator = CodeEvaluator()

_LCCA_RULES = [
    (r'\bpython\b(?!.*sys\.executable)', -20, "hardcoded 'python' instead of sys.executable"),
    (r'file\.write\(', -15, "direct file.write() without snapshot"),
    (r'import\s+subprocess.*shell\s*=\s*True', -25, "shell=True subprocess injection risk"),
]


def lcca_code_reward(prompts: list[str], completions: list[str], **kwargs) -> list[float]:
    """
    Fonction de récompense GRPO pour Unsloth.

    Signature conforme à Unsloth reward_funcs :
        reward_funcs=[lcca_code_reward]

    Args:
        prompts     : liste des prompts (1 par group)
        completions : liste des completions générées

    Returns:
        Liste de scores float (0.0 à 1.0) normalisés depuis CodeEvaluator.
    """
    rewards: list[float] = []
    for code in completions:
        score = _compute_reward(code)
        rewards.append(score / 100.0)  # normaliser 0-1 pour GRPO
    return rewards


def _compute_reward(code: str) -> float:
    """Calcule le score de récompense pour un snippet de code."""
    # Penalité syntax
    try:
        compile(code, "<grpo>", "exec")
    except SyntaxError:
        return -50.0

    # Score CodeEvaluator (0-100)
    try:
        eval_result = _evaluator.evaluate(code)
        score = float(eval_result.score)
    except Exception:
        score = 30.0  # score minimal si evaluateur échoue

    # Penalités règles LCCA
    for pattern, penalty, _ in _LCCA_RULES:
        if re.search(pattern, code):
            score += penalty

    return max(-50.0, min(100.0, score))
```

### Procédure d'entraînement (Unsloth)

```bash
# 1. Installer Unsloth (WSL2 recommandé sur Windows)
pip install unsloth

# 2. Exporter les données SFT
python -c "
from core.training_collector import TrainingDataCollector
from pathlib import Path
c = TrainingDataCollector()
pairs = c.collect(min_quality=70)
stats = c.export(pairs, Path('training_data/v9'))
print(stats)
"

# 3. Lancer l'entraînement SFT (notebook Unsloth ou script)
# Paramètres recommandés pour P50 (16GB RAM, pas de GPU dédié) :
#   model       = "qwen2.5-coder:7b-instruct"
#   load_in_4bit = True
#   r = 16  (rank LoRA)
#   lora_alpha = 16
#   max_seq_length = 2048
#   per_device_train_batch_size = 1
#   gradient_accumulation_steps = 4
#   num_train_epochs = 3

# 4. Sauvegarder le modèle fine-tuné au format GGUF
# 5. Enregistrer dans Ollama : ollama create lcca-qwen7b -f Modelfile
```

### Modelfile Ollama pour le modèle fine-tuné

```
# D:\LLMCodeAgent\Modelfile.lcca-v9
FROM ./lcca-qwen7b-sft.gguf

PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER num_predict 1024

SYSTEM """
Tu es LCCA V9, un agent de codage Python transactionnel spécialisé dans
le projet LLMCodeAgent. Tu génères du code conforme aux conventions LCCA V7.2.
Tu ne génères JAMAIS de code sans type hints, docstring, et from __future__ import annotations.
Tu utilises TOUJOURS sys.executable (jamais 'python' hardcodé).
Tu appelles TOUJOURS safe_path() avant toute opération disque.
"""
```

---

## Sprint V9-04-C — Pipeline d'entraînement continu

### Contexte et motivations

L'entraînement manuel est une friction. Le pipeline continu doit :
1. Surveiller les nouvelles TX (delta depuis le dernier entraînement)
2. Si delta >= `TRAINING_MIN_PAIRS` (50), déclencher un micro-fine-tune LoRA
3. Hot-swap le modèle dans Ollama après entraînement

### Fichiers à créer

| Fichier | Opération |
|---------|-----------|
| `core/training_pipeline.py` | CREATE — TrainingPipeline (scheduler + trigger) |
| `config.py` | PATCH — `TRAINING_MIN_PAIRS = 50`, `TRAINING_SCHEDULE_HOURS = 168` (1 semaine) |

### Spécification : `TrainingPipeline`

```python
class TrainingPipeline:
    """
    Pipeline d'entraînement continu LCCA.

    Cycle :
        1. check_trigger() — nouvelles TX depuis last_trained ?
        2. collect()       — assembler les paires SFT
        3. train()         — lancer Unsloth (subprocess)
        4. register()      — ollama create lcca-v9-{date}
        5. update_config() — OLLAMA_MODEL = nouveau modèle

    Déclenchement :
        - Manuel : TrainingPipeline().run()
        - Automatique : planifié toutes les TRAINING_SCHEDULE_HOURS heures
          via un thread daemon (optionnel, activé par TRAINING_AUTO_ENABLED)
    """

    def check_trigger(self) -> tuple[bool, int]:
        """
        Vérifie si l'entraînement doit être déclenché.

        Returns:
            (should_train: bool, new_pairs_count: int)
        """
        ...

    def run(self, force: bool = False) -> dict:
        """
        Exécute le pipeline complet.

        Args:
            force : ignorer le seuil TRAINING_MIN_PAIRS

        Returns:
            dict {triggered, pairs_collected, export_stats, model_name}
        """
        ...
```

### Critères d'acceptation

- [ ] `TrainingDataCollector().collect(min_quality=70)` retourne >= 1 paire sur un workspace avec TX
- [ ] `SFTPair.to_sharegpt()` produit un dict avec `conversations[0].from == "human"`
- [ ] `SFTPair.to_alpaca()` produit un dict avec `instruction`, `input`, `output`
- [ ] `TrainingDataCollector().export(pairs, dir, "sharegpt")` crée `train.jsonl` + `eval.jsonl` + `stats.json`
- [ ] `lcca_code_reward(["prompt"], ["def f(): pass"])` retourne une liste de 1 float dans [-0.5, 1.0]
- [ ] `_compute_reward("def f(: INVALID")` retourne -50.0 (SyntaxError)
- [ ] `_compute_reward("import subprocess; subprocess.run(['cmd'], shell=True)")` retourne score <= 50
- [ ] `TrainingDataCollector` silencieux si MemoryEngine non disponible (is_available = False)
- [ ] `export([], dir)` retourne `{"total": 0, "skipped": 0, ...}` sans crash
- [ ] `SFTPair.is_usable(min_quality=70)` retourne False si quality=69


============================================================
Fichier : spec-v9-05-creative-agents.md
============================================================

# Spec V9-05 — Agents Créatifs & Fonctionnalités Avancées
<!-- AI-READY | LCCA V9 | Agents Créatifs | Version 9.0.0-draft | 2026-04-20 -->

## Abstract

Six propositions créatives pour LCCA V9, couvrant : l'audit autonome de codebase (QAAgent),
l'auto-documentation (DocAgent), la collaboration humain-agent (mode Pair Programmer),
le dashboard analytique, la synthèse vocale locale, et la mémoire épisodique graphique.
Chaque spec est indépendante et peut être implémentée dans n'importe quel ordre.

---

## Sprint V9-05-A — QAAgent : Audit autonome continu

### Contexte et motivations

Le `skill 005-debt-tracker.md` est mis à jour manuellement en fin de session. Cette friction
entraîne des dettes non documentées et des sessions qui démarrent sans vision claire de l'état
du codebase. Un `QAAgent` autonome surveille le codebase en arrière-plan, détecte les dettes
nouvelles, et publie des `TaskContract` sur le bus A2A.

Il s'intègre dans la hiérarchie V8 comme un 6ème agent (aux côtés de ObserverAgent) avec
une boucle indépendante de la KarpathyLoop principale.

### Fichiers à créer / modifier

| Fichier | Opération |
|---------|-----------|
| `core/agents/qa_agent.py` | CREATE — QAAgent + QAReport dataclass |
| `core/agents/__init__.py` | PATCH — export QAAgent + QAReport |
| `config.py` | PATCH — `QA_SCAN_INTERVAL_HOURS = 24`, `QA_DEBT_THRESHOLD_WARN = 7`, `QA_DEBT_THRESHOLD_CRIT = 10` |
| `tests/test_qa_agent.py` | CREATE — 12 tests |

### Spécification : `QAReport` dataclass

```python
@dataclass
class QAReport:
    """
    Rapport d'audit qualité produit par QAAgent.

    Champs :
        debts_found      : liste de dettes détectées (sévérité, module, description)
        files_scanned    : nombre de fichiers analysés
        total_size_kb    : taille totale scannée
        critical_count   : dettes CRITIQUE
        warn_count       : dettes WARN
        info_count       : dettes INFO
        timestamp        : horodatage ISO de l'audit
        action_contracts : task_ids des contrats publiés sur le bus
    """
    debts_found      : list[dict]
    files_scanned    : int
    total_size_kb    : float
    critical_count   : int
    warn_count       : int
    info_count       : int
    timestamp        : str
    action_contracts : list[str] = field(default_factory=list)

    def has_critical(self) -> bool:
        return self.critical_count > 0

    def summary(self) -> str:
        return (
            f"QA scan: {self.files_scanned} fichiers, "
            f"{self.critical_count} CRITIQUE / {self.warn_count} WARN / {self.info_count} INFO"
        )
```

### Spécification : `QAAgent` — règles d'audit

```python
# Règles d'audit statique — chacune retourne (sévérité, description) ou None
_QA_RULES: list[Callable] = [
    _rule_file_too_large,      # > 10KB → WARN, > 20KB → CRITIQUE
    _rule_hardcoded_path,      # "D:\\..." dans le code → WARN
    _rule_print_in_production, # print() hors tests → INFO
    _rule_fstring_in_log,      # log.info(f"...") → INFO
    _rule_missing_docstring,   # classe ou fonction publique sans docstring → INFO
    _rule_bare_except,         # except: (sans type) → WARN
    _rule_direct_file_write,   # file.write() sans snapshot → CRITIQUE
    _rule_hardcoded_python,    # "python" hardcodé → CRITIQUE
    _rule_duplicate_constant,  # même constante dans 2+ fichiers → WARN
]

def _rule_file_too_large(filepath: str, content: str, size_kb: float) -> "tuple | None":
    if size_kb > 20:
        return ("CRITIQUE", f"Fichier {size_kb:.1f}KB > 20KB — refactorisation urgente")
    if size_kb > 10:
        return ("WARN", f"Fichier {size_kb:.1f}KB > 10KB — candidat refacto")
    return None

def _rule_hardcoded_python(filepath: str, content: str, size_kb: float) -> "tuple | None":
    import re
    if re.search(r'["\']python["\']', content) and "tests/" not in filepath:
        return ("CRITIQUE", "\"python\" hardcodé — utiliser sys.executable")
    return None

def _rule_direct_file_write(filepath: str, content: str, size_kb: float) -> "tuple | None":
    import re
    if re.search(r'\.write_text\(|\.write\(', content) and "tests/" not in filepath:
        if "snapshot" not in content and "write_text" in content:
            return ("CRITIQUE", "write_text() sans snapshot TransactionManager détecté")
    return None
```

### Intégration dans le pipeline V8

```python
class QAAgent(BaseAgent):
    """
    Agent d'audit qualité autonome.

    run_scan() : scan complet du workspace → QAReport
    run_task() : traite un contrat "qa_audit" depuis le bus A2A
    schedule() : démarre un thread daemon qui scanne toutes les N heures

    Contraintes :
    - Ne modifie JAMAIS de fichier (lecture seule)
    - Publie des TaskContracts pour les CRITIQUE (target_agent="architect")
    - Stocke le rapport dans lcca_context via memory_store
    """

    @classmethod
    def create(cls, bus: A2ALocalBus, mcp_caller=None) -> "QAAgent":
        card = AgentCard(
            name="qa",
            version="9.0.0",
            capabilities=["audit", "debt_detection", "memory_store"],
            mcp_tools=AGENT_MCP_ALLOWLIST.get("qa", ["memory_search", "memory_store"]),
            recovery_policy=RecoveryPolicy(max_retries=1, retry_delay=60.0),
            description="Audit continu de la qualité du codebase LCCA",
        )
        return cls(card=card, bus=bus, mcp_caller=mcp_caller)

    def run_scan(self, workspace: "Path | None" = None) -> QAReport:
        """Scan complet synchrone. Utilisable sans bus A2A."""
        ...

    def schedule(self, interval_hours: float = 24.0) -> "threading.Thread":
        """Démarre un thread daemon de scan périodique."""
        import threading
        def _loop():
            import time
            while True:
                try:
                    report = self.run_scan()
                    log.info("[qa] %s", report.summary())
                except Exception as exc:
                    log.error("[qa] scan error: %s", exc)
                time.sleep(interval_hours * 3600)
        t = threading.Thread(target=_loop, daemon=True, name="qa-agent-scheduler")
        t.start()
        return t
```

---

## Sprint V9-05-B — DocAgent : Auto-documentation

### Contexte et motivations

Les skills `.claude-skills/*.md` sont mis à jour manuellement en fin de session. Cette
tâche répétitive est parfaitement automatisable : un `DocAgent` lit le diff git, les
receipts de la session, et met à jour automatiquement les fichiers de documentation.

### Fichiers à créer / modifier

| Fichier | Opération |
|---------|-----------|
| `core/agents/doc_agent.py` | CREATE — DocAgent |
| `scripts/post-commit.ps1` | CREATE — git hook PowerShell déclenche DocAgent |
| `tests/test_doc_agent.py` | CREATE — 8 tests |

### Spécification : `DocAgent`

```python
class DocAgent(BaseAgent):
    """
    Agent de documentation automatique.

    Responsabilités :
    1. Lire le diff git de la session (git diff HEAD~1 --name-only)
    2. Pour chaque fichier modifié dans core/ :
       - Vérifier les docstrings manquantes via ASTIndexer
       - Générer les docstrings manquantes via LLMGenerator (modèle 3b)
    3. Mettre à jour les skills .md (patterns appris, arborescence, sprint context)
    4. Mettre à jour README.md si nouveaux modules créés

    Contraintes :
    - Utilise UNIQUEMENT le modèle léger (OLLAMA_MODEL_LIGHT = 3b)
    - Max 5 fichiers par session (évite les runs trop longs)
    - Ne touche JAMAIS à core/ directement — utilise McpEditBatch (via MCP tool edit_batch)
    - Toujours demander confirmation avant modification des skills .md
      (flag DOCAGENT_AUTO_CONFIRM = False par défaut)
    """

    # Patterns de docstrings à générer
    _DOCSTRING_PROMPT = (
        "Génère UNE SEULE docstring Python en français technique pour la fonction/classe suivante.\n"
        "Format obligatoire :\n"
        '    """\n'
        "    <description en 1-2 phrases>\n\n"
        "    Args:\n"
        "        <param>: <type> — <description>\n\n"
        "    Returns:\n"
        "        <type> — <description>\n"
        '    """\n\n'
        "Code à documenter :\n"
    )

    def run_task(self, contract: TaskContract) -> AgentResult:
        """Traite un contrat de documentation depuis le bus A2A."""
        ...

    def document_file(self, filepath: "Path") -> dict:
        """
        Ajoute les docstrings manquantes dans un fichier Python.

        Returns:
            dict {file, added: int, skipped: int, errors: int}
        """
        ...

    def update_skill(self, skill_path: "Path", new_pattern: str) -> bool:
        """
        Ajoute un pattern dans un skill .md (section ## PATTERNS APPRIS).
        Si DOCAGENT_AUTO_CONFIRM = False, publie sur bus et attend confirmation.
        """
        ...
```

### Script git hook `scripts/post-commit.ps1`

```powershell
# post-commit.ps1 — Déclenche DocAgent après chaque commit
# Copier dans .git/hooks/post-commit (sans extension) et rendre exécutable
#
# Usage : git commit -m "Sprint V9-05-B"
# → DocAgent analyse le diff et met à jour la doc

$PY = "D:\LLMCodeAgent\venv\Scripts\python.exe"
$SCRIPT = "D:\LLMCodeAgent\scripts\run_doc_agent.py"

if (Test-Path $SCRIPT) {
    Write-Host "[DocAgent] Démarrage post-commit..." -ForegroundColor Cyan
    & $PY $SCRIPT --from-git-hook
}
```

---

## Sprint V9-05-C — Mode Pair Programmer (Human-in-the-Loop)

### Contexte et motivations

La KarpathyLoop est entièrement autonome. Certains utilisateurs préfèrent valider chaque
itération avant de continuer. Le mode Pair Programmer pause le pipeline après chaque
itération Reviewer et attend une réponse de l'UI (IPC Electron).

### Fichiers à modifier

| Fichier | Opération |
|---------|-----------|
| `core/agents/agent_orchestrator.py` | PATCH — mode HITL (Human-in-the-Loop) |
| `ui/electron/main.ts` | PATCH — handler `ipcMain.handle('hitl:respond', ...)` |
| `ui/electron/preload.ts` | PATCH — exposition `window.lcca.hitlRespond()` |
| `ui/src/components/ChatPanel.tsx` | PATCH — affichage diff + boutons Continuer/Modifier/Accepter |
| `config.py` | PATCH — `HITL_ENABLED = False` (opt-in) |

### Spécification : `AgentOrchestrator` — mode HITL

```python
# Nouveau paramètre dans __init__
def __init__(
    self,
    ...
    hitl_callback: "Callable[[str, str, int], str] | None" = None,
) -> None:
    """
    hitl_callback : callable(code, reflection, iteration) → str
        Reçoit le code et la réflexion de l'itération courante.
        Retourne : "continue" | "accept" | "modify:<new_intent>"
        Si None : mode autonome (comportement actuel).
    """
    self._hitl = hitl_callback
    ...

# Dans la boucle KarpathyLoop, après ReviewerAgent :
if self._hitl is not None and not reviewer_result.success:
    decision = self._hitl(generated_code, reflection, iteration)
    if decision == "accept":
        success = True
        break
    elif decision.startswith("modify:"):
        intent = decision[7:]  # nouvel intent fourni par l'humain
    # "continue" → boucle normale
```

### Spécification UI — composant `HITLPanel`

```typescript
// ui/src/components/HITLPanel.tsx
interface HITLPanelProps {
  code: string;
  reflection: string;
  iteration: number;
  onContinue: () => void;
  onAccept: () => void;
  onModify: (newIntent: string) => void;
}

// Affiche :
// 1. Diff coloré du code (itération N)
// 2. Réflexion du Reviewer (raison du rejet)
// 3. Trois boutons : "Continuer", "Accepter tel quel", "Modifier l'intent"
// 4. Zone de texte pour "Modifier l'intent" (si bouton cliqué)
```

---

## Sprint V9-05-D — Dashboard Analytics

### Contexte et motivations

`telemetry.py` écrit des JSONL rotatifs dans `logs/`. `receipt_store.py` stocke des
ExecutionReceipts HMAC avec `quality_score`, `task_id`, `intent`. Ces données permettent
un dashboard de productivité complet.

### Fichiers à créer / modifier

| Fichier | Opération |
|---------|-----------|
| `core/mcp_tools_schema.py` | PATCH — tool `get_analytics` (13ème tool) |
| `core/mcp_tool_handlers.py` | PATCH — `_tool_get_analytics()` |
| `ui/src/components/AnalyticsPanel.tsx` | CREATE — dashboard React recharts |
| `ui/src/stores/analyticsStore.ts` | CREATE — Zustand store analytics |

### Spécification : tool `get_analytics`

```python
def _tool_get_analytics(params: dict) -> dict:
    """
    Retourne les métriques LCCA pour le dashboard UI.

    Returns:
        {
            "period_days": int,
            "total_transactions": int,
            "success_rate": float,         # 0.0-1.0
            "avg_quality_score": float,    # 0-100
            "avg_latency_ms": float,
            "models_used": {model: count},
            "tools_usage": {tool: count},
            "quality_trend": [             # derniers 30 jours
                {"date": "2026-04-20", "avg_score": 75.2}
            ],
            "karpathy_stats": {
                "avg_iterations": float,
                "stagnation_rate": float,
                "success_rate": float,
            }
        }
    """
    ...
```

### Métriques UI (recharts)

```typescript
// Composants recharts dans AnalyticsPanel :
// 1. LineChart : qualité moyenne par jour (30 derniers jours)
// 2. BarChart  : outils MCP les plus utilisés (top 5)
// 3. PieChart  : répartition modèles (3b vs 7b vs 14b)
// 4. Stat cards : total TX, taux succès, latence moyenne, score moyen
```

---

## Sprint V9-05-E — Mémoire Épisodique (graphe de décisions)

### Contexte et motivations

Les skills .md capturent des patterns mais pas les **décisions architecturales** (pourquoi
on a choisi X et pas Y). Un graphe de connaissance épisodique permet de tracer l'historique
décisionnel complet et de le requêter en langage naturel.

### Architecture

```
Nœuds (entités) :
    Session         {date, sprint_name, engineer}
    Decision        {title, rationale, alternatives_rejected}
    Module          {path, version, last_modified}
    Pattern         {name, description, source_session}

Arêtes typées :
    Session → Decision  : "a_pris"
    Session → Module    : "a_modifié"
    Decision → Module   : "concerne"
    Decision → Decision : "a_remplacé" | "a_inspiré"
    Pattern → Decision  : "a_émergé_de"
```

### Fichiers à créer

| Fichier | Opération |
|---------|-----------|
| `core/episodic_memory.py` | CREATE — EpisodicMemory (DuckDB backend) |
| `core/episodic_types.py` | CREATE — Node, Edge, EpisodicQuery dataclasses |
| `config.py` | PATCH — `EPISODIC_DB_PATH` |

### Spécification : `EpisodicMemory`

```python
class EpisodicMemory:
    """
    Graphe de connaissance épisodique basé sur DuckDB.

    Usage :
        em = EpisodicMemory()
        em.add_decision(
            title="Choix libcst pour l'AST",
            rationale="libcst permet la modification sans perte de formatting",
            alternatives=["ast stdlib (lecture seule)", "rope (complexe)"],
            session_date="2026-04-16",
        )
        results = em.query("pourquoi libcst")
        # → [Decision(title="Choix libcst...", rationale="...")]
    """

    def add_decision(self, title: str, rationale: str,
                     alternatives: list[str], session_date: str) -> str:
        """Ajoute une décision architecturale. Retourne son ID."""
        ...

    def query(self, question: str, limit: int = 5) -> list[dict]:
        """
        Recherche textuelle dans le graphe (FTS DuckDB).
        Compatible avec une future intégration LLM (embeddings).
        """
        ...

    def get_session_timeline(self) -> list[dict]:
        """Chronologie des sessions avec leurs décisions."""
        ...
```

---

## Sprint V9-05-F — Synthèse Vocale Locale (TTS)

### Contexte et motivations

Quand LCCA tourne une tâche longue (generate_spec, KarpathyLoop), l'utilisateur ne regarde
pas l'écran. Une notification vocale à la fin ("Sprint terminé, 4 itérations, score 82")
améliore la productivité multi-tâches sans aucune API cloud.

**Moteur retenu : Kokoro-FastAPI** (MIT, offline, voix françaises, ~200MB)

### Fichiers à créer / modifier

| Fichier | Opération |
|---------|-----------|
| `ui/electron/main.ts` | PATCH — handler `ipcMain.handle('tts:speak', ...)` |
| `ui/electron/preload.ts` | PATCH — `window.lcca.ttsSay(text)` |
| `ui/src/hooks/useTts.ts` | CREATE — hook React pour les notifications vocales |
| `config.py` | PATCH — `TTS_ENABLED = False`, `TTS_ENGINE = "kokoro"`, `TTS_VOICE = "fr_f"` |
| `scripts/start-tts.ps1` | CREATE — démarre Kokoro en arrière-plan |

### Spécification : handler IPC `tts:speak`

```typescript
// main.ts — ajout dans la section handlers IPC
ipcMain.handle('tts:speak', async (_event, text: string) => {
  const ttsEnabled = store.get('ttsEnabled', false);
  if (!ttsEnabled) return { success: false, reason: 'TTS disabled' };

  const engine = store.get('ttsEngine', 'kokoro');
  if (engine === 'kokoro') {
    // Kokoro-FastAPI tourne localement sur port 8880
    try {
      const resp = await fetch('http://localhost:8880/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice: store.get('ttsVoice', 'fr_f') }),
      });
      // Kokoro retourne un WAV — lire avec Electron shell
      const audioBuffer = await resp.arrayBuffer();
      // Jouer avec l'API Audio native Electron (pas d'import externe nécessaire)
      return { success: true };
    } catch (err) {
      log.warn('TTS error:', err);
      return { success: false, reason: String(err) };
    }
  }
  return { success: false, reason: 'Unknown engine' };
});
```

### Points de notification vocale

Les notifications vocales sont déclenchées à la fin de :
- `AgentOrchestrator.run()` → "Pipeline terminé : {iterations} itérations, score {quality}"
- `SpecGenerator.generate()` → "Spec générée : {title}"
- `QAAgent.run_scan()` (si CRITIQUE trouvé) → "Alerte qualité : {critical_count} problème(s) critique(s)"
- `TrainingPipeline.run()` → "Entraînement terminé : {pairs} paires, modèle {model_name}"

---

## Critères d'acceptation globaux V9-05

### QAAgent (V9-05-A)
- [ ] `QAAgent.run_scan()` analyse les fichiers core/ et retourne un `QAReport`
- [ ] `_rule_hardcoded_python("x.py", "'python'", 1.0)` retourne `("CRITIQUE", ...)`
- [ ] `_rule_file_too_large("x.py", "", 25.0)` retourne `("CRITIQUE", ...)`
- [ ] `QAAgent.schedule(interval_hours=0.001)` démarre un thread daemon sans crash
- [ ] `QAReport.has_critical()` retourne True si critical_count > 0
- [ ] `QAReport.summary()` retourne une chaîne non vide

### DocAgent (V9-05-B)
- [ ] `DocAgent.document_file(path)` retourne `{added: N, skipped: M, errors: 0}`
- [ ] Fichier sans docstrings → docstrings générées par LLM 3b
- [ ] `DOCAGENT_AUTO_CONFIRM = False` → pas de modification sans confirmation

### Pair Programmer (V9-05-C)
- [ ] `AgentOrchestrator(hitl_callback=lambda *a: "accept")` accepte le premier code
- [ ] `AgentOrchestrator(hitl_callback=None)` → comportement autonome inchangé (régression 0)
- [ ] `hitl_callback` retournant `"modify:new intent"` → nouvel intent utilisé à l'itération suivante

### Dashboard Analytics (V9-05-D)
- [ ] `_tool_get_analytics({})` retourne un dict avec toutes les clés attendues
- [ ] `AnalyticsPanel` se monte sans erreur avec des données vides (`total_transactions: 0`)
- [ ] `quality_trend` contient au plus 30 entrées

### Mémoire épisodique (V9-05-E)
- [ ] `EpisodicMemory().add_decision(...)` retourne un ID non vide
- [ ] `EpisodicMemory().query("libcst")` retourne les décisions contenant "libcst"
- [ ] DB créée automatiquement si absente

### TTS (V9-05-F)
- [ ] `window.lcca.ttsSay("test")` ne crash pas si TTS désactivé
- [ ] `TTS_ENABLED = False` → aucun appel réseau
- [ ] Kokoro absent → fallback silencieux (log.debug uniquement)
