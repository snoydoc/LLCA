# 🧠 Sprint 03 — AST Indexer & Smart Patcher

> **Durée estimée** : 5 jours  
> **Statut** : ⚪ À FAIRE  
> **Priorité** : 🔴 Critique  
> **Dépend de** : Sprint 01 (venv, config), Sprint 02 (TransactionManager)  
> **Objectif** : Indexer le code Python par AST, puis modifier ce code via libcst (jamais par texte brut).

---

## 🎯 Objectifs du Sprint

Ce sprint implémente le **cerveau technique** de LCCA : la capacité à lire du code Python comme une structure de données (AST), et à le modifier chirurgicalement sans jamais toucher au texte brut.

**Règle d'or** : `libcst` est obligatoire pour toute modification de code. `ast.parse()` est utilisé uniquement pour l'indexation (lecture seule). `regex` est **interdit** pour modifier du code.

---

## 📋 Tâches

### TASK-03-01 — `ASTIndexer` — Indexation d'un fichier
**Priorité** : 🔴 Critique  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `core/ast_indexer.py`

**Description** :  
Implémenter `_index_file()` qui parse un `.py` avec `ast` (lecture uniquement) et en extrait les symboles : fonctions, classes, imports, exports.

**Dataclasses à définir** :
```python
@dataclass
class Symbol:
    name: str
    type: str        # 'function' | 'class' | 'variable' | 'import'
    line: int
    file: str
    dependencies: Set[str] = field(default_factory=set)
    docstring: Optional[str] = None
    is_private: bool = False   # Préfixe '_'


@dataclass
class FileIndex:
    path: str
    symbols: List[Symbol]
    imports: List[str]         # Modules importés
    exported: List[str]        # Noms définis au top-level
    raw_content: str
    size_bytes: int
    last_modified: float
```

**Logique d'extraction** :
```python
def _index_file(self, file_path: Path) -> FileIndex:
    content = file_path.read_text(encoding='utf-8')
    tree = ast.parse(content)
    symbols, imports, exported = [], [], []

    for node in ast.walk(tree):
        # Imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.append(f"{module}.{alias.name}")

        # Fonctions top-level
        elif isinstance(node, ast.FunctionDef) and isinstance(node.parent, ast.Module):
            sym = Symbol(
                name=node.name,
                type="function",
                line=node.lineno,
                file=str(file_path),
                is_private=node.name.startswith('_'),
                docstring=ast.get_docstring(node)
            )
            # Collecte des dépendances (noms utilisés dans le corps)
            for child in ast.walk(node):
                if isinstance(child, ast.Name):
                    sym.dependencies.add(child.id)
            symbols.append(sym)
            exported.append(node.name)

        # Classes top-level
        elif isinstance(node, ast.ClassDef):
            sym = Symbol(
                name=node.name,
                type="class",
                line=node.lineno,
                file=str(file_path),
                docstring=ast.get_docstring(node)
            )
            for base in node.bases:
                if isinstance(base, ast.Name):
                    sym.dependencies.add(base.id)
            symbols.append(sym)
            exported.append(node.name)
    ...
```

**Critères d'acceptation** :
- [ ] Indexe correctement un fichier Python standard
- [ ] Docstrings extraites si présentes
- [ ] Fonctions privées (`_`) marquées `is_private=True`
- [ ] Fichier avec syntaxe invalide → `SyntaxError` capturé, log warning, fichier ignoré

---

### TASK-03-02 — `ASTIndexer` — Indexation du repository entier
**Priorité** : 🔴 Critique  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Implémenter `index_repository()` qui parcourt récursivement `workspace/` et indexe tous les `.py`.

