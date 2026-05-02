# Spec 12 — NL Interface (NLParser + NLOrchestrator)
> **Modules** : `core/nl_parser.py`, `core/nl_orchestrator.py`
> **Sprint** : 10 | **Statut** : ✅ VALIDÉ

---

## 1. Vue d'ensemble

Le module NL (Langage Naturel) permet à l'utilisateur d'interagir avec LCCA en **français ou anglais libre**, sans connaître la syntaxe DSL.

```
"Ajoute une fonction validate_email dans core/utils.py"
                    ↓ NLParser (Qwen via Ollama)
NLIntent { action="add_function", target_file="core/utils.py",
           symbol="validate_email", confidence=0.95 }
                    ↓ NLIntent.to_dsl()
"LCCA - utils - validate_email - Ajoute validate_email"
                    ↓ LCCAV5Fusion.execute()
Transaction atomique + patch AST + commit
```

---

## 2. NLIntent (dataclass)

```python
@dataclass
class NLIntent:
    action:           str            # add_function | modify_function | create_file | read_file | delete_function | unknown
    description:      str            # Description de la modification
    raw_command:      str            # Commande originale
    target_file:      Optional[str]  # "core/utils.py" ou None
    symbol:           Optional[str]  # "validate_email" ou None
    create_if_missing: bool          # True si le fichier doit être créé
    confidence:       float          # 0.0 à 1.0
    from_fallback:    bool           # True si heuristique (pas LLM)

    def is_actionable(self) → bool
    def to_dsl(self) → str
```

### `is_actionable()`
```python
return (
    self.action not in ("unknown",)
    and self.confidence >= 0.5
    and self.description.strip() != ""
)
```

### `to_dsl() → str`
Conversion vers le format DSL Sprint 04 :
```python
# NLIntent(action='add_function', target_file='core/conv.py', symbol='foo') →
"LCCA - conv - foo - Ajoute {description}"
```

---

## 3. NLParser

### `NLPromptBuilder`

**Prompt système** : Demande au modèle de retourner UNIQUEMENT un JSON valide sans texte autour.

**Schema JSON attendu :**
```json
{
    "action": "add_function",
    "target_file": "core/utils.py",
    "symbol": "validate_email",
    "description": "Valide un email",
    "create_if_missing": false,
    "confidence": 0.95
}
```

### `NLIntentExtractor`

**Nettoyage réponse LLM :**
1. Cherche un bloc ` ```json ... ``` `
2. Sinon : extrait de `{` à `}` (première occurrence)
3. Parse JSON

**Fallback heuristique** (si JSON invalide ou Ollama indisponible) :
| Mots-clés détectés | Action |
|-------------------|--------|
| `ajoute`, `add`, `nouvelle fonction` | `add_function` |
| `modifie`, `corrige`, `fix`, `change` | `modify_function` |
| `crée un fichier`, `nouveau fichier` | `create_file` |
| `montre`, `affiche`, `show`, `lis` | `read_file` |
| (autre) | `unknown` |

Confiance du fallback : **0.3** (faible, signale l'incertitude).

### `NLParser` — Interface publique

```python
class NLParser:
    def __init__(self, ollama_url, model, timeout, max_tokens)
    def parse(command, project_files=None) → NLIntent   # JAMAIS d'exception
    def is_available() → bool
```

**Configuration via `config.py` :**
```python
NL_MODEL      = "qwen2.5-coder:14b"
NL_MAX_TOKENS = 256    # Intent JSON est court
OLLAMA_TIMEOUT = 90    # 14B est plus lent que 7B
```

**`project_files`** (optionnel) : Liste de chemins `.py` du projet pour aider le LLM à résoudre les noms ambigus (limitée à 20 fichiers dans le prompt).

---

## 4. NLOrchestrator

### Dataclasses de résultat

**`NLResult`** :
```python
@dataclass
class NLResult:
    success:       bool
    command:       str
    intent_action: str
    intent_file:   Optional[str]
    intent_symbol: Optional[str]
    confidence:    float
    from_fallback: bool
    dsl_command:   str
    error:         str
    duration_s:    float
    dry_run:       bool
    tx_metadata:   dict

    def __str__(self) → str   # Affichage rich (✅/❌, durée, confiance...)
```

**`NLSession`** :
```python
@dataclass
class NLSession:
    results:        List[NLResult]
    commands_total: int
    commands_ok:    int

    def add(result) → None
    def summary() → str   # "Session: 5 commandes, 4 réussies (80%)"
```

### `NLOrchestrator.__init__`

```python
def __init__(
    self,
    project_dir:    Optional[Path] = None,
    nl_parser       = None,    # Injection pour tests
    orchestrator    = None,    # Injection pour tests
    min_confidence: float = 0.4,
    auto_confirm:   bool  = False,
)
```

### `run(command, dry_run=False) → NLResult`

Pipeline complet :
```
1. NLParser.parse(command, project_files) → NLIntent
2. _validate_intent(intent) → "" | message_erreur
   - action == "unknown" → refus
   - description vide → refus
   - confidence < min_confidence ET pas auto_confirm → refus
3. intent.to_dsl() → dsl_command
4. LCCAV5Fusion.execute(dsl) ou dry_run(dsl)
5. → NLResult
```

### REPL interactif — `repl()`

**Commandes spéciales** (O(1) avec sets) :
```python
_REPL_EXIT    = {"exit", "quit", "q", "bye", ":q"}
_REPL_STATUS  = {"status", "état", ":s"}
_REPL_HISTORY = {"history", "historique", ":h"}
_REPL_HELP    = {"help", "aide", "?", ":?"}
_REPL_DRY     = {"dry", "dry-run", "simulate", "sim", ":d"}
```

**Indicateur dry-run** : prefix `(dry) ▶` si mode dry-run actif.

### `refresh_project_files() → int`
À appeler après une création de fichier pour que NLParser connaisse les nouveaux fichiers.

---

## 5. Règles AI-Ready

| Règle | Détail |
|-------|--------|
| Imports module-level | `from core.nl_parser import NLParser` et `from core.orchestrator import LCCAV5Fusion` DOIVENT être en tête de fichier (pas dans `__init__`), sinon `patch("core.nl_orchestrator.NLParser")` échoue |
| `NLParser.parse()` ne lève jamais | Toujours retourne un `NLIntent` (fallback si erreur) |
| `auto_confirm=True` | Pour les tests et scripts non-interactifs (bypasse le seuil de confiance) |
| ChromaDB Python 3.14 | Ajouter `pytest.mark.skipif(sys.version_info >= (3, 14), ...)` sur tous les tests importants |
| Timeout Ollama 14B | 90s minimum (`OLLAMA_TIMEOUT = 90`) |
