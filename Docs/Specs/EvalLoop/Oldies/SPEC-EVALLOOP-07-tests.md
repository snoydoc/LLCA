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
