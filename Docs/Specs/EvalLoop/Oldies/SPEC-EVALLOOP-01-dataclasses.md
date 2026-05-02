# SPEC EvalLoop — EVAL-01 : Dataclasses + Config + État
**Version** : 1.0
**Date** : 2026-04-23
**Statut** : DRAFT
**Dépendances** : EVAL-00 (overview)

---

## 1. Objectif du sprint

Poser les fondations de données d'EvalLoop :
- Dataclasses partagées entre tous les engines
- `eval_config.toml` — configuration globale
- `eval_state.json` — palier courant par domaine (persisté)
- Fichier `EvalLoop/evalloop_types.py` — source de vérité des types

Aucune logique métier dans ce sprint. Zéro appel LLM. Zéro I/O sauf lecture config.

---

## 2. Fichiers créés

| Fichier | Rôle |
|---|---|
| `EvalLoop/evalloop_types.py` | Dataclasses centrales |
| `EvalLoop/eval_config.toml` | Configuration globale (juges, seuils, chemins) |
| `EvalLoop/eval_state.json` | État paliers par domaine (initialement vide `{}`) |

---

## 3. Dataclasses — `evalloop_types.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BenchQuestion:
    """Une question de benchmark avec métadonnées curriculum."""
    id: str                          # "py-core-001"
    domain: str                      # "python_core" | "architecture" | ...
    palier: int                      # 0 = fondations, 5 = expert
    difficulty: str                  # "easy" | "medium" | "hard" | "expert"
    question: str                    # Texte de la question
    expected_concepts: list[str]     # Concepts clés attendus dans la réponse
    rubric: str                      # Critères d'évaluation pour le juge
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "domain": self.domain,
            "palier": self.palier,
            "difficulty": self.difficulty,
            "question": self.question,
            "expected_concepts": self.expected_concepts,
            "rubric": self.rubric,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BenchQuestion":
        return cls(
            id=d["id"],
            domain=d["domain"],
            palier=d.get("palier", 0),
            difficulty=d.get("difficulty", "medium"),
            question=d["question"],
            expected_concepts=d.get("expected_concepts", []),
            rubric=d.get("rubric", ""),
            tags=d.get("tags", []),
        )


@dataclass
class ProbeResponse:
    """Réponse brute de LLCA à une question de benchmark."""
    question_id: str
    model: str                       # "qwen2.5-coder:3b"
    response: str
    duration_ms: int
    timestamp: str                   # ISO 8601
    domain: str = ""
    palier: int = 0

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "model": self.model,
            "response": self.response,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
            "domain": self.domain,
            "palier": self.palier,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProbeResponse":
        return cls(
            question_id=d["question_id"],
            model=d["model"],
            response=d["response"],
            duration_ms=d.get("duration_ms", 0),
            timestamp=d["timestamp"],
            domain=d.get("domain", ""),
            palier=d.get("palier", 0),
        )


@dataclass
class JudgeScore:
    """Score attribué par un juge externe à une réponse LLCA."""
    question_id: str
    judge: str                       # "claude-sonnet-4-6" | "gpt-4o"
    score: float                     # 0.0 → 1.0
    strengths: list[str]
    weaknesses: list[str]
    improved_answer: str             # Réponse corrigée/améliorée par le juge
    inject_recommended: bool         # Le juge recommande-t-il l'injection ?
    domain: str = ""
    palier: int = 0

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "judge": self.judge,
            "score": self.score,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "improved_answer": self.improved_answer,
            "inject_recommended": self.inject_recommended,
            "domain": self.domain,
            "palier": self.palier,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "JudgeScore":
        return cls(
            question_id=d["question_id"],
            judge=d["judge"],
            score=float(d["score"]),
            strengths=d.get("strengths", []),
            weaknesses=d.get("weaknesses", []),
            improved_answer=d.get("improved_answer", ""),
            inject_recommended=bool(d.get("inject_recommended", False)),
            domain=d.get("domain", ""),
            palier=d.get("palier", 0),
        )


@dataclass
class DistilledSkill:
    """Un skill formaté prêt à être injecté dans SkillLibrary."""
    source_question_id: str
    content: str                     # Contenu .md complet
    score: float
    domain: str
    palier: int
    judge: str
    injected_at: str                 # ISO 8601

    def to_dict(self) -> dict:
        return {
            "source_question_id": self.source_question_id,
            "content": self.content,
            "score": self.score,
            "domain": self.domain,
            "palier": self.palier,
            "judge": self.judge,
            "injected_at": self.injected_at,
        }


