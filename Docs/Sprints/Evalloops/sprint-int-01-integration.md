# INT-01 — Test d'Intégration Pipeline Complet
**Sprint** : INT-01
**Statut** : À FAIRE
**Durée estimée** : 0.5 session
**Dépendances** : EVAL-01, EVAL-02, EVAL-03, EVAL-04, EVAL-05
**Tests cibles** : 5 tests intégration (`tests/test_eval_integration.py`)

---

## Objectif

Valider le pipeline complet de bout en bout avec tous les composants mockés.
C'est le filet de sécurité final avant le premier usage en production.

Les tests d'intégration valident les **contrats entre composants**, pas les composants
individuellement (déjà couverts par EVAL-01 à EVAL-05).

---

## Fichiers à créer

| Fichier | Type | Notes |
|---------|------|-------|
| `tests/test_eval_integration.py` | Python | 5 tests bout-en-bout |

---

## Architecture du test d'intégration

```python
# Helpers communs
def _make_session_dir(tmp_path: Path) -> Path:
    """Crée une structure session minimale."""
    session = tmp_path / "sessions" / "2026-04-24_14-30"
    session.mkdir(parents=True)
    return session

def _make_config(tmp_path: Path) -> dict:
    """Config minimale sans dépendance à eval_config.toml."""
    return {
        "scoring": {
            "min_inject_score": 0.70,
            "unlock_threshold": 0.70,
            "gatekeeper_min":   0.30,
        },
        "sessions": {
            "sessions_dir": str(tmp_path / "sessions"),
            "state_file":   str(tmp_path / "eval_state.json"),
            "dedup_index":  str(tmp_path / "eval_dedup_index.json"),
        },
        "storage": {
            "collection":    "lcca_context",
        },
        "sys02_retrograde": {"retrograde_enabled": False},
        "sys03_cooldown":   {"probe_cooldown_sec": 0},
        "sys04_error_patterns": {"track_error_patterns": False},
    }
```

---

## 5 Tests d'Intégration

### Test 1 — Pipeline probe → judge_local → scores.jsonl

```python
def test_pipeline_probe_to_scores(tmp_path):
    """
    ProbeEngine (mocké) → JudgeLocal (réel) → scores.jsonl écrit correctement.
    Valide le contrat ProbeResponse → JudgeScore → sérialisation JSONL.
    """
    # Setup
    question = BenchQuestion(
        id="python_core/p0/gil_001",
        domain="python_core", palier=0,
        question="Qu'est-ce que le GIL ?",
        expected_concepts=["GIL", "thread", "CPython"],
    )
    fake_response = ProbeResponse(
        question_id="python_core/p0/gil_001",
        question=question,
        response="Le GIL (Global Interpreter Lock) protège l'interpréteur CPython. "
                 "Il empêche plusieurs threads d'exécuter du bytecode simultanément.",
        model="qwen2.5-coder:3b",
        duration_sec=8.4,
        timestamp="2026-04-24T14:30:00Z",
    )

    # Exécution
    session_dir   = _make_session_dir(tmp_path)
    judge         = JudgeLocal()
    score         = judge.score(question, fake_response)

    responses_path = session_dir / "responses.jsonl"
    scores_path    = session_dir / "scores.jsonl"
    responses_path.write_text(json.dumps(fake_response.to_dict()) + "\n", encoding="utf-8-sig")
    scores_path.write_text(json.dumps(score.to_dict()) + "\n", encoding="utf-8-sig")

    # Assertions
    loaded = JudgeScore(**json.loads(scores_path.read_text(encoding="utf-8-sig").strip()))
    assert loaded.judge == "local"
    assert loaded.inject_recommended is False
    assert loaded.improved_answer == ""
    assert 0.0 <= loaded.final_score <= 1.0
```

### Test 2 — Pipeline distill avec JudgeClaude stub

```python
def test_pipeline_distill_claude(tmp_path):
    """
    scores.jsonl avec 1 entrée JudgeClaude éligible → DistillEngine injecte.
    MemoryEngine mocké — valide le payload et le contrat store().
    """
    session_dir = _make_session_dir(tmp_path)
    config      = _make_config(tmp_path)

    # Score JudgeClaude éligible
    score = JudgeScore(
        question_id        = "python_core/p0/gil_001",
        judge              = "claude",
        final_score        = 0.82,
        inject_recommended = True,
        improved_answer    = "Le GIL est un verrou global de CPython qui sérialise les threads.",
        domain             = "python_core",
        palier             = 0,
    )
    (session_dir / "scores.jsonl").write_text(
        json.dumps(score.to_dict()) + "\n", encoding="utf-8-sig"
    )

    # Mocker MemoryEngine.store()
    with patch("EvalLoop.engines.distill_engine.MemoryEngine") as MockMem:
        mock_mem = MockMem.return_value
        mock_mem.store.return_value = StoreResult(stored=True, collection="lcca_context", entry_id="abc123")

        engine  = DistillEngine(
            dedup_path = Path(config["sessions"]["dedup_index"]),
            config     = config,
        )
        injected = engine.distill(session_dir)

    assert injected == 1
    mock_mem.store.assert_called_once()
    call_args = mock_mem.store.call_args
    assert call_args[0][0] == "lcca_context"
    payload = call_args[0][1]
    assert "content" in payload
    assert "code" not in payload
    assert "snippet" not in payload
```

