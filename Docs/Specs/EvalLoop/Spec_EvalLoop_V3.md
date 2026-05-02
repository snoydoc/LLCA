# SPEC EvalLoop V3 — Système d'Auto-Évaluation Curriculum LCCA
**Version** : 3.0  
**Date** : 2026-04-24  
**Auteur** : Révision architecturale post-audit code réel (V1 → V2 → V3)  
**Statut** : ✅ VALIDÉ — Prêt pour implémentation EVAL-01  
**Remplace** : Spec_EvalLoop_V1.md + Spec_EvalLoop_V2.md (addendums fusionnés)

---

## 1. Verdict Global V3

| Critère | Note | Justification |
|---|---|---|
| Architecture | **9/10** | Rôles clairs, patterns LCCA respectés, façades légères |
| Cohérence LCCA | **9/10** | MemoryEngine audité, imports propres, invariants respectés |
| Faisabilité | **8/10** | ~50 tests, 6 sprints, réaliste solo |
| Qualité apprentissage | **8/10** | JudgeLocal = gatekeeper pur, injection Claude contrôlée |
| Robustesse | **9/10** | Atomic write, JSONL append-only, status draft/active |

**Décision** : démarrer EVAL-01 immédiatement.

---

## 2. Ancrage dans le Code Réel LCCA

### 2.1 Interface MemoryEngine (auditée — `core/memory_engine.py` + `core/memory_engine_store.py`)

```python
# Signature réelle
engine.store(collection: str, payload: Dict[str, Any]) -> StoreResult

# StoreResult (dataclass réelle)
@dataclass
class StoreResult:
    stored:     bool
    collection: str
    entry_id:   Optional[str] = None
    reason:     Optional[str] = None

# Collections valides (frozenset réel dans memory_engine_store.py)
_VALID_COLLECTIONS = frozenset({
    "lcca_solutions", "lcca_failures", "lcca_context",
    "lcca_patches", "lcca_specs", "lcca_skills"
})

# Seuils réels (source de vérité : memory_engine_store.py)
_THRESHOLD_SOLUTIONS = 0.8
_THRESHOLD_CONTEXT   = 0.6   # → EvalLoop doit envoyer score >= 0.70 pour passer ce seuil
```

