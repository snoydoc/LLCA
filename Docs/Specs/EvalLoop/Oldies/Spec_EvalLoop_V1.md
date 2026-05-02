# SPEC EvalLoop V1 — Système d'Auto-Évaluation Curriculum LCCA
**Version** : 1.0  
**Date** : 2026-04-24  
**Auteur** : Claude Desktop (révision post-analyse code réel)  
**Statut** : VALIDÉ — Prêt pour implémentation EVAL-01  
**Remplace** : Spec_EvalLoop_ClaudeV0.md (V0) + Addendum-Spec_EvalLoopV0.MD

---

## PRÉAMBULE — Ce qui a changé entre V0 et V1

### Constats après lecture du code réel

1. **`SkillLibrary`** (`core/skill_library.py`) **n'a pas de méthode `add_skill()`**.  
   L'interface réelle est `extract_and_store(code, receipt, source_intent, quality_score)`.  
   Elle nécessite un `ExecutionReceipt` signé par HMAC.  
   → EvalLoop ne peut pas injecter directement via `SkillLibrary`. Voir section 5.

2. **`qwen2.5-coder:3b` est le seul moteur conversationnel** (`OLLAMA_MODEL = "qwen2.5-coder:3b"`).  
   C'est intentionnel : le 3b tient en full-VRAM (2.0 GB sur Quadro M2000M 4 GB).  
   Le 7b déborde en CPU (-63% vitesse). Le modèle n'est pas "défaillant" —  
   il n'est pas destiné à générer du code de production ; il est le moteur de dialogue.  
   → Pas besoin de découpler `probe_model`. Le probe évalue le modèle conversationnel tel qu'il est.

3. **Il n'existe pas de juge local "critique" disponible** sur ce hardware.  
   Un modèle 7B en CPU ferait ~4 tok/s pour scorer. Inacceptable.  
   → Le juge local est un **auto-scorer basé sur les `expected_concepts`** (regex/matching),  
   pas un LLM. Claude reste le seul juge LLM, en mode optionnel.

4. **`OLLAMA_TIMEOUT = None`** est un invariant absolu du projet.  
   Cette règle s'applique à tous les appels Ollama sans exception.

5. **Le projet est 100% offline/local** sauf pour l'Educator (GitHub) et le juge Claude (optionnel).  
   EvalLoop respecte cette contrainte : tout fonctionne sans API externe.

6. **`SkillEntry`** a `source_type` et `commit_hash` mais pas de champ `source_type="evalloop"`.  
   L'injection EvalLoop se fera dans `lcca_context` via `MemoryEngine.store()` directement,  
   avec un namespace dédié `evalloop_skills`.

---

## 1. Contexte & Motivation

LCCA dispose de deux sources d'apprentissage :

| Source | Mécanisme | Type de connaissance |
|---|---|---|
| EducatorAgent | Lecture repos GitHub | Patterns syntaxiques, APIs, idiomes |
| **EvalLoop** | Questions/réponses curriculum | Raisonnement, architecture, debugging |

EvalLoop fonctionne comme un **curriculum scolaire** : LCCA (qwen2.5-coder:3b via Ollama) répond à des questions de niveau croissant, un système de scoring analyse les réponses, les meilleures réponses améliorées sont stockées dans la mémoire LCCA.

**Principe clé** : on n'injecte jamais la réponse brute de LCCA — on injecte la réponse corrigée/complétée. LCCA apprend de l'écart entre ce qu'il a dit et ce qu'il aurait dû dire.

---

## 2. Paliers de Complexité

```
Palier 0 : Fondations — définitions, vocabulaire, concepts isolés
Palier 1 : Compréhension — "pourquoi", comparaisons simples
Palier 2 : Application — cas d'usage concrets, implémentations simples
Palier 3 : Analyse — détecter des problèmes, expliquer des comportements
Palier 4 : Synthèse — concevoir une solution à un problème ouvert
Palier 5 : Expert — edge cases, performance, compromis architecturaux
```

**Règles curriculum** :
- Session démarre au palier 0 pour un domaine jamais testé
- Palier suivant débloqué si score moyen du palier courant ≥ `seuil_unlock` (défaut 0.70)
- Domaine échouant au palier 0 → génération automatique de questions supplémentaires palier 0
- Palier courant persisté dans `eval_state.json` (écriture atomique T-14)

---

## 3. Architecture des Composants

