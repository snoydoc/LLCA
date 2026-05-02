# Sprint SI-07 — Tests d'intégration complets
<!-- AI-READY | LCCA V10.5 | Sprint SI-07 | Priorité P1 | Effort 1j | Statut : 🔲 À FAIRE -->

## Objectif

Tests d'intégration complets couvrant le pipeline Observer → Orchestrator → Auto-Fix,
les garde-fous système, et la régression sur les 1252+ tests existants.

## Contexte

- Dépendance : SI-01 ✅ à SI-05 🔲 (tous terminés)
- Tests unitaires créés dans SI-01 à SI-05 : ~80 tests
- Ce sprint : tests d'intégration pipeline + benchmark auto-fix

## Fichiers cibles

| # | Fichier | Opération | Tests |
|---|---------|-----------|-------|
| 1 | `tests/test_si_01_utils.py` | CREATE | 9 tests (SI-01) |
| 2 | `tests/test_si_integration.py` | CREATE | ~25 tests intégration |
| 3 | `tests/test_si_guardrails.py` | CREATE | ~15 tests garde-fous |

## Tests d'intégration (`test_si_integration.py`)

```python
class TestPipelineIntegration:
    """Pipeline complet Observer → Orchestrator → action."""

    def test_observe_then_decide_dry_run(self, tmp_path, si_env):
        """Observation avec signal → decide --dry-run → matched_rules non vide."""

    def test_observe_then_decide_log_only(self, tmp_path, si_env):
        """Signal slow_intent → règle log_only → actions.log mis à jour."""

    def test_observe_then_notify_no_ack(self, tmp_path, si_env, capsys):
        """Signal high severity → notify_human sans ack → message affiché."""

    def test_observe_then_notify_require_ack(self, tmp_path, si_env):
        """Signal high severity → notify avec ack → pending_actions.json mis à jour."""

    def test_approve_then_execute(self, tmp_path, si_env):
        """approve <action_id> → action exécutée → actions.log status=approved."""

    def test_observation_window_fusion(self, tmp_path, si_env):
        """3 observations, même pattern → count fusionné dans Orchestrator."""

    def test_observation_max_age_ignored(self, tmp_path, si_env):
        """Observation trop ancienne → ignorée par Orchestrator."""

    def test_cooldown_prevents_retrigger(self, tmp_path, si_env):
        """Règle déclenchée → cooldown → deuxième run → skipped."""

    def test_max_trigger_per_day(self, tmp_path, si_env):
        """Règle déclenchée max_trigger_per_day fois → bloquée."""

    def test_mode_1_blocks_retry_coder(self, tmp_path, si_env, monkeypatch):
        """Mode 1 → retry_coder_once ignoré (min_coupling_mode=2)."""

    def test_write_ahead_before_action(self, tmp_path, si_env):
        """Action qui échoue → "started" dans actions.log avant "failed"."""
```

## Tests garde-fous (`test_si_guardrails.py`)

```python
class TestGuardrails:
    """Vérification de tous les garde-fous codés en dur."""

    def test_no_autofix_without_flag(self, tmp_path):
        """AutoFix sans .auto_fix_enabled → skipped immédiat."""

    def test_no_autofix_mode_1(self, monkeypatch, tmp_path):
        """Mode 1 → AutoFix skipped."""

    def test_no_autofix_coverage_below_60(self, monkeypatch, tmp_path):
        """Coverage 55% → failed, cooldown forcé."""

    def test_no_autofix_pre_tests_red(self, monkeypatch, tmp_path):
        """Tests non verts avant patch → skipped."""

    def test_rollback_on_post_test_failure(self, monkeypatch, tmp_path):
        """Tests non verts après patch → fichier restauré exactement."""

    def test_no_autofix_patch_too_large(self, monkeypatch, tmp_path):
        """Patch > 5 lignes → skipped immédiat."""

    def test_no_multi_file_autofix(self, monkeypatch, tmp_path):
        """Tentative modification 2 fichiers → skipped."""

    def test_no_git_push(self, monkeypatch, tmp_path):
        """Succès auto-fix → git push jamais appelé."""

    def test_educator_never_modifies_rules(self, tmp_path):
        """EducatorSI.ingest() → orchestrator_rules.json inchangé."""

    def test_educator_never_modifies_whitelist(self, tmp_path):
        """EducatorSI.ingest() → auto_fix_whitelist.json inchangé."""

    def test_orchestrator_lock_prevents_double_run(self, tmp_path):
        """.orchestrator_lock présent → decide --auto skipped."""

    def test_atomic_write_no_half_json(self, tmp_path, monkeypatch):
        """Interruption simulée pendant écriture → pas de .json corrompu."""

    def test_no_infinite_retry(self, monkeypatch, tmp_path):
        """retry_coder_once → max_retries=1 → pas de 2ème tentative."""

    def test_max_5_lines_hard_limit(self, monkeypatch, tmp_path):
        """Patch exactement 6 lignes → skipped (limite dure = 5)."""

    def test_mode_3_a2abus_absent_fails_gracefully(self, monkeypatch, tmp_path):
        """Mode 3, A2ALocalBus import error → failed sans crash."""
```

