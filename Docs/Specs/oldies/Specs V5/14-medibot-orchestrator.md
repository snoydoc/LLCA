# Spec 14 — MediBotOrchestrator
> **Module** : `core/orchestrator_medi.py` | **Sprint** : 08 | **Statut** : ✅ VALIDÉ

---

## 1. Rôle

`MediBotOrchestrator` est l'orchestrateur **spécialisé pour le projet MediBot**. C'est une couche de configuration au-dessus de `LCCAV5Fusion`, préconfigurée pour travailler sur `D:\MediBot` avec :

- Connexion automatique au MemPalace MediBot
- Transactions stockées dans `D:\MediBot\.lcca_transactions\`
- Recovery des transactions incomplètes au démarrage
- Enrichissement du contexte LLM avec les specs MediBot pertinentes

---

## 2. Initialisation

```python
class MediBotOrchestrator:
    def __init__(self, workspace: Optional[Path] = None) → None
    # Raises FileNotFoundError si workspace n'existe pas
```

**Séquence de boot :**
```
1. Vérifie l'existence du workspace (FileNotFoundError sinon)
2. ExistingMemPalaceAdapter() → connexion palace MediBot
3. Crée TransactionManager(tx_dir = workspace/.lcca_transactions)
4. Crée ASTIndexer, DependencyGraph, SmartPatcher, FileSelector, MultiFilePlanner
5. RecoveryService(tx_manager) → boot_check() + auto_recover_pending()
6. wake_up_medi() → charge identity + specs MediBot
7. index_repository() + dep_graph.build() → indexation workspace MediBot
```

---

## 3. API publique

```python
def execute(command: str, auto_rollback: bool = True) → bool
def dry_run(command: str) → dict
def status() → dict
```

### `execute(command)`

1. Parse la commande via `DSLParser`
2. `_enrich_with_medi_context(intent)` → inject les specs pertinentes dans les logs
3. Délègue à `LCCAV5Fusion.execute()` via `_get_fusion()` (lazy init)

### `status() → dict`

```python
{
    "workspace":         str,
    "n_files":           int,
    "n_symbols":         int,
    "palace_available":  bool,
    "palace_path":       str | None,
    "specs_loaded":      int,
    "lcca_collections":  List[str],
}
```

---

## 4. Enrichissement du contexte

### `_enrich_with_medi_context(intent) → str`

Appelle `palace.find_relevant_specs(keywords, max_specs=2)` avec les keywords extraits de l'intent (target, sub_target, details).

Retourne une chaîne `"[spec_name]: extrait..."` injectée dans les logs pour guider le LLM.

---

## 5. Lazy init de LCCAV5Fusion

```python
def _get_fusion(self) -> LCCAV5Fusion:
    if not hasattr(self, "_fusion") or self._fusion is None:
        self._fusion = LCCAV5Fusion(
            workspace  = self.workspace,
            tx_manager = self.tx_manager,
            indexer    = self.indexer,
            dep_graph  = self.dep_graph,
            patcher    = self.patcher,
        )
    return self._fusion
```

**Partage des composants** : le même `tx_manager`, `indexer` et `dep_graph` sont partagés entre `MediBotOrchestrator` et `LCCAV5Fusion` pour éviter la double indexation.

---

## 6. Différences avec LCCAV5Fusion standard

| Aspect | LCCAV5Fusion | MediBotOrchestrator |
|--------|-------------|---------------------|
| Workspace | `config.WORKSPACE_DIR` | `D:\MediBot` |
| TX directory | `D:\LLMCodeAgent\transactions` | `D:\MediBot\.lcca_transactions` |
| MemPalace | Non connecté | Connecté (lecture) + collections `lcca_*` |
| Recovery au boot | Non | Oui (`boot_check` + `auto_recover`) |
| Contexte specs | Non | Oui (`find_relevant_specs`) |
| Indexation au boot | Oui (workspace/ vide) | Oui (code MediBot réel) |

---

## 7. Contraintes AI-Ready

- `FileNotFoundError` si `D:\MediBot` absent → message clair, pas de crash silencieux
- Palace indisponible → mode dégradé (warning + continue)
- Recovery partielle → warning + continue (pas de crash)
- `_get_fusion()` lazy → pas de double initialisation LLMGenerator
