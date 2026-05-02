# LCCA — Pipeline Feedback Loop V1
<!-- AI-READY | LCCA V11 | PipelineFeedback | Statut : VALIDÉE | Date : 2026-04-29 -->

> **Basée sur** : analyse codebase réelle 2026-04-29 (tester_agent.py, orchestrator_loop.py,
> coder_agent.py, code_evaluator.py, model_router.py, sandbox_engine.py)
> **Contraintes** : 16 GB RAM · 4 GB VRAM · 100% offline · qwen2.5-coder:3b · Windows
> **Philosophie** : corriger ce qui est borgne dans le pipeline existant — pas réécrire, pas ajouter
> une couche. Quatre problèmes identifiés par lecture du code source, quatre sprints ciblés.

---

## 1. Diagnostic — ce qui est réellement borgne

### 1.1 La réflexion Tester → Architect est une phrase, pas un diagnostic

Dans `orchestrator_loop.py`, quand le Tester échoue :

```python
reflection = tester_result.payload.get("reflection", "Tester: rejected")
reflections.append(f"Tester[{iteration}]: {reflection}")
```

Et dans `tester_runner.py`, `_build_reflection()` produit :

```
"Tester: sandbox_passed=False, tests_failed=1, stderr=..."
```

L'Architect reçoit cette chaîne à l'itération suivante via `arch_context["reflection"]`.
Il n'a aucune information sur **quelle** règle de qualité a échoué, **quelle** ligne pose
problème, ni **quoi** corriger. La boucle stagne plutôt que de converger.

**`CodeEvaluator` calcule déjà un score détaillé — il n'est jamais réinjecté dans la boucle.**
Le score et les critères (type hints, docstrings, anti-patterns) restent dans
`TesterAgent.run_task()` sans jamais remonter vers le CoderAgent.

### 1.2 ModelRouter est une île

`core/model_router.py` est implémenté, 55 tests passent. Mais :

```python
# CoderAgent.create() — comportement actuel
candidate = LLMGenerator()  # instanciation directe, ignore ModelRouter
```

Le routing complexité-faible → 3b / complexité-élevée → 7b / online n'est jamais
déclenché. Le module existe, branché nulle part.

### 1.3 SandboxEngine mode "soft" = pas de sandbox

```python
subprocess.run([sys.executable, "-c", code], cwd=str(self.workspace))
```

Mode `auto` → Docker si disponible, sinon soft. Sur la machine de dev (venv actif,
Docker non garanti), le code LLM s'exécute avec accès complet à `D:\LLMCodeAgent\`.
Le mode Docker existe (`_run_docker`) mais n'est pas activé explicitement.

### 1.4 SkillLibrary.usage_count/success_rate ne bougent jamais

`_maybe_store_skill()` dans `TesterAgent` stocke un skill si le code passe.
`KarpathyLoop` récupère les skills via `skill_library.retrieve(intent)`.
Mais il n'y a aucun code qui incrémente `usage_count` ou met à jour `success_rate`
en fonction des itérations de la boucle. Les skills sont ingérés et récupérés,
mais leur qualité n'est jamais mesurée.

---

## 2. Périmètre — ce qui est hors scope

| Hors scope V1 | Raison |
|---|---|
| Génération de tests pytest | Sprint complet indépendant (TestAgent V2), pas un fix |
| PatchAgent (diff incrémental) | Dépend de SPEC-PATCH-AGENT future |
| Routing online (API cloud) | Hors contrainte 100% offline |
| Réécriture KarpathyLoop | Pas nécessaire — les 4 sprints patchent l'existant |

---

## 3. Sprints

### Sprint FL-01 — Réflexion structurée Tester → Architect

**Objectif** : remplacer la phrase vague par un dict actionnable.

**Fichiers touchés** :
- `core/agents/tester_runner.py` — `_build_reflection()`
- `core/agents/tester_agent.py` — `run_task()` branche échec
- `core/agents/orchestrator_loop.py` — injection `arch_context`
- `core/agents/coder_builder.py` — `build_coder_prompt()` prend les hints

