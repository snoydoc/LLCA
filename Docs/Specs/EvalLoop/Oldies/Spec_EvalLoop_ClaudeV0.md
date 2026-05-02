

============================================================
Fichier : SPEC-EVALLOOP-00-overview.md
============================================================

# SPEC EvalLoop — Vue d'ensemble & Architecture
**Version** : 1.0  
**Date** : 2026-04-23  
**Statut** : DRAFT  
**Auteur** : LCCA Project

---

## 1. Contexte & Motivation

LCCA dispose d'une première source d'apprentissage : **EducatorAgent** (ingestion de repos GitHub, extraction de patterns, injection dans SkillLibrary).

**EvalLoop** est la **deuxième source d'apprentissage**, complémentaire et orthogonale :

| Source | Mécanisme | Type de connaissance |
|---|---|---|
| EducatorAgent | Lecture de code source GitHub | Patterns syntaxiques, APIs, idiomes |
| **EvalLoop** | Évaluation par questions/réponses | Raisonnement, architecture, debugging, meta-connaissance |

EvalLoop fonctionne comme un **curriculum scolaire** : LLCA répond à des questions de niveau croissant (palier 0 → N), un juge externe (Claude, GPT-4o, etc.) score les réponses et rédige des réponses améliorées, les meilleures sont distillées dans la SkillLibrary.

Le principe clé : **on n'injecte jamais la réponse brute de LLCA** — on injecte la réponse corrigée/améliorée par le juge. LLCA apprend de ses erreurs via un miroir externe.

---

## 2. Principe des Paliers de Complexité

Chaque domaine de benchmark est structuré en **paliers numérotés à partir de 0** :

```
Palier 0 : Fondations — définitions, vocabulaire, concepts isolés
Palier 1 : Compréhension — "pourquoi", comparaisons simples
Palier 2 : Application — cas d'usage concrets, implémentations simples
Palier 3 : Analyse — détecter des problèmes, expliquer des comportements
Palier 4 : Synthèse — concevoir une solution à un problème ouvert
Palier 5 : Expert — edge cases, performance, compromis architecturaux
```

**Règles curriculum** :
- Une session démarre toujours au **palier 0** pour un domaine jamais testé
- Le palier suivant n'est débloqué que si le **score moyen du palier courant ≥ seuil_unlock** (configurable, défaut 0.70)
- Un domaine où LLCA échoue au palier 0 → génération automatique de questions supplémentaires palier 0
- Le palier courant par domaine est persisté dans `eval_state.json`

---

## 3. Architecture des Composants

```
EvalLoop/
├── eval_config.toml              # Configuration globale
├── eval_state.json               # Palier courant par domaine (persisté)
├── lcca_eval.py                  # CLI point d'entrée
│
├── benchmarks/                   # Questions par domaine + palier
│   ├── python_core/
│   │   ├── palier_0.json
│   │   ├── palier_1.json
│   │   └── ...
│   ├── architecture/
│   ├── refactoring/
│   ├── debugging/
│   ├── algorithms/
│   └── llca_meta/
│
├── sessions/                     # Une session = un run probe+judge
│   └── YYYY-MM-DD_HH-MM/
│       ├── responses.jsonl       # Réponses brutes LLCA
│       ├── scores.jsonl          # Scores + réponses améliorées du juge
│       └── session_report.md     # Rapport synthèse lisible
│
├── engines/
│   ├── probe_engine.py           # Soumet questions → LLCA (Ollama local)
│   ├── judge_engine.py           # Orchestre les juges
│   ├── distill_engine.py         # Sélectionne + injecte dans SkillLibrary
│   ├── bench_generator.py        # Génère nouvelles questions via LLM
│   └── curriculum_tracker.py    # Gère les paliers, unlock, état
│
└── judges/
    ├── judge_base.py             # ABC JudgeBase (interface commune)
    ├── judge_claude.py           # Juge Claude (Anthropic API)
    └── judge_openai.py           # Futur : GPT-4o (stub V1)
```

---

## 4. Flux de Données

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 1 — PROBE                                                │
│                                                                 │
│  curriculum_tracker  →  sélectionne palier courant             │
│  bench_generator     →  questions du palier (JSON)             │
│  probe_engine        →  soumet à LLCA via Ollama               │
│                         →  responses.jsonl                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 2 — JUDGE                                                │
│                                                                 │
│  judge_engine        →  charge responses.jsonl                 │
│  judge_claude.py     →  score + improved_answer par question   │
│                         →  scores.jsonl                        │
│  curriculum_tracker  →  calcule score moyen palier             │
│                         →  unlock palier suivant si ≥ seuil    │
│                         →  met à jour eval_state.json          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 3 — DISTILL                                              │
│                                                                 │
│  distill_engine      →  filtre scores ≥ min_inject_score       │
│                         →  formate en .md LCCA                 │
│                         →  déduplique (sha256[:16])            │
│                         →  injecte via SkillLibrary            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Intégration SkillLibrary

Les skills distillés sont injectés avec `source_type = "evalloop"` :

```python
SkillLibrary.add_skill(
    content=skill_md,
    source_type="evalloop",
    metadata={
        "question_id": "py-core-001",
        "domain": "python_core",
        "palier": 2,
        "score": 0.88,
        "judge": "claude-sonnet-4-6",
        "session": "2026-04-23_21-00",
    }
)
```

Cela permet de distinguer dans la SkillLibrary :
- Skills issus de code source (EducatorAgent) → `source_type = "github"`
- Skills issus d'évaluation (EvalLoop) → `source_type = "evalloop"`

---

## 6. Extensibilité Juges

```python
class JudgeBase(ABC):
    @abstractmethod
    def score(self, question: BenchQuestion, response: ProbeResponse) -> JudgeScore:
        ...

# Implémentations V1 :
# - JudgeClaude  (Anthropic API — claude-sonnet-4-6)
# - JudgeOpenAI  (stub V1 → implémenté EVAL-06+)

# Ajout futur : JudgeGemini, JudgeMistral, JudgeLocal (Ollama critique)
```

La configuration `eval_config.toml` liste les juges actifs :
```toml
[judges]
active = ["claude"]   # ["claude", "openai"] quand les deux sont configurés
consensus_mode = false  # true = score moyen de tous les juges actifs
```

---

## 7. Sprints EvalLoop

| Sprint | Fichier spec | Contenu | Dépendances |
|---|---|---|---|
| EVAL-00 | SPEC-EVALLOOP-00-overview.md | Architecture + dataclasses + config | — |
| EVAL-01 | SPEC-EVALLOOP-01-dataclasses.md | Dataclasses + eval_config.toml + eval_state.json | — |
| EVAL-02 | SPEC-EVALLOOP-02-probe.md | probe_engine.py + curriculum_tracker.py | EVAL-01 |
| EVAL-03 | SPEC-EVALLOOP-03-judge.md | judge_base.py + judge_claude.py | EVAL-01 |
| EVAL-04 | SPEC-EVALLOOP-04-distill.md | distill_engine.py → SkillLibrary | EVAL-01, EVAL-03 |
| EVAL-05 | SPEC-EVALLOOP-05-benchgen.md | bench_generator.py + benchmarks initiaux | EVAL-01 |
| EVAL-06 | SPEC-EVALLOOP-06-cli.md | lcca_eval.py CLI + session_report.md | EVAL-02..05 |
| EVAL-07 | SPEC-EVALLOOP-07-tests.md | test_eval_*.py (~80 tests) | EVAL-01..06 |

