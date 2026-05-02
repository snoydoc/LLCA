# 🗺️ Sprint 04 — Planner, DSL Parser & Orchestrateur

> **Durée estimée** : 5 jours  
> **Statut** : ⚪ À FAIRE  
> **Priorité** : 🟠 Haute  
> **Dépend de** : Sprint 02 (TX Manager), Sprint 03 (AST Indexer, SmartPatcher)  
> **Objectif** : Parser les commandes DSL, planifier les opérations multi-fichiers, orchestrer l'exécution complète.

---

## 🎯 Objectifs du Sprint

Ce sprint connecte tous les composants entre eux dans un flux end-to-end :

```
Commande utilisateur
     ↓
[DSL Parser]       →  Intent structuré
     ↓
[File Selector]    →  Liste fichiers cibles
     ↓
[Multi Planner]    →  Plan d'opérations ordonné
     ↓
[Orchestrateur]    →  Exécution via TX Manager + SmartPatcher
     ↓
Résultat (commit ou rollback)
```

---

## 📋 Tâches

### TASK-04-01 — `DSLParser` — Parser de commandes
**Priorité** : 🔴 Critique  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `core/dsl_parser.py`

**Description** :  
Implémenter le parser du langage de commande LCCA. Le format est :  
`"Projet - Cible - Sous-cible (optionnel) - Action Details"`

**Dataclass Intent** :
```python
@dataclass
class Intent:
    project: str           # "DashboardV1"
    target: str            # "Page RDV"
    sub_target: str        # "Modal En Consultation" (optionnel)
    action: str            # "Ajoute" | "Modifie" | "Supprime" | "Crée"
    details: str           # "validate_email()"
    raw: str               # Commande originale
    confidence: float = 1.0  # Score parsing (< 0.5 → demande confirmation)
```

**Règles de parsing** :

| Pattern | Exemple | Résultat |
|---------|---------|---------|
| `Projet - Cible - Action` | `DashV1 - Auth - Ajoute login()` | project=DashV1, target=Auth, action=Ajoute |
| `Projet - Cible - Sous-cible - Action` | `DashV1 - RDV - Modal - Crée export()` | sub_target=Modal |
| Commande naturelle | `Ajoute une validation email dans auth.py` | confidence < 0.8 |

**Implémentation** :
```python
import re
from dataclasses import dataclass
from typing import Optional

ACTIONS = {"ajoute", "modifie", "supprime", "crée", "cree", "refactor", "corrige"}

@dataclass
class Intent:
    project: str
    target: str
    sub_target: Optional[str]
    action: str
    details: str
    raw: str
    confidence: float = 1.0


class DSLParser:
    def parse(self, command: str) -> Intent:
        command = command.strip()
        parts = [p.strip() for p in command.split('-')]
        
        if len(parts) >= 3:
            return self._parse_structured(parts, command)
        else:
            return self._parse_natural(command)
    
    def _parse_structured(self, parts: list, raw: str) -> Intent:
        project = parts[0]
        target = parts[1]
        
        # Détermine si la 3e partie est une action ou une sous-cible
        if len(parts) == 3:
            action, details = self._split_action(parts[2])
            return Intent(project, target, None, action, details, raw)
        else:
            sub_target = parts[2]
            action, details = self._split_action(' - '.join(parts[3:]))
            return Intent(project, target, sub_target, action, details, raw, confidence=0.95)
    
    def _split_action(self, text: str) -> tuple[str, str]:
        """Sépare 'Ajoute validate_email()' en ('Ajoute', 'validate_email()')."""
        words = text.split(' ', 1)
        action = words[0].lower().rstrip('e') + 'e'   # normalise
        details = words[1] if len(words) > 1 else ""
        return action, details
    
    def _parse_natural(self, command: str) -> Intent:
        """Parsing langage naturel avec confidence réduite."""
        action = next((a for a in ACTIONS if a in command.lower()), "modifie")
        return Intent(
            project="inconnu",
            target="inconnu", 
            sub_target=None,
            action=action,
            details=command,
            raw=command,
            confidence=0.4
        )
```

**Critères d'acceptation** :
- [ ] `"DashV1 - Page RDV - Ajoute validate_email()"` → project=DashV1, action=Ajoute
- [ ] `"DashV1 - RDV - Modal - Modifie send_sms()"` → sub_target=Modal
- [ ] Commande invalide → confidence < 0.5 (warning, pas exception)
- [ ] Tests: 6 cas de parsing → tous corrects

---

### TASK-04-02 — `FileSelector` — Sélection intelligente de fichiers
**Priorité** : 🟠 Haute  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `core/file_selector.py`

