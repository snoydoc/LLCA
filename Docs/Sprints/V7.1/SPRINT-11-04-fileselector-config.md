# -*- Sprint 11 — TASK-11-04 -*-
# LCCA V7.1 — ProjectScaffolder : Extension FileSelector + Config

## Métadonnées
| Champ        | Valeur                                              |
|--------------|-----------------------------------------------------|
| Sprint       | 11                                                  |
| Task         | TASK-11-04                                          |
| Version      | V7.1                                               |
| Statut       | À faire                                             |
| Priorité     | Moyenne                                             |
| Dépendance   | TASK-11-01                                          |
| Fichiers     | `core/file_selector.py`, `config.py`                |

---

## Objectif

Étendre `FileSelector` et `config.py` pour permettre à LCCA de travailler
sur des répertoires arbitraires hors workspace, de manière sécurisée.

---

## Modifications `config.py`

### Ajouts

```python
# ── V7.1 — ProjectScaffolder ──────────────────────────────────────────────────

# Répertoires autorisés pour le scaffolding hors workspace
SCAFFOLD_ALLOWED_ROOTS: list[Path] = [
    Path("D:/LLMCodeAgent"),
    Path("D:/MediBot"),
]

# Répertoires explicitement interdits (sécurité)
SCAFFOLD_DENIED_ROOTS: list[Path] = [
    Path("C:/Windows"),
    Path("C:/Program Files"),
    Path("C:/Users"),
]

# Nombre max de fichiers générables par scaffold
SCAFFOLD_MAX_FILES: int = 8

# Extensions autorisées pour la génération
SCAFFOLD_ALLOWED_EXTENSIONS: set[str] = {
    ".py", ".md", ".txt", ".json", ".toml",
    ".yaml", ".yml", ".cfg", ".ini", ".html",
    ".css", ".js", ".ts",
}
```

---

## Modifications `core/file_selector.py`

### Nouvelle méthode `select_external()`

```python
def select_external(
    self,
    target_dir: Path,
    pattern: str = "*.py",
    recursive: bool = True,
) -> list[str]:
    """
    Sélectionne des fichiers dans un répertoire externe au workspace.

    Utilisé par ProjectScaffolder pour indexer un projet existant
    avant de le modifier.

    Args:
        target_dir : Répertoire cible (absolu, hors workspace).
        pattern    : Glob pattern (défaut: "*.py").
        recursive  : Si True, cherche récursivement.

    Returns:
        Liste de chemins absolus (strings).

    Raises:
        SecurityError : Si target_dir est dans un répertoire interdit.
    """
```

### Nouvelle méthode `validate_external_path()`

```python
def validate_external_path(self, path: Path) -> None:
    """
    Vérifie qu'un chemin externe est autorisé.

    Raises:
        SecurityError : chemin interdit ou path traversal détecté.
    """
    from config import SCAFFOLD_DENIED_ROOTS

    resolved = path.resolve()

    # Anti path-traversal
    try:
        resolved.relative_to(resolved.anchor)
    except ValueError:
        raise SecurityError(f"Path traversal détecté : {path}")

    # Vérification liste noire
    for denied in SCAFFOLD_DENIED_ROOTS:
        if str(resolved).startswith(str(denied.resolve())):
            raise SecurityError(f"Répertoire interdit : {path}")
```

### Nouvelle exception

```python
class SecurityError(Exception):
    """Levée quand un chemin externe viole les règles de sécurité."""
```

---

## Critères d'acceptance

- [ ] `select_external()` liste correctement les fichiers d'un dossier externe
- [ ] `validate_external_path()` bloque `../../etc/passwd` avec `SecurityError`
- [ ] `validate_external_path()` bloque `C:\Windows\System32` avec `SecurityError`
- [ ] `SCAFFOLD_ALLOWED_ROOTS` et `SCAFFOLD_DENIED_ROOTS` utilisés cohérents
- [ ] `SCAFFOLD_MAX_FILES` respecté lors du scaffolding
- [ ] Tests existants de `FileSelector` non cassés

---

## Tests à écrire

Fichier : `tests/test_file_selector_v71.py`

```
test_select_external_lists_files()
test_validate_path_blocks_traversal()
test_validate_path_blocks_system_dirs()
test_validate_path_allows_lcca_dir()
test_select_external_respects_max_files()
```