---

## 8. Invariants & Règles

- `probe_engine` : 100% offline (Ollama local) — jamais d'appel réseau
- `judge_engine` : API externe optionnelle — mode dégradé si absent (log warning + skip distill)
- Injection SkillLibrary : déduplication sha256[:16] obligatoire (même pattern Educator)
- `auto_push = false` invariant — EvalLoop ne fait jamais de git push
- Sessions immuables : `responses.jsonl` et `scores.jsonl` jamais modifiés après écriture
- `eval_state.json` : écriture atomique `.tmp → Path.replace()` (règle T-14)
- Palier 0 toujours disponible, même si unlock non atteint (fallback)


============================================================
Fichier : SPEC-EVALLOOP-01-dataclasses.md
============================================================

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


============================================================
Fichier : SPEC-EVALLOOP-02-probe.md
============================================================

# SPEC EvalLoop — EVAL-02 : ProbeEngine + CurriculumTracker
**Version** : 1.0
**Date** : 2026-04-23
**Statut** : DRAFT
**Dépendances** : EVAL-01 (dataclasses + config)

---

## 1. Objectif du sprint

Implémenter les deux composants de la **Phase 1 — PROBE** :

1. **`curriculum_tracker.py`** — Gestion des paliers, unlock, état persisté
2. **`probe_engine.py`** — Soumission des questions à LLCA via Ollama (100% offline)

Ce sprint produit `responses.jsonl` dans le dossier de session.

---

## 2. Fichiers créés

| Fichier | Rôle |
|---|---|
| `EvalLoop/engines/curriculum_tracker.py` | Paliers + unlock + eval_state.json |
| `EvalLoop/engines/probe_engine.py` | Questions → LLCA → responses.jsonl |

---

## 3. `curriculum_tracker.py`

### Responsabilités
- Charger / sauvegarder `eval_state.json` (écriture atomique)
- Retourner le palier courant pour un domaine
- Décider si un palier peut être débloqué (score moyen ≥ seuil_unlock)
- Sélectionner les questions du palier courant depuis `benchmarks/{domain}/palier_{N}.json`

### Interface publique

```python
class CurriculumTracker:
    def __init__(self, evalloop_dir: Path, config: dict):
        ...

    def get_current_palier(self, domain: str) -> int:
        """Retourne le palier courant pour un domaine (0 si jamais testé)."""

    def get_questions_for_session(self, domain: str, count: int) -> list[BenchQuestion]:
        """Charge count questions du palier courant pour le domaine.
        Fallback palier 0 si le fichier palier N n'existe pas encore."""

    def record_palier_scores(
        self,
        domain: str,
        palier: int,
        scores: list[float],
        session_timestamp: str,
    ) -> bool:
        """Enregistre les scores d'un palier. Retourne True si le palier suivant
        est débloqué (score_moyen >= seuil_unlock)."""

    def get_state(self, domain: str) -> PalierState:
        """Retourne l'état complet d'un domaine."""

    def _load_state(self) -> dict[str, PalierState]:
        """Charge eval_state.json. Retourne {} si absent."""

    def _save_state(self) -> None:
        """Écriture atomique .tmp → Path.replace() (règle T-14)."""

    def _load_bench_file(self, domain: str, palier: int) -> list[BenchQuestion]:
        """Charge benchmarks/{domain}/palier_{N}.json.
        Retourne [] si fichier absent (log warning)."""
```