**Description** :  
Sélectionner les fichiers à modifier en combinant :
1. Recherche par symboles dans l'index AST
2. Recherche par nom de fichier (fuzzy matching)
3. Règle : max 3 fichiers par transaction (contrainte spec)

**Interface** :
```python
class FileSelector:
    def __init__(self, indexer: ASTIndexer, dep_graph: DependencyGraph):
        self.indexer = indexer
        self.dep_graph = dep_graph
    
    def select(self, intent: Intent) -> List[str]:
        """
        Retourne max MAX_FILES_PER_TX fichiers pertinents.
        """
        candidates = set()
        
        # Stratégie 1: Symbole exact dans l'index
        for term in [intent.target, intent.sub_target, intent.details]:
            if term:
                symbols = self.indexer.find_symbol_definition(term)
                for sym in symbols:
                    rel = Path(sym.file).relative_to(self.indexer.workspace)
                    candidates.add(str(rel))
        
        # Stratégie 2: Nom de fichier contient le terme
        for path in self.indexer.files:
            path_lower = path.lower()
            if any(t and t.lower() in path_lower for t in [intent.target, intent.sub_target]):
                candidates.add(path)
        
        # Stratégie 3: Contenu contient tous les termes
        terms = [t for t in [intent.target, intent.sub_target, intent.details] if t]
        if terms:
            content_matches = self.indexer.search_by_content(terms[:2])
            candidates.update(content_matches[:3])
        
        # Si action = créer et aucun fichier trouvé → suggère nouveau fichier
        if not candidates and intent.action in ["crée", "cree", "ajoute"]:
            suggested = f"src/{intent.target.lower().replace(' ', '_')}.py"
            return [suggested]
        
        return list(candidates)[:MAX_FILES_PER_TX]
```

**Critères d'acceptation** :
- [ ] Trouve un fichier si son nom contient le target
- [ ] Trouve un fichier si une fonction dedans correspond au symbole cherché
- [ ] Max 3 fichiers retournés (contrainte hard)
- [ ] Action "crée" + aucun match → retourne un chemin suggéré

---

### TASK-04-03 — `MultiFilePlanner` — Ordonnancement des opérations
**Priorité** : 🟠 Haute  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `core/planner.py`

**Description** :  
À partir de la liste de fichiers cibles et de l'intent, créer un plan d'opérations ordonné et valide.

**Dataclass PlannedOperation** :
```python
@dataclass
class PlannedOperation:
    file: str
    action: str              # 'create' | 'modify' | 'delete'
    target_symbol: Optional[str]  # Nom fonction/classe à modifier
    description: str
    dependencies: List[str]  # Autres fichiers dont dépend cette op
    priority: OpPriority = OpPriority.NORMAL
    patch_type: str = "add_function"  # 'add_function' | 'modify_function' | 'add_import'
```

**Algorithme de tri** :  
Tri topologique simple : les fichiers sans dépendances d'abord, les fichiers "core" en haute priorité.

**Validation du plan** :
```python
def validate_plan_consistency(self, ops: List[PlannedOperation]) -> Tuple[bool, List[str]]:
    """
    Retourne (valide: bool, erreurs: List[str]).
    Vérifie:
    - Pas de symbole modifié 2 fois
    - Pas de fichier supprimé et modifié dans la même TX
    - Max MAX_FILES_PER_TX fichiers distincts
    """
```

**Critères d'acceptation** :
- [ ] Plan avec dépendances → fichiers sans dépendances exécutés en premier
- [ ] Même symbole modifié 2x → `validate()` retourne False + message d'erreur
- [ ] Plus de 3 fichiers → erreur de validation

---

### TASK-04-04 — `Orchestrator` — Coordination end-to-end
**Priorité** : 🔴 Critique  
**Effort** : 1.5 jours  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `core/orchestrator.py`

**Description** :  
Implémenter la classe `LCCAV5Fusion` qui orchestre l'exécution d'une commande complète, du parsing jusqu'au commit.