@dataclass
class PalierState:
    """État curriculum d'un domaine (palier courant + scores historiques)."""
    domain: str
    current_palier: int = 0
    palier_scores: dict[int, float] = field(default_factory=dict)  # {palier: score_moyen}
    unlocked_at: dict[int, str] = field(default_factory=dict)      # {palier: ISO timestamp}

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "current_palier": self.current_palier,
            "palier_scores": {str(k): v for k, v in self.palier_scores.items()},
            "unlocked_at": {str(k): v for k, v in self.unlocked_at.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PalierState":
        return cls(
            domain=d["domain"],
            current_palier=d.get("current_palier", 0),
            palier_scores={int(k): float(v) for k, v in d.get("palier_scores", {}).items()},
            unlocked_at={int(k): v for k, v in d.get("unlocked_at", {}).items()},
        )
```

---

## 4. `eval_config.toml`

```toml
[general]
project_root = "D:\\LLMCodeAgent"
evalloop_dir = "D:\\LLMCodeAgent\\EvalLoop"
sessions_dir = "D:\\LLMCodeAgent\\EvalLoop\\sessions"
benchmarks_dir = "D:\\LLMCodeAgent\\EvalLoop\\benchmarks"

[llca]
# LLCA via Ollama local — 100% offline
ollama_base_url = "http://localhost:11434"
model = "qwen2.5-coder:3b"
timeout = null                    # Jamais de timeout (règle LCCA)
max_tokens = 1500

[judges]
active = ["claude"]               # Juges actifs
consensus_mode = false            # true = score moyen multi-juges
claude_model = "claude-sonnet-4-6"

[scoring]
min_inject_score = 0.75           # Score minimum pour injection SkillLibrary
seuil_unlock = 0.70               # Score moyen palier requis pour débloquer palier+1
max_palier = 5

[curriculum]
# Domaines actifs (dans l'ordre de priorité)
domains = [
    "python_core",
    "architecture",
    "refactoring",
    "debugging",
    "algorithms",
    "llca_meta",
]

[domains.python_core]
description = "Fondamentaux Python : OOP, GC, typing, async"
questions_per_palier = 5          # Nombre de questions par palier

[domains.architecture]
description = "Design patterns, SOLID, découpage système"
questions_per_palier = 5

[domains.refactoring]
description = "Identifier et corriger la dette technique"
questions_per_palier = 5

[domains.debugging]
description = "Lire un traceback, diagnostiquer, corriger"
questions_per_palier = 5

[domains.algorithms]
description = "Complexité, structures de données, algorithmes"
questions_per_palier = 5

[domains.llca_meta]
description = "Questions sur LCCA lui-même et ses propres règles"
questions_per_palier = 3
```

---

## 5. `eval_state.json` (état initial)

```json
{}
```

Peuplé progressivement par `curriculum_tracker.py`. Exemple après quelques sessions :

```json
{
  "python_core": {
    "domain": "python_core",
    "current_palier": 2,
    "palier_scores": {"0": 0.82, "1": 0.75},
    "unlocked_at": {
      "0": "2026-04-23T21:00:00",
      "1": "2026-04-23T21:30:00",
      "2": "2026-04-23T22:00:00"
    }
  },
  "architecture": {
    "domain": "architecture",
    "current_palier": 0,
    "palier_scores": {},
    "unlocked_at": {}
  }
}
```

Écriture : **atomique** `.tmp → Path.replace()` (règle T-14 LCCA).

---

## 6. Conventions de nommage des IDs de questions

Format : `{domain_prefix}-p{palier}-{sequence:03d}`

Exemples :
- `py-p0-001` — python_core, palier 0, question 1
- `arch-p2-003` — architecture, palier 2, question 3
- `debug-p1-007` — debugging, palier 1, question 7
- `meta-p0-001` — llca_meta, palier 0, question 1

Préfixes domaines :
| Domaine | Préfixe |
|---|---|
| python_core | py |
| architecture | arch |
| refactoring | refact |
| debugging | debug |
| algorithms | algo |
| llca_meta | meta |

---

## 7. Tests attendus — `test_eval_01_types.py` (~20 tests)

- `BenchQuestion.to_dict()` / `from_dict()` — round-trip
- `BenchQuestion.from_dict()` — valeurs par défaut (palier=0, tags=[])
- `ProbeResponse.to_dict()` / `from_dict()` — round-trip
- `JudgeScore.to_dict()` / `from_dict()` — round-trip, score float, inject_recommended bool
- `DistilledSkill.to_dict()` — contenu intact
- `PalierState.to_dict()` / `from_dict()` — clés int ↔ str, round-trip
- `PalierState` défaut — current_palier=0, dicts vides
- `JudgeScore.from_dict()` — score converti float même si int en JSON
