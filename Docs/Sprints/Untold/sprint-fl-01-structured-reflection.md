# Sprint FL-01 — Réflexion structurée Tester → Architect
<!-- AI-READY | LCCA V11 | Sprint FL-01 | Priorité P0 | Effort 1j | Statut : 🔲 À FAIRE -->

## Objectif

Remplacer la chaîne vague `"Tester: sandbox_passed=False, tests_failed=1"` par un
diagnostic structuré (`StructuredReflection`) contenant les critères `CodeEvaluator`
traduits en instructions correctables pour le LLM.

**CodeEvaluator calcule déjà le bon diagnostic — il n'est jamais réinjecté dans la boucle.**
Ce sprint branche ce qui existe sur ce qui manque.

## Prérequis

- `core/agents/tester_runner.py` — `_build_reflection()`, `TesterReceiptBuilder` existants ✅
- `core/agents/tester_agent.py` — `run_task()` existant ✅
- `core/code_evaluator.py` — `EvaluationResult.criteria` (list[CriterionScore]) existant ✅
- `core/agents/orchestrator_loop.py` — `KarpathyLoop.run()` existant ✅
- `core/agents/coder_builder.py` — `build_coder_prompt()` existant ✅

## Fichiers cibles

| # | Fichier | Opération | Lignes estimées |
|---|---------|-----------|-----------------|
| 1 | `core/agents/tester_runner.py` | PATCH — ajout `StructuredReflection` + `_criteria_to_fix_hints()` + signature étendue | +70 lignes |
| 2 | `core/agents/tester_agent.py` | PATCH — `run_task()` branche échec enrichie | +15 lignes |
| 3 | `core/agents/orchestrator_loop.py` | PATCH — injection `fix_hints` + `last_quality_score` dans arch_context | +25 lignes |
| 4 | `core/agents/coder_builder.py` | PATCH — `build_coder_prompt()` étendue | +20 lignes |
| 5 | `tests/test_fl_01.py` | CREATE | ~120 lignes |

## Spécification

### 1. Nouveau type dans `tester_runner.py`

Ajouter **avant** `TesterReceiptBuilder` (ligne ~20 du fichier actuel) :

```python
# FL-01 : dataclass résultat structuré
from dataclasses import dataclass, field, asdict as _asdict
from typing import List, Dict, Any

@dataclass
class StructuredReflection:
    """
    FL-01 : Diagnostic actionnable produit par TesterAgent.
    Remplace la chaîne vague "Tester: sandbox_passed=False...".
    """
    sandbox_passed:    bool
    quality_score:     int
    quality_criteria:  List[Dict[str, Any]]   # [{name, score, max, details}, ...]
    stderr_short:      str                    # 200 chars max
    fix_hints:         List[str]              # instructions LLM, max 5
    iteration:         int

    def to_dict(self) -> Dict[str, Any]:
        return _asdict(self)
```

### 2. Helper `_criteria_to_fix_hints()` dans `tester_runner.py`

Ajouter **après** `StructuredReflection` :

```python
# Mapping nom critère CodeEvaluator → instruction LLM actionnable
_HINT_MAP: Dict[str, str | None] = {
    "Syntaxe Python": None,   # bloquant — pas de hint utile (code invalide)
    "Type hints":     "Add type annotations to all function arguments and return values",
    "Docstrings":     "Add a docstring to every function and class",
    "Complexité":     "Reduce cyclomatic complexity — split functions exceeding 10 branches",
    "Anti-patterns":  None,   # détaillé via criterion.details ci-dessous
}

def _criteria_to_fix_hints(criteria: list) -> List[str]:
    """
    Traduit les critères CodeEvaluator en instructions correctables.
    Retourne max 5 hints, les critères les plus impactants en premier.

    Args:
        criteria : list[CriterionScore] — chaque objet a .name .score .max .details

    Returns:
        List[str] — vide si criteria est vide ou None.
    """
    if not criteria:
        return []

    hints: List[str] = []
    # Trier par score croissant (pires critères en premier)
    sorted_crit = sorted(criteria, key=lambda c: getattr(c, "score", 0))

    for c in sorted_crit:
        score   = getattr(c, "score",   0)
        max_s   = getattr(c, "max",     1)
        name    = getattr(c, "name",    "Unknown")
        details = getattr(c, "details", "") or ""

        if score >= max_s:
            continue   # critère plein — rien à corriger

        # Hint générique si mappé
        generic = _HINT_MAP.get(name)
        if generic:
            hints.append(generic)

        # Hint spécifique depuis details (ex: "bare_except at line 12")
        if details and details not in ("Valide", "Valid"):
            specific = f"Fix: {details}"
            if specific not in hints:
                hints.append(specific)

    return hints[:5]
```