**Nouveau type** dans `core/agents/tester_runner.py` :

```python
@dataclass
class StructuredReflection:
    sandbox_passed: bool
    quality_score: int
    quality_criteria: list[dict]   # [{"name": "type_hints", "score": 5, "max": 20, "details": "..."}, ...]
    stderr_short: str              # 200 chars max
    fix_hints: list[str]           # ["Add type hints to all function args", "Remove bare except"]
    iteration: int
```

**`_build_reflection()` modifiée** (signature compatible) :

```python
def _build_reflection(
    sandbox_result: dict,
    receipt: ExecutionReceipt,
    eval_result=None,          # EvaluationResult optionnel — rétrocompat
    iteration: int = 0,
) -> StructuredReflection:
    ...
```

**Règle** : si `eval_result` est None (appelant ne fournit pas), `fix_hints` est vide
et `quality_criteria` est `[]`. Rétrocompat totale.

**Génération des `fix_hints`** depuis `EvaluationResult.criteria` :

```python
def _criteria_to_fix_hints(criteria: list[CriterionScore]) -> list[str]:
    """
    Traduit les critères CodeEvaluator en instructions correctables pour le LLM.
    Retourne au maximum 5 hints, les plus impactants en premier.
    """
    _HINT_MAP = {
        "Syntaxe Python":    None,                              # bloquant, pas de hint utile
        "Type hints":        "Add type annotations to all function arguments and return values",
        "Docstrings":        "Add a docstring to every function and class",
        "Complexité":        "Reduce cyclomatic complexity — split functions over 10 branches",
        "Anti-patterns":     None,                              # détaillé dans details
    }
    hints = []
    # Trier par score croissant (les pires critères en premier)
    sorted_criteria = sorted(criteria, key=lambda c: c.score)
    for c in sorted_criteria:
        if c.score >= c.max:
            continue   # critère plein — pas de hint
        # Hint générique mappé
        generic = _HINT_MAP.get(c.name)
        if generic:
            hints.append(generic)
        # Hint spécifique depuis details (ex: "bare_except detected at line 12")
        if c.details and c.details not in ("Valide", "Valid"):
            hints.append(f"Fix: {c.details}")
    return hints[:5]
```

**Dans `TesterAgent.run_task()`** — branche échec :

```python
# Avant
reflection = _build_reflection(sandbox_result, receipt)

# Après
reflection = _build_reflection(
    sandbox_result, receipt,
    eval_result=eval_result_obj,   # déjà calculé juste au-dessus
    iteration=contract.context.get("iteration", 0),
)
reject_payload = {
    ...
    "reflection": reflection.stderr_short,           # str pour rétrocompat
    "reflection_structured": asdict(reflection),     # nouveau, ignoré par ancien code
}
```

**Dans `orchestrator_loop.py`** :

```python
# Avant
if reflections:
    arch_context["reflection"] = " | ".join(reflections[-3:])

# Après
arch_context["reflection"] = " | ".join(reflections[-3:])
if structured_reflections:
    recent_hints = []
    for sr in structured_reflections[-2:]:
        recent_hints.extend(sr.get("fix_hints", []))
    arch_context["fix_hints"] = list(dict.fromkeys(recent_hints))  # dédup, ordre préservé
    arch_context["last_quality_score"] = structured_reflections[-1].get("quality_score", 0)
```

**Dans `coder_builder.py`** — `build_coder_prompt()` :

```python
def build_coder_prompt(intent: str, domain: str, skills_ctx: str,
                       fix_hints: list[str] | None = None,
                       last_quality_score: int | None = None) -> str:
    lines = [f"Domain: {domain}", f"Task: {intent}"]
    if last_quality_score is not None and last_quality_score < 100:
        lines.append(f"\nPrevious attempt quality score: {last_quality_score}/100")
    if fix_hints:
        lines.append("\nRequired fixes for this iteration:")
        for hint in fix_hints:
            lines.append(f"  - {hint}")
    if skills_ctx:
        lines.append(f"\nAvailable skills (reuse if relevant):\n{skills_ctx}")
    lines.append("\nGenerate a Python function or module. Output ONLY the Python code:")
    return "\n".join(lines)
```

