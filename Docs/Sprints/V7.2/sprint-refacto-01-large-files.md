# Sprint REFACTO-01 — Refactorisation des fichiers trop grands
<!-- AI-READY | Sprint REFACTO-01 | Version 1.0.0 | 2026-04-19 -->

## Contexte & objectif

Plusieurs fichiers du projet dépassent le seuil de lisibilité et de maintenabilité.
Un fichier "trop grand" dans LCCA V7.2 est défini ainsi :

| Seuil | Signification |
|-------|---------------|
| > 20 KB | À surveiller |
| > 25 KB | Refactorisation recommandée |
| > 30 KB | Refactorisation obligatoire |

Les fichiers visés cumulent plusieurs problèmes : responsabilités multiples dans une seule classe,
schémas de données mélangés au code métier, définitions statiques volumineuses embarquées dans le
module principal, et handlers répétitifs sans abstraction.

**Prérequis** : Sprint UI-06b vert (timeout web_search corrigé).
**Livrable** : 8 fichiers refactorisés, tests existants toujours verts, aucune régression API publique.

---

## Inventaire des fichiers ciblés

| Priorité | Fichier | Taille | Problème principal |
|----------|---------|--------|--------------------|
| 🔴 P0 | `core/mcp_server.py` | 35.9 KB | Tool defs + handlers + lifecycle + stdio dans une seule classe |
| 🔴 P0 | `core/transaction_manager.py` | 21.0 KB | Dataclasses + logique ACID + helpers legacy + cleanup dans un seul fichier |
| 🟠 P1 | `core/nl_orchestrator.py` | 20.3 KB | REPL + logique métier + affichage mélangés |
| 🟠 P1 | `core/nl_parser.py` | 20.2 KB | NLIntent dataclass + PromptBuilder + IntentExtractor + NLParser dans un seul module |
| 🟠 P1 | `core/spec_validator.py` | 19.7 KB | 15 classes RuleChecker + service + helpers dans un seul fichier |
| 🟡 P2 | `core/orchestrator.py` | 19.1 KB | Flux principal + Spec Layer + méthodes utilitaires mélangés |
| 🟡 P2 | `core/smart_patcher.py` | 18.7 KB | 3 transformers libcst + SmartPatcher API + fallback texte dans un seul fichier |
| 🟡 P2 | `core/code_evaluator.py` | 18.4 KB | 5 critères d'évaluation + scorers + dataclasses + interface dans un seul module |

---

## Tâche 1 — `core/mcp_server.py` → 4 modules (P0)

### Problème
35.9 KB. Contient : définitions `_TOOLS` (JSON statique, ~200 lignes), `McpServer.__init__`
avec 11 dépendances, 11 handlers `_tool_*`, lifecycle JSON-RPC, boucle stdio.
Ajouter un nouveau tool oblige à modifier la même classe god-object.

### Découpage cible

```
core/
  mcp_server.py          → McpServer (lifecycle + dispatch + stdio) — < 12 KB
  mcp_tools_schema.py    → _TOOLS list + schemas inputSchema          — < 6 KB
  mcp_tool_handlers.py   → Mixin McpToolHandlers (11 _tool_* méthodes) — < 16 KB
  mcp_types.py           → constantes JSON-RPC (_ERR_*, _JSONRPC)      — < 1 KB
```

### Règles de découpage

```python
# mcp_types.py — NOUVEAU
_JSONRPC              = "2.0"
_ERR_PARSE            = -32700
_ERR_INVALID_REQ      = -32600
_ERR_METHOD_NOT_FOUND = -32601
_ERR_INVALID_PARAMS   = -32602
_ERR_INTERNAL         = -32603
_ERR_SECURITY         = -32001
_ERR_TOOL_FAILED      = -32002
```

```python
# mcp_tools_schema.py — NOUVEAU
# Contient uniquement _TOOLS : List[Dict[str, Any]]
# Zéro logique, zéro import de config
# Importé par mcp_server.py : from core.mcp_tools_schema import _TOOLS
from __future__ import annotations
from typing import Any, Dict, List
_TOOLS: List[Dict[str, Any]] = [ ... ]  # Les 11 définitions actuelles
```

