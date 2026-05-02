# PROJ-01 — ProjectManager + Scan Filesystem
**Statut** : TODO
**Priorité** : P0
**Durée estimée** : 45 min
**Dépendances** : PROJ-00

---

## Objectif

Implémenter `ProjectManager` — le module CRUD des projets. La source de vérité est le
**scan filesystem** (`projects/*/. llca/project.json`). `index.cache.json` est un cache
de performance uniquement, jamais la source de vérité.

---

## Nouveaux fichiers à créer

```
core/project_manager.py       # CRUD + scan filesystem + index.cache.json
```

---

## Implémentation — core/project_manager.py

```python
class ProjectManager:
    """
    CRUD projets. Source de vérité : scan projects/*/.llca/project.json.
    index.cache.json = cache performance (reconstruit au boot, < 50 ms).
    """

    def list_projects(self) -> list[ProjectMeta]:
        """Scanne projects/*/.llca/project.json, reconstruit cache, retourne triés par last_opened."""

    def get_project(self, project_id: str) -> ProjectMeta | None:
        """Lookup par id ou slug. Lit depuis le cache si disponible."""

    def create_project(self, name: str, description: str = "", storage_mode: str = "shared",
                       tags: list[str] | None = None, target_dir: str | None = None) -> ProjectMeta:
        """
        Crée la structure projects/{slug}/.llca/project.json.
        Génère un slug ASCII lowercase depuis le nom.
        Initialise history.jsonl vide, skills/, specs/.
        Met à jour index.cache.json.
        """

    def archive_project(self, project_id: str) -> bool:
        """status: active → archived. Met à jour project.json et le cache."""

    def update_last_opened(self, project_id: str) -> None:
        """Met à jour last_opened dans project.json (appelé à chaque project_open MCP)."""

    def _rebuild_cache(self, projects: list[ProjectMeta]) -> None:
        """Écrit index.cache.json depuis la liste en mémoire."""

    def _parse_meta(self, path: Path) -> ProjectMeta | None:
        """Parse un project.json. Retourne None si invalide (log warning)."""

    def _generate_slug(self, name: str) -> str:
        """ASCII lowercase, tirets, unique dans projects/. Ex: 'Mon Projet 2' → 'mon-projet-2'"""
```

### Dataclass `ProjectMeta`

```python
@dataclass
class ProjectMeta:
    id: str
    slug: str
    name: str
    description: str
    created_at: str
    last_opened: str
    status: str                    # active | archived | paused
    tags: list[str]
    model_override: str | None
    storage_mode: str              # shared | isolated
    legacy_namespaces: list[str]   # [] pour les projets normaux, ["lcca_*"] pour legacy
    history: dict
    stats: dict
    migrated_from_v9: bool
```

---

## Tests requis (minimum 12)

```python
# tests/test_proj_01.py

def test_list_projects_empty_when_no_projects(tmp_dir)
def test_list_projects_finds_project_json(tmp_dir)
def test_list_projects_sorted_by_last_opened(tmp_dir)
def test_list_projects_ignores_invalid_json(tmp_dir)
def test_list_projects_ignores_archived_by_default(tmp_dir)
def test_create_project_creates_directory_structure(tmp_dir)
def test_create_project_generates_slug_from_name(tmp_dir)
def test_create_project_slug_is_unique(tmp_dir)
def test_create_project_storage_mode_default_shared(tmp_dir)
def test_archive_project_changes_status(tmp_dir)
def test_update_last_opened_modifies_json(tmp_dir)
def test_rebuild_cache_writes_index_cache_json(tmp_dir)
def test_get_project_by_slug(tmp_dir)
def test_get_project_by_id(tmp_dir)
def test_generate_slug_ascii_lowercase(tmp_dir)
```

---

## Critères de validation

- [ ] `test_proj_01.py` : tous les tests passent
- [ ] `list_projects()` ne lit **jamais** `index.cache.json` comme source de vérité
- [ ] Un `project.json` invalide (JSON cassé) ne plante pas `list_projects()` — log warning et skip
- [ ] `_generate_slug()` produit un slug ASCII pur (pas d'accents, pas d'espaces)
- [ ] `create_project()` crée `history.jsonl`, `skills/`, `specs/`, `history_archive/`
