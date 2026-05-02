# EVAL-03 — Questions Manuelles + CurriculumTracker
**Sprint** : EVAL-03
**Statut** : À FAIRE
**Durée estimée** : 1 session
**Dépendances** : EVAL-01
**Tests cibles** : 10 tests (`tests/test_eval_03_curriculum.py`)

---

## Objectif

Créer les questions de benchmark paliers 0 et 1 pour `python_core`, et implémenter
le `CurriculumTracker` qui gère la progression par domaine.

---

## Fichiers à créer

| Fichier | Type | Notes |
|---------|------|-------|
| `EvalLoop/benchmarks/__init__.py` | Vide | Package |
| `EvalLoop/benchmarks/python_core/palier_0.json` | JSON | 10 questions actives |
| `EvalLoop/benchmarks/python_core/palier_1.json` | JSON | 10 questions actives |
| `EvalLoop/engines/curriculum_tracker.py` | Python | Gestion paliers |
| `tests/test_eval_03_curriculum.py` | Python | 10 tests |

---

## Format des questions

```json
[
  {
    "id": "python_core/p0/gil_001",
    "domain": "python_core",
    "palier": 0,
    "question": "Qu'est-ce que le GIL en Python et pourquoi existe-t-il ?",
    "expected_concepts": ["GIL", "Global Interpreter Lock", "thread", "mémoire", "CPython"],
    "rubric": "La réponse doit expliquer le rôle du GIL dans la gestion mémoire de CPython et son impact sur le multi-threading.",
    "status": "active",
    "tags": ["concurrence", "cpython", "threads"]
  }
]
```

**Règles** :
- `expected_concepts` : tokens **exacts**, cas-insensitif, matching `\bword\b`
- `status` : toujours `"active"` pour les paliers 0 et 1 (écriture manuelle = déjà validé)
- Paliers 2+ peuvent avoir `status: "draft"` — activés via `review-bench`

---

## 10 Questions Palier 0 — `python_core`