### Règles CurriculumTracker
- `eval_state.json` absent → créé avec `{}` au premier appel `_save_state`
- Palier inconnu pour un domaine → défaut 0 (jamais d'exception)
- `get_questions_for_session` : si count > questions disponibles → retourne tout ce qui existe
- Ordre questions dans `get_questions_for_session` : aléatoire (shuffle) pour éviter le biais de position
- `record_palier_scores` : score_moyen = `sum(scores) / len(scores)` si `len(scores) > 0`, sinon 0.0
- Unlock atomique : `_save_state()` appelé même si unlock = False (persistance scores)

---

## 4. `probe_engine.py`

### Responsabilités
- Recevoir une liste de `BenchQuestion`
- Soumettre chaque question à LLCA via Ollama REST API (local)
- Produire `responses.jsonl` dans le dossier session
- Mesurer `duration_ms` par question

### Interface publique

```python
class ProbeEngine:
    def __init__(self, config: dict, session_dir: Path):
        ...

    def run(self, questions: list[BenchQuestion]) -> list[ProbeResponse]:
        """Lance le probe sur toutes les questions.
        Écrit responses.jsonl au fur et à mesure (append JSONL, pas batch).
        Retourne la liste complète des ProbeResponse."""

    def _probe_one(self, question: BenchQuestion) -> ProbeResponse:
        """Soumet une seule question à Ollama. Retourne ProbeResponse."""

    def _build_prompt(self, question: BenchQuestion) -> str:
        """Construit le prompt système + user pour la question."""
```

### Format du prompt Ollama

```
SYSTEM:
Tu es LCCA, un assistant expert en développement Python.
Réponds en français. Sois précis, structuré, et cite des exemples concrets.
Domaine : {domain} | Palier : {palier}

USER:
{question.question}
```

### Écriture JSONL — append ligne par ligne

```python
# Après chaque _probe_one(), écrire immédiatement :
with open(session_dir / "responses.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps(response.to_dict(), ensure_ascii=False) + "\n")
```

Pourquoi append ligne par ligne : si Ollama plante à mi-session, les réponses déjà obtenues sont préservées.

### Appel Ollama REST

```python
import urllib.request
import json

payload = {
    "model": config["llca"]["model"],
    "prompt": prompt,
    "stream": False,
    "options": {
        "num_predict": config["llca"]["max_tokens"],
    }
}
# POST http://localhost:11434/api/generate
# timeout=None (règle LCCA : OLLAMA_TIMEOUT = None)
```

### Règles ProbeEngine
- `urllib.request` stdlib uniquement (pas de `requests`)
- `timeout=None` obligatoire sur `urllib.request.urlopen` (règle LCCA)
- Si Ollama répond avec une erreur HTTP → `ProbeResponse.response = f"[ERREUR OLLAMA: {status}]"`, `duration_ms = 0`
- Si `OSError` (Ollama éteint) → log critique + `raise` (pas de swallow silencieux)
- `responses.jsonl` ouvert en mode `"a"` (append) — jamais tronqué si relance en milieu de session
- Reprendre une session interrompue : `ProbeEngine.run()` vérifie les IDs déjà présents dans `responses.jsonl` et skip les questions déjà répondues

---

## 5. Format `responses.jsonl`

Une ligne JSON par réponse (NDJSON) :

```jsonl
{"question_id": "py-p0-001", "model": "qwen2.5-coder:3b", "response": "...", "duration_ms": 4230, "timestamp": "2026-04-23T21:05:12", "domain": "python_core", "palier": 0}
{"question_id": "py-p0-002", "model": "qwen2.5-coder:3b", "response": "...", "duration_ms": 3810, "timestamp": "2026-04-23T21:06:01", "domain": "python_core", "palier": 0}
```

---

## 6. Tests attendus — `test_eval_02_probe.py` (~18 tests)

### CurriculumTracker
- `get_current_palier` domaine inconnu → 0
- `get_current_palier` domaine existant → palier persisté
- `get_questions_for_session` fichier absent → [] + log warning
- `get_questions_for_session` count > dispo → retourne tout
- `get_questions_for_session` ordre aléatoire (shuffle)
- `record_palier_scores` score_moyen calculé correctement
- `record_palier_scores` unlock si score >= seuil → retourne True + palier incrémenté
- `record_palier_scores` no unlock si score < seuil → retourne False + palier inchangé
- `record_palier_scores` liste vide → score 0.0 + no unlock
- Écriture atomique : `eval_state.json.tmp` créé puis renommé

### ProbeEngine
- `_build_prompt` contient domain + palier + question
- `_probe_one` appel Ollama mocké → ProbeResponse correct
- `_probe_one` Ollama erreur HTTP → ProbeResponse avec `[ERREUR OLLAMA: 500]`
- `run` écrit responses.jsonl ligne par ligne
- `run` skip questions déjà présentes dans responses.jsonl (reprise session)
- `run` retourne liste ProbeResponse dans le même ordre que questions
- `run` OSError Ollama → exception propagée (pas swallowée)


============================================================
Fichier : SPEC-EVALLOOP-03-judge.md
============================================================

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


============================================================
Fichier : SPEC-EVALLOOP-04-distill.md
============================================================

# SPEC EvalLoop — EVAL-04 : DistillEngine → SkillLibrary
**Version** : 1.0
**Date** : 2026-04-23
**Statut** : DRAFT
**Dépendances** : EVAL-01 (dataclasses), EVAL-03 (JudgeScore)

---

## 1. Objectif du sprint

Implémenter la **Phase 3 — DISTILL** :

- Lire `scores.jsonl` d'une session
- Filtrer les scores ≥ `min_inject_score`
- Formater chaque `improved_answer` en `.md` LCCA avec frontmatter YAML
- Dédupliquer par sha256[:16] (même pattern Educator)
- Injecter via `SkillLibrary.add_skill()`

Ce sprint clôt le cycle probe → judge → distill.

---

## 2. Fichiers créés / modifiés

| Fichier | Action |
|---|---|
| `EvalLoop/engines/distill_engine.py` | Créé — distillation + injection |
| `core/skill_library.py` | Aucune modification — `add_skill()` suffisant |

---

## 3. `distill_engine.py`

### Interface publique

```python
class DistillEngine:
    def __init__(self, config: dict, session_dir: Path, skill_lib_path: Path):
        # skill_lib_path : chemin vers le dossier SkillLibrary LCCA
        ...

    def run(
        self,
        min_score: float | None = None,
        questions_index: dict[str, BenchQuestion] | None = None,
    ) -> list[DistilledSkill]:
        """Distille les scores de la session courante.
        
        min_score : override config["scoring"]["min_inject_score"] si fourni.
        questions_index : pour enrichir le frontmatter (domain, palier, tags).
        Retourne la liste des DistilledSkill injectés (sans les dédupliqués skippés).
        """

    def _load_scores(self) -> list[JudgeScore]:
        """Charge scores.jsonl. Retourne [] si absent."""

    def _format_skill_md(
        self,
        score: JudgeScore,
        question: BenchQuestion | None,
    ) -> str:
        """Formate en .md LCCA avec frontmatter YAML."""

    def _sha256_content(self, content: str) -> str:
        """sha256(content.encode()).hexdigest()[:16]"""

    def _is_duplicate(self, content_hash: str) -> bool:
        """Vérifie si le hash est déjà présent dans un skill existant SkillLibrary.
        Cherche le commentaire <!-- dedup:{hash} --> dans les fichiers .md du dossier."""

    def _inject(self, skill_md: str, score: JudgeScore, question: BenchQuestion | None) -> None:
        """Appelle SkillLibrary.add_skill() avec source_type='evalloop'."""
```

---

## 4. Format `.md` du skill distillé

```markdown
---
source: evalloop/{question_id}
domain: {domain}
palier: {palier}
difficulty: {difficulty}
score: {score}
judge: {judge_id}
session: {session_name}
date: {YYYY-MM-DD}
tags: [{tag1}, {tag2}]
---

{improved_answer}

<!-- dedup:{sha256[:16]} -->
```

Exemple concret :

```markdown
---
source: evalloop/py-p0-001
domain: python_core
palier: 0
difficulty: medium
score: 0.88
judge: claude-sonnet-4-6
session: 2026-04-23_21-00
date: 2026-04-23
tags: [OOP, metaclass, memory]
---

# `__new__` vs `__init__` en Python

En Python, la création d'un objet passe par deux étapes distinctes...

[contenu rédigé par le juge]

<!-- dedup:a3f8c2d91b4e0f7a -->
```

---

## 5. Appel `SkillLibrary.add_skill()`

```python
from core.skill_library import SkillLibrary

skill_lib = SkillLibrary(skill_lib_path)
skill_lib.add_skill(
    content=skill_md,
    source_type="evalloop",
    metadata={
        "question_id": score.question_id,
        "domain": score.domain,
        "palier": score.palier,
        "score": score.score,
        "judge": score.judge,
        "session": session_name,
    }
)
```

Le `source_type = "evalloop"` est distinct de `"github"` (EducatorAgent) — permet de filtrer par source dans les recherches SkillLibrary.

---

## 6. Règles DistillEngine

- `min_score` : si `None`, utiliser `config["scoring"]["min_inject_score"]` (défaut 0.75)
- `inject_recommended=False` sur un JudgeScore → skip, même si score >= min_score
  - Ratio : le juge a explicitement signalé que la réponse n'est pas utile
- `improved_answer` vide (`""`) → skip (pas de contenu à injecter)
- Déduplication obligatoire avant injection : sha256[:16] sur le contenu brut `improved_answer`
- Ordre d'injection : scores décroissants (meilleure réponse en premier)
- Rapport distillation : log `INFO` pour chaque skill injecté, `DEBUG` pour chaque skip
- Sessions immuables : `scores.jsonl` jamais modifié par DistillEngine

---

## 7. Déduplication entre sessions

Problème : si deux sessions consécutives obtiennent le même `improved_answer` pour la même question, on ne doit pas injecter deux fois.

Solution : `<!-- dedup:{hash} -->` en fin de chaque skill .md. `_is_duplicate()` scanne les fichiers `.md` du dossier SkillLibrary pour détecter le hash.

Optimisation V1 : scan exhaustif acceptable (SkillLibrary < 1000 fichiers). V2+ : index en mémoire.

---

## 8. Tests attendus — `test_eval_04_distill.py` (~18 tests)

- `_format_skill_md` : frontmatter YAML correct (source, domain, palier, score, judge, date)
- `_format_skill_md` : improved_answer inclus dans le contenu
- `_format_skill_md` : commentaire `<!-- dedup:{hash} -->` présent
- `_sha256_content` : hash 16 caractères hexadécimaux
- `_sha256_content` : deux contenus identiques → même hash
- `_sha256_content` : deux contenus différents → hash différent (probabilistique)
- `_is_duplicate` : hash absent dans SkillLibrary → False
- `_is_duplicate` : hash présent dans un fichier SkillLibrary → True
- `_load_scores` : scores.jsonl valide → liste JudgeScore
- `_load_scores` : scores.jsonl absent → []
- `run()` : score < min_score → skippé
- `run()` : inject_recommended=False → skippé même si score >= min_score
- `run()` : improved_answer vide → skippé
- `run()` : score >= min_score + inject=True → add_skill appelé
- `run()` : doublon détecté → add_skill non appelé
- `run()` : min_score override → utilise la valeur fournie
- `run()` : retourne uniquement les skills effectivement injectés
- `run()` : injection ordonnée par score décroissant


============================================================
Fichier : SPEC-EVALLOOP-05-benchgen.md
============================================================

# SPEC EvalLoop — EVAL-05 : BenchGenerator + Benchmarks Initiaux
**Version** : 1.0
**Date** : 2026-04-23
**Statut** : DRAFT
**Dépendances** : EVAL-01 (dataclasses + config)

---

## 1. Objectif du sprint

Deux livrables distincts :

1. **`bench_generator.py`** — Génère de nouvelles questions via LLM (Ollama local)
2. **Benchmarks initiaux** — 6 domaines × 3 paliers × 5 questions = 90 questions minimum

Les benchmarks sont écrits **à la main** pour les paliers 0 et 1 (contrôle qualité humain).
Le générateur est utilisé pour les paliers 2+ et pour l'enrichissement continu.

---

## 2. Fichiers créés

| Fichier | Rôle |
|---|---|
| `EvalLoop/engines/bench_generator.py` | Génération questions via LLM |
| `EvalLoop/benchmarks/python_core/palier_0.json` | 5 questions palier 0 |
| `EvalLoop/benchmarks/python_core/palier_1.json` | 5 questions palier 1 |
| `EvalLoop/benchmarks/python_core/palier_2.json` | 5 questions palier 2 |
| `EvalLoop/benchmarks/architecture/palier_0.json` | 5 questions palier 0 |
| `EvalLoop/benchmarks/architecture/palier_1.json` | 5 questions palier 1 |
| `EvalLoop/benchmarks/debugging/palier_0.json` | 5 questions palier 0 |
| `EvalLoop/benchmarks/debugging/palier_1.json` | 5 questions palier 1 |
| `EvalLoop/benchmarks/algorithms/palier_0.json` | 5 questions palier 0 |
| `EvalLoop/benchmarks/refactoring/palier_0.json` | 5 questions palier 0 |
| `EvalLoop/benchmarks/llca_meta/palier_0.json` | 3 questions palier 0 |

---

## 3. `bench_generator.py`

### Responsabilités
- Générer N nouvelles questions pour un domaine + palier via Ollama
- Valider le format JSON retourné par le LLM
- Écrire / enrichir le fichier `benchmarks/{domain}/palier_{N}.json`
- Éviter les doublons (déduplication par question.lower().strip())

### Interface publique

```python
class BenchGenerator:
    def __init__(self, config: dict, benchmarks_dir: Path):
        ...

    def generate(
        self,
        domain: str,
        palier: int,
        count: int = 5,
    ) -> list[BenchQuestion]:
        """Génère count questions pour le domaine+palier via LLM.
        Déduplication contre les questions existantes du même fichier.
        Retourne les nouvelles questions générées (sans les doublons)."""

    def save(self, questions: list[BenchQuestion], domain: str, palier: int) -> Path:
        """Append les questions dans benchmarks/{domain}/palier_{N}.json.
        Crée le fichier si absent. Retourne le chemin du fichier."""

    def _build_gen_prompt(self, domain: str, palier: int, count: int) -> str:
        """Construit le prompt de génération."""

    def _parse_llm_response(self, raw: str) -> list[dict]:
        """Parse la réponse JSON du LLM. Tolère les erreurs partielles."""

    def _validate_question(self, q: dict) -> bool:
        """Vérifie que la question a tous les champs requis."""

    def _load_existing(self, domain: str, palier: int) -> list[BenchQuestion]:
        """Charge les questions existantes pour déduplication."""
```

### Prompt de génération

```
SYSTEM:
Tu es un expert en évaluation de LLMs spécialisés en développement Python.
Tu génères des questions de benchmark pour évaluer le niveau d'un assistant IA.
Réponds UNIQUEMENT en JSON valide, sans balises Markdown.

USER:
Génère {count} questions de benchmark pour le domaine "{domain_description}" au palier {palier}.

Palier {palier} signifie : {palier_description}

Pour chaque question, retourne ce format JSON exact :
[
  {
    "id": "{prefix}-p{palier}-{seq:03d}",
    "domain": "{domain}",
    "palier": {palier},
    "difficulty": "easy|medium|hard|expert",
    "question": "La question complète en français",
    "expected_concepts": ["concept1", "concept2"],
    "rubric": "Critères d'évaluation : la réponse doit mentionner...",
    "tags": ["tag1", "tag2"]
  }
]

Questions à éviter (déjà présentes) :
{existing_questions_list}
```

Descriptions de paliers :
```python
PALIER_DESCRIPTIONS = {
    0: "Fondations — définitions, vocabulaire, concepts isolés. Exemples : 'Qu'est-ce que X ?', 'Quel est le rôle de Y ?'",
    1: "Compréhension — 'pourquoi', comparaisons simples. Exemples : 'Quelle est la différence entre A et B ?', 'Pourquoi utiliser X plutôt que Y ?'",
    2: "Application — cas d'usage concrets, implémentations simples. Exemples : 'Implémente X', 'Comment utiliser Y pour faire Z ?'",
    3: "Analyse — détecter des problèmes, expliquer des comportements. Exemples : 'Quel problème pose ce code ?', 'Pourquoi ce bug se produit-il ?'",
    4: "Synthèse — concevoir une solution à un problème ouvert. Exemples : 'Conçois une architecture pour...', 'Comment refactoriser ce système ?'",
    5: "Expert — edge cases, performance, compromis architecturaux. Exemples : 'Quel est l'impact sur le GC de...', 'Quels sont les trade-offs de...'",
}
```

### Règles BenchGenerator
- `urllib.request` pour Ollama (même pattern que ProbeEngine)
- `timeout=None` pour Ollama
- Si le LLM retourne un JSON partiellement invalide → parser les questions valides, log warning pour les invalides
- Séquence d'ID : `_next_seq()` = max(ID existants) + 1 pour ce domaine/palier
- `save()` : lecture du fichier existant → merge → écriture (jamais tronquer)
- Fichier JSON indenté (indent=2, ensure_ascii=False) pour lisibilité humaine

---

## 4. Benchmarks initiaux — Palier 0 (fondations)

### Philosophie palier 0

Les questions palier 0 doivent être **sans ambiguïté**, avec **une seule bonne réponse**,
testant la compréhension de base. LLCA doit les réussir à ≥ 80% si son SkillLibrary
est correctement alimenté. Si LLCA échoue au palier 0, c'est un signal clair de lacune.

### `python_core/palier_0.json` — 5 questions

```json
[
  {
    "id": "py-p0-001",
    "domain": "python_core",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce que le GIL en Python ? Quel est son impact sur le multithreading ?",
    "expected_concepts": ["Global Interpreter Lock", "thread", "bytecode", "I/O bound", "CPU bound"],
    "rubric": "La réponse doit définir le GIL, expliquer qu'il limite l'exécution bytecode Python à un seul thread à la fois, et distinguer I/O-bound (threads utiles) vs CPU-bound (threads bloqués par GIL).",
    "tags": ["GIL", "concurrency", "threading"]
  },
  {
    "id": "py-p0-002",
    "domain": "python_core",
    "palier": 0,
    "difficulty": "easy",
    "question": "Quelle est la différence entre une liste et un tuple en Python ?",
    "expected_concepts": ["mutable", "immutable", "hashable", "performance", "use case"],
    "rubric": "La réponse doit distinguer mutabilité (liste modifiable, tuple non), hashabilité (tuple hashable donc utilisable comme clé dict), et mentionner au moins un cas d'usage concret pour chaque.",
    "tags": ["collections", "immutable", "basics"]
  },
  {
    "id": "py-p0-003",
    "domain": "python_core",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce qu'un décorateur Python ? Donne un exemple simple.",
    "expected_concepts": ["wrapper", "closure", "functools.wraps", "higher-order function"],
    "rubric": "La réponse doit expliquer qu'un décorateur est une fonction prenant une fonction en argument et retournant une fonction modifiée, avec un exemple de code fonctionnel.",
    "tags": ["decorators", "closures", "OOP"]
  },
  {
    "id": "py-p0-004",
    "domain": "python_core",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce que le duck typing en Python ?",
    "expected_concepts": ["duck typing", "interface", "isinstance", "Protocol", "comportement"],
    "rubric": "La réponse doit expliquer le principe ('si ça marche comme un canard...'), le lier à la philosophie Python (EAFP vs LBYL), et mentionner l'alternative typing.Protocol.",
    "tags": ["typing", "duck-typing", "protocols"]
  },
  {
    "id": "py-p0-005",
    "domain": "python_core",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce qu'un générateur Python et pourquoi l'utiliser ?",
    "expected_concepts": ["yield", "lazy evaluation", "mémoire", "iterable", "generator expression"],
    "rubric": "La réponse doit distinguer générateur vs liste (lazy vs eager), expliquer yield, et mentionner l'avantage mémoire pour les grandes séquences.",
    "tags": ["generators", "memory", "iterables"]
  }
]
```

### `architecture/palier_0.json` — 5 questions

```json
[
  {
    "id": "arch-p0-001",
    "domain": "architecture",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce que le principe SOLID ? Liste les 5 principes.",
    "expected_concepts": ["Single Responsibility", "Open/Closed", "Liskov", "Interface Segregation", "Dependency Inversion"],
    "rubric": "La réponse doit nommer les 5 principes SOLID avec leur description courte. Au moins 3 doivent être expliqués avec un exemple ou une conséquence pratique.",
    "tags": ["SOLID", "OOP", "design-principles"]
  },
  {
    "id": "arch-p0-002",
    "domain": "architecture",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce que le pattern Singleton ? Quand l'utiliser ?",
    "expected_concepts": ["instance unique", "état global", "thread safety", "anti-pattern", "module Python"],
    "rubric": "La réponse doit décrire le pattern (une seule instance), mentionner les risques (état global, tests difficiles), et expliquer qu'en Python un module est déjà un singleton.",
    "tags": ["patterns", "singleton", "creational"]
  },
  {
    "id": "arch-p0-003",
    "domain": "architecture",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce que la séparation des responsabilités (SRP) ? Donne un exemple de violation.",
    "expected_concepts": ["Single Responsibility", "cohésion", "couplage", "raison de changer"],
    "rubric": "La réponse doit définir SRP (une classe = une raison de changer), donner un exemple concret de violation (ex: classe qui lit les données ET les affiche ET les sauvegarde).",
    "tags": ["SOLID", "SRP", "cohesion"]
  },
  {
    "id": "arch-p0-004",
    "domain": "architecture",
    "palier": 0,
    "difficulty": "easy",
    "question": "Quelle est la différence entre composition et héritage en POO ?",
    "expected_concepts": ["composition", "héritage", "couplage", "flexibilité", "has-a vs is-a"],
    "rubric": "La réponse doit distinguer 'est-un' (héritage) vs 'a-un' (composition), expliquer pourquoi 'favor composition over inheritance', et donner un exemple concret.",
    "tags": ["OOP", "composition", "inheritance"]
  },
  {
    "id": "arch-p0-005",
    "domain": "architecture",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce qu'une API REST ? Quels sont ses principes fondamentaux ?",
    "expected_concepts": ["stateless", "ressources", "HTTP verbes", "JSON", "idempotent"],
    "rubric": "La réponse doit mentionner : stateless, ressources identifiées par URL, utilisation des verbes HTTP (GET/POST/PUT/DELETE), format échange (JSON), et idempotence.",
    "tags": ["REST", "API", "HTTP"]
  }
]
```

### `debugging/palier_0.json` — 5 questions

```json
[
  {
    "id": "debug-p0-001",
    "domain": "debugging",
    "palier": 0,
    "difficulty": "easy",
    "question": "Comment lire un traceback Python ? Explique les éléments clés.",
    "expected_concepts": ["call stack", "ligne d'erreur", "exception type", "message", "most recent call last"],
    "rubric": "La réponse doit expliquer la structure d'un traceback : lecture de bas en haut, type d'exception, message, fichier + numéro de ligne, et la pile d'appels.",
    "tags": ["debugging", "traceback", "exceptions"]
  },
  {
    "id": "debug-p0-002",
    "domain": "debugging",
    "palier": 0,
    "difficulty": "easy",
    "question": "Quelle est la différence entre une exception et une erreur en Python ?",
    "expected_concepts": ["BaseException", "Exception", "Error", "SyntaxError", "RuntimeError", "hiérarchie"],
    "rubric": "La réponse doit expliquer la hiérarchie (BaseException → Exception), distinguer erreurs (SyntaxError, IndentationError) des exceptions runtime, et mentionner qu'on attrape généralement Exception.",
    "tags": ["exceptions", "error-handling", "basics"]
  },
  {
    "id": "debug-p0-003",
    "domain": "debugging",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce que pdb et comment l'utiliser pour déboguer du code Python ?",
    "expected_concepts": ["breakpoint()", "pdb.set_trace()", "n/s/c/q", "post-mortem", "inspection variables"],
    "rubric": "La réponse doit mentionner breakpoint() (Python 3.7+) ou pdb.set_trace(), les commandes de base (n=next, s=step, c=continue, q=quit), et comment inspecter les variables locales.",
    "tags": ["pdb", "debugging", "tools"]
  },
  {
    "id": "debug-p0-004",
    "domain": "debugging",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce qu'une NameError en Python ? Quelles en sont les causes courantes ?",
    "expected_concepts": ["variable non définie", "scope", "typo", "import manquant", "closure"],
    "rubric": "La réponse doit expliquer qu'une NameError indique un nom non défini dans le scope courant, lister les causes (typo, variable avant assignation, import oublié, scope incorrect).",
    "tags": ["exceptions", "NameError", "scope"]
  },
  {
    "id": "debug-p0-005",
    "domain": "debugging",
    "palier": 0,
    "difficulty": "easy",
    "question": "Comment utiliser le module logging en Python ? Quels sont les niveaux de log ?",
    "expected_concepts": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "basicConfig", "getLogger"],
    "rubric": "La réponse doit lister les 5 niveaux (DEBUG/INFO/WARNING/ERROR/CRITICAL), expliquer basicConfig pour la configuration de base, et montrer un exemple d'usage logging.getLogger(__name__).",
    "tags": ["logging", "debugging", "best-practices"]
  }
]
```

---

## 5. Tests attendus — `test_eval_05_benchgen.py` (~15 tests)

- `_validate_question` : champs requis présents → True
- `_validate_question` : champ manquant → False
- `_parse_llm_response` : JSON valide → liste dicts
- `_parse_llm_response` : JSON avec balises ```json → parse correct
- `_parse_llm_response` : JSON invalide → [] + log warning
- `_parse_llm_response` : liste partielle (1 valide / 1 invalide) → retourne juste le valide
- `_load_existing` : fichier absent → []
- `_load_existing` : fichier valide → liste BenchQuestion
- `generate()` LLM mocké → liste BenchQuestion (sans doublons avec existants)
- `generate()` déduplication : question identique dans existants → skippée
- `save()` fichier absent → créé avec les questions
- `save()` fichier existant → questions appendées (pas tronquées)
- `save()` JSON indenté + ensure_ascii=False
- `generate()` LLM retourne JSON vide → retourne []
- `_next_seq()` : max existant 3 → next = 4


============================================================
Fichier : SPEC-EVALLOOP-06-cli.md
============================================================

# SPEC EvalLoop — EVAL-06 : CLI lcca_eval.py + Rapport
**Version** : 1.0
**Date** : 2026-04-23
**Statut** : DRAFT
**Dépendances** : EVAL-02, EVAL-03, EVAL-04, EVAL-05

---

## 1. Objectif du sprint

Implémenter le **CLI `lcca_eval.py`** (racine projet) et le **rapport de session Markdown**.

Le CLI est le seul point d'entrée pour tout EvalLoop. Il orchestre les engines
dans l'ordre correct et expose les 6 commandes principales.

---

## 2. Fichiers créés

| Fichier | Rôle |
|---|---|
| `lcca_eval.py` | CLI racine EvalLoop |
| `EvalLoop/engines/session_reporter.py` | Générateur de session_report.md |

---

## 3. Interface CLI

```bash
# 1. Générer / enrichir les benchmarks pour un domaine
python lcca_eval.py gen-bench --domain python_core --palier 0 --count 5

# 2. Probe : soumettre les questions du palier courant à LLCA
python lcca_eval.py probe --domain python_core --session 2026-04-23

# 3. Judge : scorer les réponses via Claude
python lcca_eval.py judge --session 2026-04-23 --judge claude

# 4. Distill : injecter les meilleures réponses dans SkillLibrary
python lcca_eval.py distill --session 2026-04-23 --min-score 0.75

# 5. Rapport de session
python lcca_eval.py report --session 2026-04-23

# 6. Statut curriculum (paliers courants par domaine)
python lcca_eval.py status
```

---

## 4. Sous-commandes détaillées

### `gen-bench`

```
Arguments :
  --domain DOMAIN     Domaine cible (python_core|architecture|...)
  --palier N          Palier à enrichir (défaut : palier courant du domaine)
  --count N           Nombre de questions à générer (défaut : 5)

Sortie :
  [GEN] python_core palier 0 — 5 questions générées → benchmarks/python_core/palier_0.json
  [GEN] Doublons ignorés : 0
  [GEN] Total questions fichier : 10
```

### `probe`

```
Arguments :
  --domain DOMAIN     Domaine cible (ou "all" pour tous les domaines actifs)
  --session LABEL     Label session (YYYY-MM-DD ou YYYY-MM-DD_HH-MM)
                      Si absent : généré automatiquement (datetime now)
  --questions N       Nombre de questions par domaine (défaut : config questions_per_palier)

Sortie :
  [PROBE] Session : sessions/2026-04-23_21-00/
  [PROBE] Domaine : python_core | Palier : 0 | 5 questions
  [PROBE] py-p0-001 ✓ (4230 ms)
  [PROBE] py-p0-002 ✓ (3810 ms)
  ...
  [PROBE] Terminé — 5/5 réponses | responses.jsonl écrit
```

### `judge`

```
Arguments :
  --session LABEL     Label session (ou "latest" pour la dernière session)
  --judge JUDGE       Juge à utiliser : "claude" | "all" (défaut : config active)

Sortie :
  [JUDGE] Session : sessions/2026-04-23_21-00/
  [JUDGE] Juge : claude-sonnet-4-6
  [JUDGE] py-p0-001 → score 0.82 (inject: ✓)
  [JUDGE] py-p0-002 → score 0.61 (inject: ✗ score < 0.75)
  ...
  [JUDGE] Terminé — 5/5 scorés | scores.jsonl écrit
  [JUDGE] Score moyen palier 0 : 0.71 (seuil unlock : 0.70) → PALIER 1 DÉBLOQUÉ ✓
```

### `distill`

```
Arguments :
  --session LABEL     Label session
  --min-score FLOAT   Override seuil d'injection (défaut : config 0.75)

Sortie :
  [DISTILL] Session : sessions/2026-04-23_21-00/
  [DISTILL] py-p0-001 → INJECTÉ (score 0.82)
  [DISTILL] py-p0-002 → SKIP (score 0.61 < 0.75)
  [DISTILL] py-p0-003 → SKIP (doublon détecté)
  ...
  [DISTILL] Terminé — 3 skills injectés / 5 évalués
```

### `report`

```
Arguments :
  --session LABEL     Label session

Sortie : génère sessions/{label}/session_report.md et l'affiche
```

### `status`

```
Sortie :
  [STATUS] Curriculum EvalLoop — état actuel
  ┌─────────────────┬────────┬──────────────┬─────────────────┐
  │ Domaine         │ Palier │ Score actuel │ Prochain seuil  │
  ├─────────────────┼────────┼──────────────┼─────────────────┤
  │ python_core     │   2    │    0.82      │ 0.70 (palier 3) │
  │ architecture    │   0    │    —         │ 0.70 (palier 1) │
  │ debugging       │   0    │    —         │ 0.70 (palier 1) │
  │ algorithms      │   0    │    —         │ 0.70 (palier 1) │
  │ refactoring     │   0    │    —         │ 0.70 (palier 1) │
  │ llca_meta       │   0    │    —         │ 0.70 (palier 1) │
  └─────────────────┴────────┴──────────────┴─────────────────┘
```

---

## 5. `session_reporter.py`

### Format `session_report.md`

```markdown
# Rapport EvalLoop — Session 2026-04-23_21-00

**Date** : 2026-04-23 21:00:00
**Domaine** : python_core | **Palier** : 0
**Modèle LLCA** : qwen2.5-coder:3b
**Juge** : claude-sonnet-4-6

---

## Résumé

| Métrique | Valeur |
|---|---|
| Questions posées | 5 |
| Réponses obtenues | 5 |
| Score moyen | 0.72 |
| Score min | 0.55 |
| Score max | 0.88 |
| Skills injectés | 3 |
| Durée probe totale | 21.4s |
| Palier débloqué | ✓ Palier 1 débloqué |

---

## Détail par question

### py-p0-001 — Score : 0.88 ✓ INJECTÉ

**Question** : Qu'est-ce que le GIL en Python ? ...

**Forces** :
- Définition correcte du GIL
- Distinction I/O vs CPU-bound claire

**Faiblesses** :
- Pas de mention de multiprocessing comme alternative

**Durée réponse LLCA** : 4230 ms

---

### py-p0-002 — Score : 0.61 ✗ SKIP

...

---

## Progression Curriculum

python_core palier 0 → score moyen 0.72 ≥ 0.70 → **Palier 1 débloqué** ✓
```

### Interface publique

```python
class SessionReporter:
    def __init__(self, session_dir: Path):
        ...

    def generate(
        self,
        responses: list[ProbeResponse],
        scores: list[JudgeScore],
        distilled: list[DistilledSkill],
        palier_unlocked: bool,
        palier_current: int,
    ) -> Path:
        """Génère session_report.md dans session_dir. Retourne le chemin."""
```

---

## 6. Résolution de session par label

```
"2026-04-23"        → sessions/2026-04-23_*/ (première trouvée, tri alpha)
"2026-04-23_21-00"  → sessions/2026-04-23_21-00/ (exact)
"latest"            → sessions/ dernier dossier (tri alpha décroissant)
```

Si le dossier de session n'existe pas → erreur explicite + exit(1).

---

## 7. Règles CLI

- `argparse` stdlib uniquement (pas de click, typer)
- Exit code 0 = succès, 1 = erreur (fichier manquant, API indispo), 2 = usage incorrect
- Toutes les sorties sur `sys.stdout` sauf erreurs fatales (`sys.stderr`)
- `--help` sur chaque sous-commande (argparse natif)
- Import tardif des engines (évite import circulaire au démarrage)
- `lcca_eval.py` autonome : `sys.path.insert(0, str(Path(__file__).parent))` pour import EvalLoop

---

## 8. Tests attendus — `test_eval_06_cli.py` (~15 tests)

- `gen-bench` : args parsés + BenchGenerator appelé + sortie console correcte
- `probe` : session créée automatiquement si absent
- `probe` : `--domain all` → tous les domaines actifs config
- `judge` : `--session latest` → dernier dossier session
- `judge` : juge indisponible → exit code 1 + message explicite
- `distill` : `--min-score` override correct
- `report` : session_report.md généré
- `status` : tableau curriculum affiché
- Session resolve : "2026-04-23" → premier dossier correspondant
- Session resolve : "latest" → dernier dossier
- Session resolve : inexistante → exit 1 + message
- `SessionReporter.generate()` : frontmatter correct, toutes les sections présentes
- `SessionReporter.generate()` : palier_unlocked=True → message unlock dans rapport
- `SessionReporter.generate()` : 0 scores → rapport partiel (probe only)
- Import tardif engines : `import lcca_eval` ne plante pas si Ollama absent


============================================================
Fichier : SPEC-EVALLOOP-07-tests.md
============================================================

# SPEC EvalLoop — EVAL-07 : Tests complets (~80 tests)
**Version** : 1.0
**Date** : 2026-04-23
**Statut** : DRAFT
**Dépendances** : EVAL-01 à EVAL-06

---

## 1. Objectif du sprint

Finaliser la couverture de tests EvalLoop. Ce sprint consolide tous les tests
des sprints précédents et ajoute les tests d'intégration manquants.

Cible : **≥ 80 tests** répartis sur 7 fichiers.

---

## 2. Répartition des fichiers de tests

| Fichier | Tests | Couverture |
|---|---|---|
| `tests/test_eval_01_types.py` | ~20 | Dataclasses + round-trips |
| `tests/test_eval_02_probe.py` | ~18 | CurriculumTracker + ProbeEngine |
| `tests/test_eval_03_judge.py` | ~20 | JudgeBase + JudgeClaude + JudgeEngine |
| `tests/test_eval_04_distill.py` | ~18 | DistillEngine + formatage + dédup |
| `tests/test_eval_05_benchgen.py` | ~15 | BenchGenerator + benchmarks JSON |
| `tests/test_eval_06_cli.py` | ~15 | CLI lcca_eval.py + SessionReporter |
| `tests/test_eval_integration.py` | ~10 | Intégration bout-en-bout |

**Total estimé : 116 tests** (les specs EVAL-01 à EVAL-06 définissent déjà ~106 tests unitaires).

---

## 3. `test_eval_integration.py` — Tests bout-en-bout

Ces tests simulent un cycle complet probe → judge → distill sur `tmp_path`.
Tous les appels réseaux (Ollama + Anthropic) sont mockés.

### Tests d'intégration

```python
# INT-01 : Cycle complet (probe → judge → distill) sur domaine python_core palier 0
def test_full_cycle_probe_judge_distill(tmp_path):
    """
    Setup :
      - eval_config.toml dans tmp_path (questions_per_palier=2)
      - 2 questions palier_0.json dans tmp benchmarks
      - Mock Ollama (2 réponses)
      - Mock Anthropic API (2 scores : 0.85 + 0.62)
    Assertions :
      - responses.jsonl créé avec 2 entrées
      - scores.jsonl créé avec 2 entrées
      - 1 skill injecté (score 0.85 >= 0.75)
      - 1 skill skippé (score 0.62 < 0.75)
      - eval_state.json mis à jour (python_core palier_scores[0] = 0.735)
      - Palier 0 score moyen 0.735 >= 0.70 → palier 1 débloqué dans eval_state.json
    """

# INT-02 : Reprise de session interrompue
def test_session_resume(tmp_path):
    """
    Setup : responses.jsonl pré-rempli avec 1 réponse sur 2
    Assertion : ProbeEngine skip la question déjà présente, probe uniquement la 2ème
    """

# INT-03 : Mode dégradé — Juge indisponible
def test_judge_unavailable_graceful_degradation(tmp_path):
    """
    Setup : ANTHROPIC_API_KEY absent de os.environ
    Assertion :
      - judge.run() retourne [] sans exception
      - scores.jsonl non créé
      - distill.run() avec scores vides → 0 injection, 0 exception
    """

# INT-04 : Curriculum — unlock palier
def test_curriculum_unlock_progression(tmp_path):
    """
    Setup : 5 scores palier 0 ≥ 0.70 (score moyen 0.80)
    Assertion :
      - current_palier python_core = 1 après record_palier_scores
      - eval_state.json persisté avec unlocked_at[1] défini
    """

# INT-05 : Curriculum — no unlock si score insuffisant
def test_curriculum_no_unlock_low_score(tmp_path):
    """
    Setup : 5 scores palier 0, score moyen 0.60
    Assertion : current_palier reste 0
    """

# INT-06 : Gen-bench → Probe → Judge → Distill (pipeline LLM complet mocké)
def test_full_pipeline_with_gen_bench(tmp_path):
    """
    Setup : aucun fichier bench existant
    Actions :
      1. BenchGenerator.generate() (LLM mocké) → crée palier_0.json avec 3 questions
      2. ProbeEngine.run() (Ollama mocké) → responses.jsonl
      3. JudgeEngine.run() (Claude mocké) → scores.jsonl
      4. DistillEngine.run() → injection SkillLibrary
    Assertion : pipeline complet sans exception + skills injectés
    """

# INT-07 : Écriture atomique eval_state.json (T-14)
def test_eval_state_atomic_write(tmp_path):
    """
    Assertion : après save_state(), aucun fichier .tmp traîne dans le dossier
    """

# INT-08 : Sessions JSONL — append correct
def test_jsonl_append_is_valid_ndjson(tmp_path):
    """
    Assertion : chaque ligne de responses.jsonl et scores.jsonl est un JSON valide
    """

# INT-09 : Frontmatter distillé contient les champs obligatoires
def test_distilled_skill_frontmatter_complete(tmp_path):
    """
    Assertion : skill distillé contient source, domain, palier, score, judge, date, tags
    """

# INT-10 : source_type="evalloop" dans les skills injectés
def test_distilled_skill_source_type_evalloop(tmp_path):
    """
    Mock SkillLibrary.add_skill() et vérifier que source_type="evalloop" est passé
    """
```

---

## 4. Conventions de test EvalLoop

### Fixture commune `_make_eval_config(tmp_path)`

```python
def _make_eval_config(tmp_path: Path) -> dict:
    """Crée une config EvalLoop minimale pour les tests.
    Ne dépend pas de eval_config.toml réel (chemins absolus Windows)."""
    return {
        "general": {
            "evalloop_dir": str(tmp_path),
            "sessions_dir": str(tmp_path / "sessions"),
            "benchmarks_dir": str(tmp_path / "benchmarks"),
        },
        "llca": {
            "ollama_base_url": "http://localhost:11434",
            "model": "qwen2.5-coder:3b",
            "timeout": None,
            "max_tokens": 1500,
        },
        "judges": {
            "active": ["claude"],
            "consensus_mode": False,
            "claude_model": "claude-sonnet-4-6",
        },
        "scoring": {
            "min_inject_score": 0.75,
            "seuil_unlock": 0.70,
            "max_palier": 5,
        },
        "curriculum": {
            "domains": ["python_core"],
        },
        "domains": {
            "python_core": {
                "description": "Test domain",
                "questions_per_palier": 5,
            }
        },
    }
```

### Règles de test EvalLoop

1. **Jamais d'appel réseau réel** dans les tests (conftest.py autouse bloque urlopen)
2. **`tmp_path` pour toutes les I/O** — jamais de chemins `D:\LLMCodeAgent\EvalLoop\` réels
3. **Mock Ollama** : même pattern que ProbeEngine (lignes NDJSON)
4. **Mock Anthropic API** : retourner un JSON valide avec score, strengths, weaknesses, improved_answer
5. **`import pytest`** inclus même si non utilisé directement (convention LCCA tests)
6. **Déduplication** testée sur `tmp_path` — créer manuellement un fichier .md avec `<!-- dedup:HASH -->` pour tester `_is_duplicate`
7. **EvalLoop imports** : `sys.path.insert(0, str(Path(__file__).parent.parent / "EvalLoop"))` dans les fichiers de test ou dans conftest

### Mock Ollama pour ProbeEngine

```python
import json
from unittest.mock import patch, MagicMock

def _make_ollama_mock(response_text: str):
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps({
        "response": response_text,
        "done": True,
        "model": "qwen2.5-coder:3b",
    }).encode("utf-8")
    return mock_resp
```

### Mock Anthropic API pour JudgeClaude

```python
def _make_claude_mock(score: float, inject: bool = True):
    payload = {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "score": score,
                "strengths": ["Réponse claire"],
                "weaknesses": [] if score > 0.7 else ["Incomplet"],
                "improved_answer": "# Réponse améliorée\n\nContenu de test.",
                "inject_recommended": inject,
            })
        }]
    }
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
    mock_resp.status = 200
    return mock_resp