```python
# mcp_tool_handlers.py — NOUVEAU
class McpToolHandlers:
    """
    Mixin portant les 11 handlers _tool_*.
    Suppose que self._memory, self._edit_batch, ... sont définis par McpServer.
    Aucun __init__, aucune logique lifecycle.
    """
    def _tool_memory_search(self, args: Dict) -> Dict: ...
    def _tool_memory_store(self, args: Dict) -> Dict: ...
    # ... 9 autres handlers
```

```python
# mcp_server.py — REFACTORISÉ
from core.mcp_tool_handlers import McpToolHandlers
from core.mcp_tools_schema  import _TOOLS
from core.mcp_types         import _JSONRPC, _ERR_PARSE, ...

class McpServer(McpToolHandlers):
    """Lifecycle JSON-RPC + dispatch + stdio. Handlers dans McpToolHandlers."""
    def __init__(self, ...): ...
    def handle(self, request): ...
    def serve_stdio(self): ...
    # Plus de _tool_* ici
```

### Contrat API : zéro régression
- `from core.mcp_server import McpServer` continue de fonctionner
- `McpServer().serve_stdio()` identique
- `McpServer._tool_web_search` accessible (via héritage)

### Tests à vérifier
- `tests/test_mcp_server.py` — tous les tests existants doivent passer
- Lancer : `python -m pytest tests/test_mcp_server.py -v`

---

## Tâche 2 — `core/transaction_manager.py` → 3 modules (P0)

### Problème
21.0 KB. Mélange : enums/dataclasses (`TxStatus`, `OpType`, `FileSnapshot`, `Operation`,
`Transaction`), logique ACID principale (`begin/log_operation/commit/rollback`),
helpers legacy (`begin_legacy`, `snapshot`, `restore`), et cleanup WAL.

### Découpage cible

```
core/
  transaction_manager.py   → TransactionManager (ACID core) — < 12 KB
  transaction_types.py     → TxStatus, OpType, FileSnapshot, Operation, Transaction, TransactionError — < 5 KB
  transaction_legacy.py    → helpers legacy (begin_legacy, snapshot, restore, rollback_legacy) — < 3 KB
```

### Règles de découpage

```python
# transaction_types.py — NOUVEAU
# Zéro logique, que des dataclasses + enums.
# Importé par transaction_manager.py et tout le projet qui manipule ces types.
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

class TxStatus(Enum): ...
class OpType(Enum): ...

@dataclass
class FileSnapshot: ...

@dataclass
class Operation: ...

@dataclass
class Transaction: ...

class TransactionError(RuntimeError): ...
```

```python
# transaction_legacy.py — NOUVEAU
# Méthodes stateless legacy — peuvent être des fonctions ou un mixin.
class TransactionLegacyMixin:
    def begin_legacy(self, ...): ...
    def commit_legacy(self, ...): ...
    def rollback_legacy(self, ...): ...
    def snapshot(self, ...): ...
    def restore(self, ...): ...
    def new_tx_id(self) -> str: ...
    def md5(self, ...) -> str: ...
```

```python
# transaction_manager.py — REFACTORISÉ
from core.transaction_types  import TxStatus, OpType, FileSnapshot, Operation, Transaction, TransactionError
from core.transaction_legacy import TransactionLegacyMixin

class TransactionManager(TransactionLegacyMixin):
    """Logique ACID : begin / log_operation / commit / rollback / cleanup."""
    # Plus de dataclasses ici
    # Plus de helpers legacy ici (dans le mixin)
```

### Contrat API : zéro régression
```python
# Rétrocompatibilité — ajouter dans transaction_manager.py :
from core.transaction_types import (
    TxStatus, OpType, FileSnapshot, Operation, Transaction, TransactionError
)
# Ainsi : from core.transaction_manager import TxStatus  continue de fonctionner
```

---

## Tâche 3 — `core/nl_parser.py` → 3 modules (P1)