```
EvalLoop/
├── eval_config.toml              # Configuration globale
├── eval_state.json               # Palier courant par domaine
├── lcca_eval.py                  # CLI point d'entrée (à la racine D:\LLMCodeAgent\)
│
├── benchmarks/                   # Questions par domaine + palier
│   ├── python_core/
│   │   ├── palier_0.json         # Écrites à la main (contrôle qualité)
│   │   ├── palier_1.json         # Écrites à la main
│   │   └── palier_2.json         # Peut être généré par LLM, statut "draft"
│   ├── architecture/
│   ├── refactoring/
│   ├── debugging/
│   ├── algorithms/
│   └── lcca_meta/
│
├── sessions/
│   └── YYYY-MM-DD_HH-MM/
│       ├── responses.jsonl       # Réponses brutes LCCA (append-only)
│       ├── scores.jsonl          # Scores + réponses améliorées (append-only)
│       └── session_report.md     # Rapport lisible
│
├── engines/
│   ├── probe_engine.py           # Soumet questions → LCCA via Ollama
│   ├── judge_engine.py           # Orchestre les juges
│   ├── distill_engine.py         # Sélectionne + stocke dans MemoryEngine
│   ├── bench_generator.py        # Génère nouvelles questions via LLM (paliers 2+)
│   └── curriculum_tracker.py    # Gère paliers, unlock, état persisté
│
└── judges/
    ├── judge_base.py             # ABC commun
    ├── judge_local.py            # Juge local : matching expected_concepts (défaut V1)
    └── judge_claude.py           # Juge Claude API (optionnel, --judge claude)
```

---

## 4. Flux de Données

```
PHASE 1 — PROBE
  curriculum_tracker  → sélectionne palier courant
  benchmarks/{domain}/palier_{N}.json → questions
  probe_engine        → soumet à LCCA via Ollama (timeout=None)
                      → responses.jsonl (append ligne par ligne)

PHASE 2 — JUDGE
  judge_engine        → charge responses.jsonl
  JudgeLocal          → score automatique par expected_concepts matching (défaut)
  JudgeClaude         → score + improved_answer via API Anthropic (optionnel)
                      → scores.jsonl (append ligne par ligne)
  curriculum_tracker  → calcule score moyen palier
                      → unlock palier suivant si ≥ seuil
                      → met à jour eval_state.json (atomique)

PHASE 3 — DISTILL
  distill_engine      → filtre scores ≥ min_inject_score
                      → formate en .md LCCA avec frontmatter
                      → déduplique sha256[:16]
                      → stocke via MemoryEngine.store("evalloop_skills", ...)
```

---

## 5. Injection Mémoire — Interface Réelle

**La `SkillLibrary` nécessite un `ExecutionReceipt` HMAC signé.**  
EvalLoop ne génère pas de receipts, donc il **contourne `SkillLibrary`** et injecte directement via `MemoryEngine` dans une collection dédiée.

```python
from core.memory_engine import MemoryEngine

mem = MemoryEngine()
mem.store("evalloop_skills", {
    "content":     skill_md,          # improved_answer formaté en Markdown
    "source":      "evalloop",
    "question_id": score.question_id,
    "domain":      score.domain,
    "palier":      score.palier,
    "score":       score.score,
    "judge":       score.judge,
    "session":     session_name,
    "dedup_hash":  sha256_content[:16],
})
```

Cette collection `evalloop_skills` est distincte de `lcca_skills` (SkillLibrary) et de `lcca_context` (mémoire générale). Elle peut être recherchée via `MemoryEngine.search()`.

---

## 6. Juges — Architecture Révisée

### Juge par défaut : `JudgeLocal` (100% offline)

Scoring basé sur la correspondance entre la réponse LCCA et les `expected_concepts` de la question.

```
score = (concepts_trouvés / total_concepts_attendus) * 0.8 + bonus_longueur * 0.2
```

- `concepts_trouvés` : nombre de `expected_concepts` présents dans la réponse (insensible à la casse)
- `bonus_longueur` : 1.0 si réponse > 100 mots, 0.5 si 50-100 mots, 0.0 si < 50 mots
- `improved_answer` en mode local : template structuré généré à partir du `rubric` + `expected_concepts`
- `inject_recommended` : True si score ≥ 0.60

Ce juge est **rapide** (< 1ms), **déterministe**, **100% offline**.  
Il évalue si LCCA "couvre" les concepts attendus, pas la qualité rédactionnelle.

### Juge optionnel : `JudgeClaude` (API externe)

Activé avec `--judge claude`. Nécessite `ANTHROPIC_API_KEY` dans `os.environ`.

- Score subjectif 0.0-1.0 avec forces/faiblesses détaillées
- `improved_answer` rédigée en Markdown par Claude (200-600 mots)
- `timeout = 30` (appel API externe — contrairement à Ollama timeout=None)
- Mode dégradé si API indisponible → JudgeScore score=0.0, inject=False

