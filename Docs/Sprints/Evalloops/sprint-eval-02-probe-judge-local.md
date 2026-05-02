# EVAL-02 — ProbeEngine + JudgeLocal
**Sprint** : EVAL-02
**Statut** : À FAIRE
**Durée estimée** : 1 session
**Dépendances** : EVAL-01
**Tests cibles** : 15 tests (`tests/test_eval_02_judge.py`)

---

## Objectif

Implémenter le moteur de probe (appel Ollama) et le juge local (gatekeeper offline).
Ces deux composants constituent le "bras droit" d'EvalLoop — le seul qui fonctionne
en mode 100% offline sans API externe.

---

## Fichiers à créer

| Fichier | Type | Notes |
|---------|------|-------|
| `EvalLoop/engines/__init__.py` | Vide | Package |
| `EvalLoop/engines/probe_engine.py` | Python | Appel OllamaClient |
| `EvalLoop/judges/__init__.py` | Vide | Package |
| `EvalLoop/judges/judge_base.py` | Python | ABC JudgeBase |
| `EvalLoop/judges/judge_local.py` | Python | Gatekeeper offline |
| `tests/test_eval_02_judge.py` | Python | 15 tests |

---

## ProbeEngine

```python
# -*- coding: utf-8-sig -*-
from __future__ import annotations
import logging
import time
from datetime import datetime, timezone

from core.ollama_client import OllamaClient
from config import OLLAMA_MODEL, OLLAMA_URL, OLLAMA_TIMEOUT, OLLAMA_MAX_TOKENS
from EvalLoop.evalloop_types import BenchQuestion, ProbeResponse

log = logging.getLogger("lcca.evalloop.probe")

_SYSTEM_PROMPT = (
    "Tu es un assistant technique expert en Python et en architecture logicielle. "
    "Réponds de façon précise et structurée."
)
# PAS de "Tu es LCCA" — incorrect conceptuellement (LCCA est le système, pas le modèle)


class ProbeEngine:
    def __init__(self, model: str = None, base_url: str = None):
        self._client = OllamaClient(
            base_url   = base_url or OLLAMA_URL,
            model      = model or OLLAMA_MODEL,
            timeout    = OLLAMA_TIMEOUT,    # None — INVARIANT ABSOLU (règle LCCA)
            max_tokens = OLLAMA_MAX_TOKENS,
        )
        self._model = model or OLLAMA_MODEL

    def probe(self, question: BenchQuestion) -> ProbeResponse:
        """Soumet une question à Ollama et retourne la réponse brute."""
        t0 = time.monotonic()
        response = self._client.generate(
            system = _SYSTEM_PROMPT,
            user   = question.question,
        )
        duration = time.monotonic() - t0

        return ProbeResponse(
            question_id  = question.id,
            question     = question,
            response     = response,
            model        = self._model,
            duration_sec = round(duration, 2),
            timestamp    = datetime.now(timezone.utc).isoformat(),
        )

    def probe_batch(self, questions: list[BenchQuestion], cooldown_sec: float = 0.0):
        """
        Probe une liste de questions avec pause optionnelle entre chaque.
        cooldown_sec = 0 par défaut (pas de pause).
        Augmenter à 2.0 si contention GPU observée (SYS-03).
        """
        for q in questions:
            yield self.probe(q)
            if cooldown_sec > 0:
                time.sleep(cooldown_sec)
```

---

## JudgeBase (ABC)

```python
# judge_base.py
from abc import ABC, abstractmethod
from EvalLoop.evalloop_types import BenchQuestion, ProbeResponse, JudgeScore

class JudgeBase(ABC):
    @abstractmethod
    def score(self, question: BenchQuestion, response: ProbeResponse) -> JudgeScore:
        ...
```

---

## JudgeLocal — Algorithme de Scoring

