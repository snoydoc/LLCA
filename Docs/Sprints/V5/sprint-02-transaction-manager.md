# 🔒 Sprint 02 — Transaction Manager ACID

> **Durée estimée** : 5 jours  
> **Statut** : ⚪ À FAIRE  
> **Priorité** : 🔴 Critique  
> **Dépend de** : Sprint 01 (venv, config, logger)  
> **Objectif** : Implémenter le cœur transactionnel avec WAL, snapshots MD5, rollback atomique.

---

## 🎯 Objectifs du Sprint

Le Transaction Manager est le composant anti-crash de LCCA. Il garantit que **toute modification de fichier est soit totalement appliquée, soit totalement annulée**. Aucun état intermédiaire corrumpu n'est possible.

### Principes ACID implémentés :
| Propriété | Implémentation |
|-----------|---------------|
| **Atomicité** | Rollback complet si une op échoue |
| **Cohérence** | Snapshot MD5 avant/après chaque fichier |
| **Isolation** | Une seule transaction active à la fois |
| **Durabilité** | WAL JSONL écrit avant toute exécution |

---

## 📋 Tâches

### TASK-02-01 — Dataclasses de base
**Priorité** : 🔴 Critique  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Définir toutes les dataclasses et enums utilisées par le Transaction Manager. Ces types sont partagés avec les autres modules.

**Fichier cible** : `core/transaction_manager.py` (section types)

**Types à implémenter** :

```python
class TxStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class OpType(Enum):
    WRITE_FILE = "write_file"
    EDIT_FILE = "edit_file"
    DELETE_FILE = "delete_file"
    PATCH_FILE = "patch_file"    # Modification AST (principal)
    CREATE_DIR = "create_dir"
    MOVE_FILE = "move_file"


@dataclass
class FileSnapshot:
    path: str
    content_hash: str   # MD5 du contenu
    content: Optional[str]
    exists: bool
    mtime: float = 0.0


@dataclass
class Operation:
    op_id: str          # UUID court: 8 chars
    type: OpType
    target_path: str
    before: FileSnapshot
    after: Optional[FileSnapshot]
    timestamp: str
    metadata: Dict[str, Any]
    rollback_data: Optional[str] = None  # Path vers backup physique


@dataclass
class Transaction:
    tx_id: str          # Format: tx_{hash12}
    dsl_input: str      # Commande originale
    project: str
    intent: str
    status: TxStatus
    created_at: str
    completed_at: Optional[str]
    operations: List[Operation]
    context_refs: List[str]
    checkpoint_path: Optional[str] = None
```

**Critères d'acceptation** :
- [ ] Tous les types définis sans erreur d'import
- [ ] `asdict(transaction)` fonctionne (nécessaire pour WAL JSON)
- [ ] `TxStatus.PENDING.value == "pending"` → True

---

### TASK-02-02 — Write-Ahead Log (WAL)
**Priorité** : 🔴 Critique  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Implémenter le système de journalisation WAL (Write-Ahead Log). Chaque événement est écrit dans `transactions/wal.jsonl` **avant** l'exécution de l'opération correspondante. Ce fichier permet la recovery en cas de crash.

**Fichier cible** : `core/transaction_manager.py` → méthode `_write_wal()`

**Format WAL (JSONL)** — une entrée JSON par ligne :
```jsonl
{"type":"BEGIN","tx_id":"tx_abc123","timestamp":"2026-04-16T10:00:00","data":{...}}
{"type":"OP_START","tx_id":"tx_abc123","op_id":"a1b2c3d4","target":"workspace/module.py"}
{"type":"OP_SUCCESS","tx_id":"tx_abc123","op_id":"a1b2c3d4","after_hash":"d4e5f6"}
{"type":"COMMIT","tx_id":"tx_abc123","timestamp":"2026-04-16T10:01:00","n_ops":2}
```