```

---

## 5. Checklist de validation EVAL-07

Avant de déclarer EVAL-07 TERMINÉ :

```
[ ] test_eval_01_types.py     : 20 tests PASSED
[ ] test_eval_02_probe.py     : 18 tests PASSED
[ ] test_eval_03_judge.py     : 20 tests PASSED
[ ] test_eval_04_distill.py   : 18 tests PASSED
[ ] test_eval_05_benchgen.py  : 15 tests PASSED
[ ] test_eval_06_cli.py       : 15 tests PASSED
[ ] test_eval_integration.py  : 10 tests PASSED
[ ] 0 test réseau réel (conftest.py vérifié)
[ ] 0 chemin D:\LLMCodeAgent hardcodé dans les tests
[ ] pytest complet (régression globale) : 0 test cassé
```

---

## 6. Ajout au compteur global LCCA

À la fin de EVAL-07, mettre à jour `002-context.md` :

```
EVAL-01 types        : +20 tests
EVAL-02 probe        : +18 tests
EVAL-03 judge        : +20 tests
EVAL-04 distill      : +18 tests
EVAL-05 benchgen     : +15 tests
EVAL-06 CLI          : +15 tests
EVAL-07 intégration  : +10 tests
─────────────────────────────────
EvalLoop total       : +116 tests
```

Nouveau total global : 1463 + 116 = **1579 tests**.