## Fixture `si_env`

```python
@pytest.fixture
def si_env(tmp_path, monkeypatch):
    """
    Crée un environnement SelfImprove complet dans tmp_path.
    Redirige tous les chemins config via monkeypatch.
    """
    # Créer structure
    for d in ["observations", "auto_fixes", "patterns", "engines"]:
        (tmp_path / d).mkdir()

    # Config minimale
    cfg = {
        "general": {"coupling_mode": 2},
        "observer": {
            "interval_sec": 60,
            "wal_dir": str(tmp_path / "transactions"),
            "log_file": str(tmp_path / "lcca.log"),
            "test_results_file": str(tmp_path / "last_results.json"),
            "patterns_file": str(tmp_path / "observer_patterns.json"),
        },
        "orchestrator": {
            "observation_window": 3,
            "observation_max_age_sec": 600,
            "rules_file": str(tmp_path / "orchestrator_rules.json"),
        },
        "auto_fix": {"min_coverage": 0.60, "failure_cooldown_sec": 3600, "auto_push": False},
        "paths": {
            "self_improve_dir": str(tmp_path),
            "observations_dir": str(tmp_path / "observations"),
            "auto_fixes_dir": str(tmp_path / "auto_fixes"),
            "patterns_dir": str(tmp_path / "patterns"),
            "actions_log": str(tmp_path / "actions.log"),
            "pending_actions": str(tmp_path / "pending_actions.json"),
            "borgnes_map": str(tmp_path / "borgnes_map.json"),
        },
    }
    monkeypatch.setattr("SelfImprove.si_config.load_config", lambda: cfg)
    return cfg
```

## Benchmark auto-fix (100 runs)

```python
class TestAutoFixBenchmark:
    """Vérifie qu'aucune régression sur 100 cycles patch/rollback."""

    def test_no_regression_100_runs(self, tmp_path, si_env):
        """
        100 cycles : patch appliqué + rollback systématique.
        Le fichier source doit être identique avant et après chaque cycle.
        """
        source = "import asyncio\n\nasync def foo():\n    asyncio.create_task(bar())\n"
        target = tmp_path / "core" / "test_module.py"
        target.parent.mkdir()
        target.write_text(source, encoding="utf-8-sig")
        original = target.read_text("utf-8-sig")

        engine = AutoFixEngine(si_env)
        for i in range(100):
            target.write_text(original, "utf-8-sig")  # reset
            # Simuler le cycle patch + rollback
            snapshot = target.read_text("utf-8-sig")
            # ... appel engine avec mock coverage + tests
            assert target.read_text("utf-8-sig") == original, f"Régression au cycle {i}"
```

## Critères d'acceptation

- [ ] Tous les tests SI-01 à SI-07 : verts
- [ ] Régression globale : 1252+ tests existants toujours verts
- [ ] Benchmark 100 runs auto-fix : 0 régression
- [ ] Tous les garde-fous : testés et validés

## Protocole d'exécution

```
1. filesystem:write_file tests/test_si_01_utils.py
2. filesystem:write_file tests/test_si_integration.py
3. filesystem:write_file tests/test_si_guardrails.py
4. [relire les trois fichiers]
5. pytest tests/test_si_01_utils.py tests/test_si_integration.py tests/test_si_guardrails.py -v
6. pytest tests/ -x -q  (régression globale complète)
```

## Mise à jour skills (fin de sprint)

- **001** : pattern "si_env fixture — monkeypatch load_config → cfg dict complet"
- **002** : état tests mis à jour : +~120 tests SelfImprove (test_si_01 à test_si_guardrails)
