# SPEC EvalLoop — EVAL-03 : JudgeBase + JudgeClaude
**Version** : 1.0
**Date** : 2026-04-23
**Statut** : DRAFT
**Dépendances** : EVAL-01 (dataclasses)

---

## 1. Objectif du sprint

Implémenter la **Phase 2 — JUDGE** :

1. **`judge_base.py`** — ABC commun à tous les juges
2. **`judge_claude.py`** — Juge Claude via Anthropic API
3. **`judge_engine.py`** — Orchestre les juges actifs, produit `scores.jsonl`

Ce sprint est le seul qui nécessite une API externe (Anthropic API).
Mode dégradé obligatoire si l'API est absente.

---

## 2. Fichiers créés

| Fichier | Rôle |
|---|---|
| `EvalLoop/judges/judge_base.py` | ABC JudgeBase |
| `EvalLoop/judges/judge_claude.py` | Juge Claude (Anthropic API) |
| `EvalLoop/judges/judge_openai.py` | Stub V1 (non fonctionnel, interface uniquement) |
| `EvalLoop/engines/judge_engine.py` | Orchestre les juges → scores.jsonl |

---

## 3. `judge_base.py`

```python
from abc import ABC, abstractmethod
from evalloop_types import BenchQuestion, ProbeResponse, JudgeScore


class JudgeBase(ABC):
    """Interface commune à tous les juges externes."""

    @property
    @abstractmethod
    def judge_id(self) -> str:
        """Identifiant unique du juge : 'claude-sonnet-4-6', 'gpt-4o', etc."""

    @abstractmethod
    def score(
        self,
        question: BenchQuestion,
        response: ProbeResponse,
    ) -> JudgeScore:
        """Score une réponse LLCA. Retourne un JudgeScore complet.
        
        Doit toujours retourner un JudgeScore valide — jamais lever d'exception
        vers l'appelant. En cas d'échec API : score=0.0, weaknesses=["Erreur API"],
        inject_recommended=False.
        """

    def is_available(self) -> bool:
        """Vérifie que le juge est accessible (ping léger). Défaut : True."""
        return True
```

---

## 4. `judge_claude.py`

### Responsabilités
- Appeler Anthropic API avec question + rubrique + réponse LLCA
- Parser la réponse JSON structurée du modèle
- Retourner un `JudgeScore` complet avec `improved_answer`

### Prompt de scoring

```
SYSTEM:
Tu es un évaluateur expert en développement Python et en ingénierie logicielle.
Tu évalues les réponses d'un LLM local (LCCA) à des questions techniques.

Ta tâche :
1. Attribuer un score de 0.0 à 1.0 à la réponse
2. Lister les points forts (forces)
3. Lister les points faibles (faiblesses)
4. Rédiger une réponse améliorée (improved_answer) en Markdown
5. Recommander ou non l'injection dans la base de connaissances

Réponds UNIQUEMENT en JSON valide, sans balises Markdown, avec cette structure exacte :
{
  "score": 0.82,
  "strengths": ["..."],
  "weaknesses": ["..."],
  "improved_answer": "# Titre\n\n...",
  "inject_recommended": true
}

USER:
## Question
{question.question}

## Critères d'évaluation (rubric)
{question.rubric}

## Concepts attendus
{', '.join(question.expected_concepts)}

## Réponse LLCA à évaluer
{response.response}
```

### Règles `improved_answer`
- Toujours en Markdown
- Structure : titre H1 → explication → exemple code → cas d'usage
- Longueur cible : 200–600 mots
- Langue : **français** (même langue que les questions)
- En cas de réponse LLCA correcte : l'improved_answer complète et enrichit, ne répète pas

### Interface publique

