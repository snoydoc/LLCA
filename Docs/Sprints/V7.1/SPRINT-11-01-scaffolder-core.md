# -*- Sprint 11 — TASK-11-01 -*-
# LCCA V7.1 — ProjectScaffolder : Moteur core

## Métadonnées
| Champ        | Valeur                          |
|--------------|---------------------------------|
| Sprint       | 11                              |
| Task         | TASK-11-01                      |
| Version      | V7.1                            |
| Statut       | À faire                         |
| Priorité     | Critique (bloquant TASK-11-02+) |
| Fichier cible| `core/scaffolder.py`            |

---

## Objectif

Créer le module `core/scaffolder.py` qui permet à LCCA de scaffolder des
projets et dossiers **en dehors du workspace** de manière transactionnelle,
avec rollback automatique en cas d'erreur à mi-chemin.

---

## Contexte & Motivation

Actuellement, LCCA est limité à `D:\LLMCodeAgent\workspace\`.
Toute commande du type :

- `"Crée une application dans D:\CodingTests\FileMerge"`
- `"Crée un dossier MonProjet avec un main.py"`

...échoue avec `action=unknown` car aucun composant ne gère
la création de dossiers et le scaffolding multi-fichiers hors workspace.

Cette tâche introduit `ProjectScaffolder` comme nouveau moteur dédié,
**sans modifier le pipeline existant** (LCCAV5Fusion reste intact).

---

## Composants à créer

### 1. `ScaffoldIntent` (dataclass)

```python
@dataclass
class ScaffoldIntent:
    project_name: str           # "FileMerge"
    target_dir: Path            # D:\LLMCodeAgent\CodingTests\FileMerge
    description: str            # "application qui merge des fichiers .MD"
    files: list[ScaffoldFile]   # fichiers à générer
    raw_command: str            # commande originale
```

### 2. `ScaffoldFile` (dataclass)

```python
@dataclass
class ScaffoldFile:
    relative_path: str   # "file_merger.py" | "README.md" | "tests/test_merger.py"
    content: str         # contenu généré (par LLM ou stub)
    encoding: str = "utf-8-sig"
```

### 3. `ProjectScaffolder` (classe principale)

```python
class ProjectScaffolder:
    def __init__(self, llm=None, tx_manager=None) -> None: ...

    def scaffold(self, intent: ScaffoldIntent) -> ScaffoldResult: ...
    def dry_run(self, intent: ScaffoldIntent) -> ScaffoldResult: ...
    def rollback(self, result: ScaffoldResult) -> None: ...
```

### 4. `ScaffoldResult` (dataclass)

```python
@dataclass
class ScaffoldResult:
    success: bool
    project_name: str
    target_dir: Path
    files_created: list[Path]
    files_failed: list[tuple[Path, str]]   # (path, error_message)
    error: str = ""
    duration_s: float = 0.0
    dry_run: bool = False
```

---

## Comportement attendu

### Flux `scaffold(intent)`

```
1. Vérifier que target_dir n'existe pas déjà (ou demander confirmation)
2. Créer target_dir (mkdir parents=True)
3. Pour chaque ScaffoldFile :
   a. Créer les sous-dossiers si nécessaire
   b. Écrire le fichier avec encoding utf-8-sig
   c. Logger dans WAL (OpType.WRITE_FILE)
4. Si une erreur survient → rollback() : supprimer tous les fichiers créés
5. Retourner ScaffoldResult
```

### Rollback
- Supprimer uniquement les fichiers créés par ce scaffold (pas les fichiers préexistants)
- Si `target_dir` était vide avant → la supprimer également
- Logger le rollback dans le WAL

### Sécurité
- Refuser les chemins avec `..` (path traversal)
- Refuser d'écraser un dossier existant non vide (sauf flag `--force`)
- Valider que `target_dir` est dans un répertoire autorisé (pas `C:\Windows`, etc.)

---

## Critères d'acceptance

- [ ] `scaffold()` crée correctement l'arborescence sur disque
- [ ] `dry_run()` retourne le plan sans écrire
- [ ] `rollback()` supprime tous les fichiers créés en cas d'erreur
- [ ] Path traversal (`../../etc`) est refusé avec `SecurityError`
- [ ] Dossier cible préexistant non vide → refus + message clair
- [ ] WAL trace chaque fichier créé (OpType.WRITE_FILE)

---

## Tests à écrire

Fichier : `tests/test_scaffolder.py`

```
test_scaffold_creates_files()
test_scaffold_dry_run_no_write()
test_scaffold_rollback_on_error()
test_scaffold_refuses_path_traversal()
test_scaffold_refuses_existing_nonempty_dir()
test_scaffold_wal_entries()
```