### 3. Signature étendue de `_build_reflection()` dans `tester_runner.py`

Remplacer la fonction existante :

```python
# AVANT
def _build_reflection(sandbox_result: dict, receipt: ExecutionReceipt) -> str:
    sandbox_ok = sandbox_result.get("success", False)
    stderr_short = (sandbox_result.get("stderr", "") or "")[:200]
    return (
        f"Tester: sandbox_passed={sandbox_ok}, "
        f"tests_failed={receipt.tests_failed}"
        + (f", stderr={stderr_short}" if stderr_short else "")
    )

# APRÈS — FL-01 (signature étendue, rétrocompat : eval_result optionnel)
def _build_reflection(
    sandbox_result: dict,
    receipt: "ExecutionReceipt",
    eval_result=None,    # EvaluationResult (CodeEvaluator) — optionnel
    iteration: int = 0,
) -> StructuredReflection:
    """
    FL-01 : Construit une réflexion structurée depuis les résultats sandbox.

    Rétrocompat : eval_result=None → fix_hints=[], quality_criteria=[]
                  Les appelants existants qui ne passent pas eval_result
                  continuent de fonctionner sans modification.
    """
    sandbox_ok   = sandbox_result.get("success", False)
    stderr       = sandbox_result.get("stderr", "") or ""
    stderr_short = stderr[:200]

    quality_score    = 0
    quality_criteria: List[Dict[str, Any]] = []
    fix_hints:        List[str] = []

    if eval_result is not None:
        quality_score = getattr(eval_result, "score", 0)
        criteria = getattr(eval_result, "criteria", [])
        for c in (criteria or []):
            quality_criteria.append({
                "name":    getattr(c, "name",    "Unknown"),
                "score":   getattr(c, "score",   0),
                "max":     getattr(c, "max",     1),
                "details": getattr(c, "details", "") or "",
            })
        fix_hints = _criteria_to_fix_hints(criteria)

    return StructuredReflection(
        sandbox_passed   = sandbox_ok,
        quality_score    = quality_score,
        quality_criteria = quality_criteria,
        stderr_short     = stderr_short,
        fix_hints        = fix_hints,
        iteration        = iteration,
    )
```

> ⚠️ `TesterReceiptBuilder` et `_run_sandbox_safe` ne sont **pas touchés**.
> `_hash` non plus. Seule `_build_reflection` est modifiée.

### 4. PATCH `tester_agent.py` — branche échec de `run_task()`

Dans `run_task()`, après le calcul de `quality_score` (ligne ~80 du fichier actuel),
**garder l'objet `eval_result`** pour le passer à `_build_reflection` :

```python
# FL-01 : conserver eval_result pour la réflexion structurée
try:
    eval_result = self._evaluator.evaluate(code, filename="<agent_output>")
    quality_score = eval_result.score
except Exception as exc:
    logger.debug("[tester] evaluator error: %s", exc)
    eval_result   = None
    quality_score = 0
```

Dans la branche `else` (échec, lignes ~105-120 du fichier) :

```python
# AVANT
reflection = _build_reflection(sandbox_result, receipt)
reject_payload = {
    "rejected": True,
    ...
    "reflection": reflection,
    ...
}

# APRÈS — FL-01
reflection_struct = _build_reflection(
    sandbox_result,
    receipt,
    eval_result=eval_result,                     # FL-01 : nouvel arg
    iteration=contract.context.get("iteration", 0),
)
reject_payload = {
    "rejected":                True,
    "tester_ok":               False,
    "sandbox_passed":          sandbox_ok,
    "quality_score":           quality_score,
    "reflection":              reflection_struct.stderr_short,   # str — rétrocompat
    "reflection_structured":   reflection_struct.to_dict(),      # FL-01 : nouveau
    "fix_hints":               reflection_struct.fix_hints,      # FL-01 : raccourci
    "original_intent":         original_intent,
    "task_id":                 contract.task_id,
}
```

### 5. PATCH `orchestrator_loop.py` — injection dans `arch_context`