**Logique** :
```python
def index_repository(self) -> Dict[str, FileIndex]:
    self.files.clear()
    self.symbols_table.clear()
    
    py_files = [
        f for f in self.workspace.rglob("*.py")
        if "__pycache__" not in str(f)
    ]
    
    log.info(f"Indexation de {len(py_files)} fichiers Python...")
    
    for py_file in py_files:
        try:
            idx = self._index_file(py_file)
            rel_path = str(py_file.relative_to(self.workspace))
            self.files[rel_path] = idx
            for sym in idx.symbols:
                self.symbols_table.setdefault(sym.name, []).append(sym)
        except SyntaxError as e:
            log.warning(f"Syntaxe invalide {py_file}: {e}")
        except Exception as e:
            log.error(f"Erreur indexation {py_file}: {e}")
    
    self._resolve_cross_file_deps()
    log.info(f"Index: {len(self.files)} fichiers, {len(self.symbols_table)} symboles")
    return self.files
```

**Critères d'acceptation** :
- [ ] `workspace/` vide → index vide, pas d'erreur
- [ ] Fichiers `__pycache__/` exclus
- [ ] Re-indexation idempotente (appel 2x = même résultat)
- [ ] Performance : < 2 secondes pour 100 fichiers

---

### TASK-03-03 — `DependencyGraph` — Graphe d'impact
**Priorité** : 🟠 Haute  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `core/dependency_graph.py`

**Description** :  
Construire un graphe orienté de dépendances entre fichiers Python. Permet de savoir : "Si je modifie `auth.py`, quels autres fichiers peuvent être impactés ?"

**Interface publique** :
```python
class DependencyGraph:
    def build(self, files: Dict[str, FileIndex]) -> None:
        """Construit le graphe depuis l'index."""

    def get_dependents(self, file_path: str) -> List[str]:
        """Retourne les fichiers qui importent file_path."""

    def get_dependencies(self, file_path: str) -> List[str]:
        """Retourne les fichiers dont dépend file_path."""

    def get_impact_radius(self, file_path: str, depth: int = 2) -> Set[str]:
        """Fichiers impactés par une modif (BFS jusqu'à depth niveaux)."""

    def to_dict(self) -> Dict[str, List[str]]:
        """Sérialisation pour stockage."""
```

**Critères d'acceptation** :
- [ ] `get_impact_radius("core/auth.py")` retourne tous les fichiers qui l'importent directement ou indirectement
- [ ] Cycle de dépendances détecté sans crash (warning log)
- [ ] Graphe sérialisable en JSON

---

### TASK-03-04 — `SmartPatcher` — `AddFunctionTransformer`
**Priorité** : 🔴 Critique  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `core/smart_patcher.py`

**Description** :  
Implémenter le transformer libcst qui ajoute une nouvelle fonction à la fin d'un module Python.

**Règles** :
- Utilise `libcst.CSTTransformer` (jamais manipulation de texte brut)
- Préserve le formatting existant (indentation, blank lines)
- Compatible Black (sortable post-modification)
- Vérifie via `compile()` que le résultat est syntaxiquement valide

**Implémentation** :
```python
class AddFunctionTransformer(cst.CSTTransformer):
    """Ajoute une ou plusieurs fonctions à la fin du module."""

    def __init__(self, func_code: str):
        self.func_code = func_code
        self.added = False

    def leave_Module(
        self,
        original_node: cst.Module,
        updated_node: cst.Module
    ) -> cst.Module:
        if self.added:
            return updated_node

        try:
            new_module = cst.parse_module(self.func_code)
        except cst.ParserSyntaxError as e:
            raise SyntaxError(f"Code à injecter invalide: {e}") from e

        # Ajoute 2 lignes vides avant la nouvelle fonction (PEP8)
        separator = cst.EmptyLine(newline=cst.Newline())
        new_body = list(updated_node.body) + [separator, separator] + list(new_module.body)

        self.added = True
        return updated_node.with_changes(body=new_body)
```

**Critères d'acceptation** :
- [ ] Fonction ajoutée à la fin du module
- [ ] 2 lignes vides avant la fonction (PEP8 E302)
- [ ] Code injecté invalide → `SyntaxError` levée avant toute modification
- [ ] Module original préservé si erreur

---