**Tests à créer** — `tests/test_fl_01.py` (18 tests) :

| Classe | Tests |
|---|---|
| `TestStructuredReflection` | dataclass fields, asdict, fix_hints vide si eval=None |
| `TestBuildReflectionEnriched` | avec eval_result, sans eval_result (rétrocompat) |
| `TestCriteriaToFixHints` | critère plein ignoré, top 5 max, détails inclus |
| `TestOrchestratorContextInjection` | fix_hints dans arch_context, dédup, max 2 itérations |
| `TestCoderPromptWithHints` | prompt enrichi, prompt sans hints, score affiché |
| `TestTesterRejectPayload` | reflection_structured présent, reflection str rétrocompat |

**Invariants FL-01** :

- `_build_reflection()` ne lève jamais si `eval_result=None` (rétrocompat)
- `reflection_structured` absent du payload = ignoré silencieusement par l'Architect
- `fix_hints` max 5 items depuis `_criteria_to_fix_hints`, 10 max dans `arch_context` (dédup 2 itérations)
- `last_quality_score` absent de `arch_context` si premier essai (pas de `0` parasite)
- `asdict()` importé depuis `dataclasses` stdlib uniquement

---

### Sprint FL-02 — Branchement ModelRouter dans le pipeline

**Objectif** : que `CoderAgent` consulte réellement `ModelRouter` avant de sélectionner
son modèle LLM. `ReviewerAgent` en second temps (même pattern, moindre priorité).

**Fichiers touchés** :
- `core/agents/coder_agent.py` — `create()` + `_generate_code()`
- `core/agents/agent_orchestrator.py` — instanciation du router
- `core/llm_generator.py` — nouveau paramètre `model_override`
- `core/model_router.py` — aucun changement (déjà conforme)

**Principe** : `ModelRouter` est instancié une seule fois dans `AgentOrchestrator.create()`
et injecté dans les agents. Chaque agent consulte le router avant chaque appel LLM,
en passant le `complexity_score` issu du contexte du contrat.

**Dans `AgentOrchestrator.create()`** :

```python
from core.model_router import ModelRouter
router = ModelRouter()   # charge online_models.json, routing.enabled=False par défaut
coder    = CoderAgent.create(bus, mcp_caller, llm_generator, router=router)
reviewer = ReviewerAgent.create(bus, mcp_caller, llm_generator, router=router)
```

**Dans `CoderAgent.__init__()`** :

```python
def __init__(self, ..., router=None) -> None:
    ...
    self._router = router   # None = comportement actuel (aucune régression)
```

**Dans `CoderAgent._generate_code()`** :

```python
def _generate_code(self, contract: TaskContract, skills_ctx: str) -> str:
    if self._llm is None:
        return ""

    model_override: str | None = None
    if self._router is not None:
        complexity = contract.context.get("complexity_score", 0)
        decision = self._router.get_model("coding", complexity, api_key=None)
        if not decision.fallback_used:
            model_override = decision.model_name
            log.info("[coder] ModelRouter -> %s (reason: %s)",
                     model_override, decision.reason)

    prompt = _build_coder_prompt(
        contract.intent, contract.domain, skills_ctx,
        fix_hints=contract.context.get("fix_hints"),
        last_quality_score=contract.context.get("last_quality_score"),
    )
    try:
        raw = self._llm.generate_text(
            system=_CODER_SYSTEM,
            user=prompt,
            model_override=model_override,
        )
        ...
```

**Dans `LLMGenerator.generate_text()`** — ajout `model_override` :

```python
def generate_text(self, system: str, user: str,
                  model_override: str | None = None) -> str:
    model = model_override or self.ollama.model   # rétrocompat totale si None
    ...
```