```json
[
  {
    "id": "python_core/p0/gil_001",
    "domain": "python_core",
    "palier": 0,
    "question": "Qu'est-ce que le GIL en Python et pourquoi existe-t-il ?",
    "expected_concepts": ["GIL", "Global Interpreter Lock", "thread", "mémoire", "CPython"],
    "rubric": "Expliquer le rôle du GIL dans CPython et son impact sur le multi-threading.",
    "status": "active",
    "tags": ["concurrence", "cpython"]
  },
  {
    "id": "python_core/p0/list_tuple_001",
    "domain": "python_core",
    "palier": 0,
    "question": "Quelle est la différence entre une liste et un tuple en Python ?",
    "expected_concepts": ["liste", "tuple", "mutable", "immutable", "hashable"],
    "rubric": "Distinguer mutabilité, usage comme clé de dict, performance.",
    "status": "active",
    "tags": ["types", "structures"]
  },
  {
    "id": "python_core/p0/str_repr_001",
    "domain": "python_core",
    "palier": 0,
    "question": "Quelle est la différence entre __str__ et __repr__ en Python ?",
    "expected_concepts": ["__str__", "__repr__", "lisible", "débogage", "repr"],
    "rubric": "Distinguer usage utilisateur (__str__) et débogage (__repr__). Mentionner str() vs repr().",
    "status": "active",
    "tags": ["dunder", "classes"]
  },
  {
    "id": "python_core/p0/property_001",
    "domain": "python_core",
    "palier": 0,
    "question": "À quoi sert le décorateur @property en Python ?",
    "expected_concepts": ["property", "getter", "setter", "encapsulation", "attribut"],
    "rubric": "Expliquer l'accès contrôlé aux attributs sans changer l'API publique.",
    "status": "active",
    "tags": ["classes", "decorateurs"]
  },
  {
    "id": "python_core/p0/args_kwargs_001",
    "domain": "python_core",
    "palier": 0,
    "question": "Expliquez *args et **kwargs en Python.",
    "expected_concepts": ["args", "kwargs", "positional", "keyword", "déballage"],
    "rubric": "Expliquer arguments positionnels variadic et keyword variadic, avec exemples.",
    "status": "active",
    "tags": ["fonctions", "arguments"]
  },
  {
    "id": "python_core/p0/comprehension_001",
    "domain": "python_core",
    "palier": 0,
    "question": "Quelle est la différence entre une compréhension de liste et map() ?",
    "expected_concepts": ["compréhension", "map", "lisibilité", "lazy", "liste"],
    "rubric": "Comparer lisibilité, évaluation (eager vs lazy), et cas d'usage appropriés.",
    "status": "active",
    "tags": ["fonctionnel", "performance"]
  },
  {
    "id": "python_core/p0/context_manager_001",
    "domain": "python_core",
    "palier": 0,
    "question": "Comment fonctionne le protocole de gestionnaire de contexte (with statement) ?",
    "expected_concepts": ["with", "__enter__", "__exit__", "contexte", "ressource"],
    "rubric": "Expliquer __enter__ et __exit__, exemples avec fichiers et locks.",
    "status": "active",
    "tags": ["protocoles", "ressources"]
  },
  {
    "id": "python_core/p0/eq_is_001",
    "domain": "python_core",
    "palier": 0,
    "question": "Quelle est la différence entre == et is en Python ?",
    "expected_concepts": ["==", "is", "identité", "égalité", "None"],
    "rubric": "Distinguer égalité de valeur et identité d'objet. Mentionner le cas de None.",
    "status": "active",
    "tags": ["operateurs", "objets"]
  },
  {
    "id": "python_core/p0/none_false_001",
    "domain": "python_core",
    "palier": 0,
    "question": "Expliquez la différence entre None, False et 0 en Python.",
    "expected_concepts": ["None", "False", "falsy", "bool", "type"],
    "rubric": "Distinguer les trois valeurs falsy, leurs types, et les pièges de comparaison.",
    "status": "active",
    "tags": ["types", "comparaisons"]
  },
  {
    "id": "python_core/p0/isinstance_001",
    "domain": "python_core",
    "palier": 0,
    "question": "Quelle est la différence entre isinstance() et type() ?",
    "expected_concepts": ["isinstance", "type", "héritage", "sous-classe", "ABCMeta"],
    "rubric": "Expliquer pourquoi isinstance() est préféré (héritage). Cas d'usage de type() exact.",
    "status": "active",
    "tags": ["types", "heritage"]
  }
]
```

---

## 10 Questions Palier 1 — `python_core`

