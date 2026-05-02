# Spec 04 — SmartPatcher
<!-- AI-READY | core/smart_patcher.py | Sprint 03 | Tests: 6/6 PASSED -->

## Rôle

Modification chirurgicale de code Python via `libcst` (AST Concrete Syntax Tree).

> **⚠️ JAMAIS de texte brut, JAMAIS de regex pour modifier du code Python.**
> SmartPatcher retourne toujours un `str` — il n'écrit JAMAIS sur disque.
> C'est le `TransactionManager` (via `LCCAV5Fusion`) qui écrit.

---

## Localisation

```
D:\LLMCodeAgent\core\smart_patcher.py
```

---

## Transformers libcst

### `AddFunctionTransformer`

Ajoute une ou plusieurs fonctions **à la fin du module**.

**Comportement :**
- Valide le code à injecter (`libcst.parse_module()`) avant transformation
- Insère 2 lignes vides avant la nouvelle fonction (PEP 8 E302, via `leading_lines`)
- N'ajoute qu'une fois (flag `self._added`)

**Constructeur :**
```python
AddFunctionTransformer(func_code: str)
# Lève SyntaxError si func_code est invalide
```

### `ModifyFunctionTransformer`

Remplace le **corps** d'une fonction existante.

**Comportement :**
- Préserve : signature, décorateurs, type hints
- Préserve optionnellement la docstring (`preserve_docstring=True` par défaut)
- Parse le nouveau corps via un wrapper `def _tmp_():` pour créer un `IndentedBlock`
- Flag `self.modified` pour éviter les modifications multiples

**Constructeur :**
```python
ModifyFunctionTransformer(
    target_name: str,
    new_body_code: str,
    preserve_docstring: bool = True
)
```

**Vérification** : après transformation, si `transformer.modified == False`
→ la fonction cible n'a pas été trouvée → lever `ValueError`.

### `AddImportTransformer`

Ajoute un import en tête de module **sans créer de doublon**.

**Comportement :**
- Supporte `import module` et `from module import name1, name2`
- Placement : après `from __future__ import ...` et la docstring module
- Vérifie d'abord si l'import existe déjà (ne fait rien si présent)

**Constructeur :**
```python
AddImportTransformer(
    module: str,
    names: Optional[Sequence[str]] = None
)
# names=None → "import module"
# names=["fn1", "fn2"] → "from module import fn1, fn2"
```

---

## `SmartPatcher` — Interface publique

### `__init__(workspace=None)`

| Param | Défaut | Description |
|-------|--------|-------------|
| `workspace` | `D:\LLMCodeAgent\workspace` | Dossier racine des fichiers cibles |

### `apply_patch(file_path, patch_type, **kwargs) → str`

Interface unifiée. Lit le fichier, applique le transformer, valide, retourne le nouveau contenu.

**Validation double :**
1. `compile(source, ...)` AVANT le patch (source originale)
2. `compile(new_code, ...)` APRÈS le patch (résultat)

| `patch_type` | kwargs requis | Description |
|--------------|---------------|-------------|
| `"add_function"` | `code: str` | Ajoute une fonction en fin de module |
| `"modify_function"` | `name: str`, `code: str`, `preserve_docstring: bool` | Remplace le corps |
| `"add_import"` | `module: str`, `names: Optional[List[str]]` | Ajoute un import |

**Lève :**
- `ImportError` si `libcst` non installé
- `SyntaxError` si source ou résultat invalide
- `ValueError` si `patch_type` inconnu ou fonction introuvable

### `add_function(path, func_code) → str`
### `modify_function(path, func_name, new_body_code, preserve_docstring=True) → str`
### `add_import(path, module, names=None) → str`

Méthodes de commodité (même logique que `apply_patch`).

---

## Règles critiques

```
❌ INTERDIT : file.write() direct
❌ INTERDIT : regex sur le code source Python
❌ INTERDIT : ast.parse() pour modifier (lire seulement)
✅ OBLIGATOIRE : libcst pour toute modification
✅ OBLIGATOIRE : compile() avant ET après chaque patch
✅ OBLIGATOIRE : SmartPatcher retourne str, jamais None, jamais écriture disque
```

---

## Pattern PEP8 E302 (`AddFunctionTransformer`)

```python
# Avant injection : 2 EmptyLine via leading_lines
blank_lines = [cst.EmptyLine(), cst.EmptyLine()]
new_stmts[0] = first.with_changes(
    leading_lines=blank_lines + existing_leading
)
```

---

## Pattern `ModifyFunctionTransformer` (wrapper)

```python
# Trick : parser un corps de fonction seul est impossible en libcst
# → envelopper dans def _tmp_(): pour obtenir un IndentedBlock
wrapper = f"def _tmp_():\n{self._indent(self.new_body_code)}\n"
tmp_module = cst.parse_module(wrapper)
new_body: cst.IndentedBlock = tmp_module.body[0].body
```

---

## Exemple d'usage

```python
from core.smart_patcher import SmartPatcher

patcher = SmartPatcher(workspace=Path("D:/proj/workspace"))

# Ajouter une fonction
new_code = patcher.apply_patch(
    "auth.py",
    "add_function",
    code="def validate_email(email: str) -> bool:\n    return '@' in email\n"
)

# new_code est le contenu Python complet du fichier modifié
# À passer à TransactionManager.log_operation() pour écriture ACID
```

---

## Tests

Fichier : `tests/test_smart_patcher.py`
**6/6 PASSED**

Cas couverts :
- `add_function` — fichier simple → fonction ajoutée en fin
- `add_function` — PEP8 E302 : 2 lignes vides avant la nouvelle fonction
- `modify_function` — corps remplacé, signature préservée
- `modify_function` — docstring préservée (`preserve_docstring=True`)
- `modify_function` — fonction introuvable → `ValueError`
- `add_import` — ajout sans doublon
- Syntaxe invalide en entrée → `SyntaxError`