### Problème
20.2 KB. Mélange : `NLIntent` dataclass (avec logique `to_dsl`), `NLPromptBuilder`
(construction de prompt), `NLIntentExtractor` (parsing JSON + fallback), `NLParser` (HTTP + interface).

### Découpage cible

```
core/
  nl_parser.py          → NLParser (HTTP Ollama + interface publique) — < 8 KB
  nl_intent.py          → NLIntent dataclass + to_dsl() + VALID_ACTIONS — < 5 KB
  nl_intent_builder.py  → NLPromptBuilder + NLIntentExtractor          — < 8 KB
```

### Règles

```python
# nl_intent.py — NOUVEAU
@dataclass
class NLIntent:
    action: str
    description: str
    raw_command: str
    target_file: Optional[str] = None
    symbol: Optional[str] = None
    create_if_missing: bool = False
    confidence: float = 0.0
    from_fallback: bool = False

    def is_actionable(self) -> bool: ...
    def to_dsl(self) -> str: ...
```

```python
# nl_intent_builder.py — NOUVEAU
class NLPromptBuilder:
    def build(self, command, project_files) -> tuple[str, str]: ...

class NLIntentExtractor:
    def extract(self, raw, original_command) -> NLIntent: ...
    def _clean_response(self, raw) -> str: ...
    def _build_intent(self, data, original_command) -> NLIntent: ...
    def _heuristic_fallback(self, command) -> NLIntent: ...
```

### Contrat API
```python
# nl_parser.py — ajouter rétrocompat :
from core.nl_intent import NLIntent  # re-export
```

---

## Tâche 4 — `core/nl_orchestrator.py` → 2 modules (P1)

### Problème
20.3 KB. Mélange : `NLResult`/`NLSession` dataclasses, logique orchestration
(`_validate_intent`, `_scan_project_files`), et REPL interactif avec affichage
(`repl`, `_print_banner`, `_print_help`).

### Découpage cible

```
core/
  nl_orchestrator.py     → NLOrchestrator (run + dry_run + validation + scan) — < 12 KB
  nl_repl.py             → NLRepl (repl + _print_banner + _print_help) — < 6 KB
  nl_types.py            → NLResult + NLSession dataclasses — < 4 KB
```

### Règles

```python
# nl_types.py — NOUVEAU
@dataclass
class NLResult: ...

@dataclass
class NLSession: ...
```

```python
# nl_repl.py — NOUVEAU
class NLRepl:
    """REPL interactif découplé de NLOrchestrator."""
    def __init__(self, orchestrator: NLOrchestrator): ...
    def start(self) -> None: ...  # ancienne méthode repl()
    def _print_banner(self) -> None: ...
    def _print_help(self) -> None: ...
```

```python
# nl_orchestrator.py — REFACTORISÉ
class NLOrchestrator:
    def run(self, command, dry_run=False) -> NLResult: ...
    def dry_run(self, command) -> NLResult: ...
    def repl(self) -> None:
        NLRepl(self).start()  # délègue au NLRepl
```

---

## Tâche 5 — `core/spec_validator.py` → 2 modules (P1)

### Problème
19.7 KB. 15 classes `RuleChecker` concrètes + `RULE_REGISTRY` + `_format_notes`
+ `SpecValidatorService` dans un seul fichier.
Ajouter une règle = modifier un fichier déjà dense.

### Découpage cible

```
core/
  spec_validator.py        → SpecValidatorService + _format_notes — < 6 KB
  spec_validator_rules.py  → RuleChecker ABC + Rule1..Rule15 + RULE_REGISTRY + _build_registry_v72() — < 14 KB
```

### Règles

```python
# spec_validator_rules.py — NOUVEAU
from abc import ABC, abstractmethod

class RuleChecker(ABC):
    rule_id: str
    description: str
    blocking: bool

    @abstractmethod
    def analyze(self, body_md: str) -> list[dict]: ...

class Rule1SmartPatcherStr(RuleChecker): ...
# ... Rule2 à Rule15

def _build_registry_v72() -> dict[str, RuleChecker]: ...
RULE_REGISTRY: dict[str, RuleChecker] = _build_registry_v72()
```

