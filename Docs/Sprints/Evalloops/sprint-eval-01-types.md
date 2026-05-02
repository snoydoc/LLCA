# EVAL-01 — Dataclasses + Configuration
**Sprint** : EVAL-01
**Statut** : À FAIRE
**Durée estimée** : 1 session
**Dépendances** : Aucune
**Tests cibles** : 15 tests (`tests/test_eval_01_types.py`)

---

## Objectif

Poser les fondations du package EvalLoop : les 5 dataclasses, la configuration TOML,
et les fichiers d'état initiaux. Pas de logique métier dans ce sprint — uniquement les types.

---

## Fichiers à créer

| Fichier | Type | Notes |
|---------|------|-------|
| `EvalLoop/__init__.py` | Vide | Package Python |
| `EvalLoop/evalloop_types.py` | Python | 5 dataclasses + to_dict/from_dict |
| `EvalLoop/eval_config.toml` | TOML | Config globale (voir Spec_EvalLoop_Final.md §4) |
| `EvalLoop/eval_state.json` | JSON | `{}` — état initial vide |
| `EvalLoop/eval_dedup_index.json` | JSON | `[]` — index dedup vide |
| `EvalLoop/README_EvalLoop.md` | Markdown | Limitations V3 documentées |
| `tests/test_eval_01_types.py` | Python | 15 tests |

---

## Contenu `evalloop_types.py`

5 dataclasses à implémenter avec `to_dict()` / `from_dict()` complets :

- `BenchQuestion` — question curriculum avec statut draft/active
- `ProbeResponse` — réponse brute Ollama
- `JudgeScore` — score d'un juge (local ou claude)
- `DistilledSkill` — entrée prête pour MemoryEngine
- `PalierState` — état courant d'un domaine (avec `recent_scores: List[float]` pour SYS-02)

**Invariants à encoder dans les valeurs par défaut** :
```python
@dataclass
class JudgeScore:
    inject_recommended: bool = False   # INVARIANT — False par défaut
    improved_answer:    str  = ""      # INVARIANT — vide par défaut
```

**Encodage** : `# -*- coding: utf-8-sig -*-` en en-tête de fichier.

---

## Contenu `README_EvalLoop.md`

```markdown
# EvalLoop V3 — Benchmark Curriculum LCCA

## Ce que fait EvalLoop V3
- Évalue la qualité des réponses de LCCA sur des questions progressives
- Adapte la difficulté selon les performances (curriculum par paliers)
- Injecte les corrections JudgeClaude dans MemoryEngine (lcca_context)
- Mesure les métriques de santé Ollama (temps, longueur, taux erreur)

## Limitations V3 (angles morts documentés)

### SYS-01 : Probe sans mémoire active
EvalLoop V3 est un **benchmark sans mémoire active**.
Le probe ne lit pas lcca_context pendant l'évaluation — les skills déjà injectés
ne sont pas fournis au modèle comme contexte.
Raison : contention VRAM sur Quadro M2000M 4GB (ChromaDB embeddings + Ollama 3b).
Statut : reporté V4.

### SYS-02 : Rétrogradation désactivée
La montée de palier est unidirectionnelle en V3.
Flag `retrograde_enabled = false` dans eval_config.toml.
Activer en V4 si stagnation observée.

### SYS-04 : Détection d'erreurs récurrentes désactivée
Les erreurs répétées sur une même question ne génèrent pas d'alerte.
Flag `track_error_patterns = false` dans eval_config.toml.

## Règles d'utilisation

### Payload DistillEngine — règle stricte
Le payload injecté dans MemoryEngine contient une seule clé textuelle : `"content"`.
Ne jamais ajouter `"code"`, `"snippet"`, `"error"`, `"text"` — ces clés sont
prioritaires dans extract_content() et détourneraient silencieusement l'indexation.

### Import et sys.path
EvalLoop ne peut pas être importé sans sys.path configuré sur la racine LCCA.
Point d'entrée : `lcca_eval.py` (configure sys.path automatiquement).
Tests : `tests/conftest.py` configure sys.path (existant).
```

---

## Tests (`test_eval_01_types.py`)

15 tests obligatoires :

```
BenchQuestion
  test_bench_question_defaults          → status=="active", tags==[]
  test_bench_question_to_dict           → round-trip sérialisé proprement
  test_bench_question_from_dict         → reconstruit correctement depuis dict
  test_bench_question_status_draft      → peut avoir status=="draft"

JudgeScore
  test_judge_score_invariant_inject     → inject_recommended==False par défaut (INVARIANT)
  test_judge_score_invariant_answer     → improved_answer=="" par défaut (INVARIANT)
  test_judge_score_to_dict              → tous les champs présents
  test_judge_score_from_dict            → round-trip complet

ProbeResponse
  test_probe_response_to_dict
  test_probe_response_from_dict

DistilledSkill
  test_distilled_skill_score_threshold  → score=0.70 est valide (≥ _MIN_INJECT_SCORE)
  test_distilled_skill_score_low        → score=0.65 < 0.70 (documentation du seuil)
  test_distilled_skill_to_dict

PalierState
  test_palier_state_defaults            → palier=0, avg_score=0.0, recent_scores==[]
  test_palier_state_to_dict
```

---

## Smoke test manuel (à exécuter après création)

```bash
cd D:\LLMCodeAgent
python -c "
import sys; sys.path.insert(0, 'D:\\LLMCodeAgent')
from EvalLoop.evalloop_types import BenchQuestion, JudgeScore, PalierState
q = BenchQuestion(id='test', domain='python_core', palier=0, question='?', expected_concepts=['GIL'])
s = JudgeScore(question_id='test', judge='local')
p = PalierState(domain='python_core')
assert s.inject_recommended is False
assert s.improved_answer == ''
assert p.recent_scores == []
print('EVAL-01 smoke test : OK')
"
```

---

## Checklist

```
[ ] EvalLoop/__init__.py créé (vide)
[ ] EvalLoop/evalloop_types.py créé (5 dataclasses + to_dict/from_dict)
[ ] EvalLoop/eval_config.toml créé (copier depuis Spec_EvalLoop_Final.md §4)
[ ] EvalLoop/eval_state.json créé → {}
[ ] EvalLoop/eval_dedup_index.json créé → []
[ ] EvalLoop/README_EvalLoop.md créé (limitations V3 documentées)
[ ] tests/test_eval_01_types.py créé (15 tests)
[ ] smoke test manuel → "OK"
[ ] pytest tests/test_eval_01_types.py -v → 15 passed, 0 failed
[ ] git add EvalLoop/ && git commit -m "EVAL-01: dataclasses + config"
```
