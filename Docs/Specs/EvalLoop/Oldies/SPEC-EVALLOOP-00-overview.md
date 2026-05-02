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
