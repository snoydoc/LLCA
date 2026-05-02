# Spec 03 — DependencyGraph
<!-- AI-READY | core/dependency_graph.py | Sprint 03 | Tests: intégrés -->

## Rôle

Graphe orienté de dépendances inter-fichiers Python.
Répond à : "Si je modifie `auth.py`, quels autres fichiers sont impactés ?"

---

## Localisation

```
D:\LLMCodeAgent\core\dependency_graph.py
```

---

## `DependencyGraph` — API publique

### Attributs internes

| Attribut | Type | Description |
|----------|------|-------------|
| `_deps` | `Dict[str, List[str]]` | A → B : A importe B (A dépend de B) |
| `_dependents` | `Dict[str, List[str]]` | A → B : B importe A (B dépend de A) |

Les clés sont des chemins relatifs (ex : `"auth.py"`, `"core/utils.py"`).

### `build(files: Dict[str, FileIndex]) → None`

Construit le graphe depuis l'index produit par `ASTIndexer`.

**Résolution des imports :**
1. `"core.auth"` → essai `"core/auth.py"` (conversion `.` → `/` + `.py`)
2. Sinon essai avec le dernier segment : `"auth"` → `"auth.py"`
3. Ignore les imports vers des modules non présents dans `files`
4. Ignore les auto-références (un fichier ne se dépend pas lui-même)

Après construction, détecte les cycles via DFS et les loggue (sans crash).

### `get_dependencies(file_path: str) → List[str]`

Retourne les fichiers dont `file_path` dépend (imports directs).

```python
graph.get_dependencies("controllers/auth.py")
# → ["core/utils.py", "models/user.py"]
```

### `get_dependents(file_path: str) → List[str]`

Retourne les fichiers qui importent `file_path`.

```python
graph.get_dependents("core/utils.py")
# → ["controllers/auth.py", "controllers/rdv.py"]
```

### `get_impact_radius(file_path: str, depth=2) → Set[str]`

BFS sur le graphe inversé (dépendants) jusqu'à `depth` niveaux.
Retourne l'ensemble des fichiers impactés par une modification de `file_path`.
N'inclut pas `file_path` lui-même dans le résultat.

```python
impacted = graph.get_impact_radius("core/utils.py", depth=2)
# → {"controllers/auth.py", "controllers/rdv.py", "main.py"}
```

### `to_dict() → Dict[str, List[str]]`

Sérialise le graphe (clé = fichier, valeur = liste de fichiers importés).

### `to_json() → str`

Retourne la représentation JSON du graphe.

---

## Algorithme de détection de cycles

DFS récursif sur `_deps` avec `visited` + `rec_stack`.
Si un nœud est dans `rec_stack` lors d'un retour → cycle détecté.
Les cycles sont loggués (`WARNING`) mais n'empêchent pas l'utilisation du graphe.

---

## Exemple d'usage combiné

```python
from core.ast_indexer import ASTIndexer
from core.dependency_graph import DependencyGraph
from pathlib import Path

indexer = ASTIndexer(workspace=Path("D:/proj/workspace"))
files = indexer.index_repository()

graph = DependencyGraph()
graph.build(files)

# Quels fichiers seront impactés si on modifie utils.py ?
impacted = graph.get_impact_radius("utils.py", depth=3)
print("Fichiers à re-tester:", impacted)
```

---

## Contraintes

- **Lecture seule** : `DependencyGraph` ne modifie jamais les fichiers
- **Chemins relatifs** uniquement (relatifs au workspace)
- **`build()` est idempotent** : efface et recrée les structures à chaque appel
- **Cycles** : détectés et loggués, jamais une erreur fatale

---

## Intégration

Utilisé par :
- `FileSelector` — pour étendre les candidats si nécessaire
- `LCCAV5Fusion` — pour la re-indexation post-commit
- `MultiFilePlanner` — pour valider les dépendances du plan