### Configuration juges

```toml
[judges]
default = "local"           # "local" = JudgeLocal (défaut V1)
active = ["local"]          # ["local", "claude"] pour cross-validation
consensus_mode = false
claude_model = "claude-sonnet-4-6"
```

---

## 7. Sprints EvalLoop V1

| Sprint | Fichiers | Contenu | Dépendances |
|---|---|---|---|
| EVAL-01 | `evalloop_types.py` + configs | Dataclasses + eval_config.toml + eval_state.json | — |
| EVAL-02 | `curriculum_tracker.py` + `probe_engine.py` | Paliers + probe Ollama → responses.jsonl | EVAL-01 |
| EVAL-03 | `judge_base.py` + `judge_local.py` + `judge_claude.py` + `judge_engine.py` | Scoring local + Claude optionnel → scores.jsonl | EVAL-01 |
| EVAL-04 | `distill_engine.py` | Sélection + injection MemoryEngine `evalloop_skills` | EVAL-01, EVAL-03 |
| EVAL-05 | `bench_generator.py` + benchmarks initiaux | Génération questions + 9 fichiers JSON initiaux | EVAL-01 |
| EVAL-06 | `lcca_eval.py` + `session_reporter.py` | CLI + rapport Markdown | EVAL-02..05 |
| EVAL-07 | `tests/test_eval_*.py` | ~80 tests, 0 appel réseau réel | EVAL-01..06 |

---

## 8. Invariants & Règles

- `probe_engine` : `timeout=None` sur urlopen (règle LCCA absolue)
- `urllib.request` stdlib uniquement — jamais `requests`
- `eval_state.json` : écriture atomique `.tmp → Path.replace()` (règle T-14)
- Sessions immuables : `responses.jsonl` et `scores.jsonl` jamais modifiés après écriture
- `auto_push = false` invariant — EvalLoop ne fait jamais de git push
- Déduplication sha256[:16] obligatoire avant injection (même pattern Educator)
- Questions palier 0/1 écrites à la main uniquement (contrôle qualité humain)
- Questions générées par LLM (palier 2+) : statut `"status": "draft"` jusqu'à revue humaine
- Mode dégradé si Claude API absent : JudgeLocal toujours disponible, 0 exception propagée
- `lcca_eval.py` : `sys.path.insert` pour import `EvalLoop.*` (autonomie du module)

---

---
# EVAL-01 : Dataclasses + Config + État
---

## Objectif EVAL-01

Poser les fondations de données. Zéro appel LLM. Zéro I/O sauf lecture config.

## Fichiers créés

| Fichier | Rôle |
|---|---|
| `EvalLoop/evalloop_types.py` | Dataclasses centrales |
| `EvalLoop/eval_config.toml` | Configuration globale |
| `EvalLoop/eval_state.json` | État paliers (initialement `{}`) |

## Dataclasses — `evalloop_types.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BenchQuestion:
    id: str                          # "py-p0-001"
    domain: str                      # "python_core" | "architecture" | ...
    palier: int                      # 0 = fondations, 5 = expert
    difficulty: str                  # "easy" | "medium" | "hard" | "expert"
    question: str
    expected_concepts: list[str]     # Concepts clés attendus
    rubric: str                      # Critères d'évaluation
    tags: list[str] = field(default_factory=list)
    status: str = "active"           # "active" | "draft" (généré par LLM, non revu)

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> "BenchQuestion": ...


@dataclass
class ProbeResponse:
    question_id: str
    model: str                       # "qwen2.5-coder:3b"
    response: str
    duration_ms: int
    timestamp: str                   # ISO 8601
    domain: str = ""
    palier: int = 0

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> "ProbeResponse": ...


@dataclass
class JudgeScore:
    question_id: str
    judge: str                       # "local" | "claude-sonnet-4-6"
    score: float                     # 0.0 → 1.0
    strengths: list[str]
    weaknesses: list[str]
    improved_answer: str             # Réponse corrigée/complétée
    inject_recommended: bool
    domain: str = ""
    palier: int = 0
    sub_scores: dict[str, float] = field(default_factory=dict)
    # sub_scores exemples : {"concept_coverage": 0.8, "length_bonus": 0.5}

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> "JudgeScore": ...


@dataclass
class DistilledSkill:
    source_question_id: str
    content: str                     # Markdown complet
    score: float
    domain: str
    palier: int
    judge: str
    injected_at: str                 # ISO 8601
    dedup_hash: str                  # sha256[:16] du contenu

    def to_dict(self) -> dict: ...


