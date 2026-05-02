# 🛡️ Sprint 06 — Recovery Service, Executor & Error Analyzer

> **Durée estimée** : 4 jours  
> **Statut** : ⚪ À FAIRE  
> **Priorité** : 🟠 Haute  
> **Dépend de** : Sprint 02 (TX Manager), Sprint 03 (SmartPatcher), Sprint 05 (MemPalace)  
> **Objectif** : Implémenter le service de recovery au boot, l'exécuteur sandbox, et l'analyseur d'erreurs automatique.

---

## 🎯 Objectifs du Sprint

Ce sprint rend LCCA **résistant aux pannes** : si Python crashe au milieu d'une transaction, le prochain démarrage détecte l'état incohérent et le répare automatiquement. Il ajoute également un exécuteur pour valider le code généré (tests) et un analyseur d'erreurs pour suggérer des correctifs.

### Composants du sprint :
- `core/recovery_service.py` — Boot check + auto-recovery via WAL
- `core/executor.py` — Sandbox d'exécution + validation tests
- `core/error_analyzer.py` — Analyse des erreurs Python + suggestions

---

## 📋 Tâches

### TASK-06-01 — `RecoveryService` — Boot check WAL
**Priorité** : 🔴 Critique  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `core/recovery_service.py`

**Description** :  
Au démarrage de LCCA, lire le WAL (`transactions/wal.jsonl`) et détecter les transactions non terminées (BEGIN présent mais pas de COMMIT ou ROLLBACK).

**Algorithme de détection** :
```python
def boot_check(self) -> List[str]:
    """
    Lit le WAL et retourne les tx_ids des transactions orphelines.
    Une transaction est orpheline si:
      - Elle a un BEGIN
      - Elle n'a pas de COMMIT ni de ROLLED_BACK
    """
    open_tx: Dict[str, Dict] = {}
    
    if not self.wal_path.exists():
        return []
    
    with open(self.wal_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                tx_id = entry.get("tx_id")
                event_type = entry.get("type")
                
                if event_type == "BEGIN":
                    open_tx[tx_id] = entry
                elif event_type in ("COMMIT", "ROLLBACK"):
                    open_tx.pop(tx_id, None)
            except json.JSONDecodeError:
                log.warning(f"WAL ligne invalide ignorée: {line[:80]}")
    
    orphaned = list(open_tx.keys())
    if orphaned:
        log.warning(f"🔍 {len(orphaned)} transaction(s) orpheline(s) détectée(s): {orphaned}")
    return orphaned
```

**Critères d'acceptation** :
- [ ] WAL vide → liste vide, pas d'erreur
- [ ] TX avec BEGIN+COMMIT → non détectée comme orpheline
- [ ] TX avec BEGIN sans COMMIT → détectée comme orpheline
- [ ] WAL avec lignes JSON invalides → ignorées avec warning, pas de crash
- [ ] Performance : < 100ms pour un WAL de 10 000 lignes

---

### TASK-06-02 — `RecoveryService` — Auto-recovery
**Priorité** : 🔴 Critique  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Pour chaque transaction orpheline, décider si on rollback (état intermédiaire dangereux) ou si on peut compléter (toutes les ops ont réussi = juste le COMMIT manque).

**Logique de décision** :
```python
def auto_recover_pending(self, orphaned_ids: List[str]) -> Dict[str, str]:
    """
    Pour chaque tx orpheline:
    - Si toutes les ops sont OP_SUCCESS → tenter COMMIT tardif
    - Si au moins une OP_START sans OP_SUCCESS → ROLLBACK
    
    Retourne: {tx_id: "committed" | "rolled_back" | "failed"}
    """
    results = {}
    
    for tx_id in orphaned_ids:
        tx_state = self._reconstruct_tx_state(tx_id)
        
        if tx_state["all_ops_succeeded"]:
            log.info(f"✅ Recovery: commit tardif de {tx_id}")
            # Tous les fichiers sont déjà en état final — juste écrire le COMMIT dans le WAL
            self.tx_manager._write_wal({
                "type": "COMMIT",
                "tx_id": tx_id,
                "timestamp": datetime.now().isoformat(),
                "n_ops": tx_state["n_ops"],
                "recovery": True
            })
            results[tx_id] = "committed"
        else:
            log.warning(f"⏮️  Recovery: rollback de {tx_id} (op incomplète détectée)")
            try:
                self.tx_manager.rollback(tx_id=tx_id)
                results[tx_id] = "rolled_back"
            except Exception as e:
                log.error(f"Rollback {tx_id} échoué: {e}")
                results[tx_id] = "failed"
    
    return results

def _reconstruct_tx_state(self, tx_id: str) -> Dict:
    """Reconstitue l'état d'une TX depuis le WAL."""
    ops_started = set()
    ops_succeeded = set()
    
    with open(self.wal_path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if entry.get("tx_id") != tx_id:
                    continue
                if entry["type"] == "OP_START":
                    ops_started.add(entry["op_id"])
                elif entry["type"] == "OP_SUCCESS":
                    ops_succeeded.add(entry["op_id"])
            except:
                continue
    
    return {
        "all_ops_succeeded": ops_started == ops_succeeded and len(ops_started) > 0,
        "n_ops": len(ops_started),
        "incomplete_ops": ops_started - ops_succeeded
    }
```