**Décision EvalLoop** : injection dans `lcca_context` avec `score >= 0.70`.  
Pourquoi `lcca_context` et non `lcca_skills` ? Les réponses améliorées sont des _contextes de raisonnement_, pas des fonctions Python extractibles par `SkillLibrary.extract_and_store()` (qui requiert un `ExecutionReceipt` HMAC signé — EvalLoop n'en produit pas).

### 2.2 SkillLibrary — Pourquoi on n'y touche pas

`SkillLibrary.extract_and_store()` requiert un `ExecutionReceipt` signé (`core/receipt_store.py`). EvalLoop ne passe pas par le pipeline TesterAgent → pas de receipt valide → V8-Regle-17 bloque le stockage. Contournement impossible sans simuler un receipt, ce qui violerait l'intégrité HMAC.

**Conclusion** : EvalLoop injecte via `MemoryEngine.store("lcca_context", {...})` directement. `lcca_skills` reste réservé au pipeline Architect→Coder→Reviewer→Tester.

### 2.3 Modèle LLM — Invariants config.py

```python
OLLAMA_MODEL   = "qwen2.5-coder:3b"   # Seul modèle viable (2.0 GB VRAM)
OLLAMA_TIMEOUT = None                  # INVARIANT ABSOLU — ne jamais mettre d'entier
OLLAMA_URL     = "http://localhost:11434"
```

Le 3b n'est pas "défaillant" — il est le moteur conversationnel de LCCA, contraint par le hardware (Quadro M2000M 4 GB VRAM). Le 7b déborderait en CPU (-63% vitesse).

**Implication pour EvalLoop** :
- `bench_generator.py` est désactivé en V3 (le 3b ne génère pas des questions de qualité)
- Le probe évalue le modèle tel qu'il est — c'est le but
- Les questions paliers 2+ sont écrites à la main ou importées

### 2.4 OllamaClient — Interface réelle (`core/ollama_client.py`)

```python
# Méthode à utiliser pour le probe
client.generate(system: str, user: str) -> str
# ou
client.chat(system: str, history: list[dict]) -> str
```

ProbeEngine instancie OllamaClient directement (import lazy pour éviter le circulaire) :
```python
from core.ollama_client import OllamaClient
from core.llm_config import cfg_read   # Pour OLLAMA_URL, OLLAMA_MODEL, etc.
```

### 2.5 Import pattern — Résolution BLK-03

Le package EvalLoop doit avoir son propre `__init__.py`. Le CLI `lcca_eval.py` à la racine fait :
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # Une seule fois au démarrage
```
Conforme au pattern LCCA (`lcca_si.py`). Pas d'import lazy dans les engines — le `sys.path` est résolu en amont par le CLI.

---

## 3. Architecture

```
D:\LLMCodeAgent\
├── lcca_eval.py                      # CLI point d'entrée (racine — comme lcca_si.py)
│
└── EvalLoop/
    ├── __init__.py                   # Package Python propre
    ├── eval_config.toml              # Configuration globale
    ├── eval_state.json               # Palier courant par domaine (atomic write)
    │
    ├── benchmarks/                   # Questions curriculum
    │   ├── python_core/
    │   │   ├── palier_0.json         # Manuel obligatoire
    │   │   ├── palier_1.json         # Manuel obligatoire
    │   │   └── palier_2.json         # Manuel recommandé (statut draft possible)
    │   ├── architecture/
    │   ├── debugging/
    │   └── lcca_meta/
    │
    ├── sessions/
    │   └── YYYY-MM-DD_HH-MM/
    │       ├── responses.jsonl       # Réponses brutes (append-only)
    │       ├── scores.jsonl          # Scores JudgeLocal + inject_recommended (append-only)
    │       └── session_report.md     # Rapport lisible
    │
    ├── engines/
    │   ├── probe_engine.py           # Soumet questions → Ollama
    │   ├── judge_engine.py           # Orchestre JudgeLocal + JudgeClaude
    │   ├── distill_engine.py         # Sélectionne + stocke dans MemoryEngine
    │   └── curriculum_tracker.py    # Gère paliers, unlock, état persisté
    │
    └── judges/
        ├── judge_base.py             # ABC commun
        ├── judge_local.py            # Gatekeeper offline (scoring surface)
        └── judge_claude.py           # Juge qualitatif (injection via API Anthropic)
```

**Absent de la V3** : `bench_generator.py` — désactivé, questions manuelles uniquement.

---

## 4. Dataclasses (`evalloop_types.py`)

```python
# -*- coding: utf-8-sig -*-
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List

@dataclass
class BenchQuestion:
    """Une question du curriculum."""
    id:                str                    # UUID ou slug lisible
    domain:            str                    # "python_core", "architecture", etc.
    palier:            int                    # 0–5
    question:          str                    # Texte de la question
    expected_concepts: List[str]              # Tokens attendus (pour JudgeLocal)
    rubric:            str = ""               # Critères d'évaluation (pour JudgeClaude)
    status:            str = "active"         # "active" | "draft"
    tags:              List[str] = field(default_factory=list)

@dataclass
class ProbeResponse:
    """Réponse brute de LCCA à une question."""
    question_id:  str
    question:     BenchQuestion
    response:     str
    model:        str
    duration_sec: float
    timestamp:    str                         # ISO 8601 UTC

@dataclass
class JudgeScore:
    """Score produit par un juge."""
    question_id:      str
    judge:            str                     # "local" | "claude"
    # Scores composants (tous entre 0.0 et 1.0)
    concept_score:    float = 0.0             # Coverage des expected_concepts (tokenisé)
    coherence_score:  float = 0.0             # Concepts dans un rayon de 100 mots
    structure_score:  float = 0.0             # Code blocks / listes / exemples
    # Score final
    final_score:      float = 0.0            # Combinaison pondérée
    # Décision injection
    inject_recommended: bool = False          # INVARIANT JudgeLocal : toujours False
    improved_answer:    str  = ""             # INVARIANT JudgeLocal : toujours ""
    # Diagnostics
    strengths:    List[str] = field(default_factory=list)
    weaknesses:   List[str] = field(default_factory=list)

@dataclass
class DistilledSkill:
    """Entrée prête à être injectée dans MemoryEngine."""
    question_id:    str
    domain:         str
    palier:         int
    improved_answer: str
    score:          float                     # >= 0.70 pour passer _THRESHOLD_CONTEXT
    dedup_hash:     str                       # SHA256[:16] de improved_answer
    judge:          str                       # Toujours "claude" en V3
    injected_at:    str = ""                  # ISO 8601, rempli après store()

@dataclass
class PalierState:
    """État courant d'un domaine dans eval_state.json."""
    domain:              str
    current_palier:      int   = 0
    questions_done:      int   = 0
    avg_score:           float = 0.0
    unlock_threshold:    float = 0.70
    sessions_completed:  int   = 0
```

---

## 5. Composants

### 5.1 ProbeEngine (`engines/probe_engine.py`)

**Responsabilité** : soumettre une BenchQuestion à LCCA via OllamaClient et retourner une ProbeResponse.

```python
class ProbeEngine:
    def __init__(self, model: str = None, base_url: str = None):
        # Import lazy : résolu par le sys.path du CLI
        from core.ollama_client import OllamaClient
        from config import OLLAMA_MODEL, OLLAMA_URL, OLLAMA_TIMEOUT, OLLAMA_MAX_TOKENS
        self._client = OllamaClient(
            base_url   = base_url or OLLAMA_URL,
            model      = model or OLLAMA_MODEL,
            timeout    = OLLAMA_TIMEOUT,     # None — INVARIANT ABSOLU
            max_tokens = OLLAMA_MAX_TOKENS,
        )

    def probe(self, question: BenchQuestion) -> ProbeResponse:
        """Soumet la question et retourne la réponse brute."""
        system = (
            "Tu es un assistant technique expert en Python et en architecture logicielle. "
            "Réponds de façon précise et structurée."
        )
        # Pas de "Tu es LCCA" — incorrect conceptuellement
        ...
```

**Règles** :
- `OLLAMA_TIMEOUT = None` transmis tel quel à OllamaClient — ne jamais mettre d'entier
- `system` générique — ne pas personnifier LCCA dans le prompt probe
- Le probe ne filtre pas la réponse — c'est le rôle du juge

### 5.2 JudgeLocal (`judges/judge_local.py`) — Gatekeeper

**Rôle** : filtrer les réponses catastrophiques avant qu'elles atteignent JudgeClaude ou DistillEngine. **Ne génère pas de contenu injectabe.**

**Invariants absolus** :
```python
improved_answer   = ""     # Jamais de contenu — MAJ-01 résolu
inject_recommended = False  # Jamais d'injection depuis JudgeLocal
```

**Algorithme de scoring** :

```python
def score(self, question: BenchQuestion, response: ProbeResponse) -> JudgeScore:
    # 1. concept_score : matching tokenisé (\bword\b)
    #    Empêche "list" de matcher "listing", "thread" de matcher "threading"
    concepts_found = self._find_concepts_tokenized(response.response, question.expected_concepts)
    concept_score  = len(concepts_found) / max(len(question.expected_concepts), 1)

    # 2. coherence_score : vérifie que les concepts trouvés sont groupés
    #    Fenêtre glissante de 100 mots — pénalise le keyword stuffing
    coherence_score = self._coherence_score(response.response, question.expected_concepts)

    # 3. structure_score : remplace length_score (MAJ-02 résolu)
    #    Code blocks (```) → +0.1
    #    Listes (- ou *)   → +0.1
    #    Exemples concrets (exemple, ex:, >>>) → +0.1
    #    Maximum : 0.3
    structure_score = self._structure_score(response.response)

    # Pondération
    final_score = concept_score * 0.6 + coherence_score * 0.2 + structure_score * 0.2

    return JudgeScore(
        question_id       = question.id,
        judge             = "local",
        concept_score     = concept_score,
        coherence_score   = coherence_score,
        structure_score   = structure_score,
        final_score       = final_score,
        inject_recommended = False,    # INVARIANT
        improved_answer   = "",        # INVARIANT
        weaknesses        = self._list_missing(question.expected_concepts, concepts_found),
    )
```

**Seuil gatekeeper** : `final_score >= 0.30` pour passer à JudgeClaude. En dessous : réponse rejetée, loguée, non transmise.

### 5.3 JudgeClaude (`judges/judge_claude.py`) — Juge Qualitatif

**Rôle** : évaluer en profondeur les réponses ayant passé le gatekeeper local. Seul à produire `improved_answer` et à `inject_recommended = True`.

**Conditions d'activation** :
- Flag `--judge claude` au CLI
- `JudgeLocal.final_score >= 0.30` (réponse non catastrophique)
- Score local suffisant pour valoir l'appel API

**Production** :
```python
improved_answer    = "<réponse corrigée et enrichie>"  # Non vide
inject_recommended = True                               # Si final_score >= 0.70
```

**Poids dans DistillEngine** : seules les entrées `judge == "claude"` et `inject_recommended == True` sont injectées. Les entrées `judge == "local"` ne sont jamais injectées, même si `final_score` est élevé.

### 5.4 DistillEngine (`engines/distill_engine.py`)

**Responsabilité** : lire `scores.jsonl`, filtrer les entrées injectables, dédupliquer, stocker dans MemoryEngine.

```python
class DistillEngine:
    def __init__(self):
        # Import lazy — évite import circulaire si DistillEngine importé depuis __init__
        self._mem = None

    def _get_mem(self):
        if self._mem is None:
            from core.memory_engine import MemoryEngine
            self._mem = MemoryEngine()
        return self._mem

    def distill(self, session_dir: Path) -> int:
        """
        Lit scores.jsonl, injecte les DistilledSkill éligibles dans lcca_context.
        Retourne le nombre d'entrées injectées.
        """
        scores_path = session_dir / "scores.jsonl"
        injected = 0

        for line in scores_path.read_text(encoding="utf-8-sig").splitlines():
            score = JudgeScore(**json.loads(line))

            # Filtre strict : claude uniquement + inject_recommended
            if score.judge != "claude" or not score.inject_recommended:
                continue
            if score.final_score < 0.70:   # min_inject_score — dépasse _THRESHOLD_CONTEXT=0.6
                continue

            # Déduplication par hash
            dedup_hash = hashlib.sha256(score.improved_answer.encode()).hexdigest()[:16]
            if self._is_duplicate(dedup_hash):
                continue

            # Payload pour lcca_context
            payload = {
                "content":    score.improved_answer,
                "score":      score.final_score,          # >= 0.70 > _THRESHOLD_CONTEXT=0.6
                "domain":     score.question_id.split("/")[0],
                "source":     "evalloop",
                "dedup_hash": dedup_hash,
                "judge":      "claude",
            }
            result = self._get_mem().store("lcca_context", payload)
            if result.stored:
                injected += 1

        return injected

    def _is_duplicate(self, dedup_hash: str) -> bool:
        """
        Vérifie si le hash est déjà dans lcca_context.
        
        Note VIG-04 : si MemoryEngine.search() utilise du semantic search (embeddings),
        la requête exacte par hash peut ne pas retrouver l'entrée.
        Solution de repli : index local eval_dedup_index.json (écriture atomique).
        """
        # Approche primaire : index local (fiable, pas de dépendance au moteur de recherche)
        index_path = Path(__file__).parent.parent / "eval_dedup_index.json"
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            index = []
        return dedup_hash in index

    def _register_hash(self, dedup_hash: str) -> None:
        """Ajoute le hash à l'index local (écriture atomique)."""
        index_path = Path(__file__).parent.parent / "eval_dedup_index.json"
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            index = []
        if dedup_hash not in index:
            index.append(dedup_hash)
            tmp = index_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(index, indent=2), encoding="utf-8")
            tmp.replace(index_path)   # Path.replace() — T-14 : atomique Windows + Linux
