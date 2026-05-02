# Spec 07 — Planner (Planner + MultiFilePlanner)
> **Module** : `core/planner.py` | **Sprint** : 04 | **Statut** : ✅ VALIDÉ

---

## 1. Rôle

`planner.py` contient **deux planificateurs** avec deux APIs différentes :

- **`Planner`** (Sprint 01) — API manuelle legacy. Construit un `Plan` depuis une liste de dicts fournis explicitement par l'utilisateur.
- **`MultiFilePlanner`** (Sprint 04) — API automatique. Génère des `PlannedOperation` depuis un `Intent` + liste de fichiers, avec tri topologique et validation de cohérence.

---

## 2. Dataclasses

### `OpPriority` (IntEnum)
```python
HIGH   = 1   # Fichiers core, action "crée"
NORMAL = 2   # Ajout/modification standard
LOW    = 3   # Suppression, refactor
```

### `PatchOperation` (legacy Sprint 01)
```python
@dataclass
class PatchOperation:
    file: Path
    operation: str          # "add_function" | "modify_function" | "add_import" | "create"
    target_name: str = ""
    code: str = ""
```

### `PlannedOperation` (Sprint 04)
```python
@dataclass
class PlannedOperation:
    file: str               # Chemin relatif workspace
    action: str             # 'create' | 'modify' | 'delete'
    target_symbol: Optional[str]
    description: str
    dependencies: List[str] = []
    priority: OpPriority = NORMAL
    patch_type: str = "add_function"   # 'add_function' | 'modify_function' | 'add_import'

    @property
    def file_path(self) -> Path
```

### `Plan` (legacy Sprint 01)
```python
@dataclass
class Plan:
    task_label: str
    operations: list[PatchOperation]

    def is_valid(self, max_files: int = 3) -> bool
```

---

## 3. Planner — API legacy

```python
class Planner:
    def build(self, task_label: str, operations: list[dict]) -> Plan
```

**Format dict attendu :**
```python
{"file": "path.py", "operation": "add_function", "target_name": "fn", "code": "def fn(): ..."}
```

**Raises** `ValueError` si `> MAX_FILES_PER_TX` fichiers distincts.

---

## 4. MultiFilePlanner — API automatique

### `create_plan(intent_details, target_files, intent_action, intent_target) → List[PlannedOperation]`

Pipeline :
1. Dédoublonnage des fichiers + limite MAX
2. Pour chaque fichier : `_infer_op_params()` → `(action, patch_type, priority)`
3. Pour chaque fichier : `_infer_symbol()` → nom de symbole depuis les détails
4. `_topological_sort()` → tri par priorité + longueur dépendances

### `validate_plan_consistency(ops) → Tuple[bool, List[str]]`

Règles validées :
| Règle | Message d'erreur |
|-------|-----------------|
| `> MAX_FILES_PER_TX` fichiers | "Trop de fichiers (N > 3)" |
| Même symbole modifié dans ≥2 fichiers | "Symbole 'X' modifié dans plusieurs fichiers" |
| Fichier supprimé ET modifié | "Fichier à la fois supprimé et modifié" |

---

## 5. Inférence des paramètres d'opération

### `_infer_op_params(intent_action, file, intent_target, intent_details)`

| intent_action | action | patch_type | priority |
|---------------|--------|------------|---------|
| `ajoute` | modify | add_function | NORMAL |
| `modifie` | modify | modify_function | NORMAL |
| `supprime` | delete | add_function | LOW |
| `cree`/`crée` | create | add_function | HIGH |
| `refactor` | modify | modify_function | LOW |
| `corrige` | modify | modify_function | HIGH |

**Surcharges :**
- Si `"import"` dans details → `patch_type = "add_import"`
- Si `"core"` ou `"__init__"` dans le nom de fichier → `priority = HIGH`

### `_infer_symbol(details) → Optional[str]`

1. Cherche `\b(identifier)\s*(` → extrait le nom de fonction
2. Sinon : premier mot snake_case valide
3. Sinon : `None`

### `_topological_sort(ops) → List[PlannedOperation]`

Tri stable Python par `(priority.value, len(dependencies))`. Les opérations HIGH sans dépendances arrivent en premier.

---

## 6. Rétrocompatibilité

`Planner` (Sprint 01) est conservé pour `test_smoke.py` et les usages manuels.
`MultiFilePlanner` est utilisé par `LCCAV5Fusion` depuis Sprint 04.

---

## 7. Contraintes AI-Ready

- `MAX_FILES_PER_TX` importé depuis `config` (jamais hardcodé)
- `PlannedOperation.file` est un `str` relatif (pas un `Path` absolu) pour sérialisation JSON
- `PlannedOperation.file_path` est la property qui retourne le `Path` correspondant