### TASK-03-05 — `SmartPatcher` — `ModifyFunctionTransformer`
**Priorité** : 🔴 Critique  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Modifier le corps d'une fonction existante en préservant sa signature (paramètres, décorateurs, type hints, docstring).

**Séquence de modification** :
1. Trouver la `FunctionDef` par nom
2. Parser le nouveau corps
3. Remplacer uniquement `body` de la FunctionDef
4. Préserver `decorators`, `params`, `returns` (type hint)

```python
class ModifyFunctionTransformer(cst.CSTTransformer):
    def __init__(self, target_name: str, new_body_code: str, preserve_docstring: bool = True):
        self.target_name = target_name
        self.new_body_code = new_body_code
        self.preserve_docstring = preserve_docstring
        self.modified = False

    def leave_FunctionDef(
        self,
        original_node: cst.FunctionDef,
        updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        if original_node.name.value != self.target_name or self.modified:
            return updated_node

        # Parse le nouveau corps
        wrapper = f"def _tmp():\n{self._indent(self.new_body_code)}"
        new_func = cst.parse_module(wrapper).body[0]
        new_body = new_func.body

        # Optionnel: préserve la docstring originale
        if self.preserve_docstring:
            original_body = original_node.body
            if (original_body.body and
                isinstance(original_body.body[0], cst.SimpleStatementLine) and
                isinstance(original_body.body[0].body[0], cst.Expr) and
                isinstance(original_body.body[0].body[0].value, (cst.SimpleString, cst.ConcatenatedString))):
                docstring_stmt = original_body.body[0]
                new_body = new_body.with_changes(
                    body=[docstring_stmt] + list(new_body.body)
                )

        self.modified = True
        return updated_node.with_changes(body=new_body)

    @staticmethod
    def _indent(code: str, spaces: int = 4) -> str:
        return '\n'.join(' ' * spaces + line for line in code.splitlines())
```

**Critères d'acceptation** :
- [ ] Signature (params, decorators, return type) inchangée
- [ ] Docstring préservée si `preserve_docstring=True`
- [ ] Fonction non trouvée → `ValueError` avec message clair
- [ ] Nouveau corps invalide → `SyntaxError` avant modification

---

### TASK-03-06 — `SmartPatcher` — `AddImportTransformer`
**Priorité** : 🟠 Haute  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Ajouter un import en tête de fichier sans créer de doublon.

**Critères d'acceptation** :
- [ ] Import déjà présent → pas de doublon, pas d'erreur
- [ ] `from module import name` → ajouté si absent
- [ ] `import module` → ajouté si absent
- [ ] Import ajouté **après** `from __future__ import ...` si présent
- [ ] Import ajouté **après** la docstring module si présente

---

### TASK-03-07 — `SmartPatcher.apply_patch()` — Interface générique
**Priorité** : 🔴 Critique  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Créer l'interface haut niveau qui orchestre les transformers et écrit le résultat dans le fichier. Toujours utilisée **via** le `TransactionManager` (jamais directement).

```python
def apply_patch(self, file_path: str, patch_type: str, **kwargs) -> str:
    """
    Interface générique. Retourne le nouveau contenu (ne l'écrit PAS lui-même).
    C'est le TransactionManager qui gère l'écriture.
    """
    path = self.workspace / file_path
    source = path.read_text(encoding='utf-8')
    
    # Validation syntaxe AVANT modification
    try:
        compile(source, file_path, 'exec')
    except SyntaxError as e:
        raise SyntaxError(f"Fichier source invalide avant patch: {e}") from e
    
    tree = cst.parse_module(source)
    
    if patch_type == "add_function":
        transformer = AddFunctionTransformer(kwargs['code'])
    elif patch_type == "modify_function":
        transformer = ModifyFunctionTransformer(kwargs['name'], kwargs['code'])
    elif patch_type == "add_import":
        transformer = AddImportTransformer(kwargs['module'], kwargs.get('names'))
    else:
        raise ValueError(f"Type de patch inconnu: {patch_type}")
    
    new_tree = tree.visit(transformer)
    new_code = new_tree.code
    
    # Validation syntaxe APRÈS modification
    try:
        compile(new_code, file_path, 'exec')
    except SyntaxError as e:
        raise SyntaxError(f"Résultat du patch invalide: {e}") from e
    
    return new_code
```