```

**Règle T-14** : toujours `Path.replace()`, jamais `Path.rename()` (échoue Windows si cible existe).

### 5.5 CurriculumTracker (`engines/curriculum_tracker.py`)

**Responsabilité** : gérer `eval_state.json` — palier courant, unlock, progression.

```python
class CurriculumTracker:
    def __init__(self, state_path: Path):
        self._path = state_path

    def get_state(self, domain: str) -> PalierState: ...
    def update_state(self, domain: str, score: float) -> None:
        """Atomic write — T-14 pattern."""
        ...
    def is_unlocked(self, domain: str, palier: int) -> bool:
        """Palier n débloqué si avg_score palier n-1 >= unlock_threshold."""
        ...
    def load_questions(self, domain: str, palier: int) -> List[BenchQuestion]:
        """Charge palier_N.json, filtre status == 'active'."""
        ...
```

**eval_state.json format** :
```json
{
  "python_core": {
    "current_palier": 1,
    "questions_done": 12,
    "avg_score": 0.73,
    "unlock_threshold": 0.70,
    "sessions_completed": 3
  }
}
```

---

## 6. Configuration (`eval_config.toml`)

```toml
[model]
ollama_url   = "http://localhost:11434"
# model non spécifié → lire depuis config.py (OLLAMA_MODEL)
# OLLAMA_TIMEOUT = None → invariant absolu, non configurable ici

