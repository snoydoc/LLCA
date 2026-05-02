# SPEC EvalLoop — Version Finale Consolidée
**Date** : 2026-04-24
**Statut** : ✅ VERROUILLÉE — Prête pour implémentation EVAL-01 à EVAL-05
**Construit sur** : Spec V3 + Addendum V3 + Revue architecturale croisée (2 IA)
**Remplace** : Spec_EvalLoop_V3.md + Addendum_V3.md (fusionnés et corrigés)

---

## 1. Périmètre V3 — Ce qu'est EvalLoop

EvalLoop est un **benchmark de régression curriculum** pour LCCA.

Il évalue périodiquement la qualité des réponses du modèle local (`qwen2.5-coder:3b`) sur des
questions progressives, injecte les corrections dans `MemoryEngine`, et adapte le niveau de difficulté
en fonction des performances.

**Ce que V3 N'EST PAS** (reporté V4) :
- Un système d'apprentissage actif (SYS-01 : le probe ne lit pas `lcca_context` pendant l'évaluation)
- Un générateur de questions automatique (BenchGenerator désactivé — le 3b ne génère pas de questions de qualité)
- Un système de push git automatique (`auto_push = false` invariant absolu)

---

## 2. Architecture Finale

```
D:\LLMCodeAgent\
├── lcca_eval.py                        # CLI point d'entrée (racine — même pattern que lcca_si.py)
│
└── EvalLoop/
    ├── __init__.py                     # Package Python (vide)
    ├── evalloop_types.py               # 5 dataclasses + to_dict/from_dict
    ├── eval_config.toml                # Configuration globale
    ├── eval_state.json                 # Palier courant par domaine (atomic write)
    ├── eval_dedup_index.json           # Index SHA256[:16] des skills injectés (atomic write)
    ├── README_EvalLoop.md              # Documentation comportement V3 + limites
    │
    ├── benchmarks/
    │   ├── python_core/
    │   │   ├── palier_0.json           # 10 questions — écriture manuelle obligatoire
    │   │   └── palier_1.json           # 10 questions — écriture manuelle obligatoire
    │   ├── architecture/               # À créer en EVAL-03+
    │   ├── debugging/
    │   └── lcca_meta/
    │
    ├── sessions/
    │   └── YYYY-MM-DD_HH-MM/
    │       ├── responses.jsonl         # Réponses brutes (append-only)
    │       ├── scores.jsonl            # Scores JudgeLocal/JudgeClaude (append-only)
    │       └── session_report.md       # Rapport lisible + métriques santé (OPP-01)
    │
    ├── engines/
    │   ├── probe_engine.py
    │   ├── judge_engine.py
    │   ├── distill_engine.py
    │   └── curriculum_tracker.py
    │
    └── judges/
        ├── judge_base.py
        ├── judge_local.py
        └── judge_claude.py
```

---

## 3. Dataclasses (`evalloop_types.py`)

```python
# -*- coding: utf-8-sig -*-
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

@dataclass
class BenchQuestion:
    id:                str
    domain:            str
    palier:            int
    question:          str
    expected_concepts: List[str]
    rubric:            str = ""
    status:            str = "active"      # "active" | "draft"
    tags:              List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]: ...
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BenchQuestion": ...

@dataclass
class ProbeResponse:
    question_id:  str
    question:     BenchQuestion
    response:     str
    model:        str
    duration_sec: float
    timestamp:    str                      # ISO 8601 UTC

@dataclass
class JudgeScore:
    question_id:        str
    judge:              str                # "local" | "claude"
    concept_score:      float = 0.0
    coherence_score:    float = 0.0
    structure_score:    float = 0.0
    final_score:        float = 0.0
    inject_recommended: bool  = False      # INVARIANT JudgeLocal : toujours False
    improved_answer:    str   = ""         # INVARIANT JudgeLocal : toujours ""
    domain:             str   = ""
    palier:             int   = 0
    strengths:    List[str] = field(default_factory=list)
    weaknesses:   List[str] = field(default_factory=list)

@dataclass
class DistilledSkill:
    question_id:     str
    domain:          str
    palier:          int
    improved_answer: str
    score:           float
    dedup_hash:      str                   # SHA256[:16] de improved_answer
    judge:           str                   # Toujours "claude" en V3
    injected_at:     str = ""             # ISO 8601, rempli après store()

@dataclass
class PalierState:
    domain:             str
    current_palier:     int   = 0
    questions_done:     int   = 0
    avg_score:          float = 0.0
    unlock_threshold:   float = 0.70
    sessions_completed: int   = 0
    recent_scores:      List[float] = field(default_factory=list)  # Pour SYS-02 rétrogradation
```

