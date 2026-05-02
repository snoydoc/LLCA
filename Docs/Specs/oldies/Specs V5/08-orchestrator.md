# Spec 08 — Orchestrateur (LCCAV5Fusion)
> **Module** : `core/orchestrator.py` | **Sprints** : 04, 09 | **Statut** : ✅ VALIDÉ

---

## 1. Rôle

`LCCAV5Fusion` est le **cœur exécutif du système LCCA**. Il orchestre le pipeline complet de modification de code, du parsing de la commande jusqu'au commit (ou rollback) de la transaction.

`Orchestrator` est un alias legacy conservé pour la rétrocompatibilité Sprint 01.

---

## 2. Architecture par injection de dépendances

```python
class LCCAV5Fusion:
    def __init__(
        self,
        workspace:  Optional[Path] = None,
        tx_manager = None,    # TransactionManager
        indexer    = None,    # ASTIndexer
        dep_graph  = None,    # DependencyGraph
        patcher    = None,    # SmartPatcher
        llm        = None,    # LLMGenerator (Sprint 09)
    ) -> None
```

Si un paramètre est `None`, l'objet par défaut est créé automatiquement depuis `config`. Cela permet l'injection de mocks dans les tests.

**Instanciation automatique des composants :**
```
LCCAV5Fusion.__init__
    ├── TransactionManager(TRANSACTIONS_DIR)
    ├── ASTIndexer(workspace)
    ├── DependencyGraph()
    ├── SmartPatcher()
    ├── LLMGenerator()          ← Sprint 09
    ├── FileSelector(indexer, dep_graph, workspace)
    └── MultiFilePlanner()
```

---

## 3. Pipeline d'exécution — `execute(command, auto_rollback=True)`

```
command: str
    │
    ▼
1. DSLParser().parse(command) → Intent
    │  (confidence faible → warning, pas d'arrêt)
    ▼
2. FileSelector.select(intent) → List[str] (≤3 fichiers)
    │  (vide → return False)
    ▼
3. MultiFilePlanner.create_plan(...) → List[PlannedOperation]
    │  + validate_plan_consistency() → (bool, errors)
    │  (invalide → return False)
    ▼
4. TransactionManager.begin(dsl_input, project, intent) → tx_id
    │
    ▼
5. Pour chaque PlannedOperation :
    ├── Lit le fichier existant (existing_context pour LLM)
    ├── LLMGenerator.generate(op, intent, context) → GenerationResult
    │   ├── Cache hit → code depuis cache disque
    │   ├── Ollama disponible → code généré
    │   └── Fallback → stub minimal
    ├── _do_patch() :
    │   ├── action="create" → write_text() direct
    │   └── action="modify" → SmartPatcher.apply_patch() → write_text()
    └── TransactionManager.log_operation(path, op_type, _do_patch, metadata)
    │
    ▼
6. _validate_changes() → bool
    │  (Executor.check_syntax() sur chaque .py modifié)
    │  (JAMAIS pytest en subprocess depuis une TX active)
    │  (échec → raise RuntimeError → goto 8)
    ▼
7. TransactionManager.commit()
    │
    ▼
8. Re-indexation (index_repository + dep_graph.build)
    + _update_sprint_log(intent, plan, tx_id)
    │
    └── return True

Exception/erreur à n'importe quelle étape :
    └── auto_rollback=True → TransactionManager.rollback()
    └── return False
```

---

## 4. Méthodes publiques

| Méthode | Description |
|---------|-------------|
| `execute(command, auto_rollback=True) → bool` | Exécution complète avec transaction |
| `dry_run(command) → dict` | Simulation sans écriture disque |

### `dry_run(command) → dict`
Retourne :
```python
{
    "intent":       Intent,
    "target_files": List[str],
    "plan":         List[PlannedOperation],
    "plan_valid":   bool,
    "plan_errors":  List[str],
    "llm_available": bool,    # Sprint 09
}
```

---

## 5. Méthodes privées

### `_validate_changes() → bool`
- Récupère les fichiers `.py` de la TX courante
- Crée `Executor(workspace, tests_dir=Path("/dev/null"))`
- Appelle `executor.check_syntax(rel_path)` sur chacun
- **JAMAIS** `run_tests()` depuis une TX active (timeout garanti)

### `_generate_stub(op, intent) → str` *(DEPRECATED Sprint 09)*
Délègue à `self.llm.fallback.generate()`. Conservé pour rétrocompatibilité.

### `_update_sprint_log(intent, plan, tx_id) → None`
Ajoute une entrée markdown dans `Docs/Sprints/current-sprint.md` (append, jamais overwrite).

---

## 6. Gestion des métadonnées TX

```python
self.tx_manager.log_operation(
    self.workspace / op.file,
    op_type,
    _do_patch,
    metadata={
        "intent":    intent.details,
        "symbol":    op.target_symbol,
        "patch_type": op.patch_type,
        "llm_model": gen_result.model,
        "from_cache": gen_result.from_cache,
    },
)
```

---

## 7. Alias legacy `Orchestrator`

```python
class Orchestrator:
    def execute_plan(self, plan) -> bool
```

Délègue vers `LCCAV5Fusion`. Accepte un `Plan` Sprint 01 ou une commande `str`.
**Ne jamais supprimer** — utilisé par `test_smoke.py`.

---

## 8. Critères de qualité AI

| Critère | Valeur |
|---------|--------|
| Injection de dépendances | ✅ Tous les composants injectables |
| Rollback automatique | ✅ `auto_rollback=True` par défaut |
| LLM découplé | ✅ `LLMGenerator` séparé, fallback garanti |
| Pas d'écriture directe | ✅ Seul `log_operation` écrit |
| Re-indexation après commit | ✅ `index_repository()` + `dep_graph.build()` |
| Log sprint automatique | ✅ `_update_sprint_log()` |