@dataclass
class PalierState:
    domain: str
    current_palier: int = 0
    palier_scores: dict[int, float] = field(default_factory=dict)
    unlocked_at: dict[int, str] = field(default_factory=dict)

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> "PalierState": ...
```

**Différences V0 → V1** :
- `BenchQuestion.status` ajouté : `"active"` | `"draft"` (questions LLM non revues)
- `JudgeScore.sub_scores` ajouté : granularité optionnelle pour le scoring local
- `DistilledSkill.dedup_hash` ajouté directement (évite recalcul)

## `eval_config.toml`

```toml
[general]
project_root   = "D:\\LLMCodeAgent"
evalloop_dir   = "D:\\LLMCodeAgent\\EvalLoop"
sessions_dir   = "D:\\LLMCodeAgent\\EvalLoop\\sessions"
benchmarks_dir = "D:\\LLMCodeAgent\\EvalLoop\\benchmarks"

[llca]
ollama_base_url = "http://localhost:11434"
model           = "qwen2.5-coder:3b"
timeout         = null         # Invariant absolu LCCA : OLLAMA_TIMEOUT = None
max_tokens      = 1500

[judges]
default         = "local"      # JudgeLocal par défaut (100% offline)
active          = ["local"]    # Ajouter "claude" pour cross-validation
consensus_mode  = false
claude_model    = "claude-sonnet-4-6"

[scoring]
min_inject_score = 0.70        # Seuil injection MemoryEngine (local moins précis → 0.70)
seuil_unlock     = 0.70        # Score moyen palier requis pour unlock palier+1
max_palier       = 5
max_skill_tokens = 600         # Limite taille improved_answer (en mots)

[curriculum]
domains = [
    "python_core",
    "architecture",
    "refactoring",
    "debugging",
    "algorithms",
    "lcca_meta",
]

[domains.python_core]
description          = "Fondamentaux Python : OOP, GC, typing, async"
questions_per_palier = 5

[domains.architecture]
description          = "Design patterns, SOLID, découpage système"
questions_per_palier = 5

[domains.refactoring]
description          = "Identifier et corriger la dette technique"
questions_per_palier = 5

[domains.debugging]
description          = "Lire un traceback, diagnostiquer, corriger"
questions_per_palier = 5

[domains.algorithms]
description          = "Complexité, structures de données, algorithmes"
questions_per_palier = 5

[domains.lcca_meta]
description          = "Questions sur LCCA lui-même et ses propres règles"
questions_per_palier = 3
```

**Différences V0 → V1** :
- `judges.default = "local"` (non `"claude"`)
- `scoring.min_inject_score = 0.70` (non `0.75` — JudgeLocal moins précis, seuil adapté)
- `scoring.max_skill_tokens = 600` ajouté (limite taille improved_answer)
- `llca.timeout = null` commenté explicitement (invariant)

## Tests attendus — `test_eval_01_types.py` (~22 tests)

Identiques à V0, plus :
- `BenchQuestion.status` : défaut "active"
- `BenchQuestion.from_dict` : status="draft" préservé
- `JudgeScore.sub_scores` : défaut `{}`, round-trip to_dict/from_dict
- `DistilledSkill.dedup_hash` : champ présent dans to_dict()

---
---
# EVAL-02 : ProbeEngine + CurriculumTracker
---

## Objectif EVAL-02

Implémenter la **Phase 1 — PROBE**.

## Fichiers créés

| Fichier | Rôle |
|---|---|
| `EvalLoop/engines/curriculum_tracker.py` | Paliers + unlock + eval_state.json |
| `EvalLoop/engines/probe_engine.py` | Questions → LCCA → responses.jsonl |

## `curriculum_tracker.py`

Interface publique **identique à V0** — voir V0 pour les détails.

Règles supplémentaires V1 :
- `get_questions_for_session` : filtre `status == "active"` — skip les questions "draft"
- Si toutes les questions d'un palier sont en "draft" → log warning + retourne []

## `probe_engine.py`

**Prompt système V1** (remplacement du prompt V0) :

```
SYSTEM:
Tu es un assistant expert en développement Python et en architecture logicielle.
Réponds de manière précise, structurée, avec des exemples concrets quand pertinent.
Domaine évalué : {domain} | Niveau : palier {palier}
Réponds en français.

