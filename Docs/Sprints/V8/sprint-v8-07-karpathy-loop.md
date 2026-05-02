# Sprint V8-07 — KarpathyLoop + métriques composites
<!-- AI-READY | Sprint V8 | Phase rc | 2026-04-20 -->

## Objectif

Implémenter la **boucle d'auto-expérimentation locale** : LCCA génère N variantes d'un code, mesure chaque variante en sandbox, conserve la meilleure.

> **V8-Règle-18** : La boucle s'arrête après **3 itérations sans amélioration** (`MAX_STAGNATION = 3`).

Ce sprint est autonome — il n'est pas sur le chemin critique du pipeline A2A. Il peut être activé à la demande via `lcca improve`.

---

## Fichiers à créer / modifier

| # | Fichier | Opération |
|---|---------|-----------|
| 1 | `core/karpathy_loop.py` | CREATE |
| 2 | `config.py` | PATCH — `KARPATHY_MAX_ITERATIONS = 20`, `KARPATHY_MAX_STAGNATION = 3` |
| 3 | `tests/test_karpathy_loop.py` | CREATE — 12 tests |

---

## Spécification : `core/karpathy_loop.py`

```python
# core/karpathy_loop.py
"""
KarpathyLoop V8 — Auto-expérimentation locale.
Génère des variantes de code et conserve la meilleure selon un score composite.

V8-Règle-18 : Arrêt après MAX_STAGNATION itérations sans amélioration.
Anti-régression : la suite de tests existante DOIT passer avant validation.
Deux métriques obligatoires : succès fonctionnel + qualité statique.
"""
import hashlib
import logging
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from core.code_evaluator import CodeEvaluator
from core.sandbox_engine import SandboxEngine
import config

log = logging.getLogger("lcca.karpathy")


@dataclass
class KarpathyMetrics:
    """Métriques d'une variante de code."""
    functional_score: float    # 0.0-1.0 (tests sandbox passent)
    quality_score: int         # 0-100 (CodeEvaluator)
    regression_passed: bool    # Ancienne suite de tests OK ?
    novelty_score: float = 1.0 # 0.0-1.0 (diversité vs variantes précédentes)

    @property
    def composite(self) -> float:
        """
        Score composite pondéré.
        - regression_passed=False → 0.0 (disqualifié)
        - functional_score pèse 60%, quality_score 40%
        - novelty_score modifie : favorise les variantes nouvelles en cas d'égalité
        """
        if not self.regression_passed:
            return 0.0
        base = (self.functional_score * 0.6) + (self.quality_score / 100 * 0.4)
        # Bonus novelty léger (max +5%) pour casser les égalités
        return base * (1.0 + self.novelty_score * 0.05)

    def is_better_than(self, other: "KarpathyMetrics") -> bool:
        return self.composite > other.composite

    def to_dict(self) -> dict:
        return {
            "functional_score": self.functional_score,
            "quality_score": self.quality_score,
            "regression_passed": self.regression_passed,
            "novelty_score": self.novelty_score,
            "composite": self.composite,
        }


@dataclass
class KarpathyResult:
    """Résultat final de la boucle."""
    best_code: str
    best_metrics: KarpathyMetrics
    iterations: int
    stagnation_cause: bool  # Arrêt par stagnation (vs max_iterations)
    all_scores: List[float]  # Historique des composites


class KarpathyLoop:
    """
    Boucle d'auto-amélioration locale.

    Utilisation :
        loop = KarpathyLoop()
        result = loop.iterate(
            base_code="def add(a, b): return a + b",
            intent="optimiser add() pour des entiers",
            target_file="math_utils.py",
        )
    """
    MAX_STAGNATION: int = getattr(config, "KARPATHY_MAX_STAGNATION", 3)
    MAX_ITERATIONS: int = getattr(config, "KARPATHY_MAX_ITERATIONS", 20)

    def __init__(
        self,
        sandbox: Optional[SandboxEngine] = None,
        evaluator: Optional[CodeEvaluator] = None,
        generator=None,         # LLMGenerator — injecté (évite import circulaire)
        skill_library=None,     # SkillLibrary — pour novelty_score
    ):
        self._sandbox = sandbox or SandboxEngine(mode="soft")
        self._evaluator = evaluator or CodeEvaluator()
        self._generator = generator
        self._skill_lib = skill_library

    def iterate(
        self,
        base_code: str,
        intent: str,
        target_file: str = "<karpathy>",
        regression_fn: Optional[Callable[[], bool]] = None,
        max_iterations: Optional[int] = None,
    ) -> KarpathyResult:
        """
        Boucle principale.

        Args:
            base_code: Code de départ.
            intent: Objectif (utilisé pour le prompt de mutation LLM).
            target_file: Nom de fichier pour CodeEvaluator.
            regression_fn: Callable → bool, retourne True si la suite de tests existante passe.
                           Si None, regression_passed=True par défaut (pas de guard).
            max_iterations: Override de MAX_ITERATIONS.
        """
        max_iter = max_iterations or self.MAX_ITERATIONS
        previous_codes: List[str] = []

        best_code = base_code
        best_metrics = self._evaluate(base_code, target_file, regression_fn, previous_codes)
        stagnation = 0
        all_scores = [best_metrics.composite]

        log.info("karpathy.iterate start composite=%.3f max_iter=%d", best_metrics.composite, max_iter)

        for i in range(max_iter):
            if stagnation >= self.MAX_STAGNATION:
                log.info("karpathy.iterate stop: stagnation=%d after %d iterations", stagnation, i)
                return KarpathyResult(best_code, best_metrics, i, True, all_scores)

            temperature = 0.3 + i * 0.05  # Exploration croissante
            variant = self._mutate(best_code, intent, temperature)

            if not variant or variant == best_code:
                stagnation += 1
                continue

            metrics = self._evaluate(variant, target_file, regression_fn, previous_codes)
            all_scores.append(metrics.composite)
            previous_codes.append(variant)

            if metrics.is_better_than(best_metrics):
                delta = metrics.composite - best_metrics.composite
                log.info("karpathy iter=%d improvement delta=+%.3f composite=%.3f",
                         i, delta, metrics.composite)
                best_code = variant
                best_metrics = metrics
                stagnation = 0
            else:
                stagnation += 1
                log.debug("karpathy iter=%d no improvement stagnation=%d", i, stagnation)

        return KarpathyResult(best_code, best_metrics, max_iter, False, all_scores)

    # ── Méthodes internes ─────────────────────────────────────────────

    def _evaluate(
        self,
        code: str,
        target_file: str,
        regression_fn: Optional[Callable[[], bool]],
        previous_codes: List[str],
    ) -> KarpathyMetrics:
        """Évalue une variante avec les 3 critères."""
        # 1. Sandbox fonctionnel
        try:
            sandbox_result = self._sandbox.run_code(code)
            functional_ok = sandbox_result.get("success", False)
        except Exception:
            functional_ok = False

        # 2. Qualité statique
        try:
            eval_result = self._evaluator.evaluate(code, filename=target_file)
            quality = getattr(eval_result, "score", 0)
        except Exception:
            quality = 0

        # 3. Non-régression (obligatoire si fournie)
        regression_ok = True
        if regression_fn is not None:
            try:
                regression_ok = bool(regression_fn())
            except Exception:
                regression_ok = False

        # 4. Nouveauté
        novelty = self._novelty_score(code, previous_codes)

        return KarpathyMetrics(
            functional_score=1.0 if functional_ok else 0.0,
            quality_score=quality,
            regression_passed=regression_ok,
            novelty_score=novelty,
        )

    def _mutate(self, code: str, intent: str, temperature: float) -> str:
        """
        Génère une variante du code via LLM.
        Si LLM indisponible : applique une mutation heuristique minimale.
        Ne lève jamais.
        """
        if self._generator is not None:
            try:
                system = (
                    "Tu es un expert Python. Génère une variante améliorée du code suivant "
                    f"en respectant l'objectif : {intent}. "
                    "Retourne UNIQUEMENT le code Python, sans explication."
                )
                user = f"```python\n{code}\n```"
                result = self._generator.generate_text(system, user)
                if isinstance(result, str) and result.strip():
                    # Nettoyer les backticks markdown
                    cleaned = result.replace("```python", "").replace("```", "").strip()
                    return cleaned
            except Exception as exc:
                log.debug("karpathy._mutate LLM error: %s", exc)

        # Fallback heuristique : ajouter un commentaire pour varier le hash
        return code + f"\n# iteration-{hashlib.md5(str(temperature).encode()).hexdigest()[:4]}"

    def _novelty_score(self, candidate: str, previous: List[str]) -> float:
        """
        Mesure la diversité d'un candidat par rapport aux variantes précédentes.
        Addendum 2.3 : empêche la convergence vers un optimum local déjà exploré.
        """
        if not previous:
            return 1.0
        import difflib
        similarities = [
            difflib.SequenceMatcher(None, candidate, p).ratio()
            for p in previous[-5:]  # Comparer aux 5 dernières seulement (performance)
        ]
        return max(0.0, 1.0 - max(similarities))

    @staticmethod
    def make_regression_fn(test_file: str) -> Callable[[], bool]:
        """
        Factory : crée un regression_fn depuis un fichier de test pytest.
        Usage : loop.iterate(..., regression_fn=KarpathyLoop.make_regression_fn("tests/test_math.py"))
        """
        import sys
        import subprocess

        def run_tests() -> bool:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", test_file, "-q", "--tb=no"],
                capture_output=True,
                timeout=60,
            )
            return result.returncode == 0

        return run_tests
```