**Règle d'activation** : `routing.enabled = false` dans `online_models.json` par défaut.
Le router est branché mais silencieux jusqu'à activation explicite dans le JSON.
Zéro changement de comportement sans activation manuelle.

**Tests à créer** — `tests/test_fl_02.py` (15 tests) :

| Classe | Tests |
|---|---|
| `TestCoderAgentRouter` | router=None (rétrocompat), router injecté → consulté, model_override transmis |
| `TestLLMGeneratorModelOverride` | model_override=None (défaut), model_override passé à OllamaClient |
| `TestOrchestratorRouterInjection` | router instancié dans create(), injecté coder+reviewer |
| `TestRouterDisabledByDefault` | routing.enabled=false → pas de model_override |
| `TestRouterComplexityPath` | complexity_score=80 → heavy local si configuré dans JSON |

**Invariants FL-02** :

- `router=None` dans CoderAgent → comportement identique à avant (0 régression)
- `model_override=None` dans LLMGenerator.generate_text() → `self.ollama.model` utilisé
- `routing.enabled=false` dans online_models.json = état par défaut du projet
- Aucun appel réseau ajouté (ModelRouter lit uniquement un JSON local)
- `AgentOrchestrator.create()` = unique point d'instanciation du router

---

### Sprint FL-03 — SandboxEngine : durcissement du mode soft

**Objectif** : réduire la surface d'exposition du mode soft sans Docker requis.

**Fichier touché** : `core/sandbox_engine.py` uniquement.

**Problème actuel** :

```python
subprocess.run([sys.executable, "-c", code],
               capture_output=True, text=True, timeout=timeout,
               cwd=str(self.workspace))
```

Le code LLM s'exécute avec :
- Accès à tout `sys.path` du venv (imports libres)
- `cwd = D:\LLMCodeAgent\workspace` → `open("../core/config.py")` est atteignable
- Aucune restriction sur les modules importables

**Solution soft-hardened** (sans Docker, sans dépendances tierces) :

```python
_FORBIDDEN_SOFT: frozenset[str] = frozenset({
    "subprocess", "socket", "pty", "ctypes",
    "importlib", "zipimport", "multiprocessing", "winreg",
})

def _prescan_imports(self, code: str) -> str | None:
    """
    Retourne le nom du premier import interdit trouvé, ou None si OK.
    Analyse AST — pas de regex. Silencieux sur SyntaxError (gérée par sandbox).
    """
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _FORBIDDEN_SOFT:
                    return alias.name
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod in _FORBIDDEN_SOFT:
                return node.module
    return None

def _run_subprocess_hardened(self, code: str, timeout: int) -> RunResult:
    """
    Mode soft durci :
    1. Pré-scan AST des imports (bloquant si import interdit, exit_code=-2)
    2. PYTHONPATH='' (pas d'accès packages venv parent)
    3. cwd = répertoire temporaire isolé (pas workspace direct)
    """
    forbidden = self._prescan_imports(code)
    if forbidden:
        return False, "", f"Import interdit bloque par sandbox : {forbidden}", -2

    import os, copy, tempfile
    env = copy.copy(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = ""

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True,
                timeout=timeout,
                cwd=tmpdir,
                env=env,
            )
            return (result.returncode == 0, result.stdout, result.stderr, result.returncode)
        except subprocess.TimeoutExpired:
            return False, "", f"Timeout apres {timeout}s", -1
        except Exception as exc:
            return False, "", str(exc), -1
```

**Migration** :
- `_run_subprocess()` (actuel) → renommé `_run_subprocess_legacy()` (conservé pour tests)
- `_run_subprocess_hardened()` → devient le nouveau `_run_subprocess()` appelé par `run()`
- `effective_mode` retourne `"soft_hardened"` au lieu de `"soft"`

**Tests à créer** — `tests/test_fl_03.py` (14 tests) :