```json
[
  {
    "id": "python_core/p1/decorator_001",
    "domain": "python_core",
    "palier": 1,
    "question": "Implémentez un décorateur Python qui mesure le temps d'exécution d'une fonction.",
    "expected_concepts": ["décorateur", "functools", "wraps", "time", "wrapper"],
    "rubric": "Implémenter avec functools.wraps, mesure correcte, préserver signature.",
    "status": "active",
    "tags": ["decorateurs", "fonctions", "performance"]
  },
  {
    "id": "python_core/p1/generator_001",
    "domain": "python_core",
    "palier": 1,
    "question": "Expliquez les générateurs Python et quand les utiliser plutôt qu'une liste.",
    "expected_concepts": ["yield", "générateur", "lazy", "mémoire", "itérateur"],
    "rubric": "Expliquer yield, évaluation paresseuse, avantages mémoire, exemples concrets.",
    "status": "active",
    "tags": ["generateurs", "memoire"]
  },
  {
    "id": "python_core/p1/mro_001",
    "domain": "python_core",
    "palier": 1,
    "question": "Qu'est-ce que le MRO (Method Resolution Order) en Python ?",
    "expected_concepts": ["MRO", "C3", "héritage", "multiple", "__mro__"],
    "rubric": "Expliquer l'algorithme C3, ordre de résolution, exemple héritage multiple.",
    "status": "active",
    "tags": ["heritage", "classes"]
  },
  {
    "id": "python_core/p1/descriptor_001",
    "domain": "python_core",
    "palier": 1,
    "question": "Qu'est-ce qu'un descripteur Python ?",
    "expected_concepts": ["descripteur", "__get__", "__set__", "data descriptor", "attribut"],
    "rubric": "Expliquer le protocole descripteur, différence data vs non-data, exemples.",
    "status": "active",
    "tags": ["classes", "protocoles"]
  },
  {
    "id": "python_core/p1/metaclass_001",
    "domain": "python_core",
    "palier": 1,
    "question": "À quoi servent les métaclasses en Python ?",
    "expected_concepts": ["métaclasse", "type", "__new__", "classe", "ABCMeta"],
    "rubric": "Expliquer que les classes sont des instances de type. Cas d'usage réels.",
    "status": "active",
    "tags": ["classes", "avance"]
  },
  {
    "id": "python_core/p1/asyncio_001",
    "domain": "python_core",
    "palier": 1,
    "question": "Expliquez la différence entre threading, multiprocessing et asyncio en Python.",
    "expected_concepts": ["threading", "multiprocessing", "asyncio", "GIL", "I/O"],
    "rubric": "Distinguer I/O-bound vs CPU-bound, rôle du GIL, cas d'usage de chacun.",
    "status": "active",
    "tags": ["concurrence", "performance"]
  },
  {
    "id": "python_core/p1/slots_001",
    "domain": "python_core",
    "palier": 1,
    "question": "Qu'est-ce que __slots__ en Python et quand l'utiliser ?",
    "expected_concepts": ["__slots__", "mémoire", "__dict__", "attribut", "performance"],
    "rubric": "Expliquer économie mémoire, suppression de __dict__, limitations (héritage).",
    "status": "active",
    "tags": ["classes", "memoire", "performance"]
  },
  {
    "id": "python_core/p1/weakref_001",
    "domain": "python_core",
    "palier": 1,
    "question": "Qu'est-ce qu'une référence faible (weakref) et quand l'utiliser ?",
    "expected_concepts": ["weakref", "référence", "garbage collector", "cycle", "cache"],
    "rubric": "Expliquer différence ref forte/faible, cycles de référence, exemples cache.",
    "status": "active",
    "tags": ["memoire", "garbage-collector"]
  },
  {
    "id": "python_core/p1/contextlib_001",
    "domain": "python_core",
    "palier": 1,
    "question": "Implémentez un gestionnaire de contexte avec @contextmanager.",
    "expected_concepts": ["contextmanager", "yield", "contextlib", "with", "__enter__"],
    "rubric": "Implémenter avec contextlib.contextmanager, gestion des exceptions via try/finally.",
    "status": "active",
    "tags": ["protocoles", "contextlib"]
  },
  {
    "id": "python_core/p1/dataclass_001",
    "domain": "python_core",
    "palier": 1,
    "question": "Qu'apportent les dataclasses Python par rapport aux classes ordinaires ?",
    "expected_concepts": ["dataclass", "__init__", "__repr__", "field", "frozen"],
    "rubric": "Expliquer génération automatique, field(), frozen=True, comparaisons avec attrs/namedtuple.",
    "status": "active",
    "tags": ["classes", "dataclasses"]
  }
]
```

---

## CurriculumTracker