**Critères d'acceptation** :
- [ ] TX avec toutes ops OP_SUCCESS → `"committed"` dans les résultats
- [ ] TX avec une OP_START sans OP_SUCCESS → `"rolled_back"`, fichiers restaurés
- [ ] Après recovery, `boot_check()` ne retourne plus les tx_ids traités
- [ ] Log clair pour chaque tx traitée

---

### TASK-06-03 — `Executor` — Validation syntaxe et tests
**Priorité** : 🟠 Haute  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `core/executor.py`

**Description** :  
Valider les fichiers modifiés après chaque patch : syntaxe Python obligatoire, tests pytest optionnels (si `tests/` existe et non vide).

**Interface** :
```python
@dataclass
class ValidationResult:
    passed: bool
    syntax_errors: List[str]       # Fichiers avec erreurs syntaxe
    test_failures: List[str]       # Tests qui échouent
    test_output: str               # Sortie complète pytest
    duration_ms: int


class Executor:
    def __init__(self, workspace: Path, tests_dir: Path):
        self.workspace = workspace
        self.tests_dir = tests_dir
    
    def validate(self, modified_files: List[str]) -> ValidationResult:
        """
        1. Vérifie syntaxe de tous les fichiers .py modifiés
        2. Si tests/ non vide → lance pytest -x -q
        """
    
    def check_syntax(self, file_path: str) -> Optional[str]:
        """
        Retourne None si syntaxe OK, sinon le message d'erreur.
        Utilise compile() (rapide, pas d'exécution).
        """
        try:
            source = (self.workspace / file_path).read_text(encoding='utf-8')
            compile(source, file_path, 'exec')
            return None
        except SyntaxError as e:
            return f"{file_path}:{e.lineno}: {e.msg}"
    
    def run_tests(self, timeout_sec: int = 30) -> Tuple[bool, str]:
        """
        Lance pytest sur tests/.
        Retourne (passed: bool, output: str).
        """
        if not any(self.tests_dir.rglob("test_*.py")):
            return True, "Pas de tests trouvés — skip"
        
        import subprocess
        result = subprocess.run(
            ["python", "-m", "pytest", str(self.tests_dir), "-x", "-q", "--tb=short"],
            capture_output=True, text=True, timeout=timeout_sec,
            cwd=self.workspace.parent
        )
        return result.returncode == 0, result.stdout + result.stderr
```

**Critères d'acceptation** :
- [ ] Fichier avec syntaxe invalide → `check_syntax()` retourne le message d'erreur
- [ ] `run_tests()` sans fichiers `test_*.py` → `(True, "skip")`
- [ ] Timeout respecté (subprocess killed après `timeout_sec`)
- [ ] Ne modifie aucun fichier (lecture seule)

---

### TASK-06-04 — `ErrorAnalyzer` — Suggestions de corrections
**Priorité** : 🟡 Normale  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `core/error_analyzer.py`

**Description** :  
Analyser les erreurs Python (SyntaxError, ImportError, AttributeError, etc.) et proposer des suggestions de correction structurées, utilisables dans le prochain prompt LLM.

**Interface** :
```python
@dataclass
class ErrorReport:
    error_type: str          # "SyntaxError", "ImportError", etc.
    file: str
    line: Optional[int]
    message: str
    suggestion: str          # Texte pour le prochain prompt LLM
    severity: str            # "blocking" | "warning" | "info"
    auto_fixable: bool       # True si LCCA peut corriger sans LLM


class ErrorAnalyzer:
    def analyze(self, error: Exception, file_path: str, source: str) -> ErrorReport:
        """Analyse une exception et génère un rapport actionnable."""
    
    def analyze_syntax_error(self, e: SyntaxError, file_path: str) -> ErrorReport:
        """
        Suggestions communes pour les SyntaxError:
        - IndentationError → "Vérifier indentation ligne X"
        - unexpected EOF → "Bloc non fermé, vérifier parenthèses/accolades"
        - invalid syntax → Contexte des 3 lignes autour
        """
    
    def analyze_import_error(self, e: ImportError, file_path: str) -> ErrorReport:
        """
        ImportError → suggestion d'ajouter l'import manquant via AddImportTransformer.
        auto_fixable = True si le module est dans requirements.txt.
        """
    
    def generate_fix_prompt(self, report: ErrorReport, context: str) -> str:
        """
        Génère le prompt LLM pour corriger l'erreur.
        Format: 'Erreur {type} ligne {line}: {msg}. Corriger en: {suggestion}'
        """
    
    def try_auto_fix(self, report: ErrorReport, patcher: 'SmartPatcher') -> bool:
        """
        Tente une correction automatique si auto_fixable.
        Retourne True si correction appliquée.
        """
```

