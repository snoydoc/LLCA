# Spec 10 — Recovery, Executor & ErrorAnalyzer
> **Modules** : `core/recovery_service.py`, `core/executor.py`, `core/error_analyzer.py`
> **Sprint** : 06 | **Statut** : ✅ VALIDÉ

---

## 1. Vue d'ensemble

Ces trois modules forment la **couche de robustesse** de LCCA :

| Module | Rôle |
|--------|------|
| `RecoveryService` | Détecte et répare les transactions orphelines au démarrage |
| `Executor` | Valide la syntaxe et lance pytest après modification |
| `ErrorAnalyzer` | Analyse les exceptions et génère des suggestions LLM |

---

## 2. RecoveryService

### `boot_check() → List[str]`

Lit le WAL JSONL ligne par ligne et retourne les `tx_id` orphelins.

**Définition d'une transaction orpheline** : a un `BEGIN` sans `COMMIT` ni `ROLLBACK`.

```python
open_tx: Dict[str, dict] = {}

for line in wal:
    if type == "BEGIN":
        open_tx[tx_id] = entry
    elif type in ("COMMIT", "ROLLBACK"):
        open_tx.pop(tx_id, None)

return list(open_tx.keys())
```

### `auto_recover_pending(orphaned_ids) → Dict[str, str]`

Résultats possibles par TX :
- `"committed"` — toutes les ops sont complètes → commit tardif dans WAL
- `"rolled_back"` — au moins une op incomplète → restore depuis `.bak`
- `"skipped"` — TX vide (BEGIN seulement, 0 ops)
- `"failed"` — exception pendant la récupération

**Logique de décision :**
```
_reconstruct_tx_state(tx_id):
    ops_started  = {op_id → target_path}  (depuis OP_START)
    ops_succeeded = {op_id}               (depuis OP_SUCCESS)
    incomplete = ops_started.keys() - ops_succeeded

if len(incomplete) == 0 → commit tardif
else → rollback depuis backups
```

**Commit tardif (late commit) :**
```python
self.tx_manager._write_wal({
    "type": "COMMIT", "tx_id": tx_id,
    "n_ops": n_ops, "recovery": True,
    "timestamp": "..."
})
```

**Rollback depuis backups :**
```
transactions/{tx_id}/{filename}_{op_id}.bak → copie vers target_path
```

---

## 3. Executor

### API

```python
class Executor:
    def __init__(self, workspace: Path, tests_dir: Path, timeout_sec: int = 30)

    def validate(self, modified_files: List[str]) → ValidationResult
    def check_syntax(self, file_path: str) → Optional[str]   # None si OK
    def run_tests(self) → Tuple[bool, str]
```

### `ValidationResult` (dataclass)
```python
@dataclass
class ValidationResult:
    passed:        bool
    syntax_errors: List[str]   # "file.py:10: invalid syntax"
    test_failures: List[str]   # Lignes "FAILED ..." de pytest
    test_output:   str
    duration_ms:   int
```

### `check_syntax(file_path) → Optional[str]`
```python
source = full_path.read_text(encoding="utf-8-sig")
compile(source, file_path, "exec")   # raise SyntaxError si invalide
# Retourne None si OK, "file:line: msg" si erreur
```

### `run_tests() → Tuple[bool, str]`
```python
subprocess.run(
    [sys.executable, "-m", "pytest", str(tests_dir), "-x", "-q", "--tb=short", "--no-header"],
    capture_output=True, text=True, timeout=timeout_sec
)
# Retourne (True, "Pas de tests trouvés — skip") si aucun test_*.py
```

### ⚠️ Règle critique : pas de pytest depuis une TX active
Appeler `run_tests()` depuis `_validate_changes()` causerait un **timeout garanti** (toute la suite de tests est lancée en subprocess pendant une transaction ouverte). Utiliser UNIQUEMENT `check_syntax()` depuis l'intérieur d'une TX.

```python
# ✅ CORRECT — depuis _validate_changes()
executor = Executor(workspace=ws, tests_dir=Path("/dev/null"))
executor.check_syntax(rel_path)

# ❌ INCORRECT — timeout garanti
executor.validate(files)   # appelle run_tests() en subprocess
```

---

## 4. ErrorAnalyzer

### `ErrorReport` (dataclass)
```python
@dataclass
class ErrorReport:
    error_type:   str           # "SyntaxError", "ImportError", etc.
    file:         str
    line:         Optional[int]
    message:      str
    suggestion:   str           # Texte actionnable pour le prochain prompt LLM
    severity:     str           # "blocking" | "warning" | "info"
    auto_fixable: bool          # True si LCCA peut corriger sans LLM
```

### `analyze(error, file_path, source) → ErrorReport`

Dispatch par type :
| Exception | Méthode |
|-----------|---------|
| `SyntaxError` | `analyze_syntax_error()` |
| `ImportError`, `ModuleNotFoundError` | `analyze_import_error()` |
| `AttributeError` | `_analyze_attribute_error()` |
| `NameError` | `_analyze_name_error()` |
| Autres | `analyze_generic()` |

### Table de suggestions SyntaxError
```python
_SYNTAX_SUGGESTIONS = {
    "unexpected indent":    "Indentation incorrecte ligne {line}...",
    "expected an indented": "Bloc attendu mais non indenté...",
    "unexpected EOF":       "Fin de fichier inattendue. Parenthèse non fermée.",
    "invalid syntax":       "Syntaxe invalide ligne {line}. Contexte: {context}",
    "EOL while scanning":   "Chaîne non fermée ligne {line}.",
}
```

### `auto_fixable` (ImportError uniquement)
`True` si le module manquant est listé dans `requirements.txt`.
```python
# requirements.txt : "libcst>=1.1.0" → packages = {"libcst", "libcst"}
pkg = re.split(r"[><=!;]", line)[0].strip().lower()
```

### `generate_fix_prompt(report, context) → str`
Prompt LLM < 200 tokens (~800 chars) :
```
"Erreur {type} [{file}:{line}]: {message}. Corriger en: {suggestion}\n\nContexte:\n```python\n{source[:300]}\n```"
```

### `try_auto_fix(report, patcher, workspace) → bool`
V1 : Gère uniquement `ImportError` avec `auto_fixable=True`.
Appelle `patcher.apply_patch(file, "add_import", module=module_name)`.

---

## 5. Intégration système

```
Boot LCCA :
    RecoveryService.boot_check()
        └── auto_recover_pending(orphaned_ids)

Transaction execute() :
    _validate_changes() → Executor.check_syntax() (JAMAIS run_tests)

Après erreur :
    ErrorAnalyzer.analyze(exc, file, source)
        └── generate_fix_prompt(report, context)
        └── try_auto_fix(report, patcher) si auto_fixable
```
