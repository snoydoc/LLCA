# Sprint SI-04 — Auto-Fix Engine
<!-- AI-READY | LCCA V10.5 | Sprint SI-04 | Priorité P1 | Effort 2j | Statut : 🔲 À FAIRE -->

## Objectif

Implémenter `AutoFixEngine` : corrections syntaxiques déterministes sur whitelist stricte,
vérifiées par coverage ≥ 60% et tests avant/après. SmartPatcher (libcst) pour `await`,
template string pour imports.

## Contexte

- Dépendance : SI-01 ✅, SI-02 🔲, SI-03 🔲
- `SmartPatcher.apply_patch()` existant : retourne `str`, jamais d'écriture disque
- `pytest --cov` disponible (couverture via `coverage.json`)
- Git disponible en local
- `auto_fix_whitelist.json` déjà créé (SI-01)

## Fichiers cibles

| # | Fichier | Opération | Lignes estimées |
|---|---------|-----------|-----------------|
| 1 | `SelfImprove/engines/auto_fix.py` | CREATE | ~300 lignes |
| 2 | `tests/test_si_04_autofix.py` | CREATE | ~120 lignes |

## Points de vigilance avant d'écrire le code

```
1. Lire core/smart_patcher.py → vérifier signature apply_patch() exacte
2. Lire core/smart_patcher_transformers.py → vérifier transformer "add_await"
3. Vérifier format WAL → adapter _get_latest_signal()
4. Vérifier format coverage.json (pytest-cov) → adapter _check_coverage()
```

## Critères d'acceptation

- [ ] Pattern `coroutine_never_awaited` : SmartPatcher appliqué, tests verts après
- [ ] Pattern `missing_import` : import ajouté en tête, pas de doublon
- [ ] Coverage < 60% → statut "failed", cooldown 1h, aucun patch écrit
- [ ] Tests non verts avant patch → statut "skipped", aucun patch écrit
- [ ] Tests non verts après patch → rollback + statut "failed"
- [ ] Patch > 5 lignes → statut "skipped" immédiat
- [ ] Commit sur branche `auto-fix/<pattern>-YYYYMMDD-HHMMSS` jamais sur main
- [ ] `auto_push = false` : aucun `git push` exécuté
- [ ] `.auto_fix_enabled` absent → statut "skipped" immédiat
- [ ] Mode couplage < 2 → statut "skipped" immédiat
- [ ] Fichier hors `allowed_files` → statut "skipped"

## Tests (`tests/test_si_04_autofix.py`)

```python
class TestAutoFixEngine:
    def test_flag_absent_returns_skipped(self, tmp_path): ...
    def test_mode_1_returns_skipped(self, monkeypatch, tmp_path): ...
    def test_pattern_not_in_whitelist(self, tmp_path): ...
    def test_file_not_in_allowed_files(self, tmp_path): ...
    def test_coverage_below_threshold_returns_failed(self, monkeypatch, tmp_path): ...
    def test_pre_patch_tests_failing_returns_skipped(self, monkeypatch, tmp_path): ...
    def test_patch_too_many_lines_returns_skipped(self, monkeypatch, tmp_path): ...
    def test_post_patch_tests_failing_triggers_rollback(self, monkeypatch, tmp_path): ...
    def test_missing_import_fix_adds_import(self, monkeypatch, tmp_path): ...
    def test_missing_import_no_duplicate(self, monkeypatch, tmp_path): ...
    def test_success_creates_patch_file(self, monkeypatch, tmp_path): ...
    def test_success_writes_auto_fix_success_log(self, monkeypatch, tmp_path): ...
    def test_rollback_restores_file(self, tmp_path): ...
    def test_auto_push_never_called(self, monkeypatch, tmp_path): ...
```

## Protocole d'exécution

```
1. filesystem:read_text_file core/smart_patcher.py       → signature apply_patch()
2. filesystem:read_text_file core/smart_patcher_transformers.py
3. filesystem:read_text_file SelfImprove/auto_fix_whitelist.json
4. filesystem:read_text_file SelfImprove/engines/orchestrator.py  → voir _action_trigger_auto_fix
5. filesystem:write_file SelfImprove/engines/auto_fix.py
6. filesystem:write_file tests/test_si_04_autofix.py
7. [relire les deux fichiers]
8. pytest tests/test_si_04_autofix.py -v
9. pytest tests/ -x -q  (régression globale)
```

## Mise à jour skills (fin de sprint)

- **001** : règle "AutoFixEngine — SmartPatcher retourne str, AutoFixEngine écrit disque"
- **001** : règle "coverage check — pytest --cov → coverage.json → line_rate"
- **002** : `SelfImprove/engines/auto_fix.py` ajouté à l'arborescence
- **003** : anti-pattern "auto_push = True — interdit, rollback si tests non verts post-patch"