**Règles de suggestion par type d'erreur** :

| Erreur | Suggestion générée |
|--------|-------------------|
| `SyntaxError: unexpected indent` | `"Indentation incorrecte ligne {line}. Vérifier les espaces/tabs."` |
| `ImportError: No module named X` | `"Module '{X}' manquant. Ajouter 'import {X}' ou installer via pip."` |
| `AttributeError: X has no attribute Y` | `"L'objet '{X}' n'a pas d'attribut '{Y}'. Vérifier le type retourné."` |
| `NameError: name X is not defined` | `"Variable '{X}' utilisée avant définition. Vérifier la portée."` |

**Critères d'acceptation** :
- [ ] `analyze(SyntaxError(...))` → rapport avec suggestion non vide
- [ ] `auto_fixable=True` pour `ImportError` d'un module dans `requirements.txt`
- [ ] `generate_fix_prompt()` retourne un prompt de moins de 200 tokens
- [ ] `try_auto_fix()` sur ImportError → ajoute l'import via SmartPatcher

---

### TASK-06-05 — Tests unitaires Recovery & Executor
**Priorité** : 🟠 Haute  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `tests/test_recovery_service.py`, `tests/test_executor.py`

**Tests recovery** :
```python
def test_boot_check_empty_wal():
    """WAL vide → liste vide."""

def test_boot_check_committed_tx():
    """TX commitée → pas détectée comme orpheline."""

def test_boot_check_orphan_tx():
    """TX BEGIN sans COMMIT → détectée."""

def test_auto_recover_rollback():
    """TX avec OP_START incomplet → rollback + fichier restauré."""

def test_auto_recover_late_commit():
    """TX avec toutes ops OP_SUCCESS → commit tardif."""
```

**Tests executor** :
```python
def test_syntax_check_valid_file():
    """Fichier valide → None retourné."""

def test_syntax_check_invalid_file():
    """Fichier avec SyntaxError → message d'erreur retourné."""

def test_run_tests_no_tests():
    """tests/ vide → (True, 'skip')."""
```

**Critères d'acceptation** :
- [ ] `pytest tests/test_recovery_service.py` → 5/5
- [ ] `pytest tests/test_executor.py` → 3/3

---

## 📊 Récapitulatif Sprint 06

| Task | Description | Effort | Statut |
|------|------------|--------|--------|
| TASK-06-01 | RecoveryService boot check | 1j | ⚪ |
| TASK-06-02 | RecoveryService auto-recovery | 1j | ⚪ |
| TASK-06-03 | Executor — syntaxe + tests | 0.5j | ⚪ |
| TASK-06-04 | ErrorAnalyzer — suggestions | 1j | ⚪ |
| TASK-06-05 | Tests unitaires | 0.5j | ⚪ |
| **TOTAL** | | **4j** | |

---

## ✅ Définition of Done (Sprint 06)

- [ ] `pytest tests/test_recovery_service.py tests/test_executor.py` → 0 erreur
- [ ] Simulation crash (SIGKILL pendant TX) → redémarrage → auto-recovery → fichiers cohérents
- [ ] `ErrorAnalyzer.analyze(SyntaxError(...))` → suggestion non vide
- [ ] `Executor.validate()` intégré dans `Orchestrator._validate_changes()`
- [ ] `004-sprint-context.md` mis à jour

---

## ⚠️ Contraintes & Risques

| Risque | Probabilité | Mitigation |
|--------|------------|------------|
| `subprocess.run(pytest)` bloque sur Windows | Faible | Utiliser `timeout` + `SIGTERM` gracieux |
| WAL corrompu (crash pendant écriture WAL) | Très faible | `fsync` + ligne JSON toujours complète avant fsync |
| `os.kill(SIGKILL)` non dispo sur Windows | Certaine | Utiliser `taskkill /F /PID` pour simuler crash dans les tests |

---

## 🔗 Navigation

⬅️ [Sprint 05 — MemPalace Integration](sprint-05-mempalace-integration.md)  
➡️ [Sprint 07 — CLI, Tests & Polish](sprint-07-cli-tests.md)