```python
class JudgeClaude(JudgeBase):
    def __init__(self, config: dict):
        # config["judges"]["claude_model"] → "claude-sonnet-4-6"
        # ANTHROPIC_API_KEY lu depuis os.environ
        ...

    @property
    def judge_id(self) -> str:
        return self._model  # "claude-sonnet-4-6"

    def score(self, question: BenchQuestion, response: ProbeResponse) -> JudgeScore:
        ...

    def is_available(self) -> bool:
        """Vérifie que ANTHROPIC_API_KEY est définie dans os.environ."""
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def _call_api(self, prompt_user: str, prompt_system: str) -> str:
        """Appel Anthropic API. Retourne le texte brut de la réponse."""

    def _parse_response(self, raw: str) -> dict:
        """Parse la réponse JSON. Strip les balises ```json si présentes."""
```

### Appel Anthropic API

```python
import urllib.request
import json
import os

headers = {
    "Content-Type": "application/json",
    "x-api-key": os.environ["ANTHROPIC_API_KEY"],
    "anthropic-version": "2023-06-01",
}
payload = {
    "model": self._model,  # "claude-sonnet-4-6"
    "max_tokens": 2000,
    "system": prompt_system,
    "messages": [{"role": "user", "content": prompt_user}],
}
# POST https://api.anthropic.com/v1/messages
# urllib.request uniquement (pas de requests)
# timeout=30 (raisonnable pour un appel API externe — contrairement à Ollama)
```

Attention : le timeout Ollama = `None` (infini). Le timeout Anthropic API = 30s (appel réseau externe).

### Mode dégradé

Si `is_available()` retourne False ou si l'API lève une exception :
```python
return JudgeScore(
    question_id=response.question_id,
    judge=self.judge_id,
    score=0.0,
    strengths=[],
    weaknesses=["Juge indisponible : API Claude inaccessible"],
    improved_answer="",
    inject_recommended=False,
    domain=response.domain,
    palier=response.palier,
)
```
Log `WARNING` — jamais d'exception propagée.

---

## 5. `judge_openai.py` (stub V1)

```python
class JudgeOpenAI(JudgeBase):
    """Stub V1 — non fonctionnel. Interface uniquement pour EVAL-06+."""

    @property
    def judge_id(self) -> str:
        return "gpt-4o-stub"

    def score(self, question, response) -> JudgeScore:
        raise NotImplementedError("JudgeOpenAI non implémenté en V1")

    def is_available(self) -> bool:
        return False
```

---

## 6. `judge_engine.py`

### Responsabilités
- Charger `responses.jsonl` d'une session
- Pour chaque réponse, appeler les juges actifs
- Écrire `scores.jsonl` (append ligne par ligne)
- Calculer les scores moyens par palier pour `curriculum_tracker`
- Mode dégradé si 0 juge disponible

### Interface publique

```python
class JudgeEngine:
    def __init__(
        self,
        config: dict,
        session_dir: Path,
        judges: list[JudgeBase] | None = None,
    ):
        # Si judges=None → instancier automatiquement depuis config["judges"]["active"]
        ...

    def run(self, questions_index: dict[str, BenchQuestion]) -> list[JudgeScore]:
        """Lance le scoring complet.
        questions_index : {question_id: BenchQuestion} pour accès rapide.
        Écrit scores.jsonl au fur et à mesure.
        Retourne la liste complète des JudgeScore."""

    def get_scores_by_palier(
        self,
        domain: str,
        palier: int,
    ) -> list[float]:
        """Lit scores.jsonl et retourne les scores pour un domaine/palier."""
```

### Écriture scores.jsonl (append ligne par ligne)

```jsonl
{"question_id": "py-p0-001", "judge": "claude-sonnet-4-6", "score": 0.82, "strengths": ["..."], "weaknesses": [], "improved_answer": "...", "inject_recommended": true, "domain": "python_core", "palier": 0}
```

### Règles JudgeEngine
- Questions sans réponse dans `responses.jsonl` → skippées (log warning)
- Questions déjà scorées dans `scores.jsonl` → skippées (reprise session)
- Consensus mode (`consensus_mode=true`) : score = moyenne de tous les juges actifs, improved_answer = meilleure (score le plus élevé)
- Aucun juge disponible → log ERROR + `run()` retourne `[]` + ne crée pas `scores.jsonl`
- `scores.jsonl` ouvert en mode `"a"` (append) — jamais tronqué si relance

---

## 7. Tests attendus — `test_eval_03_judge.py` (~20 tests)

### JudgeBase
- ABC non instanciable directement

### JudgeClaude
- `is_available()` True si ANTHROPIC_API_KEY définie, False sinon
- `_parse_response` : JSON valide → dict correct
- `_parse_response` : JSON avec balises ```json → strip + parse correct
- `_parse_response` : JSON invalide → score=0.0, inject_recommended=False
- `score()` API mockée → JudgeScore correct (score, strengths, improved_answer)
- `score()` API erreur HTTP → JudgeScore dégradé (score=0.0, inject=False)
- `score()` ANTHROPIC_API_KEY absente → JudgeScore dégradé sans appel API

### JudgeOpenAI (stub)
- `is_available()` retourne False
- `score()` lève NotImplementedError

### JudgeEngine
- `run()` questions_index vide → retourne []
- `run()` réponse sans question dans l'index → skippée
- `run()` appel juge mocké → scores.jsonl écrit correct
- `run()` reprise session : questions déjà scorées skippées
- `run()` 0 juge disponible → retourne [] + pas de fichier scores.jsonl
- `get_scores_by_palier()` filtre domaine+palier correct