```python
class JudgeLocal(JudgeBase):
    """
    Gatekeeper offline — évalue la surface des réponses.

    INVARIANTS ABSOLUS :
        inject_recommended = False  (toujours)
        improved_answer    = ""     (toujours)

    JudgeLocal ne décide jamais d'injecter et ne produit jamais de contenu amélioré.
    Son seul rôle est de filtrer les réponses catastrophiques avant JudgeClaude.
    """

    def score(self, question: BenchQuestion, response: ProbeResponse) -> JudgeScore:
        text = response.response

        concept_score   = self._concept_score(text, question.expected_concepts)
        coherence_score = self._coherence_score(text, question.expected_concepts)
        structure_score = self._structure_score(text)
        final_score     = concept_score * 0.6 + coherence_score * 0.2 + structure_score * 0.2

        found    = self._find_concepts(text, question.expected_concepts)
        missing  = [c for c in question.expected_concepts if c not in found]

        return JudgeScore(
            question_id        = question.id,
            judge              = "local",
            concept_score      = round(concept_score, 3),
            coherence_score    = round(coherence_score, 3),
            structure_score    = round(structure_score, 3),
            final_score        = round(final_score, 3),
            inject_recommended = False,   # INVARIANT
            improved_answer    = "",      # INVARIANT
            domain             = question.domain,
            palier             = question.palier,
            weaknesses         = [f"Concept manquant : {c}" for c in missing],
        )

    def _find_concepts(self, text: str, concepts: list[str]) -> set[str]:
        """Matching tokenisé \bword\b — évite 'list' dans 'listing'."""
        import re
        text_lower = text.lower()
        return {
            c for c in concepts
            if re.search(r'\b' + re.escape(c.lower()) + r'\b', text_lower)
        }

    def _concept_score(self, text: str, concepts: list[str]) -> float:
        if not concepts:
            return 1.0
        found = self._find_concepts(text, concepts)
        return len(found) / len(concepts)

    def _coherence_score(self, text: str, concepts: list[str]) -> float:
        """
        Vérifie que les concepts trouvés sont regroupés dans une fenêtre de 100 mots.
        Pénalise le keyword stuffing (concepts éparpillés dans une longue réponse).
        """
        if not concepts:
            return 1.0
        words = text.lower().split()
        if len(words) < 3:
            return 0.0

        window = 100
        best = 0.0
        for i in range(len(words)):
            chunk = " ".join(words[i:i + window])
            found_in_window = self._find_concepts(chunk, concepts)
            ratio = len(found_in_window) / len(concepts)
            if ratio > best:
                best = ratio
        return best

    def _structure_score(self, text: str) -> float:
        """
        Remplace length_score — évalue la qualité structurelle.
        Code blocks  → +0.1
        Listes       → +0.1
        Exemples     → +0.1
        Maximum : 0.3
        """
        import re
        score = 0.0
        if "```" in text:
            score += 0.1
        if re.search(r'^\s*[-*]\s', text, re.MULTILINE):
            score += 0.1
        if re.search(r'\b(exemple|ex\s*:|ex:|>>>|par exemple)\b', text, re.IGNORECASE):
            score += 0.1
        return min(score, 0.3)
```

---

## Tests (`test_eval_02_judge.py`)

15 tests obligatoires :

```
ProbeEngine
  test_probe_engine_instanciation       → instancie sans erreur (mock OllamaClient)
  test_probe_returns_probe_response     → retourne ProbeResponse correctement formé
  test_probe_timeout_is_none            → vérifie que timeout=None est transmis à OllamaClient

JudgeLocal — Invariants
  test_judge_local_never_injects        → inject_recommended is False (toujours)
  test_judge_local_no_improved_answer   → improved_answer == "" (toujours)

JudgeLocal — Concept score
  test_judge_local_full_concepts        → tous les concepts présents → concept_score==1.0
  test_judge_local_no_concepts          → aucun concept → concept_score==0.0
  test_judge_local_tokenization         → "list" ne matche pas "listing" ni "checklist"
  test_judge_local_case_insensitive     → "GIL" matche "gil" dans la réponse

JudgeLocal — Coherence score
  test_judge_local_keyword_stuffing     → concepts éparpillés → final_score < 0.5
  test_judge_local_grouped_concepts     → concepts regroupés → coherence_score élevé

JudgeLocal — Structure score
  test_judge_local_code_block           → "```" dans réponse → structure_score >= 0.1
  test_judge_local_list_bonus           → "- item" dans réponse → structure_score >= 0.1
  test_judge_local_no_structure         → texte plat → structure_score == 0.0

JudgeLocal — Gatekeeper
  test_judge_local_gatekeeper_threshold → réponse vide → final_score < 0.30
```

---

## Checklist

```
[ ] EvalLoop/engines/__init__.py créé (vide)
[ ] EvalLoop/engines/probe_engine.py créé
[ ] EvalLoop/judges/__init__.py créé (vide)
[ ] EvalLoop/judges/judge_base.py créé (ABC)
[ ] EvalLoop/judges/judge_local.py créé (algorithme complet)
[ ] tests/test_eval_02_judge.py créé (15 tests)
[ ] pytest tests/test_eval_01_types.py tests/test_eval_02_judge.py -v → 30 passed, 0 failed
[ ] git commit -m "EVAL-02: probe_engine + judge_local"
```
