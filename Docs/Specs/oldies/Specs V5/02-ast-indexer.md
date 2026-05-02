# Spec 02 — ASTIndexer
<!-- AI-READY | core/ast_indexer.py | Sprint 03 | Tests: 6/6 PASSED -->

## Rôle

Indexe récursivement tous les fichiers `.py` d'un workspace.
Produit une table de symboles cross-fichier (fonctions, classes, variables, imports).

> **Architecture duale** : `ast` stdlib pour l'INDEXATION (lecture seule).
> Ne jamais utiliser pour modifier du code (utiliser `libcst` via SmartPatcher).

---

## Localisation

```
D:\LLMCodeAgent\core\ast_indexer.py
```

---

## Dataclasses publiques

### `Symbol`
```python
@dataclass
class Symbol:
    name: str
    type: str           # 'function' | 'class' | 'variable' | 'import'
    line: int           # Numéro de ligne dans le fichier
    file: str           # Chemin absolu du fichier
    dependencies: Set[str]     # Noms utilisés (après résolution cross-file)
    docstring: Optional[str]   # Docstring si présente
    is_private: bool           # True si nom commence par '_'
```

### `FileIndex`
```python
@dataclass
class FileIndex:
    path: str           # Chemin absolu
    symbols: List[Symbol]
    imports: List[str]  # Modules importés (ex: "os", "core.auth")
    exported: List[str] # Noms définis au top-level
    raw_content: str    # Contenu brut (pour SmartPatcher + recherche)
    size_bytes: int
    last_modified: float  # Unix timestamp
```

---

## `ASTIndexer` — API publique

### `__init__(workspace: Path)`

| Attribut | Type | Description |
|----------|------|-------------|
| `workspace` | `Path` | Dossier racine à scanner |
| `files` | `Dict[str, FileIndex]` | Rempli après `index_repository()` |
| `symbols_table` | `Dict[str, List[Symbol]]` | Table cross-fichier après indexation |

### `index_repository() → Dict[str, FileIndex]`

Parcourt récursivement `workspace/` et indexe tous les `.py`.
Exclut `__pycache__/`.

**Idempotent** : efface et recrée `files` et `symbols_table` à chaque appel.

**Résolution cross-file** : après indexation de tous les fichiers,
`_resolve_cross_file_deps()` filtre les `dependencies` pour ne garder
que les noms qui correspondent à des `exported` d'autres fichiers.

**Gestion erreurs** :
- `SyntaxError` → fichier ignoré, warning loggué
- `Exception` générique → fichier ignoré, error loggué

### `_index_file(file_path: Path) → FileIndex`

Indexe un seul fichier. Lève `SyntaxError` si syntaxe invalide.

**Symboles capturés (top-level uniquement) :**
- `ast.FunctionDef` / `ast.AsyncFunctionDef` → type `"function"`
- `ast.ClassDef` → type `"class"` (dépendances = classes de base)
- `ast.Assign` / `ast.AnnAssign` → type `"variable"`
- `ast.Import` → stocke le module racine dans `imports`
- `ast.ImportFrom` → stocke `node.module` dans `imports` (jamais `module.symbole`)

**Trick "parent"** : chaque nœud AST reçoit un attribut `.parent` injecté
pour faciliter les vérifications top-level.

### `_resolve_cross_file_deps() → None`

Intersection des `dependencies` de chaque symbole avec l'ensemble de tous les `exported`.
Résultat : seules les dépendances réellement définies dans d'autres fichiers restent.

---

## Stratégie d'import dans `_index_file`

| Type d'import | Exemple | Ce qui est stocké |
|---------------|---------|-------------------|
| `import os` | `import os` | `"os"` |
| `import os.path` | `import os.path` | `"os.path"` |
| `from auth import fn` | `from auth import fn` | `"auth"` |
| `from core.auth import fn` | `from core.auth import fn` | `"core.auth"` |
| `from . import something` | relatif sans module | `"something"` |

---

## Exemple d'usage

```python
from core.ast_indexer import ASTIndexer

indexer = ASTIndexer(workspace=Path("D:/LLMCodeAgent/workspace"))
files = indexer.index_repository()

# Chercher un symbole
syms = indexer.symbols_table.get("validate_email", [])
for s in syms:
    print(s.file, s.line, s.docstring)

# Voir tous les imports d'un fichier
fi = files.get("auth.py")
print(fi.imports)   # ["re", "pathlib"]
```

---

## Contraintes

- **Lecture seule** : `ASTIndexer` ne modifie jamais les fichiers
- **`ast.parse()`** uniquement — jamais `libcst.parse_module()` ici
- **Idempotence** : relancer 2x = même résultat
- **Performance** : linéaire en nombre de fichiers (pas de cache entre appels)

---

## Tests

Fichier : `tests/test_ast_indexer.py`
**6/6 PASSED**

Cas couverts :
- `index_repository()` — workspace vide
- `index_repository()` — workspace avec 1 fichier
- `_index_file()` — fonction top-level → Symbol correct
- `_index_file()` — classe avec bases → dependencies
- `_index_file()` — SyntaxError → exception propagée
- `_resolve_cross_file_deps()` — filtrage correct des dépendances