```python
# spec_validator.py — REFACTORISÉ
from core.spec_validator_rules import RULE_REGISTRY, RuleChecker  # re-export

class SpecValidatorService:
    def validate(self, spec) -> dict: ...
```

---

## Tâche 6 — `core/smart_patcher.py` → 2 modules (P2)

### Problème
18.7 KB. 3 classes `*Transformer` libcst (AddFunction, ModifyFunction, AddImport)
+ `SmartPatcher` API + fallback texte (mode sans libcst) dans un seul fichier.

### Découpage cible

```
core/
  smart_patcher.py             → SmartPatcher (API publique + fallback texte) — < 8 KB
  smart_patcher_transformers.py → AddFunctionTransformer, ModifyFunctionTransformer, AddImportTransformer — < 10 KB
```

### Règles

```python
# smart_patcher_transformers.py — NOUVEAU
# Disponible uniquement si _LIBCST_AVAILABLE
# Importé lazily dans smart_patcher.py pour éviter l'import au chargement du module

try:
    import libcst as cst
    from smart_patcher_transformers import (
        AddFunctionTransformer,
        ModifyFunctionTransformer,
        AddImportTransformer,
    )
    _LIBCST_AVAILABLE = True
except ImportError:
    _LIBCST_AVAILABLE = False
```

---

## Tâche 7 — `core/code_evaluator.py` → 2 modules (P2)

### Problème
18.4 KB. 5 critères d'évaluation embarqués (`_CriteriaScorer` avec méthodes
`_score_syntax`, `_score_type_hints`, `_score_docstrings`, `_score_complexity`,
`_score_antipatterns`) + `EvaluationResult` dataclass + `CodeEvaluator` interface.

### Découpage cible

```
core/
  code_evaluator.py         → CodeEvaluator + EvaluationResult + CriterionScore — < 8 KB
  code_evaluator_criteria.py → _CriteriaScorer + 5 méthodes de scoring — < 10 KB
```

### Règles

```python
# code_evaluator_criteria.py — NOUVEAU
class _CriteriaScorer:
    def score_syntax(self, code: str) -> CriterionScore: ...
    def score_type_hints(self, tree: ast.AST) -> CriterionScore: ...
    def score_docstrings(self, tree: ast.AST) -> CriterionScore: ...
    def score_complexity(self, tree: ast.AST) -> CriterionScore: ...
    def score_antipatterns(self, code: str) -> CriterionScore: ...
```

```python
# code_evaluator.py — REFACTORISÉ
from core.code_evaluator_criteria import _CriteriaScorer

class CodeEvaluator:
    def __init__(self, threshold: int = 60):
        self._scorer = _CriteriaScorer()
    def evaluate(self, code: str, filename: str = "<generated>") -> EvaluationResult: ...
```

---

## Tâche 8 — `core/orchestrator.py` → 2 modules (P2)

### Problème
19.1 KB. `LCCAV5Fusion` orchestre le flux principal **et** embarque `_run_spec_layer`
(Spec Layer), `_validate_changes`, `_log_sprint_output` + méthode `dry_run` et
`execute`. L'alias `Orchestrator` legacy alourdit aussi le fichier.

### Découpage cible

```
core/
  orchestrator.py        → LCCAV5Fusion (flux principal + execute + dry_run) — < 12 KB
  orchestrator_spec.py   → OrchestratorSpecMixin (_run_spec_layer + helpers spec) — < 5 KB
  orchestrator_compat.py → Alias Orchestrator = LCCAV5Fusion + rétrocompat Sprint 01 — < 1 KB
```

### Règles

```python
# orchestrator_spec.py — NOUVEAU
class OrchestratorSpecMixin:
    """
    Mixin Spec Layer pour LCCAV5Fusion.
    Suppose que self._spec_generator, self._spec_validator sont définis.
    """
    def _run_spec_layer(self, intent, domain): ...
    def _get_spec_generator(self): ...
    def _get_spec_validator(self): ...
```