**Critères d'acceptation** :
- [ ] Valide la syntaxe avant ET après le patch
- [ ] Retourne le code modifié (n'écrit pas lui-même)
- [ ] Compatible avec `TransactionManager.log_operation()`

---

### TASK-03-08 — Tests unitaires AST & Patcher
**Priorité** : 🟠 Haute  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `tests/test_ast_indexer.py` et `tests/test_smart_patcher.py`

**Tests** :
```python
# test_ast_indexer.py
def test_index_simple_file():
    """Indexe un fichier avec 1 classe et 2 fonctions."""

def test_symbol_with_docstring():
    """Docstring extraite correctement."""

def test_syntax_error_ignored():
    """Fichier invalide → ignoré, pas de crash."""

def test_cross_file_dependency():
    """B importe A → dépendance détectée."""


# test_smart_patcher.py
def test_add_function_appended():
    """Fonction ajoutée à la fin du module."""

def test_add_function_pep8_spacing():
    """2 lignes vides avant la nouvelle fonction."""

def test_modify_preserves_signature():
    """Signature inchangée après modification corps."""

def test_modify_preserves_docstring():
    """Docstring préservée si preserve_docstring=True."""

def test_no_duplicate_import():
    """Import déjà présent → pas de doublon."""

def test_invalid_code_raises_before_write():
    """Code invalide → SyntaxError levée, fichier inchangé."""
```

**Critères d'acceptation** :
- [ ] `pytest tests/test_ast_indexer.py` → 4/4
- [ ] `pytest tests/test_smart_patcher.py` → 6/6

---

## 📊 Récapitulatif Sprint 03

| Task | Description | Effort | Statut |
|------|------------|--------|--------|
| TASK-03-01 | ASTIndexer → `_index_file()` | 1j | ⚪ |
| TASK-03-02 | ASTIndexer → `index_repository()` | 0.5j | ⚪ |
| TASK-03-03 | DependencyGraph | 1j | ⚪ |
| TASK-03-04 | SmartPatcher → AddFunction | 1j | ⚪ |
| TASK-03-05 | SmartPatcher → ModifyFunction | 1j | ⚪ |
| TASK-03-06 | SmartPatcher → AddImport | 0.5j | ⚪ |
| TASK-03-07 | `apply_patch()` interface | 0.5j | ⚪ |
| TASK-03-08 | Tests unitaires | 0.5j | ⚪ |
| **TOTAL** | | **6j** | |

---

## ✅ Définition of Done (Sprint 03)

- [ ] `pytest tests/test_ast_indexer.py tests/test_smart_patcher.py` → 0 erreur
- [ ] Modifier une fonction → hash MD5 avant ≠ hash MD5 après
- [ ] Modification avec code invalide → fichier inchangé (vérifiable par MD5)
- [ ] `apply_patch()` intégrable avec `log_operation()` du Sprint 02
- [ ] Aucun `regex` utilisé pour modifier du code

---

## ⚠️ Contraintes & Risques

| Risque | Probabilité | Mitigation |
|--------|------------|------------|
| libcst incompatible avec certains patterns Python avancés | Moyenne | Tester sur code réel MediBot |
| Performance indexation sur gros workspace (1000+ fichiers) | Faible | Indexation lazy + cache |
| Décoratateurs complexes mal préservés | Faible | Tests avec `@property`, `@staticmethod` |

---

## 🔗 Navigation

⬅️ [Sprint 02 — Transaction Manager](sprint-02-transaction-manager.md)  
➡️ [Sprint 04 — Planner & Orchestrateur](sprint-04-planner-orchestrator.md)