---

## 4. Configuration (`eval_config.toml`)

```toml
[model]
# model non spécifié → lu depuis config.py (OLLAMA_MODEL = "qwen2.5-coder:3b")
# OLLAMA_TIMEOUT = None → invariant absolu, non configurable ici

[scoring]
min_inject_score  = 0.70   # Seuil injection lcca_context — vérifié par EvalLoop, indépendant de MemoryEngine
unlock_threshold  = 0.70   # Seuil unlock palier suivant
gatekeeper_min    = 0.30   # Seuil JudgeLocal pour transmettre à JudgeClaude

[sessions]
sessions_dir  = "EvalLoop/sessions"
state_file    = "EvalLoop/eval_state.json"
dedup_index   = "EvalLoop/eval_dedup_index.json"

[storage]
collection      = "lcca_context"
max_skill_words = 400                      # ~600 tokens en français

# ── Flags système (désactivés par défaut en V3, activables en V4) ─────────────

[sys02_retrograde]
# SYS-02 : rétrogradation de palier si 3 sessions consécutives < 0.50
retrograde_enabled    = false              # Activer en V4
retrograde_threshold  = 0.50
retrograde_window     = 3                  # Nombre de sessions consécutives

[sys03_cooldown]
# SYS-03 : pause entre chaque question pour libérer le GPU
probe_cooldown_sec = 0                     # Augmenter à 2.0 si contention GPU observée

[sys04_error_patterns]
# SYS-04 : détection des erreurs récurrentes sur une même question
track_error_patterns = false               # Activer en V4
error_repeat_threshold = 3                 # Nombre de répétitions avant alerte

[health]
# OPP-01 : métriques de santé Ollama dans session_report.md
track_health_metrics = true               # Activé par défaut — coût nul
```

---

## 5. Moteur de Probe (`probe_engine.py`)

**Invariants** :
- `OLLAMA_TIMEOUT = None` transmis tel quel — ne jamais mettre d'entier (règle LCCA absolue)
- System prompt générique — ne pas personnifier LCCA ("Tu es LCCA" est incorrect conceptuellement)
- Le probe **ne lit pas** `lcca_context` — SYS-01 reporté V4 (contention VRAM sur Quadro M2000M 4GB)

```python
# probe_engine.py
from core.ollama_client import OllamaClient
from config import OLLAMA_MODEL, OLLAMA_URL, OLLAMA_TIMEOUT, OLLAMA_MAX_TOKENS

class ProbeEngine:
    def __init__(self, model: str = None, base_url: str = None):
        self._client = OllamaClient(
            base_url   = base_url or OLLAMA_URL,
            model      = model or OLLAMA_MODEL,
            timeout    = OLLAMA_TIMEOUT,    # None — INVARIANT ABSOLU
            max_tokens = OLLAMA_MAX_TOKENS,
        )

    def probe(self, question: BenchQuestion) -> ProbeResponse:
        system = (
            "Tu es un assistant technique expert en Python et en architecture logicielle. "
            "Réponds de façon précise et structurée."
        )
        # cooldown appliqué par probe_batch(), pas ici
        ...
```

---

## 6. JudgeLocal — Gatekeeper Pur

**Invariants absolus** :
```python
inject_recommended = False    # JAMAIS — JudgeLocal ne décide jamais d'injecter
improved_answer    = ""       # JAMAIS — JudgeLocal ne produit pas de contenu injectable
```

**Algorithme** :
1. `concept_score` : matching tokenisé `\bword\b` (évite "list" dans "listing")
2. `coherence_score` : fenêtre 100 mots (pénalise le keyword stuffing)
3. `structure_score` : code blocks + listes + exemples (max 0.3, remplace length_score)
4. `final_score = concept * 0.6 + coherence * 0.2 + structure * 0.2`
5. Si `final_score < gatekeeper_min (0.30)` → rejeté, non transmis à JudgeClaude

