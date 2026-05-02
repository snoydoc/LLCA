# PROJ-00 — MigrationManager + Structure .llca/
**Statut** : TODO
**Priorité** : P0 — Premier sprint obligatoire
**Durée estimée** : 30 min
**Dépendances** : Aucune

---

## Objectif

Créer la structure filesystem du Mode Projets et le mécanisme de migration automatique
depuis LLCA V9 (palace global lcca_*) vers le Mode Projets (projets/legacy/).

Ce sprint est le fondement de tous les autres. Aucun autre sprint PROJ ne peut démarrer sans lui.

---

## Nouveaux fichiers à créer

```
core/migration_manager.py       # MigrationManager : détection + migration V9 → V10
```

---

## Arborescence créée par ce sprint

```
D:\LLMCodeAgent\projects\
├── .llca\
│   ├── user_context.json           # Initialisé vide (version: 1)
│   ├── user_context.wal.jsonl      # WAL vide
│   └── index.cache.json            # Cache vide, reconstruit par PROJ-01
│
└── legacy\                         # Projet créé par la migration V9
    ├── .llca\
    │   ├── project.json            # migrated_from_v9: true, storage_mode: shared
    │   ├── context_snapshot.json   # Vide
    │   └── (pas de .lock)
    ├── history.jsonl               # Vide (pas de rétroactivité)
    ├── history_archive\
    ├── skills\                     # Skills copiés + _rewrite_paths() appliqué
    └── specs\                      # Vide
```

---

## Implémentation — core/migration_manager.py

### Classe principale

```python
class MigrationManager:
    """
    Détecte si LLCA est en mode V9 (sans projects/) et crée la structure V10.
    Non-destructif : aucune donnée supprimée ou renommée dans ChromaDB.
    Rollback = supprimer D:\LLMCodeAgent\projects\ (lcca_* restent intacts).
    """
    def needs_migration(self) -> bool:
        """True si projects/ absent ou si index.cache.json absent."""

    def run(self) -> MigrationResult:
        """Pipeline complet. Retourne MigrationResult avec statut + rapport."""
        # 1. Créer arborescence projects/.llca/
        # 2. Initialiser user_context.json vide
        # 3. Créer projet legacy (project.json)
        # 4. Copier skills globaux → projects/legacy/skills/ avec _rewrite_paths()
        # 5. Créer index.cache.json minimal
        # 6. Retourner MigrationResult

    def _rewrite_paths(self, content: str) -> str:
        """
        Substitution string simple sur le Markdown des skills.
        3 passes pour couvrir les variantes Windows.
        NE PAS utiliser libcst — les skills sont du Markdown, pas du code Python.
        """
        content = content.replace("D:\\\\LLMCodeAgent\\\\", "{PROJECT_ROOT}/")
        content = content.replace("D:\\LLMCodeAgent\\", "{PROJECT_ROOT}/")
        content = content.replace("D:/LLMCodeAgent/", "{PROJECT_ROOT}/")
        return content
```

### `project.json` du projet legacy

```json
{
  "id": "<uuid-v4-généré>",
  "slug": "legacy",
  "name": "Legacy (LLCA V9)",
  "description": "Projet de migration automatique depuis LLCA V9",
  "created_at": "<timestamp>",
  "last_opened": "<timestamp>",
  "status": "active",
  "tags": ["legacy", "migration"],
  "model_override": null,
  "storage_mode": "shared",
  "legacy_namespaces": ["lcca_*"],
  "history": {
    "compaction_threshold_mb": 10,
    "compression_strategy": "sliding_window",
    "max_history_tokens": 8000
  },
  "stats": {
    "total_sessions": 0,
    "total_tokens_spent": 0,
    "skills_generated": 0,
    "specs_validated": 0,
    "last_healthcheck": null,
    "issues_count": 0
  },
  "migrated_from_v9": true
}
```

### Double namespace legacy

Le `MemPalaceClient` du projet legacy doit charger deux namespaces :
- `project_legacy_*` — futures collections (écritures)
- `lcca_*` — collections historiques V9 (lecture en fallback)

Ce comportement est géré par `get_palace(project_id, storage_mode, legacy_namespaces=["lcca_*"])`.
**Aucune copie ni renommage ChromaDB** — ChromaDB ne supporte pas le rename natif.

---

## Tests requis (minimum 12)

```python
# tests/test_proj_00.py

def test_needs_migration_true_when_projects_absent()
def test_needs_migration_false_when_projects_exists()
def test_run_creates_projects_llca_directory()
def test_run_creates_user_context_json()
def test_run_creates_legacy_project_json()
def test_legacy_project_has_migrated_from_v9_true()
def test_legacy_project_storage_mode_is_shared()
def test_legacy_namespaces_contains_lcca_wildcard()
def test_rewrite_paths_double_backslash()
def test_rewrite_paths_single_backslash()
def test_rewrite_paths_forward_slash()
def test_rewrite_paths_preserves_non_llca_content()
def test_run_is_idempotent_if_projects_exists()
def test_run_copies_skills_to_legacy()
def test_migration_result_contains_report()
```

---

## Risques identifiés (analyse v3)

**_rewrite_paths() sur variantes de chemins** : le champ `D:\` peut apparaître sous
`D:\\`, `D:/`, ou `D:\` simple. Les 3 passes couvrent les cas connus.
Si un skill contient les deux formes dans le même fichier, les deux passes s'appliquent.
Pas de risque de double-remplacement (les passes sont idempotentes sur leur propre sortie).

---

## Critères de validation

- [ ] `test_proj_00.py` : tous les tests passent
- [ ] Migration non-destructive vérifiée (collections `lcca_*` intactes après migration)
- [ ] `_rewrite_paths()` testé sur les 3 variantes de slash
- [ ] `project.json` legacy valide JSON (pas de trailing comma, UTF-8 sans BOM)
- [ ] `index.cache.json` créé (même si vide — sera peuplé par PROJ-01)