[scoring]
min_inject_score  = 0.70   # Seuil injection lcca_context (> _THRESHOLD_CONTEXT=0.6)
unlock_threshold  = 0.70   # Seuil pour passer au palier suivant
gatekeeper_min    = 0.30   # Seuil JudgeLocal pour transmettre à JudgeClaude

[sessions]
sessions_dir      = "EvalLoop/sessions"
state_file        = "EvalLoop/eval_state.json"
dedup_index       = "EvalLoop/eval_dedup_index.json"

[bench]
# bench_generator désactivé — questions manuelles uniquement
# generator_enabled = false  (implicite en V3)

[storage]
# max_skill_words (renommé depuis max_skill_tokens — MAJ-05 résolu)
# 600 tokens ≈ 300-450 mots (anglais/français)
max_skill_words   = 400    # Conservatif : ~600 tokens en français
collection        = "lcca_context"
```

---

## 7. CLI (`lcca_eval.py`)

```python
# lcca_eval.py — racine D:\LLMCodeAgent\
# Pattern identique à lcca_si.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # Une seule fois

import argparse
# ...

# Commandes disponibles :
#   probe   --domain python_core --palier 0 [--judge local|claude]
#   judge   --session <session_dir> --judge local|claude
#   distill --session <session_dir>
#   run     --domain python_core [--judge local|claude]  # pipeline complet
#   report  --session <session_dir>
#   review-bench --domain python_core --palier 2         # MAJ-04 résolu
```

### `review-bench` — Workflow de validation des questions draft

```
python lcca_eval.py review-bench --domain python_core --palier 2

