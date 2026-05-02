# Sprint V9-02-B — Boucle de correction post-génération (opt-in)
<!-- AI-READY | LCCA V9 | Sprint V9-02-B | Priorité P0 | Effort 1j -->

## Objectif

Retenter la génération avec feedback CodeEvaluator si score < 70, max 2 fois.
**Opt-in strict** (`CORRECTION_LOOP_ENABLED=False`) avec timeout global 120s
pour éviter 9 minutes de blocage sur le modèle 14b.

## Prérequis

- V9-02-A terminé
- `CodeEvaluator.evaluate(code)` retourne objet avec `score: int` et `issues: list[str]`

## Fichiers cibles

| # | Fichier | Opération |
|---|---------|-----------|
| 1 | `core/llm_generator.py` | PATCH — refacto `generate()` avec boucle opt-in |
| 2 | `tests/test_llm_generator.py` | PATCH — 4 nouveaux tests |

## Spécification

### Architecture de `generate()` refactorée

```
generate(op, intent, context, skill_context)
  ├── Si CORRECTION_LOOP_ENABLED=False → _generate_single()  (comportement V8)
  └── Si CORRECTION_LOOP_ENABLED=True  → boucle de correction
        ├── Cache hit → retour immédiat
        ├── Boucle 0..max_retries :
        │   ├── Timeout global atteint → break
        │   ├── ollama.generate()
        │   ├── extract + sanitize + is_valid_python
        │   ├── CodeEvaluator.evaluate() → si score >= 70 → cache + retour
        │   └── Enrichir user prompt avec feedback
        └── Retour meilleur code valide ou fallback stub
```

### Méthode `_generate_single` (extraire depuis le `generate()` actuel)

```python
def _generate_single(
    self,
    op, intent,
    context: str = "",
    skill_context: str = "",
) -> GenerationResult:
    """
    Génération simple V8 — 1 appel LLM, fallback si échec.
    Préserve le comportement exact de generate() pré-V9.
    """
    import time
    t0 = time.monotonic()
    system, user = self.builder.build(op, intent, context, skill_context=skill_context)
    prompt_key = self._cache_key(system, user, self.ollama.model)
    cached = self._cache_get(prompt_key)
    if cached:
        return GenerationResult(code=cached, model=self.ollama.model, from_cache=True,
                                from_fallback=False, prompt_tokens=len(user)//4, duration_ms=0)
    try:
        raw  = self.ollama.generate(system, user)
        code = self.extractor.extract(raw)
        code = self.extractor.sanitize(code)
        ms   = int((time.monotonic() - t0) * 1000)
        if self.extractor.is_valid_python(code):
            self._cache_set(prompt_key, code)
            return GenerationResult(code=code, model=self.ollama.model, from_cache=False,
                                    from_fallback=False, prompt_tokens=len(user)//4, duration_ms=ms)
    except (ConnectionError, RuntimeError):
        pass
    code = self.fallback.generate(op, intent)
    ms = int((time.monotonic() - t0) * 1000)
    return GenerationResult(code=code, model="fallback", from_cache=False,
                            from_fallback=True, prompt_tokens=len(user)//4, duration_ms=ms)
```

### Méthode `generate` refactorée (avec boucle opt-in)