**Implémentation** :
```python
def _write_wal(self, entry: Dict) -> None:
    """
    Écrit une entrée dans le Write-Ahead Log.
    CRITIQUE: flush immédiat pour garantir durabilité même en cas de crash OS.
    """
    entry["_ts"] = datetime.now().isoformat()
    
    with open(self.wal_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, default=str) + '\n')
        f.flush()          # Flush buffer Python
        os.fsync(f.fileno())  # Flush vers disque physique (crash-safe)
```

**Critères d'acceptation** :
- [ ] `wal.jsonl` créé au premier BEGIN
- [ ] Chaque ligne est du JSON valide parseable
- [ ] Le fichier persiste après crash Python (test: `os.kill(os.getpid(), signal.SIGKILL)`)
- [ ] `fsync` appelé à chaque écriture

---

### TASK-02-03 — Snapshot de fichiers (MD5)
**Priorité** : 🔴 Critique  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Implémenter la méthode `_snapshot()` qui capture l'état complet d'un fichier avant modification.

**Fichier cible** : `core/transaction_manager.py` → méthode `_snapshot()`

**Logique** :
```python
def _snapshot(self, path: Path) -> FileSnapshot:
    """
    Crée un instantané complet d'un fichier (ou note son absence).
    Le hash MD5 permet de détecter toute modification ultérieure.
    """
    exists = path.exists()
    content: Optional[str] = None
    content_hash = ""
    mtime = 0.0
    
    if exists:
        mtime = path.stat().st_mtime
        try:
            content = path.read_text(encoding='utf-8')
            content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
        except (UnicodeDecodeError, PermissionError):
            # Fichier binaire ou protégé — hash sur mtime
            content_hash = hashlib.md5(str(mtime).encode()).hexdigest()
    
    return FileSnapshot(
        path=str(path),
        content_hash=content_hash,
        content=content,
        exists=exists,
        mtime=mtime
    )
```

**Critères d'acceptation** :
- [ ] Hash différent si contenu modifié même d'un octet
- [ ] Fichier inexistant → `exists=False`, hash vide
- [ ] Fichier binaire → pas de crash (graceful degradation)
- [ ] Test: modifier 1 char → hash change

---

### TASK-02-04 — `begin()` — Démarrage transaction
**Priorité** : 🔴 Critique  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Implémenter la méthode `begin()` qui initialise une transaction et l'écrit immédiatement dans le WAL.

**Comportement** :
1. Génère un `tx_id` unique format `tx_{uuid[:12]}`
2. Crée un objet `Transaction` avec status `PENDING`
3. Écrit `{"type":"BEGIN", ...}` dans le WAL
4. Sauvegarde dans `self.current_tx`

**Critères d'acceptation** :
- [ ] `tx_id` format `tx_abc123def456` (12 chars hex)
- [ ] WAL contient l'entrée BEGIN immédiatement
- [ ] Impossible d'appeler `begin()` si une transaction est déjà active → `RuntimeError`
- [ ] Transaction serializable en JSON sans erreur

---

### TASK-02-05 — `log_operation()` — Exécution atomique
**Priorité** : 🔴 Critique  
**Effort** : 1.5 jours  
**Statut** : ⚪ À FAIRE

**Description** :  
C'est **la méthode centrale** du système. Elle exécute une opération de manière atomique avec snapshot avant/après et possibilité de rollback.

**Séquence d'exécution** :
```
1. snapshot(before)              → état avant
2. backup physique sur disque    → fichier .bak
3. WAL OP_START                  → journalisation
4. execute_func()                → EXÉCUTION RÉELLE
5. snapshot(after)               → état après
6. validation (fichier existe)   → vérification
7. WAL OP_SUCCESS                → log succès
          ↓ si erreur à une étape :
          rollback_single_op()   → restauration depuis .bak
          WAL OP_FAIL            → log échec
          raise TransactionError
```

**Critères d'acceptation** :
- [ ] Si `execute_func()` lève une exception → fichier restauré automatiquement
- [ ] Si crash OS pendant execute → WAL permet de détecter l'op incomplète
- [ ] Backup `.bak` créé dans `transactions/{tx_id}/` avant chaque write
- [ ] Hash MD5 avant et après enregistrés dans l'opération
- [ ] Log console format : `✓ a1b2c3d4: patch_file workspace/module.py`