---

## 7. JudgeClaude — Juge Qualitatif

**Conditions d'activation** :
- Flag `--judge claude` au CLI
- `JudgeLocal.final_score >= 0.30`

**Production** :
- `improved_answer` : réponse enrichie et corrigée (non vide)
- `inject_recommended = True` si `final_score >= 0.70`

---

## 8. DistillEngine — Décisions d'Architecture Verrouillées

### 8.1 Import direct (pas de lazy)

```python
# distill_engine.py
"""DistillEngine — injection des skills évalués dans MemoryEngine.

ATTENTION : Ce module importe `core.memory_engine` au chargement.
Il ne peut pas être importé sans que sys.path contienne la racine LCCA.
Point d'entrée : lcca_eval.py (configure sys.path).
Tests : conftest.py doit configurer sys.path (voir tests/conftest.py existant).
"""
from core.memory_engine import MemoryEngine  # Import direct — pas de lazy
```

Justification : EvalLoop/ est un package séparé de core/. Il n'y a pas de dépendance circulaire.
L'import lazy hérité d'EducatorAgent est du sur-engineering ici. L'échec explicite au démarrage
est préférable à une erreur masquée à l'instanciation.

### 8.2 Guard autonome — indépendant de MemoryEngine

```python
# Constante locale — source de vérité EvalLoop
_MIN_INJECT_SCORE: float = 0.70  # Redondance intentionnelle avec _THRESHOLD_CONTEXT=0.6

def _is_eligible(self, score: JudgeScore) -> bool:
    """Critères d'injection — vérifiés par EvalLoop, indépendamment des internals MemoryEngine."""
    if score.judge != "claude":
        return False
    if not score.inject_recommended:
        return False
    if score.final_score < _MIN_INJECT_SCORE:
        return False
    if not score.improved_answer.strip():
        return False
    return True
```

**Règle** : EvalLoop ne lit jamais `mem._enforce` ni aucun attribut interne de MemoryEngine.
Le seuil 0.70 est une redondance intentionnelle — pas une délégation.

### 8.3 Payload strict — clé `content` uniquement

```python
def _build_payload(self, score: JudgeScore, dedup_hash: str) -> dict:
    """
    Payload pour lcca_context.

    RÈGLE STRICTE : une seule clé textuelle autorisée = "content".
    Ne jamais ajouter "code", "snippet", "error", "text" — extract_content()
    dans memory_engine_store.py les priorise et détournerait silencieusement l'indexation.
    Ordre extract_content : ("code", "snippet", "error", "content", "text")
    """
    return {
        "content":    score.improved_answer,  # SEULE clé textuelle — invariant
        "score":      score.final_score,
        "source":     "evalloop",
        "domain":     score.domain,
        "palier":     score.palier,
        "judge":      score.judge,
        "dedup_hash": dedup_hash,
        # INTERDIT : "code", "snippet", "error", "text"
    }
```

### 8.4 Dedup index — charge-une-fois / écrit-une-fois (anti-pattern O-01)

```python
def distill(self, session_dir: Path) -> int:
    scores_path = session_dir / "scores.jsonl"
    if not scores_path.exists():
        return 0

    index = self._load_dedup_index()    # LECTURE UNIQUE avant la boucle
    injected = 0
    new_hashes: set[str] = set()

    for line in scores_path.read_text(encoding="utf-8-sig").strip().splitlines():
        if not line.strip():
            continue
        score = JudgeScore(**json.loads(line))

        if not self._is_eligible(score):
            continue

        dedup_hash = hashlib.sha256(score.improved_answer.encode()).hexdigest()[:16]

        if dedup_hash in index:
            log.debug("distill: doublon %s — skip", dedup_hash)
            continue

        payload = self._build_payload(score, dedup_hash)
        result  = self._mem.store("lcca_context", payload)

        if result.stored:
            injected += 1
            new_hashes.add(dedup_hash)
            log.info("distill: injecté %s (score=%.2f)", score.question_id, score.final_score)

    if new_hashes:
        index.update(new_hashes)
        self._save_dedup_index(index)   # ÉCRITURE UNIQUE si changements

    return injected

def _load_dedup_index(self) -> set[str]:
    try:
        data = json.loads(self._dedup_path.read_text(encoding="utf-8"))
        return set(data)                # set pour O(1) lookup
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def _save_dedup_index(self, index: set[str]) -> None:
    """Pattern T-14 — Path.replace() atomique Windows + Linux."""
    tmp = self._dedup_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(index), indent=2), encoding="utf-8")
    tmp.replace(self._dedup_path)
```