```python
_MIN_QUALITY_SCORE = 70

def generate(
    self,
    op, intent,
    context: str = "",
    skill_context: str = "",
) -> GenerationResult:
    import time, config
    from core.code_evaluator import CodeEvaluator

    # V9-02-B : boucle opt-in
    if not getattr(config, "CORRECTION_LOOP_ENABLED", False):
        return self._generate_single(op, intent, context, skill_context)

    max_retries  = getattr(config, "LLM_MAX_CORRECTION_RETRIES", 2)
    max_total_s  = getattr(config, "LLM_GENERATION_MAX_TOTAL_SEC", 120)
    deadline     = time.monotonic() + max_total_s
    evaluator    = CodeEvaluator()

    system, user_orig = self.builder.build(op, intent, context, skill_context=skill_context)
    prompt_key = self._cache_key(system, user_orig, self.ollama.model)
    cached = self._cache_get(prompt_key)
    if cached:
        return GenerationResult(code=cached, model=self.ollama.model, from_cache=True,
                                from_fallback=False, prompt_tokens=len(user_orig)//4,
                                duration_ms=0)

    t0, user, last_code = time.monotonic(), user_orig, ""

    for attempt in range(max_retries + 1):
        if time.monotonic() > deadline:
            log.warning("generate: timeout global %ds épuisé attempt=%d", max_total_s, attempt)
            break
        try:
            raw  = self.ollama.generate(system, user)
            code = self.extractor.extract(raw)
            code = self.extractor.sanitize(code)

            if not self.extractor.is_valid_python(code):
                feedback = "SyntaxError : le code généré est invalide. Corrige la syntaxe."
            else:
                ev = evaluator.evaluate(code)
                if ev.score >= _MIN_QUALITY_SCORE:
                    ms = int((time.monotonic() - t0) * 1000)
                    self._cache_set(prompt_key, code)
                    log.info("generate: OK attempt=%d score=%d ms=%d", attempt, ev.score, ms)
                    return GenerationResult(code=code, model=self.ollama.model,
                                           from_cache=False, from_fallback=False,
                                           prompt_tokens=len(user)//4, duration_ms=ms)
                feedback = (
                    f"Score qualité {ev.score}/100 (seuil {_MIN_QUALITY_SCORE}).\n"
                    f"Problèmes : {'; '.join(ev.issues[:3])}. Corrige ces points."
                )

            last_code = code
            if attempt < max_retries:
                log.warning("generate: tentative %d/%d — %s", attempt+1, max_retries, feedback[:80])
                user = (
                    user_orig
                    + f"\n\n## Correction requise (tentative {attempt+1}/{max_retries})\n\n"
                    + feedback
                    + f"\n\nCode à corriger :\n```python\n{code[:1000]}\n```\n\n"
                    + "Génère une version corrigée et complète :"
                )

        except (ConnectionError, RuntimeError) as exc:
            log.warning("generate: Ollama indisponible attempt=%d (%s) — fallback", attempt, exc)
            code = self.fallback.generate(op, intent)
            ms = int((time.monotonic() - t0) * 1000)
            return GenerationResult(code=code, model="fallback", from_cache=False,
                                    from_fallback=True, prompt_tokens=len(user)//4,
                                    duration_ms=ms)

    # Retourner le meilleur code valide ou stub
    ms = int((time.monotonic() - t0) * 1000)
    if last_code and self.extractor.is_valid_python(last_code):
        log.warning("generate: boucle épuisée — retour meilleur code (non optimal)")
        return GenerationResult(code=last_code, model=self.ollama.model, from_cache=False,
                                from_fallback=False, prompt_tokens=len(user)//4, duration_ms=ms)
    log.warning("generate: boucle épuisée — fallback stub")
    code = self.fallback.generate(op, intent)
    return GenerationResult(code=code, model="fallback", from_cache=False,
                            from_fallback=True, prompt_tokens=len(user)//4, duration_ms=ms)
```

### Tests à ajouter : `class TestCorrectionLoop`