| Classe | Tests |
|---|---|
| `TestPrescanImports` | subprocess bloqué, socket bloqué, pathlib autorisé, json autorisé, SyntaxError ignorée |
| `TestSoftHardened` | cwd est tmpdir (pas workspace), PYTHONPATH vide dans env, timeout respecté |
| `TestForbiddenImportBlocked` | exit_code=-2, stderr contient le nom de l'import interdit |
| `TestLegacyModePreserved` | _run_subprocess_legacy() produit même résultat qu'avant FL-03 |
| `TestDockerUnchanged` | mode docker non impacté par FL-03 |

**Invariants FL-03** :

- `_prescan_imports` retourne `None` sur `SyntaxError` (gérée par sandbox lui-même)
- `_run_subprocess_legacy` conservé, jamais supprimé
- `PYTHONPATH=""` dans env → stdlib toujours disponible (`json`, `pathlib`, `ast`...)
- Pas de dépendance externe ajoutée (ast, copy, tempfile = stdlib)
- `exit_code=-2` = code interne LCCA "import bloqué" (distinct de -1 = timeout)

---

### Sprint FL-04 — SkillLibrary : métriques actives dans la boucle

**Objectif** : que `usage_count` et `success_rate` reflètent l'utilité réelle des skills
dans le pipeline.

**Fichiers touchés** :
- `core/skill_library.py` — nouvelles méthodes `record_usage()` + `record_outcome()`
- `core/agents/orchestrator_loop.py` — appels après chaque résultat Tester

**Problème** : dans `KarpathyLoop.run()`, les skills sont récupérés et injectés dans le
prompt du Coder, mais après l'itération (succès ou échec), rien n'est enregistré.
Les skills injectés dans le prompt ne savent jamais s'ils ont aidé ou non.

**Nouvelles méthodes dans `SkillLibrary`** :

```python
def record_usage(self, skill_ids: list[str]) -> None:
    """
    Incrémente usage_count pour chaque skill. Silencieux si skill_id inconnu.
    """
    for skill_id in skill_ids:
        try:
            entry = self._get_by_id(skill_id)
            if entry is not None:
                entry.usage_count = (entry.usage_count or 0) + 1
                self._persist(entry)
        except Exception as exc:
            log.debug("[skill_library] record_usage failed for %s: %s", skill_id, exc)

def record_outcome(self, skill_ids: list[str], success: bool) -> None:
    """
    Met à jour success_rate (moyenne pondérée glissante).
    Formule : new_rate = (old_rate * (n-1) + outcome) / n
    Appelé APRES record_usage pour que usage_count soit déjà incrémenté.
    """
    for skill_id in skill_ids:
        try:
            entry = self._get_by_id(skill_id)
            if entry is None:
                continue
            n = max(entry.usage_count or 1, 1)
            old_rate = entry.success_rate if isinstance(entry.success_rate, float) else 0.0
            new_rate = (old_rate * (n - 1) + (1.0 if success else 0.0)) / n
            entry.success_rate = max(0.0, min(1.0, new_rate))   # clamp invariant
            self._persist(entry)
        except Exception as exc:
            log.debug("[skill_library] record_outcome failed for %s: %s", skill_id, exc)
```

**Helper module-level dans `orchestrator_loop.py`** :

```python
def _extract_skill_ids(skill_entries) -> list[str]:
    """
    Extrait les skill_ids depuis une liste de SkillEntry ou dicts.
    Retourne [] pour tout input None/invalide/vide.
    """
    if not skill_entries:
        return []
    ids = []
    for e in skill_entries:
        if hasattr(e, "skill_id"):
            ids.append(e.skill_id)
        elif isinstance(e, dict) and "skill_id" in e:
            ids.append(e["skill_id"])
    return ids
```

**Dans `KarpathyLoop.run()`** — après chaque résultat Tester :

```python
used_skill_ids = _extract_skill_ids(skill_entries)   # skill_entries déjà en scope
if self._skill_lib is not None and used_skill_ids:
    self._skill_lib.record_usage(used_skill_ids)
    # record_outcome appelé APRES record_usage (usage_count incrémenté avant)
    self._skill_lib.record_outcome(used_skill_ids, success=tester_result.success)
```

