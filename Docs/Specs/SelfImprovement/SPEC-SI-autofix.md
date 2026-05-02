# LCCA SelfImprove V10.5 — Spécification Technique : Auto-Fix Engine
<!-- AI-READY | LCCA V10.5 | SelfImprovement | Module : AutoFix | Priorité P1 -->

## Responsabilité unique

Appliquer des corrections syntaxiques déterministes sur une whitelist stricte,
vérifiées par tests avant et après. Jamais de logique métier modifiée.

---

## Classe : `AutoFixEngine`

Fichier : `SelfImprove/engines/auto_fix.py`

```python
class AutoFixEngine:
    def __init__(self, cfg: dict | None = None): ...
    def run(self, pattern_id: str) -> str: ...
    # retourne "success" | "failed" | "skipped"

    def _check_whitelist(self, pattern_id: str) -> dict | None: ...
    def _check_coverage(self, module_path: str) -> bool: ...
    def _run_pytest(self, module_path: str, report_file: str) -> bool: ...
    def _apply_patch(self, pattern: dict, signal: dict) -> str | None: ...
    def _commit_fix(self, pattern_id: str, file_path: str) -> str: ...
    def _rollback(self, file_path: str, snapshot: str) -> None: ...
```

---

## Stratégie de correction par pattern

### `coroutine_never_awaited` — SmartPatcher (libcst)

```python
def _fix_coroutine_never_awaited(self, file_path: str, signal: dict) -> str:
    """
    Utilise SmartPatcher.apply_patch() → retourne str (n'écrit jamais disque).
    Le patch libcst ajoute 'await' devant l'expression fautive.
    """
    from core.smart_patcher import SmartPatcher

    source = Path(file_path).read_text(encoding="utf-8-sig")
    patcher = SmartPatcher()

    patch = {
        "operation": "add_await",
        "target_function": signal["context"]["function"],
        "coroutine_name": signal["context"]["error_message"].split("'")[1],
    }
    patched_source = patcher.apply_patch(source, patch)
    # apply_patch() retourne str — règle invariante LCCA (skill 001)
    return patched_source
```

### `missing_import` — Template string

```python
def _fix_missing_import(self, file_path: str, signal: dict) -> str:
    """
    Ajoute 'import X' en tête de fichier via template string.
    Pas besoin d'AST pour une insertion en tête.
    """
    module_name = signal["context"]["error_message"].split("'")[1].split(".")[0]
    source = Path(file_path).read_text(encoding="utf-8-sig")

    import_line = f"import {module_name}\n"
    if import_line.strip() in source:
        return source  # déjà présent, rien à faire

    # Insertion après les commentaires/docstrings initiaux
    lines = source.splitlines(keepends=True)
    insert_at = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped == "":
            insert_at = i + 1
        else:
            break

    lines.insert(insert_at, import_line)
    return "".join(lines)
```

---

## Processus complet avec guards

```python
def run(self, pattern_id: str) -> str:
    cfg = self._cfg
    af_dir = Path(cfg["paths"]["auto_fixes_dir"])
    si_dir = Path(cfg["paths"]["self_improve_dir"])

    # Guard 1 — flag activé
    if not (si_dir / ".auto_fix_enabled").exists():
        log.info("Auto-Fix désactivé (flag absent)")
        return "skipped"

    # Guard 2 — mode couplage
    if get_coupling_mode() < 2:
        log.info("Auto-Fix ignoré : mode couplage %s < 2", get_coupling_mode())
        return "skipped"

    # Guard 3 — whitelist
    pattern = self._check_whitelist(pattern_id)
    if pattern is None:
        log.info("Pattern %s absent de la whitelist", pattern_id)
        return "skipped"

    # Récupération du signal depuis dernière observation
    signal = self._get_latest_signal(pattern_id)
    if signal is None:
        log.info("Aucun signal actif pour %s", pattern_id)
        return "skipped"

    file_path = signal.get("file", "")
    if not file_path or not Path(file_path).exists():
        log.warning("Fichier cible introuvable : %s", file_path)
        return "failed"

    # Guard 4 — fichier dans allowed_files
    if not self._file_allowed(file_path, pattern.get("allowed_files", [])):
        log.info("Fichier %s hors allowed_files", file_path)
        return "skipped"

    # Guard 5 — coverage ≥ 60%
    if not self._check_coverage(file_path):
        log_action(pattern_id, "trigger_auto_fix", file_path, "failed",
                   "coverage < 60%", cfg)
        force_cooldown(pattern_id, cfg["auto_fix"]["failure_cooldown_sec"])
        return "failed"

    # Guard 6 — tests verts AVANT patch
    if not self._run_pytest(file_path, str(si_dir / "observations" / "pre_fix.json")):
        log.warning("Tests non verts avant auto-fix sur %s — abandon", file_path)
        log_action(pattern_id, "trigger_auto_fix", file_path, "skipped",
                   "tests non verts avant patch", cfg)
        return "skipped"

    # Snapshot avant modification
    snapshot = Path(file_path).read_text(encoding="utf-8-sig")

    # Application du patch
    patched = self._apply_patch(pattern, signal)
    if patched is None:
        log.error("Patch échoué pour %s", pattern_id)
        return "failed"

    # Guard 7 — max 5 lignes modifiées
    diff_lines = sum(
        1 for a, b in zip(snapshot.splitlines(), patched.splitlines()) if a != b
    ) + abs(len(snapshot.splitlines()) - len(patched.splitlines()))
    if diff_lines > 5:
        log.warning("Patch > 5 lignes (%s) — abandon", diff_lines)
        return "skipped"

    # Écriture du patch fichier
    patch_seq = self._next_patch_seq(af_dir)
    patch_path = af_dir / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{patch_seq:03d}.patch"
    patch_path.write_text(patched, encoding="utf-8-sig")

    # Écriture du fichier source modifié
    Path(file_path).write_text(patched, encoding="utf-8-sig")

    # Guard 8 — tests verts APRÈS patch
    if not self._run_pytest(file_path, str(si_dir / "observations" / "post_fix.json")):
        log.error("Tests non verts après patch — rollback de %s", file_path)
        self._rollback(file_path, snapshot)
        log_action(pattern_id, "trigger_auto_fix", file_path, "failed",
                   "régression post-patch — rollback effectué", cfg)
        force_cooldown(pattern_id, cfg["auto_fix"]["failure_cooldown_sec"])
        return "failed"

    # Commit et notification
    commit_hash = self._commit_fix(pattern_id, file_path)
    log_action(pattern_id, "trigger_auto_fix", file_path, "success",
               f"commit={commit_hash}", cfg)

    with open(si_dir / "auto_fix_success.log", "a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now(timezone.utc).isoformat()}|{pattern_id}|{file_path}|{commit_hash}\n")

    print(f"[AUTO-FIX] Succès : {pattern_id} sur {file_path} (commit {commit_hash[:8]})")
    return "success"
```