```python
# orchestrator_compat.py — NOUVEAU
from core.orchestrator import LCCAV5Fusion
Orchestrator = LCCAV5Fusion  # Alias rétrocompat Sprint 01
```

```python
# orchestrator.py — REFACTORISÉ
from core.orchestrator_spec import OrchestratorSpecMixin

class LCCAV5Fusion(OrchestratorSpecMixin):
    """Flux principal uniquement. Spec Layer dans OrchestratorSpecMixin."""
    ...
```

---

## Plan d'exécution recommandé

Les tâches sont indépendantes et peuvent être réalisées dans n'importe quel ordre.
L'ordre suivant minimise les risques de casse de dépendances :

```
1. mcp_types.py            (aucune dépendance entrante)
2. transaction_types.py    (aucune dépendance entrante)
3. nl_intent.py            (aucune dépendance entrante)
4. nl_types.py             (aucune dépendance entrante)
5. spec_validator_rules.py (aucune dépendance entrante)
6. mcp_tools_schema.py     (dépend de config pour SANDBOX_TIMEOUT)
7. smart_patcher_transformers.py (dépend de libcst)
8. code_evaluator_criteria.py   (dépend de ast)
─── Puis les refactos avec mixins ───
9.  mcp_tool_handlers.py   (dépend de mcp_types + sous-modules core)
10. transaction_legacy.py  (dépend de transaction_types)
11. nl_intent_builder.py   (dépend de nl_intent)
12. nl_repl.py             (dépend de nl_types + nl_orchestrator)
13. orchestrator_spec.py   (dépend de spec_generator + spec_validator)
14. orchestrator_compat.py (dépend de orchestrator)
─── Puis les fichiers principaux ───
15. mcp_server.py          (hérite de McpToolHandlers)
16. transaction_manager.py (hérite de TransactionLegacyMixin)
17. nl_parser.py           (importe nl_intent + nl_intent_builder)
18. nl_orchestrator.py     (délègue à NLRepl)
19. spec_validator.py      (importe spec_validator_rules)
20. smart_patcher.py       (importe transformers lazily)
21. code_evaluator.py      (importe _CriteriaScorer)
22. orchestrator.py        (hérite de OrchestratorSpecMixin)
```

---

## Règles transversales (toutes tâches)

1. **Rétrocompatibilité obligatoire** — chaque import existant dans le projet doit continuer de fonctionner sans modification. Utiliser des re-exports au besoin.
2. **Tests d'abord** — lancer `python -m pytest` avant et après chaque tâche. Zéro régression tolérée.
3. **Encodage** — tous les nouveaux fichiers en `# -*- coding: utf-8-sig -*-`.
4. **Docstring de module** — chaque nouveau fichier doit décrire son rôle en 3-5 lignes.
5. **Taille cible** — chaque fichier résultant doit faire < 16 KB.
6. **Pas d'imports circulaires** — les nouveaux modules de types (`*_types.py`, `*_schema.py`) ne doivent importer aucun autre module core.

---

## Critères de done (DoD)

- [ ] `python -m pytest` — 100% des tests existants passent
- [ ] `python core/mcp_server.py` — serveur démarre sans erreur
- [ ] `python -c "from core.transaction_manager import TransactionManager, TxStatus, OpType"` — OK
- [ ] `python -c "from core.nl_parser import NLParser, NLIntent"` — OK
- [ ] `python -c "from core.spec_validator import SpecValidatorService, RULE_REGISTRY"` — OK
- [ ] Aucun fichier core > 16 KB après refacto
- [ ] `004-sprint-context.md` mis à jour avec REFACTO-01 terminé

---

## Métriques attendues après sprint

| Métrique | Avant | Après |
|----------|-------|-------|
| Fichiers > 20 KB | 5 | 0 |
| Fichiers > 16 KB | 8 | 0 |
| Fichiers core au total | 32 | ~48 |
| Taille moyenne fichier core | 12.3 KB | < 8 KB |
| Taille max fichier core | 35.9 KB | < 16 KB |