USER:
{question.question}
```

Justification : le prompt V0 mentionnait "Tu es LCCA" ce qui est incorrect (LCCA est le système, pas l'identité du modèle). Le modèle répond mieux sans auto-référence.

Appel Ollama `/api/generate` :
```python
payload = {
    "model":      config["llca"]["model"],
    "prompt":     prompt,
    "stream":     False,           # stream=False pour simplicité probe (pas de streaming UI)
    "options": {
        "num_predict": config["llca"]["max_tokens"],
    }
}
# timeout = None (invariant absolu)
```

Toutes les autres règles V0 maintenues (append JSONL, reprise session, OSError propagée).

## Tests attendus — `test_eval_02_probe.py` (~20 tests)

Identiques à V0, plus :
- `get_questions_for_session` : questions "draft" filtrées
- `get_questions_for_session` : toutes "draft" → retourne [] + log warning
- `_build_prompt` : ne contient pas "Tu es LCCA"
- `_build_prompt` : contient domain et palier

---
---
# EVAL-03 : JudgeBase + JudgeLocal + JudgeClaude + JudgeEngine
---

## Objectif EVAL-03

Implémenter la **Phase 2 — JUDGE**.

## Fichiers créés

| Fichier | Rôle |
|---|---|
| `EvalLoop/judges/judge_base.py` | ABC commun |
| `EvalLoop/judges/judge_local.py` | Juge local matching (défaut V1) |
| `EvalLoop/judges/judge_claude.py` | Juge Claude API (optionnel) |
| `EvalLoop/engines/judge_engine.py` | Orchestre les juges → scores.jsonl |

## `judge_base.py`

Identique à V0 — ABC avec `judge_id`, `score()`, `is_available()`.

## `judge_local.py` (NOUVEAU V1 — remplace `judge_openai.py` stub)

```python
class JudgeLocal(JudgeBase):
    """
    Juge 100% offline basé sur le matching des expected_concepts.
    
    Algorithme de scoring :
      concept_score = len(concepts_trouvés) / len(expected_concepts)
      length_score  = 1.0 si nb_mots > 100 | 0.5 si 50-100 | 0.0 si < 50
      score         = concept_score * 0.8 + length_score * 0.2
      
    improved_answer : généré depuis rubric + expected_concepts (template structuré).
    inject_recommended : True si score >= 0.60
    """
    
    @property
    def judge_id(self) -> str:
        return "local"
    
    def score(self, question: BenchQuestion, response: ProbeResponse) -> JudgeScore:
        concepts_found = self._find_concepts(response.response, question.expected_concepts)
        concept_score  = len(concepts_found) / len(question.expected_concepts) if question.expected_concepts else 0.0
        length_score   = self._length_score(response.response)
        total_score    = round(concept_score * 0.8 + length_score * 0.2, 3)
        
        missing = [c for c in question.expected_concepts if c not in concepts_found]
        
        return JudgeScore(
            question_id       = response.question_id,
            judge             = self.judge_id,
            score             = total_score,
            strengths         = [f"Concept couvert : {c}" for c in concepts_found],
            weaknesses        = [f"Concept manquant : {c}" for c in missing],
            improved_answer   = self._build_improved(question),
            inject_recommended = total_score >= 0.60,
            domain            = response.domain,
            palier            = response.palier,
            sub_scores        = {
                "concept_coverage": round(concept_score, 3),
                "length_bonus":     round(length_score, 3),
            },
        )
    
    def is_available(self) -> bool:
        return True   # Toujours disponible
    
    def _find_concepts(self, text: str, concepts: list[str]) -> list[str]:
        """Recherche insensible à la casse de chaque concept dans le texte."""
        text_lower = text.lower()
        return [c for c in concepts if c.lower() in text_lower]
    
    def _length_score(self, text: str) -> float:
        nb_mots = len(text.split())
        if nb_mots > 100: return 1.0
        if nb_mots >= 50: return 0.5
        return 0.0
    
    def _build_improved(self, question: BenchQuestion) -> str:
        """
        Génère une réponse de référence structurée à partir du rubric.
        Format : ## {question}\n\n### Points clés\n{concepts}\n\n### Critères\n{rubric}
        """
        concepts_list = "\n".join(f"- **{c}**" for c in question.expected_concepts)
        return (
            f"## {question.question}\n\n"
            f"### Points clés à couvrir\n{concepts_list}\n\n"
            f"### Critères d'évaluation\n{question.rubric}"
        )