# Affiche chaque question draft une par une :
[1/3] Question: "Quelle est la différence entre __str__ et __repr__ ?"
      Concepts: ["__str__", "__repr__", "representation", "user-facing"]
      Rubric: "..."

[y] Activer | [n] Rejeter | [e] Editer | [s] Sauter
> _
```

**Note VIG-02** : `review-bench` est interactif (`input()` en boucle). Ne peut pas être pipé. Alternative : `review-bench --export review.json` → éditer → `review-bench --apply review.json`.

---

## 8. Format des Questions (`benchmarks/domain/palier_N.json`)

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
- `palier 0/1` : écriture manuelle uniquement — CLI refuse `gen-bench --palier 0` (non implémenté)
- `palier 2+` : peuvent être créés avec `status: "draft"` et activés via `review-bench`
- `expected_concepts` : tokens **exacts**, pas de regex — matching tokenisé `\bword\b` dans JudgeLocal

---

## 9. Format des Sessions

### `responses.jsonl` (append-only)
```json
{"question_id": "python_core/p0/gil_001", "response": "...", "model": "qwen2.5-coder:3b", "duration_sec": 8.4, "timestamp": "2026-04-24T14:30:00Z"}
```

### `scores.jsonl` (append-only)
```json
{"question_id": "python_core/p0/gil_001", "judge": "local", "concept_score": 0.8, "coherence_score": 0.6, "structure_score": 0.2, "final_score": 0.64, "inject_recommended": false, "improved_answer": ""}
```

---

## 10. Points de Vigilance (Non-Blockers)

### VIG-01 : `coherence_score` reste un proxy
Fenêtre de 100 mots peut rater si les concepts sont séparés par de la ponctuation ou des retours à la ligne. Impact faible (pondération 0.2). Corriger si faux positifs en prod : distance moyenne entre concepts.

### VIG-02 : `review-bench` est interactif
Ne peut pas être pipé. Alternative `--export`/`--apply` si besoin CI.

### VIG-03 : Mélange de juges dans `scores.jsonl`
Si `--judge local` puis `--judge claude` dans la même session, le score moyen palier sera faussé (échelles différentes). Guard dans `judge_engine.py` : si `scores.jsonl` contient des entrées d'un juge différent, log WARNING + suggestion nouvelle session.

### VIG-04 : Déduplication via index local
MemoryEngine.search() peut utiliser du semantic search (embeddings) — une requête par hash exact peut ne pas retrouver l'entrée. Solution retenue : `eval_dedup_index.json` local (fiable, pas de dépendance au moteur de recherche).

### VIG-05 : `strengths` vide dans JudgeLocal
`strengths = []` toujours. Enrichissement optionnel : `[f"Structure détectée: {s}" for s in structures_found]`.

---

## 11. Sprints d'Implémentation

### Ordre recommandé (développement vertical)

| Jour | Sprint | Livrable |
|------|--------|----------|
| 1 | EVAL-01 | `evalloop_types.py` + `eval_config.toml` + `eval_state.json` + 15 tests |
| 2 | EVAL-02 | `probe_engine.py` (mocké) + `judge_local.py` + 15 tests |
| 3 | INT-01 | Test intégration pipeline local complet mocké |
| 4 | EVAL-03 | `benchmarks/python_core/palier_0.json` (10 questions manuelles) + `curriculum_tracker.py` |
| 5 | EVAL-04 | `distill_engine.py` (mocké) + `judge_claude.py` (stub) + 10 tests |
| 6 | EVAL-05 | `lcca_eval.py` CLI + test manuel Ollama réel (1 question → log) |

**Pourquoi vertical ?** Les vrais problèmes d'intégration (imports, MemoryEngine, Ollama) apparaissent au jour 3, pas à la fin.

### EVAL-01 — Dataclasses + Config

**Fichiers** :
- `EvalLoop/__init__.py` (vide)
- `EvalLoop/evalloop_types.py` (5 dataclasses)
- `EvalLoop/eval_config.toml`
- `EvalLoop/eval_state.json` → `{}`
- `tests/test_eval_01_types.py` (15 tests)

**Tests** :
- Round-trip to_dict/from_dict pour chaque dataclass
- Valeurs par défaut correctes
- BenchQuestion.status == "active" par défaut
- JudgeScore.inject_recommended == False par défaut (invariant)
- JudgeScore.improved_answer == "" par défaut (invariant)
- DistilledSkill.score >= 0.70 accepté par check_threshold

### EVAL-02 — ProbeEngine + JudgeLocal

**Fichiers** :
- `EvalLoop/engines/probe_engine.py`
- `EvalLoop/judges/judge_base.py`
- `EvalLoop/judges/judge_local.py`
- `tests/test_eval_02_judge.py` (15 tests)

**Tests JudgeLocal critiques** :
```python
# Test anti-gaming keyword stuffing
def test_judge_local_keyword_stuffing():
    q = BenchQuestion(expected_concepts=["GIL", "thread", "mémoire"])
    r = ProbeResponse(response="GIL thread mémoire bytecode GIL thread")
    score = JudgeLocal().score(q, r)
    # coherence_score pénalise : concepts sans contexte → score final < 0.5
    assert score.final_score < 0.5