---

## Ajouts `config.py`

```python
# V8 — KarpathyLoop
KARPATHY_MAX_ITERATIONS = 20
KARPATHY_MAX_STAGNATION = 3      # V8-Règle-18
```

---

## Checklist des tests (`tests/test_karpathy_loop.py`)

### TestKarpathyMetrics
- [ ] `test_composite_zero_if_regression_fails` — regression_passed=False → composite=0.0
- [ ] `test_composite_weighted_60_40` — functional=1.0, quality=100, regression=True → ~1.05
- [ ] `test_is_better_than` — composite 0.8 > 0.7 → True
- [ ] `test_novelty_modifies_composite` — novelty=0.0 vs 1.0 → composite différent

### TestKarpathyLoop
- [ ] `test_loop_returns_result` — retourne KarpathyResult
- [ ] `test_loop_stops_after_3_no_improvement` — 3 mutations identiques → stagnation_cause=True, iterations≤4
- [ ] `test_loop_improves_on_better_variant` — mutation simulée meilleure → best_code mis à jour
- [ ] `test_regression_failure_gives_zero_score` — regression_fn → False → composite=0.0 → pas de mise à jour
- [ ] `test_loop_without_regression_fn` — regression_fn=None → regression_passed=True par défaut
- [ ] `test_max_iterations_respected` — max_iterations=3 → iterations≤3

### TestKarpathyMutate
- [ ] `test_mutate_without_generator_returns_variant` — pas de LLM → heuristique retourne str non vide
- [ ] `test_mutate_with_generator_called` — LLM mocké → generate_text appelé

### TestKarpathyNoveltScore
- [ ] `test_novelty_empty_previous` — [] → 1.0
- [ ] `test_novelty_identical_code` — code = previous[0] → ~0.0 (très faible)

---

## Activation CLI (prévue Sprint V8-08)

```bash
# Améliore une fonction existante en 20 itérations max
python main.py improve --file=core/executor.py --function=run --intent="optimiser la gestion des erreurs"
```

---

## Notes de design

- **`regression_fn=None` par défaut** : le loop est utilisable sans test suite (dégradation gracieuse).
- **Mutation heuristique** : le fallback sans LLM est intentionnellement minimal (ajoute un commentaire). En production, le LLM est attendu — la mutation heuristique sert uniquement aux tests unitaires.
- **Comparaison limitée aux 5 dernières variantes** dans `_novelty_score` : performance O(n) → O(5).
- **`make_regression_fn`** : factory statique, crée un subprocess pytest propre. Indépendant du runner de tests courant.