```

## `judge_claude.py`

Identique à V0 avec les corrections suivantes :
- `timeout = 30` pour l'appel API (pas `None` — c'est un appel réseau externe, pas Ollama)
- `improved_answer` limité à `max_skill_tokens` mots (config) avant injection
- `sub_scores` populé depuis la réponse JSON Claude si présent (optionnel)
- `judge_openai.py` **supprimé** (stub inutile — remplacé par `judge_local.py`)

## `judge_engine.py`

Règles V1 modifiées :
- Si `config["judges"]["default"] == "local"` → instancie `JudgeLocal` par défaut
- Si `"claude"` dans `config["judges"]["active"]` ET `ANTHROPIC_API_KEY` défini → instancie aussi `JudgeClaude`
- `consensus_mode=True` : score = moyenne des deux juges, improved_answer = celle de Claude si disponible, sinon locale

## Tests attendus — `test_eval_03_judge.py` (~22 tests)

Identiques à V0 pour JudgeBase + JudgeClaude, plus :

**JudgeLocal** :
- `is_available()` → True (toujours)
- `_find_concepts` : insensible à la casse
- `_find_concepts` : concept absent → pas dans la liste retournée
- `_length_score` : > 100 mots → 1.0
- `_length_score` : 50-100 mots → 0.5
- `_length_score` : < 50 mots → 0.0
- `score()` : 3/3 concepts couverts → concept_score=1.0
- `score()` : 0/3 concepts → score < 0.60 → inject_recommended=False
- `score()` : sub_scores contient concept_coverage + length_bonus
- `_build_improved` : contient question, concepts, rubric
- JudgeLocal remplace JudgeOpenAI stub (pas de `test_judge_openai_stub`)

---
---
# EVAL-04 : DistillEngine → MemoryEngine
---

## Objectif EVAL-04

Implémenter la **Phase 3 — DISTILL** avec injection dans `MemoryEngine` (pas `SkillLibrary`).

## Fichiers créés

| Fichier | Action |
|---|---|
| `EvalLoop/engines/distill_engine.py` | Créé |

**Aucune modification de `core/`** — `MemoryEngine` est utilisé tel quel.

## `distill_engine.py`

```python
class DistillEngine:
    def __init__(self, config: dict, session_dir: Path):
        # memory_engine instancié en lazy (import tardif pour éviter circulaire)
        self._session_dir = session_dir
        self._config      = config
        self._mem         = None  # lazy init
    
    def _get_mem(self):
        if self._mem is None:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
            from core.memory_engine import MemoryEngine
            self._mem = MemoryEngine()
        return self._mem
    
    def run(
        self,
        min_score: float | None = None,
        questions_index: dict[str, BenchQuestion] | None = None,
    ) -> list[DistilledSkill]:
        ...
    
    def _load_scores(self) -> list[JudgeScore]: ...
    def _format_skill_md(self, score: JudgeScore, question: BenchQuestion | None) -> str: ...
    def _sha256_content(self, content: str) -> str: ...
    def _is_duplicate(self, content_hash: str) -> bool: ...
    def _inject(self, skill_md: str, score: JudgeScore, question: BenchQuestion | None) -> None: ...
```

## Injection via MemoryEngine

```python
def _inject(self, skill_md: str, score: JudgeScore, question: BenchQuestion | None) -> None:
    dedup_hash = self._sha256_content(skill_md)
    
    mem = self._get_mem()
    mem.store("evalloop_skills", {
        "content":     skill_md,
        "source":      "evalloop",
        "question_id": score.question_id,
        "domain":      score.domain,
        "palier":      score.palier,
        "score":       score.score,
        "judge":       score.judge,
        "session":     self._session_dir.name,
        "dedup_hash":  dedup_hash,
    })