# Test invariants absolus
def test_judge_local_never_injects():
    score = JudgeLocal().score(any_question, any_response)
    assert score.inject_recommended is False
    assert score.improved_answer == ""

# Test tokenisation correcte
def test_judge_local_tokenization():
    q = BenchQuestion(expected_concepts=["list"])
    r = ProbeResponse(response="La méthode listing est utilisée dans checklist")
    score = JudgeLocal().score(q, r)
    assert score.concept_score == 0.0  # "list" ne matche pas "listing" ni "checklist"
```

### EVAL-03 — Questions Manuelles + CurriculumTracker

**Fichiers** :
- `EvalLoop/benchmarks/python_core/palier_0.json` (10 questions)
- `EvalLoop/benchmarks/python_core/palier_1.json` (10 questions)
- `EvalLoop/engines/curriculum_tracker.py`
- `tests/test_eval_03_curriculum.py` (10 tests)

**10 questions palier 0 recommandées (python_core)** :
1. GIL — définition et raison d'être
2. Différence `list` vs `tuple` (mutabilité)
3. `__str__` vs `__repr__`
4. Décoratrice `@property`
5. `*args` et `**kwargs`
6. Compréhension de liste vs `map()`
7. `with` statement et context managers
8. Différence `==` vs `is`
9. `None` vs `False` vs `0`
10. `isinstance()` vs `type()`

### EVAL-04 — DistillEngine + JudgeClaude stub

**Fichiers** :
- `EvalLoop/engines/distill_engine.py`
- `EvalLoop/judges/judge_claude.py` (stub retournant improved_answer hardcodé)
- `tests/test_eval_04_distill.py` (10 tests)

**Tests DistillEngine critiques** :
```python
# Test filtre strict — local n'injecte jamais
def test_distill_skips_local_judge():
    score_local = JudgeScore(judge="local", inject_recommended=False, ...)
    assert distill_engine._is_eligible(score_local) is False

