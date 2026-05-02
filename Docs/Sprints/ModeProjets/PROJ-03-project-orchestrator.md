# PROJ-03 — ProjectOrchestrator + 4 Workers
**Statut** : TODO
**Priorité** : P0
**Durée estimée** : 60 min
**Dépendances** : PROJ-01, PROJ-02

---

## Objectif

Implémenter le `ProjectOrchestrator` (Hierarchical Manager pattern) et ses 4 workers.
Chaque worker < 8 KB (règle REFACTO LLCA). Chaque worker est testable en isolation.

---

## Nouveaux fichiers à créer

```
core/project_orchestrator.py        # Manager hierarchical (< 8 KB)
core/project_loader.py              # Worker : lecture project.json + lock (< 8 KB)
core/project_context_assembler.py   # Worker : skills + specs + history window (< 8 KB)
core/project_checkpoint.py          # Worker : context_snapshot.json (< 8 KB)
```

> `user_context_injector.py` est le 5ème worker mais créé dans PROJ-07 (dépend de PROJ-06 WAL).
> Dans PROJ-03, `ProjectOrchestrator` injecte un bloc user_prefix vide en attendant.

---

## Dataclass `ProjectContext`

```python
@dataclass
class ProjectContext:
    meta: ProjectMeta                      # project.json parsé
    skills: list[str]                      # Contenu des .md locaux
    specs: list[dict]                      # Specs validées
    history_window: list[dict]             # N derniers messages de history.jsonl
    palace: MemPalaceClient                # Client ChromaDB (shared ou isolated)
    user_prefix: str                       # Bloc prompt utilisateur (< 800 tokens)
    snapshot: dict                         # context_snapshot.json restauré
```

---

## Implémentation

### core/project_orchestrator.py

```python
class ProjectOrchestrator:
    """Hierarchical Manager — coordonne le chargement/sauvegarde projet."""

    def __init__(self, project_manager: ProjectManager,
                 lock: ProjectLock,
                 loader: ProjectLoader,
                 assembler: ProjectContextAssembler,
                 checkpoint: ProjectCheckpoint):
        ...

    def load_project(self, project_id: str) -> ProjectContext:
        meta     = self._loader.load(project_id)           # vérifie lock + lit project.json
        context  = self._assembler.build(meta)             # skills + specs + history
        context.user_prefix = ""                           # Placeholder — peuplé par PROJ-07
        self._checkpoint.restore(context)                  # context_snapshot.json
        return context

    def save_project(self, context: ProjectContext) -> None:
        """Appelé à la fermeture. Snapshot + update last_opened + release lock."""
        self._checkpoint.save(context)
        self._project_manager.update_last_opened(context.meta.id)
        self._lock.release(context.meta.slug)
```

### core/project_loader.py

```python
class ProjectLoader:
    """Charge project.json, acquiert le lock, résout storage_mode."""

    def load(self, project_id: str) -> ProjectMeta:
        meta = self._project_manager.get_project(project_id)
        if meta is None:
            raise ProjectNotFoundError(project_id)
        self._lock.acquire(meta.slug)   # lève ProjectAlreadyOpenError si occupé
        return meta
```

### core/project_context_assembler.py

```python
class ProjectContextAssembler:
    """Assemble skills + specs + fenêtre history."""

    def build(self, meta: ProjectMeta) -> ProjectContext:
        skills  = self._load_skills(meta)     # Lit projects/{slug}/skills/*.md
        specs   = self._load_specs(meta)      # Lit projects/{slug}/specs/*.json
        history = self._load_history(meta)    # Fenêtre glissante history.jsonl
        palace  = get_palace(meta.id, meta.storage_mode, meta.legacy_namespaces)
        return ProjectContext(meta=meta, skills=skills, specs=specs,
                              history_window=history, palace=palace,
                              user_prefix="", snapshot={})

    def _load_history(self, meta: ProjectMeta) -> list[dict]:
        """Lit les N derniers messages de history.jsonl selon max_history_tokens."""
```

### core/project_checkpoint.py

```python
class ProjectCheckpoint:
    """Sauvegarde et restaure context_snapshot.json."""

    def restore(self, context: ProjectContext) -> None:
        """Lit projects/{slug}/.llca/context_snapshot.json → context.snapshot."""

    def save(self, context: ProjectContext) -> None:
        """Écrit context.snapshot dans projects/{slug}/.llca/context_snapshot.json."""
```

---

## Tests requis (minimum 12 par worker = 48 minimum)

```python
# tests/test_proj_03.py

# ProjectOrchestrator
def test_load_project_calls_loader(mock_deps)
def test_load_project_calls_assembler(mock_deps)
def test_load_project_calls_checkpoint_restore(mock_deps)
def test_save_project_calls_checkpoint_save(mock_deps)
def test_save_project_releases_lock(mock_deps)
def test_load_project_returns_project_context(mock_deps)

# ProjectLoader
def test_loader_raises_if_project_not_found(tmp_dir)
def test_loader_acquires_lock(tmp_dir)
def test_loader_raises_if_lock_occupied(tmp_dir)

# ProjectContextAssembler
def test_assembler_loads_skills_from_skills_dir(tmp_dir)
def test_assembler_loads_specs_from_specs_dir(tmp_dir)
def test_assembler_loads_history_window(tmp_dir)
def test_assembler_empty_skills_dir_returns_empty_list(tmp_dir)
def test_assembler_history_window_respects_max_tokens(tmp_dir)
def test_assembler_calls_get_palace_with_correct_args(tmp_dir, mock_palace)

# ProjectCheckpoint
def test_checkpoint_restore_reads_snapshot(tmp_dir)
def test_checkpoint_save_writes_snapshot(tmp_dir)
def test_checkpoint_restore_no_file_returns_empty_dict(tmp_dir)
```

---

## Critères de validation

- [ ] `test_proj_03.py` : tous les tests passent
- [ ] Chaque worker testable en isolation (pas de dépendances croisées entre workers)
- [ ] `project_orchestrator.py` < 8 KB, idem chaque worker
- [ ] `get_palace()` appelé avec `legacy_namespaces` du projet legacy
- [ ] `save_project()` release le lock même si `checkpoint.save()` lève une exception (try/finally)