**Précision sur `skill_entries`** : la variable est déjà dans le scope de la boucle
(utilisée pour `_format_skills_context`). Aucune modification de la structure de la boucle.

**Tests à créer** — `tests/test_fl_04.py` (14 tests) :

| Classe | Tests |
|---|---|
| `TestRecordUsage` | usage_count incrémenté, skill_id inconnu ignoré, liste vide OK, exception silencieuse |
| `TestRecordOutcome` | success_rate converge vers 1.0 après N succès, clamp [0,1], formule pondérée |
| `TestExtractSkillIds` | SkillEntry objects, dicts, liste vide, None, mixte |
| `TestLoopMetricsIntegration` | record_usage/record_outcome appelés après chaque Tester (mock skill_lib) |
| `TestSkillLibNoneGuard` | skill_lib=None dans KarpathyLoop → pas d'AttributeError |

**Invariants FL-04** :

- `record_usage()` et `record_outcome()` ne lèvent jamais (except swallowed, logged debug)
- `success_rate` invariant `[0.0, 1.0]` après toute mise à jour (clamp explicite)
- `record_outcome()` appelé APRES `record_usage()` — usage_count doit être à jour
- `_extract_skill_ids()` retourne `[]` pour tout input None/invalide
- `_maybe_store_skill()` dans TesterAgent inchangé (FL-04 ne touche pas au stockage initial)
- `usage_count` initialisé à `0` si `None` (défense contre états partiels ChromaDB)

---

## 4. Ordre d'implémentation recommandé

| Ordre | Sprint | Dépendances | Tests | Impact immédiat |
|---|---|---|---|---|
| 1 | **FL-01** | Aucune | 18 | Feedback actionnable — la boucle converge mieux |
| 2 | **FL-03** | Aucune | 14 | Sécurité sandbox — indépendant de tout le reste |
| 3 | **FL-02** | FL-01 (fix_hints prompt) | 15 | ModelRouter actif |
| 4 | **FL-04** | FL-01, FL-02 | 14 | Métriques skills vivantes |

FL-01 et FL-03 peuvent être faits en parallèle (fichiers totalement disjoints).
FL-02 dépend logiquement de FL-01 : le prompt enrichi est la raison principale
de changer de modèle selon la complexité observée.
FL-04 en dernier : dépend des skill_ids qui remontent correctement dans le contexte.

---

## 5. Comptage tests

| Sprint | Tests nouveaux | Fichier |
|---|---|---|
| FL-01 | 18 | `tests/test_fl_01.py` |
| FL-02 | 15 | `tests/test_fl_02.py` |
| FL-03 | 14 | `tests/test_fl_03.py` |
| FL-04 | 14 | `tests/test_fl_04.py` |
| **Total** | **61** | — |

Projection après ces 4 sprints : **~1599 tests** (1538 actuel + 61).

---

## 6. Fichiers modifiés par sprint (récapitulatif)

### FL-01
```
core/agents/tester_runner.py       + StructuredReflection dataclass
                                   + _criteria_to_fix_hints() helper
                                   ~ _build_reflection() signature étendue
core/agents/tester_agent.py        ~ run_task() branche échec : reflection_structured
core/agents/orchestrator_loop.py   ~ run() : fix_hints + last_quality_score dans arch_context
core/agents/coder_builder.py       ~ build_coder_prompt() : fix_hints + last_quality_score
tests/test_fl_01.py                + NOUVEAU (18 tests)
```

### FL-02
```
core/agents/coder_agent.py         ~ create() + __init__() + _generate_code() : router
core/agents/reviewer_analyzer.py   ~ analyze() : model_override optionnel
core/agents/agent_orchestrator.py  ~ create() : ModelRouter instancié + injecté
core/llm_generator.py              ~ generate_text() : model_override param
tests/test_fl_02.py                + NOUVEAU (15 tests)
```

