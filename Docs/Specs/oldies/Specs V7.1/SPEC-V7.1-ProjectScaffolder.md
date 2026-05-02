# LCCA V7.1 — Specs Techniques : ProjectScaffolder

## Document
| Champ      | Valeur                              |
|------------|-------------------------------------|
| Version    | V7.1                                |
| Auteur     | LCCA / Claude                       |
| Sprints    | TASK-11-01 à TASK-11-05             |
| Statut     | Validé pour implémentation          |

---

## 1. Vue d'ensemble

### Problème résolu

LCCA V7 ne peut opérer que dans `D:\LLMCodeAgent\workspace\` et uniquement
sur des fichiers Python existants. Les commandes suivantes échouent :

```
❌ "Crée une application dans D:\CodingTests\FileMerge"
❌ "Crée un dossier MonProjet avec un main.py"
❌ "Scaffolde un projet Flask dans D:\CodingTests\MonAPI"
```

### Solution V7.1

Introduire un second pipeline **ProjectScaffolder** en parallèle du pipeline
existant `LCCAV5Fusion`, activé uniquement quand l'action détectée est
`scaffold_project` ou `create_directory`.

```
Commande NL
    │
    ▼
NLParser → NLIntent
    │
    ├─ action ∈ {scaffold_project, create_directory}
    │       ↓
    │   ProjectScaffolder
    │       ↓
    │   ScaffoldGenerator (LLM)
    │       ↓
    │   Fichiers sur disque (transactionnel)
    │
    └─ action ∈ {add_function, modify_function, create_file, ...}
            ↓
        LCCAV5Fusion (pipeline existant, inchangé)
```

---

## 2. Architecture des modules

### Nouveaux fichiers

```
core/
├── scaffolder.py           # Moteur principal (ScaffoldIntent, ProjectScaffolder)
├── scaffold_generator.py   # Génération contenu via LLM
tests/
├── test_scaffolder.py
├── test_scaffold_generator.py
├── test_nl_parser_v71.py
├── test_file_selector_v71.py
└── test_scaffold_e2e.py
```

### Fichiers modifiés

```
core/nl_parser.py           # +2 actions, +target_dir, +prompt rules, +heuristic
core/nl_orchestrator.py     # +routing scaffold, +_run_scaffold()
core/file_selector.py       # +select_external(), +validate_external_path()
config.py                   # +SCAFFOLD_ALLOWED_ROOTS, DENIED_ROOTS, MAX_FILES
check_env.py                # +section #16 ProjectScaffolder
```

---

## 3. Interfaces complètes

### 3.1 `ScaffoldFile`

```python
@dataclass
class ScaffoldFile:
    relative_path: str          # "main.py" | "tests/test_main.py" | "README.md"
    content: str = ""           # Contenu généré (vide avant génération LLM)
    description: str = ""       # Description pour le LLM
    encoding: str = "utf-8-sig" # Encodage Windows BOM
    is_entrypoint: bool = False # True si fichier principal du projet
```

### 3.2 `ScaffoldIntent`

```python
@dataclass
class ScaffoldIntent:
    project_name: str           # "FileMerge"
    target_dir: Path            # D:\LLMCodeAgent\CodingTests\FileMerge
    description: str            # "application qui merge des fichiers .MD"
    files: list[ScaffoldFile]   # Vide au départ, rempli par ScaffoldGenerator
    raw_command: str            # Commande NL originale
    force: bool = False         # Écraser si dossier existant non vide
```

### 3.3 `ScaffoldResult`

```python
@dataclass
class ScaffoldResult:
    success: bool
    project_name: str
    target_dir: Path
    files_created: list[Path]               # Fichiers effectivement écrits
    files_failed: list[tuple[Path, str]]    # (path, message_erreur)
    error: str = ""
    duration_s: float = 0.0
    dry_run: bool = False
    rolled_back: bool = False

    def __str__(self) -> str: ...           # Affichage REPL
```

### 3.4 `ProjectScaffolder`

```python
class ProjectScaffolder:
    def __init__(
        self,
        llm=None,                   # LLMGenerator (injecté ou créé)
        tx_manager=None,            # TransactionManager (injecté ou créé)
        generator=None,             # ScaffoldGenerator (injecté ou créé)
    ) -> None: ...

    def scaffold(self, intent: ScaffoldIntent) -> ScaffoldResult:
        """
        Exécute le scaffolding complet :
        1. Valide la sécurité du chemin cible
        2. Génère le plan de fichiers via ScaffoldGenerator
        3. Génère le contenu de chaque fichier
        4. Écrit les fichiers sur disque (transactionnel)
        5. Rollback si erreur
        """

    def dry_run(self, intent: ScaffoldIntent) -> ScaffoldResult:
        """
        Simule le scaffolding sans écriture disque.
        Retourne ScaffoldResult avec files_created vide et dry_run=True.
        """

    def rollback(self, result: ScaffoldResult) -> None:
        """
        Supprime tous les fichiers listés dans result.files_created.
        Supprime target_dir si elle était vide avant le scaffold.
        """