```python
class TestCorrectionLoop:
    @pytest.fixture(autouse=True)
    def enable_loop(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "CORRECTION_LOOP_ENABLED", True)
        monkeypatch.setattr(config, "LLM_MAX_CORRECTION_RETRIES", 2)
        monkeypatch.setattr(config, "LLM_GENERATION_MAX_TOTAL_SEC", 120)

    def test_disabled_by_default(self, monkeypatch, mocker):
        """CORRECTION_LOOP_ENABLED=False → 1 seul appel LLM."""
        import config
        monkeypatch.setattr(config, "CORRECTION_LOOP_ENABLED", False)
        gen = LLMGenerator()
        spy_single = mocker.spy(gen, "_generate_single")
        op = MagicMock(action="add", patch_type="add_function",
                       target_symbol="f", file="x.py")
        intent = MagicMock(details="x", project="P", target="")
        gen.generate(op, intent)
        assert spy_single.call_count == 1

    def test_good_score_returns_immediately(self, mocker):
        gen = LLMGenerator()
        mocker.patch.object(gen.ollama, "generate", return_value="def f(): pass")
        mocker.patch.object(gen, "_cache_get", return_value=None)
        mocker.patch.object(gen, "_cache_set")
        mocker.patch("core.llm_generator.CodeEvaluator.evaluate",
                     return_value=MagicMock(score=85, issues=[]))
        op = MagicMock(action="add", patch_type="add_function",
                       target_symbol="f", file="x.py")
        result = gen.generate(op, MagicMock(details="x", project="P", target=""))
        assert result.from_fallback is False
        assert gen.ollama.generate.call_count == 1

    def test_low_score_triggers_retry(self, mocker):
        gen = LLMGenerator()
        mocker.patch.object(gen.ollama, "generate", return_value="def f(): pass")
        mocker.patch.object(gen, "_cache_get", return_value=None)
        mocker.patch.object(gen, "_cache_set")
        scores = iter([40, 85])
        mocker.patch("core.llm_generator.CodeEvaluator.evaluate",
                     side_effect=lambda c: MagicMock(score=next(scores), issues=["no docstring"]))
        result = gen.generate(MagicMock(action="add", patch_type="add_function",
                                        target_symbol="f", file="x.py"),
                              MagicMock(details="x", project="P", target=""))
        assert result.from_fallback is False
        assert gen.ollama.generate.call_count == 2

    def test_timeout_global_respected(self, mocker, monkeypatch):
        import config
        monkeypatch.setattr(config, "LLM_GENERATION_MAX_TOTAL_SEC", 0)   # expire immédiatement
        gen = LLMGenerator()
        mocker.patch.object(gen.ollama, "generate", return_value="def f(): pass")
        mocker.patch.object(gen, "_cache_get", return_value=None)
        mocker.patch("core.llm_generator.CodeEvaluator.evaluate",
                     return_value=MagicMock(score=30, issues=["low"]))
        result = gen.generate(MagicMock(action="add", patch_type="add_function",
                                        target_symbol="f", file="x.py"),
                              MagicMock(details="x", project="P", target=""))
        # Le timeout expire → retour meilleur code ou fallback
        assert isinstance(result.code, str)   # jamais None
```

## Critères d'acceptation

- [ ] `CORRECTION_LOOP_ENABLED=False` → `_generate_single()` appelé, 1 seul appel Ollama
- [ ] Score >= 70 au 1er essai → 0 retry
- [ ] Score < 70 → retry avec feedback dans le prompt
- [ ] Timeout global `LLM_GENERATION_MAX_TOTAL_SEC=0` → arrêt immédiat sans hang
- [ ] `generate()` retourne **toujours** un `GenerationResult` valide (jamais None)
- [ ] 0 régression tests V8

## Protocole d'exécution

```
1. filesystem:read_text_file core/llm_generator.py  → lire generate() complet
2. filesystem:edit_file core/llm_generator.py       → extraire _generate_single()
3. filesystem:edit_file core/llm_generator.py       → réécrire generate() avec boucle
4. bash: python -c "from core.llm_generator import LLMGenerator; print('OK')"
5. filesystem:edit_file tests/test_llm_generator.py → ajouter TestCorrectionLoop
6. bash: python -m pytest tests/test_llm_generator.py -v -k "TestCorrection"
7. bash: python -m pytest tests/ -x -q
```

## ⚠️ Points d'attention

- `_generate_single` doit être **identique** au comportement V8 de `generate()` (aucune régression)
- Le `CodeEvaluator` est instancié **à l'intérieur** de la boucle — import tardif pour éviter
  le import circulaire si CodeEvaluator importe LLMGenerator
- `last_code` peut être vide (`""`) si la 1ère itération crashe → vérifier `if last_code`
- Ne pas modifier la signature publique de `generate()` — `skill_context=""` reste optionnel

## Mise à jour skills

- **001** : pattern "V9-02-B — boucle correction opt-in, _generate_single, timeout global"
- **004** : V9-02-B TERMINÉ
