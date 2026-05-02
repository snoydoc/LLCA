# -*- Sprint 11 — TASK-11-02 -*-
# LCCA V7.1 — ProjectScaffolder : Extension NLIntent + NLParser

## Métadonnées
| Champ        | Valeur                                        |
|--------------|-----------------------------------------------|
| Sprint       | 11                                            |
| Task         | TASK-11-02                                    |
| Version      | V7.1                                          |
| Statut       | À faire                                       |
| Priorité     | Haute                                         |
| Dépendance   | TASK-11-01                                    |
| Fichiers     | `core/nl_parser.py`, `core/nl_orchestrator.py`|

---

## Objectif

Étendre `NLIntent` et `NLParser` pour reconnaître les nouvelles actions
de scaffolding, et router correctement depuis `NLOrchestrator`.

---

## Modifications `core/nl_parser.py`

### 1. Nouvelles actions valides dans `NLIntent.VALID_ACTIONS`

```python
VALID_ACTIONS: tuple = (
    "add_function",
    "modify_function",
    "create_file",        # existant — fichier unique dans workspace
    "read_file",
    "delete_function",
    "scaffold_project",   # NOUVEAU — projet multi-fichiers hors workspace
    "create_directory",   # NOUVEAU — dossier vide hors workspace
    "unknown",
)
```

### 2. Nouveau champ dans `NLIntent`

```python
@dataclass
class NLIntent:
    ...
    target_dir: Optional[str] = None   # NOUVEAU : chemin absolu cible (ex: D:\CodingTests\FileMerge)
```

### 3. Extension du prompt Ollama (`NLPromptBuilder._SYSTEM`)

Ajouter dans le prompt système les règles suivantes :

```
- If the user mentions "crée une application", "crée un projet", "scaffold",
  "nouveau projet", "génère un projet" → action = "scaffold_project"
- If the user mentions "crée un dossier", "crée un répertoire", "mkdir" → action = "create_directory"
- If a Windows or Unix absolute path is mentioned (ex: D:\CodingTests\FileMerge),
  extract it as "target_dir"
- If a subfolder is mentioned ("dans le dossier X", "sous-dossier Y"), extract as "target_dir"
```

Ajouter `target_dir` au schéma JSON attendu :

```json
{
  "action": "scaffold_project",
  "target_dir": "D:\\LLMCodeAgent\\CodingTests\\FileMerge",
  "target_file": null,
  "symbol": null,
  "description": "application qui merge des fichiers .MD en un seul fichier",
  "create_if_missing": true,
  "confidence": 0.92
}
```

### 4. Extension du fallback heuristique (`_heuristic_fallback`)

```python
# Détecter scaffold_project
if any(kw in cmd_lower for kw in (
    "crée une application", "crée un projet", "nouvelle application",
    "scaffold", "génère un projet", "crée une app"
)):
    action = "scaffold_project"

# Détecter create_directory
elif any(kw in cmd_lower for kw in (
    "crée un dossier", "crée un répertoire", "crée le dossier",
    "nouveau dossier", "mkdir"
)):
    action = "create_directory"

# Extraire target_dir : chemin Windows absolu
dir_match = re.search(r'[A-Z]:\\[\w\\]+', command)
target_dir = dir_match.group(0) if dir_match else None
```

---

## Modifications `core/nl_orchestrator.py`

### Routing dans `NLOrchestrator.run()`

Après l'étape de validation de l'intent, ajouter un branchement :

```python
# Étape 3b : routing selon l'action
if intent.action in ("scaffold_project", "create_directory"):
    return self._run_scaffold(intent, dry_run=dry_run, t0=t0)
else:
    # Pipeline existant LCCAV5Fusion (inchangé)
    ...
```

### Nouvelle méthode `_run_scaffold()`

```python
def _run_scaffold(self, intent: NLIntent, dry_run: bool, t0: float) -> NLResult:
    from core.scaffolder import ProjectScaffolder, ScaffoldIntentBuilder

    scaffold_intent = ScaffoldIntentBuilder.from_nl_intent(intent)
    scaffolder = ProjectScaffolder(llm=self.orchestrator.llm)

    if dry_run:
        result = scaffolder.dry_run(scaffold_intent)
    else:
        result = scaffolder.scaffold(scaffold_intent)

    return NLResult(
        success       = result.success,
        command       = intent.raw_command,
        intent_action = intent.action,
        intent_file   = str(result.target_dir),
        confidence    = intent.confidence,
        from_fallback = intent.from_fallback,
        error         = result.error,
        duration_s    = time.monotonic() - t0,
        dry_run       = dry_run,
    )
```

---

## Critères d'acceptance

- [ ] `"Crée une application dans D:\CodingTests\FileMerge"` → `action=scaffold_project` (conf ≥ 0.7)
- [ ] `"Crée un dossier MonProjet"` → `action=create_directory` (conf ≥ 0.6)
- [ ] `target_dir` extrait correctement depuis les chemins Windows et les mentions relatives
- [ ] Fallback heuristique reconnaît les variantes françaises
- [ ] `NLOrchestrator` route vers `_run_scaffold` sans toucher au pipeline existant

---

## Tests à écrire

Fichier : `tests/test_nl_parser_v71.py`

```
test_nl_parser_scaffold_project()
test_nl_parser_create_directory()
test_nl_parser_extract_target_dir_windows_path()
test_nl_parser_extract_target_dir_relative()
test_heuristic_fallback_scaffold()
test_heuristic_fallback_create_directory()
test_orchestrator_routes_to_scaffold()
```