---

## Coverage check

```python
def _check_coverage(self, file_path: str) -> bool:
    """
    Lance pytest --cov sur le module cible, lit coverage.json.
    Retourne True si line_rate >= min_coverage (config.toml).
    """
    import subprocess, sys, json as _json
    module = Path(file_path).stem
    cov_json = Path(self._cfg["paths"]["self_improve_dir"]) / "observations" / "coverage.json"

    result = subprocess.run(
        [sys.executable, "-m", "pytest", file_path,
         f"--cov={module}", "--cov-report=json",
         f"--cov-config=.coveragerc",
         "--quiet", "--no-header"],
        capture_output=True, timeout=120,
    )

    if not cov_json.exists():
        log.warning("coverage.json absent après pytest --cov")
        return False

    data = _json.loads(cov_json.read_text("utf-8"))
    # Structure coverage.json : {"files": {"path": {"summary": {"line_rate": 0.78}}}}
    for path_key, file_data in data.get("files", {}).items():
        if module in path_key:
            rate = file_data.get("summary", {}).get("line_rate", 0.0)
            log.info("Coverage %s : %.0f%%", file_path, rate * 100)
            return rate >= self._cfg["auto_fix"]["min_coverage"]

    log.warning("Module %s absent du rapport coverage", module)
    return False
```

---

## Commit Git isolé

```python
def _commit_fix(self, pattern_id: str, file_path: str) -> str:
    import subprocess, sys
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    branch = f"auto-fix/{pattern_id}-{ts}"

    subprocess.run(["git", "checkout", "-b", branch], capture_output=True)
    subprocess.run(["git", "add", file_path], capture_output=True)
    result = subprocess.run(
        ["git", "commit", "-m", f"[AUTO-FIX SAFE] {pattern_id} on {Path(file_path).name}"],
        capture_output=True,
    )
    # auto_push = false codé en dur — jamais de git push
    hash_line = result.stdout.decode("utf-8", errors="replace")
    return hash_line.split("]")[0].split("[")[-1].strip() if "]" in hash_line else "unknown"
```

---

## Rollback

```python
def _rollback(self, file_path: str, snapshot: str) -> None:
    """Restaure le fichier depuis le snapshot pré-patch."""
    Path(file_path).write_text(snapshot, encoding="utf-8-sig")
    log.info("Rollback effectué sur %s", file_path)
```

---

## Interdictions strictes (codées en dur — jamais à lever)

- ❌ `auto_push = True` — push git interdit
- ❌ Patch > 5 lignes — refus immédiat
- ❌ Modification de plus d'un fichier
- ❌ Tout patch non syntaxique (logique métier)
- ❌ Auto-fix si coverage < 60%
- ❌ Auto-fix si tests non verts avant patch

---

## Conventions LCCA obligatoires

- `SmartPatcher.apply_patch()` retourne `str` uniquement — n'écrit jamais disque
- Fichiers `.py` : encodage `utf-8-sig` (BOM Windows)
- `sys.executable` pour tout subprocess Python
- `log.info("msg %s", var)` — jamais de f-strings dans les logs
- `Path` partout — jamais `os.path`