# Test déduplication
def test_distill_dedup():
    score = JudgeScore(judge="claude", inject_recommended=True, improved_answer="A" * 50, ...)
    distill_engine.distill(session_with_score)
    # Deuxième distillation identique → 0 injection
    assert distill_engine.distill(session_with_same_score) == 0

# Test score minimum
def test_distill_rejects_low_score():
    score = JudgeScore(judge="claude", inject_recommended=True, final_score=0.65, ...)
    assert distill_engine._is_eligible(score) is False  # 0.65 < 0.70
```

### EVAL-05 — CLI

**Fichiers** :
- `lcca_eval.py` (racine)
- `tests/test_eval_05_cli.py` (5 tests smoke)

---

## 12. Cible Tests

| Sprint | Fichier test | Tests |
|--------|-------------|-------|
| EVAL-01 | test_eval_01_types.py | 15 |
| EVAL-02 | test_eval_02_judge.py | 15 |
| EVAL-03 | test_eval_03_curriculum.py | 10 |
| EVAL-04 | test_eval_04_distill.py | 10 |
| EVAL-05 | test_eval_05_cli.py | 5 |
| INT | test_eval_integration.py | 5 |
| **Total** | | **~60** |

Réduction vs V1 (125 tests) : réaliste pour un projet solo, priorisé sur les composants critiques (JudgeLocal + DistillEngine).

---

## 13. Checklist Pré-Implémentation

```
[ ] Créer EvalLoop/__init__.py (vide)
[ ] Créer EvalLoop/evalloop_types.py (5 dataclasses)
[ ] Créer EvalLoop/eval_config.toml (copier section 6)
[ ] Créer EvalLoop/eval_state.json → {}
[ ] Créer EvalLoop/eval_dedup_index.json → []
[ ] Créer EvalLoop/benchmarks/python_core/palier_0.json (10 questions)
[ ] Écrire tests/test_eval_01_types.py (15 tests)
[ ] Lancer : python -c "from EvalLoop.evalloop_types import BenchQuestion; print('OK')"
[ ] Lancer pytest tests/test_eval_01_types.py -v
[ ] Commit : git add EvalLoop/ && git commit -m "EVAL-01: dataclasses + config"
```

**Test smoke minimal avant tout** :
```bash
python -c "
import sys; sys.path.insert(0, 'D:\\LLMCodeAgent')
from EvalLoop.evalloop_types import BenchQuestion, JudgeScore
q = BenchQuestion(id='test', domain='python_core', palier=0, question='?', expected_concepts=['GIL'])
s = JudgeScore(question_id='test', judge='local')
assert s.inject_recommended is False
assert s.improved_answer == ''
print('Invariants OK')
"
```

---

## 14. Réponses aux Questions Ouvertes (V2 → V3)

| ID | Réponse |
|----|---------|
| Q-V2-01 | ✅ Interface MemoryEngine auditée. `store("lcca_context", {"content": ..., "score": ..., "dedup_hash": ...})` → `StoreResult`. Seuil réel `_THRESHOLD_CONTEXT = 0.6` → `min_inject_score = 0.70` passe. |
| Q-V2-02 | ✅ BenchGenerator désactivé. Questions manuelles uniquement. Le 3b n'est pas adapté à la génération de questions de qualité palier 2+. |
| Q-V2-03 | ✅ Injection auto acceptable depuis JudgeClaude uniquement. JudgeLocal = gatekeeper pur (`inject_recommended = False` invariant). |
| Q-V2-04 | ✅ `eval_state.json` local, pas de git. Artefact de session uniquement. |
| Q-V2-05 | ✅ Pipeline sur demande (`python lcca_eval.py run`). Pas de cron — consommation VRAM/RAM non négligeable. |

---

## 15. Règles LCCA Appliquées

| Règle LCCA | Application EvalLoop |
|------------|---------------------|
| `OLLAMA_TIMEOUT = None` invariant | ProbeEngine → `OllamaClient(timeout=None)` — transmis depuis `config.OLLAMA_TIMEOUT` |
| Écriture atomique `Path.replace()` (T-14) | `eval_state.json`, `eval_dedup_index.json`, session reports |
| Import lazy pour éviter circulaires | DistillEngine : `from core.memory_engine import MemoryEngine` dans `_get_mem()` |
| `utf-8-sig` (BOM Windows) | Tous les `.py` EvalLoop : `# -*- coding: utf-8-sig -*-` |
| Dataclass `to_dict()` / `from_dict()` | BenchQuestion, JudgeScore, DistilledSkill, PalierState |
| Façade légère < 8 KB | Chaque engine : orchestration uniquement, logique dans helpers |
| `auto_push = false` | `lcca_eval.py` : pas de git push automatique |
| Logs sur stderr | `log = logging.getLogger("lcca.evalloop.*")` |
| Pas de `sys.path.insert` dans les engines | Résolu par `lcca_eval.py` CLI une seule fois |
| `max_tokens` : `OLLAMA_MAX_TOKENS` depuis config | ProbeEngine lit `config.OLLAMA_MAX_TOKENS` |

---

*Spec V3 destinée à Claude Desktop — implémentation EVAL-01 immédiate.*
