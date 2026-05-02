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
