# Spec 06 — FileSelector
> **Module** : `core/file_selector.py` | **Sprint** : 04 | **Statut** : ✅ VALIDÉ

---

## 1. Rôle

`FileSelector` est le composant de **résolution de fichiers cibles** dans le pipeline LCCA. À partir d'un `Intent` DSL parsé, il identifie les fichiers du workspace à modifier, en combinant trois stratégies en cascade.

**Contrainte hard** : retourne au maximum `MAX_FILES_PER_TX = 3` fichiers.

---

## 2. API publique

```python
class FileSelector:
    def __init__(self, indexer: ASTIndexer, dep_graph: DependencyGraph, workspace: Path) -> None
    def select(self, intent: Intent) -> List[str]
    def find_symbol_definition(self, name: str) -> list[Symbol]
```

### `select(intent) → List[str]`
Retourne une liste de **chemins relatifs** (strings) au workspace, ordonnés par pertinence, tronqués à `MAX_FILES_PER_TX`.

### `find_symbol_definition(name) → list[Symbol]`
Raccourci direct vers `indexer.symbols_table`. Utile pour les lookups ponctuels.

---

## 3. Algorithme — 3 stratégies en cascade

```
Intent
  │
  ├─ Stratégie 1 : Symbole exact dans l'index AST
  │   └─ Cherche intent.target / sub_target / details dans symbols_table
  │      → retire les "()" résiduels (ex: "validate_email()" → "validate_email")
  │
  ├─ Stratégie 2 : Nom de fichier contient le terme
  │   └─ Pour chaque fichier indexé, compare intent.target/sub_target
  │      (normalisé snake_case, case-insensitive)
  │
  ├─ Stratégie 3 : Contenu brut du fichier contient tous les termes
  │   └─ Activée si candidates < MAX_FILES_PER_TX
  │      Tous les termes doivent être présents dans le contenu
  │
  └─ Fallback : action "crée/ajoute" + 0 match → chemin suggéré
      ex: "src/target_slug.py"
```

### Dédoublonnage
Un `set[str] seen` garantit l'unicité. L'ordre d'insertion est préservé (priorité à la stratégie 1).

---

## 4. Dépendances

| Composant | Rôle dans FileSelector |
|-----------|------------------------|
| `ASTIndexer` | Fourni au constructeur. `symbols_table` et `files` déjà peuplés. |
| `DependencyGraph` | Disponible pour extensions futures (V2 : expansion par impact radius). |
| `config.MAX_FILES_PER_TX` | Importé à la demande dans `select()` pour éviter circularité. |

---

## 5. Contrat comportemental

| Scénario | Résultat attendu |
|----------|-----------------|
| Intent target = nom exact d'un symbole indexé | Fichier contenant ce symbole en position 1 |
| Intent target = fragment de nom de fichier | Fichiers dont le nom contient le fragment |
| Workspace vide / aucun match | `[]` sauf si action create → `["src/{slug}.py"]` |
| Intent avec 4+ fichiers possibles | Tronqué à MAX_FILES_PER_TX |
| `find_symbol_definition("foo()")` | Cherche "foo" (strip des parenthèses) |

---

## 6. Patterns implémentation

```python
# Pattern nettoyage terme
clean = term.strip().rstrip("()")

# Pattern résolution chemin absolu → relatif
try:
    rel = str(Path(sym.file).relative_to(self.workspace))
except ValueError:
    rel = sym.file  # déjà relatif

# Pattern fallback création
target_slug = intent.target.lower().replace(" ", "_").strip("_")
suggested = f"src/{target_slug}.py"
```

---

## 7. Évolutions prévues (V2)

- Stratégie 4 : Expansion via `DependencyGraph.get_impact_radius()` pour inclure les dépendants
- Support multi-workspace (projets MediBot + LCCA simultanément)
- Pondération par fréquence de modification (historique WAL)