---

## 9. CurriculumTracker

**Format `eval_state.json`** :
```json
{
  "python_core": {
    "current_palier": 1,
    "questions_done": 12,
    "avg_score": 0.73,
    "unlock_threshold": 0.70,
    "sessions_completed": 3,
    "recent_scores": [0.68, 0.71, 0.75]
  }
}
```

**Règles** :
- Montée : `avg_score >= unlock_threshold` → `current_palier += 1`
- Descente (SYS-02, désactivée V3) : 3 sessions consécutives < 0.50 → `current_palier -= 1`
- Toutes les écritures via `Path.replace()` (pattern T-14)

---

## 10. CLI (`lcca_eval.py`)

```
Commandes :
  probe   --domain python_core [--palier 0] [--judge local|claude]
  judge   --session <session_dir> --judge local|claude
  distill --session <session_dir>
  run     --domain python_core [--judge local|claude]   # pipeline complet
  report  --session <session_dir>
  review-bench --domain python_core --palier 2          # validation questions draft
```

---

## 11. Métriques de Santé (OPP-01 — activé par défaut)

Chaque `session_report.md` inclut une section `## Santé Ollama` :

```markdown
## Santé Ollama
| Métrique | Valeur | Seuil alerte |
|---|---|---|
| Temps moyen probe | 8.4s | > 20s |
| Longueur moyenne réponse | 187 mots | < 50 mots |
| Taux erreur Ollama | 0% | > 5% |
| Questions complètes | 10/10 | < 8/10 |
```

Si une métrique dépasse son seuil → `log.warning` + mention `⚠️` dans le rapport.

---

## 12. Angles Morts Documentés (Non-Implémentés V3)

| ID | Description | Décision |
|----|-------------|----------|
| SYS-01 | Probe sans mémoire active — lcca_context non lu pendant l'évaluation | Reporté V4. Sur Quadro M2000M 4GB, ChromaDB embeddings + Ollama = contention VRAM. |
| SYS-02 | Pas de rétrogradation de palier | Flag `retrograde_enabled = false`. Implémentation V4. |
| SYS-04 | Pas de détection des erreurs récurrentes | Flag `track_error_patterns = false`. Implémentation V4. |
| SYS-05 | Seuil MemoryEngine conditionnel (`enforce_thresholds`) | Guard autonome dans EvalLoop — indépendant des internals MemoryEngine. |
| OPP-03 | A/B testing prompt système | Cross-session uniquement (pas de double probe en même session — 16min GPU bloqué). |

---

## 13. Règles LCCA Appliquées

| Règle | Application EvalLoop |
|-------|---------------------|
| `OLLAMA_TIMEOUT = None` invariant | ProbeEngine → `OllamaClient(timeout=None)` |
| `Path.replace()` atomique (T-14) | eval_state.json, eval_dedup_index.json, session_report.md |
| Pas d'import lazy sans raison (T-11 pattern) | DistillEngine : import direct MemoryEngine |
| `utf-8-sig` BOM Windows | Tous les `.py` EvalLoop |
| Dataclass `to_dict()` / `from_dict()` | BenchQuestion, JudgeScore, DistilledSkill, PalierState |
| `auto_push = false` | `lcca_eval.py` : 0 git push automatique |
| Logs stderr | `log = logging.getLogger("lcca.evalloop.*")` |
| Anti-pattern O-01 (pas de I/O en boucle) | DistillEngine : index chargé une fois, écrit une fois |
| Couplage interne interdit | EvalLoop ne lit jamais `mem._enforce` ni aucun attribut interne MemoryEngine |