```

## Format `.md` du skill distillé

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

## Règles DistillEngine V1

- `inject_recommended=False` → skip même si score >= min_score
- `improved_answer` vide → skip
- Déduplication : `<!-- dedup:{hash} -->` scanné dans `evalloop_skills` collection
  (via `MemoryEngine.search("dedup:"+hash, n=1)` puis vérification metadata)
- Injection ordonnée par score décroissant
- Sessions immuables : `scores.jsonl` jamais modifié

**Différences V0 → V1** :
- `SkillLibrary.add_skill()` **remplacé** par `MemoryEngine.store("evalloop_skills", ...)`
- `skill_lib_path: Path` **supprimé** du constructeur
- Import lazy de `MemoryEngine` (évite import circulaire au démarrage)
- Déduplication via MemoryEngine.search (pas scan fichiers .md disque)

## Tests attendus — `test_eval_04_distill.py` (~18 tests)

Identiques à V0 sauf :
- Tests utilisant `add_skill()` → remplacés par `MemoryEngine.store` mocké
- `_is_duplicate` : mocke `MemoryEngine.search` (pas de scan fichiers)
- Constructeur sans `skill_lib_path`

---
---
# EVAL-05 : BenchGenerator + Benchmarks Initiaux
---

## Objectif EVAL-05

Deux livrables :
1. `bench_generator.py` — génère questions via LLM (paliers 2+ uniquement)
2. Benchmarks initiaux — paliers 0 et 1 écrits à la main (palier 0 de V0 conservé intégralement)

## Fichiers créés

| Fichier | Rôle |
|---|---|
| `EvalLoop/engines/bench_generator.py` | Génération LLM + statut draft |
| `EvalLoop/benchmarks/python_core/palier_0.json` | 5 questions (identiques à V0) |
| `EvalLoop/benchmarks/python_core/palier_1.json` | 5 questions |
| `EvalLoop/benchmarks/python_core/palier_2.json` | 5 questions statut draft |
| `EvalLoop/benchmarks/architecture/palier_0.json` | 5 questions (identiques à V0) |
| `EvalLoop/benchmarks/architecture/palier_1.json` | 5 questions |
| `EvalLoop/benchmarks/debugging/palier_0.json` | 5 questions (identiques à V0) |
| `EvalLoop/benchmarks/debugging/palier_1.json` | 5 questions |
| `EvalLoop/benchmarks/algorithms/palier_0.json` | 5 questions |
| `EvalLoop/benchmarks/refactoring/palier_0.json` | 5 questions |
| `EvalLoop/benchmarks/lcca_meta/palier_0.json` | 3 questions |

**Benchmarks palier 0 identiques à V0** — ils sont de bonne qualité, pas de raison de les modifier.

## `bench_generator.py` — Règles V1

Identique à V0 avec modifications :
- **Questions générées systématiquement en statut `"status": "draft"`**
- Seules les questions `"status": "active"` sont utilisées par ProbeEngine
- `save()` : si palier < 2 → lève `ValueError("Palier 0/1 réservés aux questions écrites à la main")`
- Le CLI `gen-bench` refuse `--palier 0` et `--palier 1`

## Tests attendus — `test_eval_05_benchgen.py` (~16 tests)

Identiques à V0, plus :
- `generate()` : toutes les questions générées ont `status="draft"`
- `save()` avec palier=0 → ValueError
- `save()` avec palier=1 → ValueError
- `save()` avec palier=2 → OK

---
---
# EVAL-06 : CLI lcca_eval.py + Rapport
---

## Objectif EVAL-06

CLI point d'entrée + générateur de rapport.

## Fichiers créés

| Fichier | Rôle |
|---|---|
| `lcca_eval.py` | CLI racine (D:\LLMCodeAgent\) |
| `EvalLoop/engines/session_reporter.py` | Génère session_report.md |

## Interface CLI

```bash
# Benchmarks
python lcca_eval.py gen-bench --domain python_core --palier 2 --count 5
# Note : --palier 0 et --palier 1 refusés (écriture manuelle uniquement)

# Probe
python lcca_eval.py probe --domain python_core [--session 2026-04-24] [--questions 5]
python lcca_eval.py probe --domain all

# Judge
python lcca_eval.py judge --session latest [--judge local|claude|all]
# Défaut : --judge local

# Distill
python lcca_eval.py distill --session latest [--min-score 0.70]

# Rapport
python lcca_eval.py report --session latest

# Statut curriculum
python lcca_eval.py status

# Pipeline complet en une commande
python lcca_eval.py run --domain python_core [--judge local]
```

## Commande `run` (NOUVELLE V1)

Enchaîne probe → judge → distill → report en une seule commande. Utile pour les sessions automatisées.

```
python lcca_eval.py run --domain python_core --judge local
  → Crée session YYYY-MM-DD_HH-MM/
  → Probe toutes les questions du palier courant
  → Score avec JudgeLocal
  → Distille les meilleurs
  → Génère le rapport
  → Affiche le résumé