Dans `KarpathyLoop.run()`, **ajouter une liste locale** au début de la méthode :

```python
# FL-01 : accumule les réflexions structurées de la boucle (liste locale à run())
structured_reflections: list[dict] = []
```

Après le bloc qui récupère le résultat du Tester (dans la branche `else` d'échec) :

```python
# FL-01 : stocker la réflexion structurée
sr = tester_result.payload.get("reflection_structured")
if sr:
    structured_reflections.append(sr)
```

Dans la construction du `arch_context` **au début de chaque itération** (là où
`arch_context["reflection"]` est déjà rempli) :

```python
# Existant — inchangé
if reflections:
    arch_context["reflection"] = " | ".join(reflections[-3:])

# FL-01 : hints et score des 2 dernières itérations
if structured_reflections:
    recent_hints: list[str] = []
    for sr in structured_reflections[-2:]:
        recent_hints.extend(sr.get("fix_hints", []))
    # Déduplication ordre préservé
    seen: set[str] = set()
    deduped: list[str] = []
    for h in recent_hints:
        if h not in seen:
            seen.add(h)
            deduped.append(h)
    arch_context["fix_hints"]          = deduped[:10]
    arch_context["last_quality_score"] = structured_reflections[-1].get("quality_score", 0)
```

> `structured_reflections` est une liste **locale à `run()`** — pas un attribut d'instance.
> Cela évite toute accumulation entre deux appels `run()` distincts sur la même instance.

### 6. PATCH `coder_builder.py` — `build_coder_prompt()` étendue

```python
# AVANT
def build_coder_prompt(intent: str, domain: str, skills_ctx: str) -> str:

# APRÈS — FL-01 (rétrocompat : nouveaux args optionnels)
def build_coder_prompt(
    intent: str,
    domain: str,
    skills_ctx: str,
    fix_hints: list[str] | None = None,
    last_quality_score: int | None = None,
) -> str:
    """
    Construit le prompt utilisateur pour le LLM.
    FL-01 : enrichi avec fix_hints et last_quality_score si disponibles.
    """
    lines = [f"Domain: {domain}", f"Task: {intent}"]

    # FL-01 : score précédent
    if last_quality_score is not None and last_quality_score < 100:
        lines.append(f"\nPrevious attempt quality score: {last_quality_score}/100")

    # FL-01 : instructions de correction obligatoires
    if fix_hints:
        lines.append("\nRequired fixes for this iteration:")
        for hint in fix_hints:
            lines.append(f"  - {hint}")

    if skills_ctx:
        lines.append(f"\nAvailable skills (reuse if relevant):\n{skills_ctx}")

    lines.append(
        "\nGenerate a Python function or module that fulfills the task. "
        "Output ONLY the Python code:"
    )
    return "\n".join(lines)
```

Dans `CoderAgent._generate_code()`, passer les nouveaux args depuis le contexte :

```python
prompt = _build_coder_prompt(
    contract.intent,
    contract.domain,
    skills_ctx,
    fix_hints          = contract.context.get("fix_hints"),           # FL-01
    last_quality_score = contract.context.get("last_quality_score"),  # FL-01
)
```

## Tests — `tests/test_fl_01.py`

```python
# tests/test_fl_01.py
"""FL-01 — Tests réflexion structurée Tester → Architect."""
import pytest
from dataclasses import asdict
from unittest.mock import MagicMock, patch


# ── TestStructuredReflection ──────────────────────────────────────────────────

class TestStructuredReflection:
    def test_fields_present(self):
        from core.agents.tester_runner import StructuredReflection
        sr = StructuredReflection(
            sandbox_passed=False, quality_score=40,
            quality_criteria=[], stderr_short="err", fix_hints=["fix A"], iteration=1,
        )
        assert sr.sandbox_passed is False
        assert sr.quality_score == 40
        assert sr.fix_hints == ["fix A"]

    def test_to_dict_serializable(self):
        from core.agents.tester_runner import StructuredReflection
        sr = StructuredReflection(
            sandbox_passed=True, quality_score=85,
            quality_criteria=[{"name": "Type hints", "score": 15, "max": 20, "details": ""}],
            stderr_short="", fix_hints=[], iteration=0,
        )
        d = sr.to_dict()
        assert isinstance(d, dict)
        assert d["quality_score"] == 85

    def test_eval_result_none_gives_empty_hints(self):
        from core.agents.tester_runner import _build_reflection
        from core.receipt_store import ExecutionReceipt
        receipt = MagicMock(spec=ExecutionReceipt)
        receipt.tests_failed = 1
        sr = _build_reflection({"success": False, "stderr": "oops"}, receipt)
        assert sr.fix_hints == []
        assert sr.quality_criteria == []
        assert sr.quality_score == 0


# ── TestCriteriaToFixHints ────────────────────────────────────────────────────

class TestCriteriaToFixHints:
    def _make_criterion(self, name, score, max_s, details=""):
        c = MagicMock()
        c.name = name
        c.score = score
        c.max = max_s
        c.details = details
        return c

    def test_full_criterion_ignored(self):
        from core.agents.tester_runner import _criteria_to_fix_hints
        c = self._make_criterion("Type hints", 20, 20)
        assert _criteria_to_fix_hints([c]) == []

    def test_type_hints_mapped(self):
        from core.agents.tester_runner import _criteria_to_fix_hints
        c = self._make_criterion("Type hints", 5, 20)
        hints = _criteria_to_fix_hints([c])
        assert any("type annotation" in h.lower() for h in hints)

    def test_max_5_hints(self):
        from core.agents.tester_runner import _criteria_to_fix_hints
        criteria = [self._make_criterion(f"X{i}", 0, 10, f"detail {i}") for i in range(10)]
        hints = _criteria_to_fix_hints(criteria)
        assert len(hints) <= 5

    def test_details_included(self):
        from core.agents.tester_runner import _criteria_to_fix_hints
        c = self._make_criterion("Anti-patterns", 0, 15, "bare_except at line 12")
        hints = _criteria_to_fix_hints([c])
        assert any("bare_except" in h for h in hints)

    def test_empty_criteria_returns_empty(self):
        from core.agents.tester_runner import _criteria_to_fix_hints
        assert _criteria_to_fix_hints([]) == []


# ── TestBuildReflectionEnriched ───────────────────────────────────────────────

class TestBuildReflectionEnriched:
    def _make_eval_result(self, score, criteria_list):
        er = MagicMock()
        er.score = score
        er.criteria = criteria_list
        return er

    def test_with_eval_result_populates_score(self):
        from core.agents.tester_runner import _build_reflection
        receipt = MagicMock()
        receipt.tests_failed = 1
        er = self._make_eval_result(45, [])
        sr = _build_reflection({"success": False, "stderr": ""}, receipt, eval_result=er)
        assert sr.quality_score == 45

    def test_stderr_truncated_200(self):
        from core.agents.tester_runner import _build_reflection
        receipt = MagicMock()
        receipt.tests_failed = 1
        long_err = "E" * 500
        sr = _build_reflection({"success": False, "stderr": long_err}, receipt)
        assert len(sr.stderr_short) <= 200

    def test_iteration_stored(self):
        from core.agents.tester_runner import _build_reflection
        receipt = MagicMock()
        receipt.tests_failed = 0
        sr = _build_reflection({"success": True, "stderr": ""}, receipt, iteration=3)
        assert sr.iteration == 3


# ── TestOrchestratorContextInjection ─────────────────────────────────────────

class TestOrchestratorContextInjection:
    """Vérifie que fix_hints et last_quality_score remontent dans arch_context."""

    def _make_loop(self):
        from core.agents.orchestrator_loop import KarpathyLoop
        arch  = MagicMock(); arch.run_task.return_value = MagicMock(
            success=True,
            payload={"dispatched": ["sub_001"]},
        )
        coder = MagicMock(); coder.run_task.return_value = MagicMock(
            success=True,
            payload={"generated_code": "def f(): pass"},
        )
        reviewer = MagicMock(); reviewer.run_task.return_value = MagicMock(success=True, payload={})
        tester_fail = MagicMock(
            success=False,
            payload={
                "quality_score": 42,
                "reflection": "err",
                "reflection_structured": {
                    "fix_hints": ["Add type hints", "Remove bare except"],
                    "quality_score": 42,
                    "sandbox_passed": False,
                    "quality_criteria": [],
                    "stderr_short": "",
                    "iteration": 0,
                },
            },
        )
        tester_ok = MagicMock(
            success=True,
            payload={"quality_score": 88, "tester_ok": True},
        )
        tester = MagicMock()
        tester.run_task.side_effect = [tester_fail, tester_ok]
        return KarpathyLoop(arch, coder, reviewer, tester, max_iterations=3, timeout_sec=3600)

    def test_fix_hints_injected_on_second_iteration(self):
        loop = self._make_loop()
        import time
        deadline = time.monotonic() + 3600
        result = loop.run("t001", "create a function", deadline)
        # L'Architect a été appelé 2× — vérifier que le 2ème appel a fix_hints
        calls = loop._architect.run_task.call_args_list
        assert len(calls) >= 2
        second_ctx = calls[1][0][0].context   # TaskContract du 2ème appel
        assert "fix_hints" in second_ctx
        assert "Add type hints" in second_ctx["fix_hints"]

    def test_no_fix_hints_on_first_iteration(self):
        loop = self._make_loop()
        import time
        deadline = time.monotonic() + 3600
        loop.run("t001", "create a function", deadline)
        first_ctx = loop._architect.run_task.call_args_list[0][0][0].context
        assert "fix_hints" not in first_ctx

    def test_dedup_hints_across_iterations(self):
        """Deux itérations avec le même hint → hint dédupliqué."""
        from core.agents.orchestrator_loop import KarpathyLoop
        # Setup simplifié avec 3 itérations, même hint répété
        arch  = MagicMock(); arch.run_task.return_value = MagicMock(
            success=True, payload={"dispatched": ["s1"]})
        coder = MagicMock(); coder.run_task.return_value = MagicMock(
            success=True, payload={"generated_code": "def f(): pass"})
        reviewer = MagicMock(); reviewer.run_task.return_value = MagicMock(success=True, payload={})
        same_sr = {
            "fix_hints": ["Add type hints"],
            "quality_score": 30,
            "sandbox_passed": False,
            "quality_criteria": [], "stderr_short": "", "iteration": 0,
        }
        tester = MagicMock()
        tester.run_task.side_effect = [
            MagicMock(success=False, payload={"quality_score": 30, "reflection": "x", "reflection_structured": same_sr}),
            MagicMock(success=False, payload={"quality_score": 30, "reflection": "x", "reflection_structured": same_sr}),
            MagicMock(success=True,  payload={"quality_score": 80, "tester_ok": True}),
        ]
        loop = KarpathyLoop(arch, coder, reviewer, tester, max_iterations=5, timeout_sec=3600)
        import time
        loop.run("t002", "test dedup", time.monotonic() + 3600)
        third_ctx = loop._architect.run_task.call_args_list[2][0][0].context
        # "Add type hints" ne doit apparaître qu'une fois
        assert third_ctx.get("fix_hints", []).count("Add type hints") == 1


# ── TestCoderPromptWithHints ──────────────────────────────────────────────────

class TestCoderPromptWithHints:
    def test_prompt_without_hints(self):
        from core.agents.coder_builder import build_coder_prompt
        p = build_coder_prompt("create parse_json", "api", "")
        assert "Required fixes" not in p
        assert "quality score" not in p

    def test_prompt_with_hints_contains_them(self):
        from core.agents.coder_builder import build_coder_prompt
        p = build_coder_prompt(
            "create parse_json", "api", "",
            fix_hints=["Add type hints", "Remove bare except"],
            last_quality_score=45,
        )
        assert "Add type hints" in p
        assert "Remove bare except" in p
        assert "45/100" in p

    def test_prompt_no_score_when_first_iteration(self):
        from core.agents.coder_builder import build_coder_prompt
        p = build_coder_prompt("create f", "global", "", fix_hints=None, last_quality_score=None)
        assert "quality score" not in p.lower()


# ── TestTesterRejectPayload ───────────────────────────────────────────────────

class TestTesterRejectPayload:
    """Vérifie que TesterAgent.run_task() inclut reflection_structured dans le payload."""

    def test_reflection_str_retrocompat(self):
        """La clé 'reflection' reste une str pour rétrocompat."""
        from core.agents.tester_agent import TesterAgent
        from core.agents.a2a_bus import A2ALocalBus, TaskContract

        bus  = MagicMock(spec=A2ALocalBus)
        card = MagicMock()
        sandbox = MagicMock(); sandbox.run.return_value = (False, "", "err", 1)
        evaluator = MagicMock(); evaluator.evaluate.return_value = MagicMock(score=30, criteria=[])

        agent = TesterAgent(card=card, bus=bus, sandbox=sandbox, evaluator=evaluator)
        contract = TaskContract(
            task_id="t1", intent="x", domain="global",
            source_agent="reviewer", target_agent="tester",
        )
        contract.context["code"] = "def f(): pass"
        contract.context["original_payload"] = {}

        result = agent.run_task(contract)
        assert isinstance(result.payload.get("reflection"), str)

    def test_reflection_structured_present(self):
        """La clé 'reflection_structured' est présente et est un dict."""
        from core.agents.tester_agent import TesterAgent
        from core.agents.a2a_bus import A2ALocalBus, TaskContract

        bus  = MagicMock(spec=A2ALocalBus)
        card = MagicMock()
        sandbox = MagicMock(); sandbox.run.return_value = (False, "", "err", 1)
        evaluator = MagicMock(); evaluator.evaluate.return_value = MagicMock(score=30, criteria=[])

        agent = TesterAgent(card=card, bus=bus, sandbox=sandbox, evaluator=evaluator)
        contract = TaskContract(
            task_id="t1", intent="x", domain="global",
            source_agent="reviewer", target_agent="tester",
        )
        contract.context["code"] = "def f(): pass"
        contract.context["original_payload"] = {}

        result = agent.run_task(contract)
        assert isinstance(result.payload.get("reflection_structured"), dict)
```

## Critères d'acceptation

- [ ] `pytest tests/test_fl_01.py` : 18 passed
- [ ] `_build_reflection(sandbox_result, receipt)` sans `eval_result` → `fix_hints == []` (rétrocompat)
- [ ] `_build_reflection(sandbox_result, receipt)` sans `eval_result` → `stderr_short` extrait correctement
- [ ] `pytest tests/test_v8_04.py tests/test_orchestrator.py` : toujours verts
- [ ] `TesterReceiptBuilder`, `_run_sandbox_safe`, `_hash` — non modifiés

## Protocole d'exécution

```
1. filesystem:read_text_file core/agents/tester_runner.py
2. filesystem:edit_file core/agents/tester_runner.py
   → ajouter StructuredReflection + _HINT_MAP + _criteria_to_fix_hints
   → remplacer _build_reflection() (signature étendue)
3. filesystem:read_text_file core/agents/tester_agent.py
4. filesystem:edit_file core/agents/tester_agent.py
   → conserver eval_result dans run_task()
   → enrichir reject_payload avec reflection_structured + fix_hints
5. filesystem:read_text_file core/agents/orchestrator_loop.py
6. filesystem:edit_file core/agents/orchestrator_loop.py
   → ajouter structured_reflections liste locale dans run()
   → injecter fix_hints + last_quality_score dans arch_context
7. filesystem:read_text_file core/agents/coder_builder.py
8. filesystem:edit_file core/agents/coder_builder.py
   → étendre build_coder_prompt()
9. filesystem:read_text_file core/agents/coder_agent.py
10. filesystem:edit_file core/agents/coder_agent.py
    → passer fix_hints + last_quality_score à _build_coder_prompt()
11. filesystem:write_file tests/test_fl_01.py
12. bash: python -m pytest tests/test_fl_01.py -v
13. bash: python -m pytest tests/test_v8_04.py tests/test_orchestrator.py -v
14. bash: python -m pytest tests/ -x -q
```

## ⚠️ Points d'attention

- `structured_reflections` = liste **locale à `run()`**, pas attribut d'instance → pas d'accumulation entre sessions
- `eval_result` est l'objet retourné par `self._evaluator.evaluate()` — déjà calculé dans `run_task()`, à conserver en variable avant le bloc `if sandbox_ok`
- `_build_reflection()` retourne désormais un `StructuredReflection`, pas une `str` — les anciens tests qui comparent `isinstance(reflection, str)` cassent → à mettre à jour
- `build_coder_prompt()` signature étendue : les alias `_build_coder_prompt` et `build_coder_prompt_legacy` dans `coder_builder.py` ne sont **pas** nécessaires — la signature avec args optionnels suffit

## Mise à jour skills post-sprint

- **001** : FL-01 — `StructuredReflection`, `_criteria_to_fix_hints`, `_build_reflection` signature étendue, `structured_reflections` liste locale dans KarpathyLoop.run()
- **002** : arbo tester_runner.py + 18 tests test_fl_01.py, état tests ~1556
- **004** : FL-01 TERMINÉ