### Test 3 — Curriculum update après session

```python
def test_pipeline_curriculum_update(tmp_path):
    """
    CurriculumTracker.update_state() après 5 scores → eval_state.json mis à jour.
    Valide la persistance et le calcul de avg_score.
    """
    config  = _make_config(tmp_path)
    tracker = CurriculumTracker(
        state_path     = Path(config["sessions"]["state_file"]),
        benchmarks_dir = tmp_path / "benchmarks",
        config         = config,
    )

    scores = [0.65, 0.70, 0.72, 0.68, 0.75]
    for s in scores:
        tracker.update_state("python_core", s)

    state = tracker.get_state("python_core")
    assert state.questions_done == 5
    assert abs(state.avg_score - sum(scores) / len(scores)) < 0.01
    assert state.current_palier == 0  # Pas encore 0.70 de moyenne (0.70 exactement → palier 1)
```

### Test 4 — Dedup cross-session (invariant I/O)

```python
def test_pipeline_dedup_cross_session(tmp_path):
    """
    Même improved_answer dans deux sessions différentes → deuxième distill() retourne 0.
    Valide que eval_dedup_index.json persiste correctement entre deux appels.
    """
    config      = _make_config(tmp_path)
    session1    = _make_session_dir(tmp_path)
    session2    = tmp_path / "sessions" / "2026-04-25_10-00"
    session2.mkdir(parents=True)

    same_answer = "Le GIL est un verrou global de CPython."
    score = JudgeScore(
        question_id="python_core/p0/gil_001", judge="claude",
        final_score=0.80, inject_recommended=True, improved_answer=same_answer,
        domain="python_core", palier=0,
    )
    for s_dir in [session1, session2]:
        (s_dir / "scores.jsonl").write_text(json.dumps(score.to_dict()) + "\n", encoding="utf-8-sig")

    with patch("EvalLoop.engines.distill_engine.MemoryEngine") as MockMem:
        MockMem.return_value.store.return_value = StoreResult(stored=True, collection="lcca_context", entry_id="x")
        engine = DistillEngine(Path(config["sessions"]["dedup_index"]), config)

        assert engine.distill(session1) == 1   # Première fois : injecté
        assert engine.distill(session2) == 0   # Même hash : ignoré
```

### Test 5 — Invariants JudgeLocal jamais injectés

```python
def test_pipeline_judge_local_never_in_distill(tmp_path):
    """
    scores.jsonl avec uniquement des entrées JudgeLocal → DistillEngine injecte 0.
    Même avec final_score=0.99, JudgeLocal n'est jamais éligible à l'injection.
    """
    config      = _make_config(tmp_path)
    session_dir = _make_session_dir(tmp_path)

    # Score local avec score parfait — ne doit jamais être injecté
    score = JudgeScore(
        question_id="python_core/p0/gil_001", judge="local",
        final_score=0.99, inject_recommended=False, improved_answer="",
        domain="python_core", palier=0,
    )
    (session_dir / "scores.jsonl").write_text(json.dumps(score.to_dict()) + "\n", encoding="utf-8-sig")

    with patch("EvalLoop.engines.distill_engine.MemoryEngine"):
        engine   = DistillEngine(Path(config["sessions"]["dedup_index"]), config)
        injected = engine.distill(session_dir)

    assert injected == 0   # INVARIANT : JudgeLocal n'injecte jamais
```

---

## Checklist

```
[ ] tests/test_eval_integration.py créé (5 tests)
[ ] pytest tests/test_eval_integration.py -v → 5 passed, 0 failed
[ ] pytest tests/test_eval_*.py -v → 60 passed, 0 failed (suite complète)
[ ] Vérifier qu'aucun test d'intégration ne fait d'appel réseau réel (Ollama, Anthropic)
[ ] Vérifier que MemoryEngine est toujours mocké dans les tests d'intégration
[ ] git commit -m "INT-01: tests intégration pipeline complet"
[ ] Mise à jour 002-context.md : EvalLoop V3 + compteur tests
```

---

## État Final Attendu (Post INT-01)

```
tests/
  test_eval_01_types.py        15 tests  ✅
  test_eval_02_judge.py        15 tests  ✅
  test_eval_03_curriculum.py   10 tests  ✅
  test_eval_04_distill.py      10 tests  ✅
  test_eval_05_cli.py           5 tests  ✅
  test_eval_integration.py      5 tests  ✅
  ─────────────────────────────────────
  Total EvalLoop               60 tests

EvalLoop/
  __init__.py
  evalloop_types.py
  eval_config.toml
  eval_state.json
  eval_dedup_index.json
  README_EvalLoop.md
  benchmarks/python_core/palier_0.json   (10 questions)
  benchmarks/python_core/palier_1.json   (10 questions)
  engines/
    probe_engine.py
    judge_engine.py
    distill_engine.py
    curriculum_tracker.py
    session_reporter.py
  judges/
    judge_base.py
    judge_local.py
    judge_claude.py       (stub V3)
  sessions/               (créé au premier run)

lcca_eval.py              (CLI racine)
```