---

### TASK-02-06 — `commit()` et `rollback()`
**Priorité** : 🔴 Critique  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Finaliser une transaction (commit) ou annuler toutes ses opérations (rollback).

**`commit()` — séquence** :
1. Status → `COMMITTED`
2. WAL `{"type": "COMMIT", ...}`
3. `self.current_tx = None`

**`rollback()` — séquence** :
1. Pour chaque opération **en ordre inverse** (LIFO) :
   - Si fichier n'existait pas → le supprimer
   - Si fichier existait → restaurer depuis `.bak`
   - Restaurer le `mtime` original (évite les rebuild inutiles)
2. Status → `ROLLED_BACK`
3. WAL `{"type": "ROLLBACK", ...}`

**Critères d'acceptation** :
- [ ] Après `rollback()`, le fichier est **identique bit à bit** à son état avant la transaction
- [ ] Hash MD5 après rollback == hash MD5 au snapshot before
- [ ] `mtime` restauré
- [ ] `current_tx = None` après commit ou rollback
- [ ] Rollback partiel possible (jusqu'à un `op_id` spécifique)

---

### TASK-02-07 — Tests unitaires Transaction Manager
**Priorité** : 🟠 Haute  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `tests/test_transaction_manager.py`

**Tests à implémenter** :
```python
def test_begin_creates_wal_entry():
    """Vérifie que BEGIN est bien écrit dans le WAL."""

def test_snapshot_captures_hash():
    """Modification d'un fichier → hash différent."""

def test_commit_changes_status():
    """Après commit, status == COMMITTED."""

def test_rollback_restores_file():
    """Après rollback, contenu == contenu original."""

def test_rollback_on_exception():
    """Si execute_func() lève une exception → fichier restauré."""

def test_double_begin_raises():
    """Appeler begin() 2x sans commit → RuntimeError."""

def test_nested_backup_created():
    """Le .bak est créé dans transactions/{tx_id}/."""

def test_wal_is_valid_jsonl():
    """Chaque ligne du WAL est du JSON parseable."""
```

**Critères d'acceptation** :
- [ ] `pytest tests/test_transaction_manager.py` → 8/8 tests passent

---

## 📊 Récapitulatif Sprint 02

| Task | Description | Effort | Statut |
|------|------------|--------|--------|
| TASK-02-01 | Dataclasses & Enums | 0.5j | ⚪ |
| TASK-02-02 | Write-Ahead Log | 1j | ⚪ |
| TASK-02-03 | Snapshot MD5 | 0.5j | ⚪ |
| TASK-02-04 | `begin()` | 0.5j | ⚪ |
| TASK-02-05 | `log_operation()` | 1.5j | ⚪ |
| TASK-02-06 | `commit()` / `rollback()` | 1j | ⚪ |
| TASK-02-07 | Tests unitaires | 0.5j | ⚪ |
| **TOTAL** | | **5.5j** | |

---

## ✅ Définition of Done (Sprint 02)

- [ ] `pytest tests/test_transaction_manager.py` → 0 erreur
- [ ] Simulation crash milieu de transaction → rollback propre
- [ ] WAL lisible et complet après crash simulé
- [ ] Aucune écriture directe sans snapshot (`file.write()` interdit hors log_operation)
- [ ] `004-sprint-context.md` mis à jour

---

## ⚠️ Contraintes & Risques

| Risque | Probabilité | Mitigation |
|--------|------------|------------|
| `os.fsync()` lent sur SSD avec antivirus | Moyenne | Désactiver antivirus sur `transactions/` |
| Transaction orpheline si 2 processus tournent | Faible | Lock fichier ou PID check |
| WAL qui grossit indéfiniment | Moyenne | Archiver après 7 jours (Sprint 07) |

---

## 🔗 Navigation

⬅️ [Sprint 01 — Setup](sprint-01-setup-fondations.md)  
➡️ [Sprint 03 — AST Indexer & Smart Patcher](sprint-03-ast-indexer.md)