```

## Règles CLI V1

Identiques à V0, plus :
- `--judge` : défaut `"local"` (pas `"claude"`)
- `--palier 0` et `--palier 1` sur `gen-bench` → exit(1) + message explicite
- `run` : commande pipeline tout-en-un
- `argparse` stdlib uniquement

## Tests attendus — `test_eval_06_cli.py` (~17 tests)

Identiques à V0, plus :
- `gen-bench --palier 0` → exit(1)
- `gen-bench --palier 1` → exit(1)
- `run` : enchaîne probe + judge + distill
- `judge` sans argument → utilise juge "local" par défaut

---
---
# EVAL-07 : Tests complets
---

## Cible : ≥ 80 tests, 0 appel réseau réel

| Fichier | Tests | Couverture |
|---|---|---|
| `tests/test_eval_01_types.py` | ~22 | Dataclasses + round-trips + status + sub_scores |
| `tests/test_eval_02_probe.py` | ~20 | CurriculumTracker + ProbeEngine + filtre draft |
| `tests/test_eval_03_judge.py` | ~22 | JudgeBase + JudgeLocal + JudgeClaude + JudgeEngine |
| `tests/test_eval_04_distill.py` | ~18 | DistillEngine + MemoryEngine.store mocké |
| `tests/test_eval_05_benchgen.py` | ~16 | BenchGenerator + refus palier 0/1 |
| `tests/test_eval_06_cli.py` | ~17 | CLI + commande run + refus palier 0/1 |
| `tests/test_eval_integration.py` | ~10 | Cycle complet mocké |

**Total estimé : 125 tests** (V0 prévoyait 116 — delta +9 pour les nouvelles règles V1).

## Tests d'intégration V1

Identiques à V0 (INT-01 à INT-10) avec les mises à jour :
- `INT-01` : mock `MemoryEngine.store` au lieu de `SkillLibrary.add_skill`
- `INT-03` : JudgeLocal disponible même sans API → `judge.run()` retourne des scores valides (pas `[]`)
- Nouveau `INT-11` : Questions "draft" filtrées par ProbeEngine

## Fixture commune `_make_eval_config(tmp_path)`

Identique à V0.

## Mock JudgeLocal (pas de mock nécessaire — il est déterministe)

JudgeLocal n'appelle aucune API. Utiliser une vraie instance dans les tests.

## Mock MemoryEngine pour DistillEngine

```python
from unittest.mock import MagicMock

mem_mock = MagicMock()
mem_mock.store.return_value = MagicMock(stored=True, reason="")
mem_mock.search.return_value = {"evalloop_skills": []}  # pas de doublon
```

## Conventions V1

- `import pytest` inclus même si non utilisé (convention LCCA tests)
- `tmp_path` pour toutes les I/O
- `sys.path.insert(0, str(Path(__file__).parent.parent / "EvalLoop"))` dans conftest ou chaque test file
- 0 chemin `D:\LLMCodeAgent` hardcodé dans les tests

---

## Checklist de validation EVAL-07

```
[ ] test_eval_01_types.py     : 22 tests PASSED
[ ] test_eval_02_probe.py     : 20 tests PASSED
[ ] test_eval_03_judge.py     : 22 tests PASSED
[ ] test_eval_04_distill.py   : 18 tests PASSED
[ ] test_eval_05_benchgen.py  : 16 tests PASSED
[ ] test_eval_06_cli.py       : 17 tests PASSED
[ ] test_eval_integration.py  : 10 tests PASSED
[ ] 0 test réseau réel (conftest.py autouse vérifié)
[ ] 0 chemin D:\LLMCodeAgent hardcodé dans les tests
[ ] pytest complet régression : 0 test cassé hors EvalLoop
```

---

## Compteur global LCCA post-EvalLoop

```
EVAL-01 types        : +22 tests
EVAL-02 probe        : +20 tests
EVAL-03 judge        : +22 tests
EVAL-04 distill      : +18 tests
EVAL-05 benchgen     : +16 tests
EVAL-06 CLI          : +17 tests
EVAL-07 intégration  : +10 tests
─────────────────────────────────
EvalLoop total       : +125 tests

État avant EvalLoop  : 1483 tests (post-PROJ-04)
État après EvalLoop  : 1608 tests (estimé)
```

---

## Réponses aux Questions Ouvertes de l'Addendum

| ID | Réponse |
|----|---------|
| **Q-01** | Budget API Claude = 0 par défaut. JudgeLocal est le juge par défaut. Claude = option `--judge claude` utilisée manuellement. |
| **Q-02** | `SkillLibrary.add_skill()` **n'existe pas**. Interface réelle : `extract_and_store(code, receipt, ...)` nécessite un `ExecutionReceipt`. EvalLoop utilise `MemoryEngine.store("evalloop_skills", ...)` directement. |
| **Q-03** | Le 3B est le seul modèle viable (full-GPU). Le 7B déborde en CPU (-63%). EvalLoop évalue le modèle tel qu'il est en production. |
| **Q-04** | `eval_state.json` = artefact local uniquement. `auto_push = false` s'applique. Pas de versionnement git. |
| **Q-05** | Collision sha256[:16] : probabilité ~1/65536. En cas de collision, le skill est skippé (faux positif acceptable). La déduplication est une protection best-effort, pas une garantie cryptographique. |
