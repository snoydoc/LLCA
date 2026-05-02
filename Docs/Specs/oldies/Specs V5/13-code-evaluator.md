# Spec 13 — CodeEvaluator
> **Module** : `core/code_evaluator.py` | **Sprint** : 11 | **Statut** : ✅ VALIDÉ

---

## 1. Rôle

`CodeEvaluator` évalue la **qualité statique** d'un code Python généré par le LLM, sur une échelle 0–100. L'évaluation est purement statique (AST + heuristiques), sans exécution du code.

En V1, le score est **informatif** : il ne bloque pas le patch, mais est loggé pour tracking qualité.

---

## 2. API publique

```python
class CodeEvaluator:
    def __init__(self, threshold: int = 60) → None
    def evaluate(code: str, filename: str = "<generated>") → EvaluationResult
    def evaluate_diff(before: str, after: str, filename: str) → Dict
```

---

## 3. Critères d'évaluation (total = 100 pts)

| # | Critère | Poids | Méthode |
|---|---------|-------|---------|
| 1 | Syntaxe Python valide | 30 pts | `ast.parse()` — bloquant (0 si invalide) |
| 2 | Présence de type hints | 20 pts | Ratio fonctions typées |
| 3 | Présence de docstrings | 20 pts | Module + fonctions/classes |
| 4 | Complexité cyclomatique | 15 pts | McCabe simplifié, inversement proportionnel |
| 5 | Absence d'anti-patterns | 15 pts | AST walk + regex |

### Seuil par défaut : 60 pts (`passed = score >= threshold`)

---

## 4. Dataclasses

### `CriterionScore`
```python
@dataclass
class CriterionScore:
    name:    str
    score:   int    # Points obtenus
    max:     int    # Points possibles
    details: str    # Explication courte
```

### `EvaluationResult`
```python
@dataclass
class EvaluationResult:
    filename:     str
    score:        int           # 0-100
    passed:       bool          # score >= threshold
    threshold:    int
    criteria:     List[CriterionScore]
    syntax_error: Optional[str] # Message si syntaxe invalide
    n_functions:  int
    n_classes:    int
    n_lines:      int
    complexity:   int           # Complexité cyclomatique brute

    def summary(self) → str     # Rapport lisible avec barres ASCII
    def to_dict(self) → Dict    # Sérialisation pour logs/JSON
```

---

## 5. Détail des critères

### Critère 1 — Syntaxe (30 pts)
```python
try:
    tree = ast.parse(code, filename=filename)
    # → 30 pts
except SyntaxError as exc:
    # → 0 pts, passed=False immédiat
    return EvaluationResult(score=0, ...)
```

### Critère 2 — Type hints (20 pts)

**Score proportionnel** : `(fully_typed + partially_typed * 0.5) / total_funcs * 20`

- **Fully typed** : return annoté ET tous les args non-self/cls annotés
- **Partially typed** : return OU au moins un arg annoté

Si aucune fonction → **20 pts accordés** (bonus : pas applicable).

### Critère 3 — Docstrings (20 pts)

Compte : module docstring + toute `FunctionDef`/`AsyncFunctionDef`/`ClassDef` avec docstring.

```python
# Détection docstring :
isinstance(node.body[0], ast.Expr)
and isinstance(node.body[0].value, ast.Constant)
and isinstance(node.body[0].value.value, str)
```

Score = `found / total * 20`

### Critère 4 — Complexité cyclomatique (15 pts)

**Nœuds comptés** : `If`, `For`, `AsyncFor`, `While`, `ExceptHandler`, `With`, `AsyncWith`, `Assert`, `BoolOp` (chaque opérande supplémentaire +1).

| Complexité | Score |
|-----------|-------|
| ≤ 3 | 15 pts (excellent) |
| 4–6 | 9–15 pts (acceptable) |
| 7–10 | 2–9 pts (élevée) |
| > 10 | 0 pts (trop élevée) |

### Critère 5 — Anti-patterns (15 pts)

| Anti-pattern | Pénalité |
|-------------|----------|
| `except:` sans type (bare except) | -5 pts |
| `global nom` | -4 pts |
| `from X import *` | -3 pts |
| `print(...)` | -3 pts |
| `eval(...)` ou `exec(...)` | -5 pts |

`score = max(15 - total_deductions, 0)`

---

## 6. `evaluate_diff(before, after, filename) → Dict`

```python
{
    "filename":     str,
    "score_before": int,
    "score_after":  int,
    "delta":        int,     # score_after - score_before
    "improved":     bool,    # delta >= 0
    "passed_after": bool,
    "result_after": EvaluationResult,
}
```

---

## 7. Exemple de `summary()`

```
=======================================================
  CodeEvaluator — auth.py
=======================================================
  Score global : 75/100  (✅ PASSED, seuil=60)
  Lignes : 45 | Fonctions : 3 | Classes : 1 | Complexité : 5
-------------------------------------------------------
  Syntaxe Python         30/30  [██████████████████████████████]
    → Valide
  Type hints             12/20  [████████████░░░░░░░░]
    → 2/3 fonction(s) complètement typée(s), 0 partiellement
  Docstrings             16/20  [████████████████░░░░]
    → 4/5 entité(s) documentée(s) (module inclus)
  Complexité cyclom.     12/15  [████████████░░░]
    → Complexité 5 — acceptable (4-6)
  Anti-patterns           5/15  [█████░░░░░░░░░░]
    → 2 anti-pattern(s) : `print()` dans le code; bare `except:`
=======================================================
```

---

## 8. Intégration dans le pipeline LCCA

```python
# Dans LCCAV5Fusion.execute() — après génération, avant patch :
evaluator = CodeEvaluator(threshold=60)
result = evaluator.evaluate(generated_code, filename=op.file)
log.info(result.summary())
if not result.passed:
    log.warning("Code qualité insuffisante (score=%d/100)", result.score)
# V1 : informatif uniquement — ne bloque pas le patch
```

---

## 9. Contraintes AI-Ready

- Évaluation **purement statique** (jamais d'exécution)
- `ast` stdlib uniquement (pas de libcst pour l'évaluation)
- Si syntaxe invalide → score = 0, `passed = False` immédiat
- `threshold` validé dans `__init__` (0 ≤ threshold ≤ 100)
- `to_dict()` pour sérialisation dans les métadonnées TX