```

### 3.5 `ScaffoldGenerator`

```python
class ScaffoldGenerator:
    def __init__(self, llm=None) -> None: ...

    def generate_project_plan(
        self,
        intent: ScaffoldIntent,
    ) -> list[ScaffoldFile]:
        """
        Phase 1 : demande au LLM la liste des fichiers à créer.
        Retourne une liste de ScaffoldFile avec content="" (pas encore généré).
        Utilise le stub si Ollama indisponible.
        """

    def generate_file_content(
        self,
        scaffold_file: ScaffoldFile,
        project_context: str = "",
    ) -> str:
        """
        Phase 2 : génère le contenu d'un fichier via Ollama.
        project_context = noms + descriptions des autres fichiers du projet.
        Retourne du code/texte prêt à écrire sur disque.
        """

    def is_available(self) -> bool:
        """True si Ollama répond correctement."""
```

### 3.6 `ScaffoldIntentBuilder`

```python
class ScaffoldIntentBuilder:
    @staticmethod
    def from_nl_intent(intent: NLIntent) -> ScaffoldIntent:
        """
        Convertit un NLIntent (action=scaffold_project) en ScaffoldIntent.
        Résout target_dir : chemin absolu ou relatif à BASE_DIR.
        """
```

---

## 4. Sécurité

### 4.1 Règles de validation de chemin

| Règle | Comportement |
|-------|-------------|
| Chemin avec `..` | `SecurityError` |
| Chemin dans `SCAFFOLD_DENIED_ROOTS` | `SecurityError` |
| Chemin hors `SCAFFOLD_ALLOWED_ROOTS` | Warning + confirmation |
| Dossier cible non vide + `force=False` | `ScaffoldError` avec message clair |
| Extension non dans `SCAFFOLD_ALLOWED_EXTENSIONS` | Ignoré silencieusement |

### 4.2 Limites

| Paramètre | Valeur | Configurable |
|-----------|--------|-------------|
| Max fichiers par scaffold | 8 | `SCAFFOLD_MAX_FILES` |
| Max taille fichier généré | 50 KB | hardcodé |
| Timeout LLM par fichier | 90s | `OLLAMA_TIMEOUT` |

---

## 5. Comportement transactionnel

Le scaffolding est **atomique** : soit tous les fichiers sont créés, soit aucun.

```
BEGIN scaffold tx
    ├─ Créer target_dir
    ├─ Écrire fichier 1 → WAL WRITE_FILE
    ├─ Écrire fichier 2 → WAL WRITE_FILE
    ├─ Écrire fichier N → WAL WRITE_FILE
    ├─ [Erreur sur fichier K]
    │       ↓
    │   ROLLBACK
    │   ├─ Supprimer fichier 1..K-1
    │   └─ Supprimer target_dir si vide
    └─ COMMIT → WAL COMMIT
```

Le WAL existant (`transactions/wal.jsonl`) est utilisé.
Chaque fichier créé génère une entrée `OpType.WRITE_FILE`.

---

## 6. Extension NLParser — schéma JSON complet V7.1

```json
{
  "action": "scaffold_project | create_directory | add_function | modify_function | create_file | read_file | delete_function | unknown",
  "target_dir": "D:\\LLMCodeAgent\\CodingTests\\FileMerge | null",
  "target_file": "core/utils.py | null",
  "symbol": "validate_email | null",
  "description": "description claire de ce qu'il faut faire",
  "create_if_missing": true,
  "confidence": 0.92
}
```

---

## 7. Mots-clés reconnus par le fallback heuristique

### `scaffold_project`
```
"crée une application"   "crée un projet"      "nouvelle application"
"génère un projet"       "scaffold"             "crée une app"
"initialise un projet"   "bootstrappe"          "crée un nouveau projet"
```

### `create_directory`
```
"crée un dossier"        "crée un répertoire"   "crée le dossier"
"nouveau dossier"        "mkdir"                "crée un sous-dossier"
"sous-dossier"
```

### Extraction `target_dir`
```python
# Chemin Windows absolu
re.search(r'[A-Z]:\\[\w\\. -]+', command)

# Mention "dans le dossier X" / "dans X"
re.search(r'dans\s+(?:le\s+dossier\s+)?([A-Z]:\\[\w\\. -]+|[\w/\\. -]+)', command)

# Mention "sous-dossier X" → relatif à BASE_DIR
re.search(r'sous-dossier\s+([\w. -]+)', command)
```

---

## 8. Plan de migration (ordre d'implémentation)

```
TASK-11-04  config.py + file_selector.py      (fondations sécurité)
TASK-11-01  core/scaffolder.py                (moteur core)
TASK-11-03  core/scaffold_generator.py        (LLM)
TASK-11-02  nl_parser.py + nl_orchestrator.py (routing)
TASK-11-05  tests e2e + check_env.py          (validation)
```

---

## 9. Compatibilité V7

Le pipeline `LCCAV5Fusion` existant n'est **pas modifié**.
Les 56/58 tests qui passent actuellement doivent rester verts après V7.1.

Seuls les fichiers suivants sont modifiés (pas réécrits) :
- `config.py` — ajouts de constantes uniquement
- `core/nl_parser.py` — ajouts dans les listes existantes + nouveau champ dataclass
- `core/nl_orchestrator.py` — ajout d'un branchement + nouvelle méthode privée
- `core/file_selector.py` — ajout de deux méthodes publiques