### FL-03
```
core/sandbox_engine.py             + _prescan_imports()
                                   + _FORBIDDEN_SOFT frozenset
                                   ~ _run_subprocess() → _run_subprocess_hardened()
                                   + _run_subprocess_legacy() (rétrocompat)
                                   ~ effective_mode : "soft_hardened"
tests/test_fl_03.py                + NOUVEAU (14 tests)
```

### FL-04
```
core/skill_library.py              + record_usage()
                                   + record_outcome()
                                   (+ _get_by_id() si méthode absente)
core/agents/orchestrator_loop.py   + _extract_skill_ids()
                                   ~ run() : record_usage/record_outcome après Tester
tests/test_fl_04.py                + NOUVEAU (14 tests)
```

---

## 7. Règles invariantes (numérotation suite à 001-master.md)

| Ref | Règle | Fichier porteur |
|---|---|---|
| FL-01-R1 | `_build_reflection()` ne lève jamais si `eval_result=None` | tester_runner.py |
| FL-01-R2 | `reflection_structured` absent du payload = ignoré silencieusement | orchestrator_loop.py |
| FL-01-R3 | `fix_hints` max 5 dans `_criteria_to_fix_hints`, 10 max dans arch_context (dédup 2 iter.) | orchestrator_loop.py |
| FL-01-R4 | `last_quality_score` absent de `arch_context` si iteration=0 | orchestrator_loop.py |
| FL-02-R1 | `router=None` dans CoderAgent = comportement identique à avant FL-02 | coder_agent.py |
| FL-02-R2 | `routing.enabled=false` dans online_models.json = état par défaut du projet | model_router.py |
| FL-02-R3 | `AgentOrchestrator.create()` = unique point d'instanciation ModelRouter | agent_orchestrator.py |
| FL-02-R4 | `model_override=None` dans generate_text() = `self.ollama.model` inchangé | llm_generator.py |
| FL-03-R1 | `_prescan_imports` retourne `None` sur `SyntaxError` | sandbox_engine.py |
| FL-03-R2 | `_run_subprocess_legacy` conservé, jamais supprimé | sandbox_engine.py |
| FL-03-R3 | `PYTHONPATH=""` dans env soft-hardened | sandbox_engine.py |
| FL-03-R4 | `exit_code=-2` = import bloqué (distinct de `-1` = timeout/exception) | sandbox_engine.py |
| FL-04-R1 | `record_usage/record_outcome` silencieux sur toute exception (logged debug) | skill_library.py |
| FL-04-R2 | `success_rate` invariant `[0.0, 1.0]` (clamp explicite) | skill_library.py |
| FL-04-R3 | `record_outcome()` toujours appelé APRES `record_usage()` | orchestrator_loop.py |
| FL-04-R4 | `_extract_skill_ids()` retourne `[]` pour tout input None/invalide | orchestrator_loop.py |

---

## 8. Critères de succès (definition of done par sprint)

### FL-01 done si :
- `pytest tests/test_fl_01.py` : 18 passed
- `pytest tests/test_v8_04.py tests/test_orchestrator.py` : toujours verts
- `_build_reflection(sandbox_result, receipt)` sans `eval_result` : résultat identique à avant

### FL-02 done si :
- `pytest tests/test_fl_02.py` : 15 passed
- `pytest tests/test_model_router.py` : toujours verts
- `CoderAgent.create(bus)` sans `router=` : même comportement qu'avant FL-02

### FL-03 done si :
- `pytest tests/test_fl_03.py` : 14 passed
- `SandboxEngine(mode="soft").run("import subprocess\nprint(1)")` : exit_code=-2
- `SandboxEngine(mode="soft").run("import json\nprint(json.dumps({'a':1}))")` : success=True

### FL-04 done si :
- `pytest tests/test_fl_04.py` : 14 passed
- Après `KarpathyLoop.run()` avec skill_lib mockée : `record_usage` appelé >= 1× par itération Tester
- `KarpathyLoop(skill_lib=None)` : aucune AttributeError

---

<!-- AI-READY | SPEC-PIPELINE-FEEDBACK-V1 | 2026-04-29 -->