**Flux complet** :
```python
def execute(self, command: str, auto_rollback: bool = True) -> bool:
    try:
        # 1. Parse
        intent = DSLParser().parse(command)
        if intent.confidence < 0.5:
            log.warning(f"Confidence faible ({intent.confidence:.0%}): {command}")
            # Demander confirmation (pour l'instant: log + continuer)
        
        # 2. Sélection fichiers
        target_files = self.selector.select(intent)
        if not target_files:
            log.error("Aucun fichier cible identifié")
            return False
        
        # 3. Plan
        plan = self.planner.create_plan(intent.details, target_files)
        valid, errors = self.planner.validate_plan_consistency(plan)
        if not valid:
            log.error(f"Plan invalide: {errors}")
            return False
        
        # 4. Transaction BEGIN
        tx_id = self.tx_manager.begin(command, intent.project, 
                                      f"{intent.action} {intent.details}", [])
        
        # 5. Exécution du plan
        for op in plan:
            generated = self._generate_code_for_op(op, intent)
            
            def do_it(op=op, code=generated):
                if op.action == "create":
                    full = self.workspace / op.file
                    full.parent.mkdir(parents=True, exist_ok=True)
                    full.write_text(code, encoding='utf-8-sig')
                    return code
                else:
                    new_code = self.patcher.apply_patch(op.file, op.patch_type, 
                                                        code=code, name=op.target_symbol)
                    (self.workspace / op.file).write_text(new_code, encoding='utf-8-sig')
                    return new_code
            
            self.tx_manager.log_operation(
                OpType.PATCH_FILE if op.action == "modify" else OpType.WRITE_FILE,
                op.file, do_it,
                metadata={"intent": intent.details, "symbol": op.target_symbol}
            )
        
        # 6. Validation finale
        if self._validate_changes():
            self.tx_manager.commit()
            self.indexer.index_repository()  # Re-indexation
            self._update_sprint_log(intent, plan)
            return True
        
        raise Exception("Validation post-patch échouée")
    
    except Exception as e:
        log.error(f"Erreur exécution: {e}")
        if auto_rollback and self.tx_manager.current_tx:
            self.tx_manager.rollback()
        return False
```

**`_update_sprint_log()`** — Mise à jour automatique du sprint en cours :
```python
def _update_sprint_log(self, intent: Intent, plan: List[PlannedOperation]):
    """Ajoute une entrée dans Docs/Sprints/current-sprint.md."""
    log_path = Path("D:/LLMCodeAgent/Docs/Sprints/current-sprint.md")
    entry = (
        f"\n### {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"- **Commande**: `{intent.raw}`\n"
        f"- **Fichiers modifiés**: {', '.join(op.file for op in plan)}\n"
        f"- **TX**: `{self.tx_manager.last_committed_tx}`\n"
    )
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(entry)
```

**Critères d'acceptation** :
- [ ] `execute("DashV1 - Auth - Ajoute login()")` → ne crash pas
- [ ] Erreur en cours → rollback automatique → fichiers restaurés
- [ ] `current-sprint.md` mis à jour après chaque exécution réussie
- [ ] Index AST re-créé après commit

---

### TASK-04-05 — `_validate_changes()` — Validation post-patch
**Priorité** : 🟠 Haute  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Valider que tous les fichiers modifiés sont syntaxiquement valides après patch.

```python
def _validate_changes(self) -> bool:
    """Vérifie la syntaxe de tous les .py modifiés dans la TX courante."""
    if not self.tx_manager.current_tx:
        return True
    
    for op in self.tx_manager.current_tx.operations:
        file_path = self.workspace / op.target_path
        if file_path.suffix != '.py' or not file_path.exists():
            continue
        
        source = file_path.read_text(encoding='utf-8')
        try:
            compile(source, op.target_path, 'exec')
        except SyntaxError as e:
            log.error(f"Syntaxe invalide après patch: {op.target_path}: {e}")
            return False
    
    return True
```

**Critères d'acceptation** :
- [ ] Patch qui génère du code invalide → `_validate_changes()` retourne False → rollback déclenché
- [ ] Tous les fichiers .py de la TX vérifiés

---

## 📊 Récapitulatif Sprint 04

| Task | Description | Effort | Statut |
|------|------------|--------|--------|
| TASK-04-01 | DSL Parser | 1j | ⚪ |
| TASK-04-02 | File Selector | 1j | ⚪ |
| TASK-04-03 | Multi File Planner | 1j | ⚪ |
| TASK-04-04 | Orchestrateur end-to-end | 1.5j | ⚪ |
| TASK-04-05 | Validation post-patch | 0.5j | ⚪ |
| **TOTAL** | | **5j** | |

---

## ✅ Définition of Done (Sprint 04)

- [ ] `python main.py "DashV1 - Auth - Ajoute login()"` → exécution sans crash
- [ ] Erreur dans une opération → rollback automatique déclenché
- [ ] `current-sprint.md` mis à jour après exécution
- [ ] Tests d'intégration `tests/test_orchestrator.py` → 3+ scénarios passent

---

## 🔗 Navigation

⬅️ [Sprint 03 — AST Indexer](sprint-03-ast-indexer.md)  
➡️ [Sprint 05 — MemPalace Integration](sprint-05-mempalace-integration.md)