```python
# -*- coding: utf-8-sig -*-
"""
curriculum_tracker.py — Gestion des paliers et de la progression par domaine.

Responsabilité :
  - Lire/écrire eval_state.json (atomic write — T-14)
  - Décider si un palier est débloqué
  - Charger les questions d'un palier
  - Mettre à jour le score moyen
  - (V4) Rétrograder si 3 sessions consécutives < 0.50
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import List, Dict, Any

from EvalLoop.evalloop_types import BenchQuestion, PalierState

log = logging.getLogger("lcca.evalloop.curriculum")

MAX_PALIER = 5


class CurriculumTracker:
    def __init__(self, state_path: Path, benchmarks_dir: Path, config: Dict[str, Any]):
        self._state_path     = state_path
        self._benchmarks_dir = benchmarks_dir
        self._config         = config

    def get_state(self, domain: str) -> PalierState:
        """Retourne l'état courant du domaine. Crée l'état par défaut si absent."""
        data = self._load_state()
        if domain not in data:
            return PalierState(domain=domain)
        return PalierState(**data[domain])

    def update_state(self, domain: str, score: float) -> PalierState:
        """Met à jour le score moyen et gère les montées de palier. Atomic write."""
        data = self._load_state()
        state = PalierState(**data[domain]) if domain in data else PalierState(domain=domain)

        state.questions_done += 1
        state.avg_score = (
            (state.avg_score * (state.questions_done - 1) + score) / state.questions_done
        )

        # Historique récent pour SYS-02 (rétrogradation)
        state.recent_scores.append(score)
        if len(state.recent_scores) > 10:
            state.recent_scores = state.recent_scores[-10:]

        # Montée de palier
        if (state.avg_score >= state.unlock_threshold
                and state.current_palier < MAX_PALIER):
            old = state.current_palier
            state.current_palier += 1
            state.sessions_completed += 1
            state.avg_score = 0.0  # Reset pour le nouveau palier
            log.info("Progression %s : palier %d → %d", domain, old, state.current_palier)

        # Rétrogradation (SYS-02 — désactivée en V3)
        retrograde_enabled = self._config.get("sys02_retrograde", {}).get("retrograde_enabled", False)
        if retrograde_enabled:
            window    = self._config["sys02_retrograde"].get("retrograde_window", 3)
            threshold = self._config["sys02_retrograde"].get("retrograde_threshold", 0.50)
            if (len(state.recent_scores) >= window
                    and all(s < threshold for s in state.recent_scores[-window:])
                    and state.current_palier > 0):
                state.current_palier -= 1
                log.warning("Rétrogradation %s → palier %d", domain, state.current_palier)

        data[domain] = state.to_dict()
        self._save_state(data)
        return state

    def is_unlocked(self, domain: str, palier: int) -> bool:
        """Palier 0 toujours débloqué. Palier N débloqué si palier courant >= N."""
        if palier == 0:
            return True
        state = self.get_state(domain)
        return state.current_palier >= palier

    def load_questions(self, domain: str, palier: int) -> List[BenchQuestion]:
        """Charge palier_N.json, filtre status == 'active'."""
        path = self._benchmarks_dir / domain / f"palier_{palier}.json"
        if not path.exists():
            log.warning("Fichier benchmark absent : %s", path)
            return []
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return [
            BenchQuestion.from_dict(q)
            for q in data
            if q.get("status", "active") == "active"
        ]

    def _load_state(self) -> dict:
        try:
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_state(self, data: dict) -> None:
        """Écriture atomique — pattern T-14 (Path.replace() Windows + Linux)."""
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._state_path)
```

---

## Tests (`test_eval_03_curriculum.py`)

10 tests :

```
CurriculumTracker
  test_curriculum_initial_state         → domaine inconnu → PalierState par défaut
  test_curriculum_update_score          → score mis à jour correctement
  test_curriculum_unlock_threshold      → avg >= 0.70 → palier monte
  test_curriculum_no_unlock_below       → avg < 0.70 → palier reste
  test_curriculum_palier_0_always_unlocked → is_unlocked("domain", 0) == True
  test_curriculum_palier_1_locked       → palier 1 locked si current_palier == 0
  test_curriculum_load_questions_active → charge uniquement status=="active"
  test_curriculum_load_questions_draft  → questions draft filtrées
  test_curriculum_atomic_write          → eval_state.json créé après update
  test_curriculum_recent_scores_window  → recent_scores limité à 10 entrées
```

---

## Checklist

```
[ ] EvalLoop/benchmarks/__init__.py créé (vide)
[ ] EvalLoop/benchmarks/python_core/palier_0.json créé (10 questions actives)
[ ] EvalLoop/benchmarks/python_core/palier_1.json créé (10 questions actives)
[ ] EvalLoop/engines/curriculum_tracker.py créé
[ ] PalierState.to_dict() et from_dict() implémentés (EVAL-01 si manquants)
[ ] tests/test_eval_03_curriculum.py créé (10 tests)
[ ] pytest tests/test_eval_01_types.py tests/test_eval_02_judge.py tests/test_eval_03_curriculum.py -v → 40 passed, 0 failed
[ ] git commit -m "EVAL-03: benchmarks python_core + curriculum_tracker"
```
