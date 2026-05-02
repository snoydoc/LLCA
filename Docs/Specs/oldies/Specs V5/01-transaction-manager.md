# Spec 01 — TransactionManager
<!-- AI-READY | core/transaction_manager.py | Sprint 02+07 | Tests: 9/9 PASSED -->

## Rôle

Gestion ACID des modifications de fichiers Python.
Garantit que toute opération est soit entièrement commitée, soit entièrement annulée.

---

## Localisation

```
D:\LLMCodeAgent\core\transaction_manager.py
```

---

## Dataclasses & Enums publics

### `TxStatus` (Enum)
| Valeur | Description |
|--------|-------------|
| `PENDING` | TX créée mais pas démarrée |
| `RUNNING` | TX en cours d'exécution |
| `COMMITTED` | TX finalisée avec succès |
| `ROLLED_BACK` | TX annulée |
| `FAILED` | TX échouée sans rollback |

### `OpType` (Enum)
| Valeur | Usage |
|--------|-------|
| `WRITE_FILE` | Écriture complète d'un fichier |
| `EDIT_FILE` | Modification partielle |
| `DELETE_FILE` | Suppression |
| `PATCH_FILE` | Modification AST (libcst) — **principal** |
| `CREATE_DIR` | Création répertoire |
| `MOVE_FILE` | Déplacement |

### `FileSnapshot`
```python
@dataclass
class FileSnapshot:
    path: str
    content_hash: str   # MD5 du contenu
    content: Optional[str]
    exists: bool
    mtime: float        # timestamp modtime
```

### `Operation`
```python
@dataclass
class Operation:
    op_id: str              # 8 chars hex UUID
    type: OpType
    target_path: str
    before: FileSnapshot
    after: Optional[FileSnapshot]
    timestamp: str          # ISO 8601 UTC
    metadata: Dict[str, Any]
    rollback_data: Optional[str]  # path vers .bak
```

### `Transaction`
```python
@dataclass
class Transaction:
    tx_id: str              # "tx_{uuid[:12]}"
    dsl_input: str
    project: str
    intent: str
    status: TxStatus
    created_at: str         # ISO 8601 UTC
    completed_at: Optional[str]
    operations: List[Operation]
    context_refs: List[str]
    checkpoint_path: Optional[str]
```

### `TransactionError` (Exception)
Levée quand une opération ne peut pas continuer (ex: `log_operation` sans TX active).

---

## `TransactionManager` — API publique

### `__init__(tx_dir=None, wal_path=None)`

| Param | Type | Défaut | Description |
|-------|------|--------|-------------|
| `tx_dir` | `Path` | `D:\LLMCodeAgent\transactions\` | Répertoire des backups |
| `wal_path` | `Path` | `tx_dir / "wal.jsonl"` | Fichier WAL |

> **CRITIQUE** : `wal_path` est toujours dérivé de `tx_dir`, jamais depuis une constante globale hardcodée.

### `begin(dsl_input="", project="lcca", intent="") → str`

Démarre une nouvelle transaction. Retourne le `tx_id`.

**Séquence interne :**
1. Vérifie qu'aucune TX n'est déjà active (sinon `RuntimeError`)
2. Génère `tx_id = "tx_{uuid[:12]}"`
3. Écrit `{"type": "BEGIN", ...}` dans le WAL (avec `fsync`)
4. Crée l'objet `Transaction` et le stocke dans `self.current_tx`

### `log_operation(target_path, op_type, execute_func, metadata=None) → Operation`

Exécute une opération de manière atomique.

**Séquence ACID :**
1. `_snapshot(target_path)` → hash MD5 avant
2. `_backup(tx_id, path)` → copie `.bak` dans `transactions/{tx_id}/`
3. WAL `OP_START`
4. `execute_func()` ← exécution réelle
5. `_snapshot(target_path)` → hash MD5 après
6. WAL `OP_SUCCESS`

En cas d'erreur : restaure depuis `.bak` + WAL `OP_FAIL` + lève `TransactionError`.

**Exemple d'usage :**
```python
def _do_patch():
    full_path.write_text(new_code, encoding="utf-8-sig")

tx_manager.log_operation(
    full_path,
    OpType.PATCH_FILE,
    _do_patch,
    metadata={"intent": "validate_email", "patch_type": "add_function"}
)
```

### `commit() → str`

Finalise la TX courante. Écrit `COMMIT` dans le WAL. Retourne le `tx_id`.

### `rollback(reason="") → str`

Annule toutes les opérations en ordre LIFO (restauration depuis `.bak`).
Écrit `ROLLBACK` dans le WAL. Retourne le `tx_id`.

### `archive_old_wal_entries(days_to_keep=7) → int`

Déplace les entrées WAL de plus de N jours dans un fichier archive.
Retourne le nombre d'entrées archivées.

### `recover_incomplete() → List[str]`

Lit le WAL, rollback toute TX avec `BEGIN` sans `COMMIT`.
API legacy (Sprint 01) — préférer `RecoveryService.boot_check()`.

---

## Format WAL (wal.jsonl)

Chaque ligne = un enregistrement JSON + timestamp `_ts` :

```jsonl
{"type":"BEGIN","tx_id":"tx_a3f2b8d9e1c4","input":"DashV1 - Auth - Ajoute login()","intent":"ajoute login()","_ts":"2026-04-17T10:30:00Z"}
{"type":"OP_START","tx_id":"tx_a3f2b8d9e1c4","op_id":"a1b2c3d4","op_type":"patch_file","target":"D:/LLMCodeAgent/workspace/auth.py","hash_before":"abc123","_ts":"..."}
{"type":"OP_SUCCESS","tx_id":"tx_a3f2b8d9e1c4","op_id":"a1b2c3d4","hash_after":"def456","_ts":"..."}
{"type":"COMMIT","tx_id":"tx_a3f2b8d9e1c4","n_ops":1,"_ts":"..."}
```

---

## Contraintes & invariants

- **Une seule TX active à la fois** (`self.current_tx` est `None` ou `Transaction`)
- **fsync systématique** : `f.flush() + os.fsync(f.fileno())` après chaque écriture WAL
- **Backups dans `transactions/{tx_id}/`** avec nom `{filename}_{uuid6}.bak`
- **Rollback LIFO** : opérations annulées dans l'ordre inverse
- **Encodage** : toujours `utf-8` pour le WAL, `utf-8-sig` pour les fichiers Python

---

## API Legacy (rétrocompatibilité Sprint 01)

| Méthode | Description |
|---------|-------------|
| `new_tx_id()` | Génère un `tx_id` sans créer de TX |
| `md5(path)` | Calcule le MD5 d'un fichier |
| `snapshot(tx_id, path)` | Copie dans `transactions/{tx_id}/` |
| `begin_legacy(tx_id, file_path, hash_before)` | WAL BEGIN (ancienne API) |
| `commit_legacy(tx_id, file_path, hash_after)` | WAL COMMIT (ancienne API) |
| `rollback_legacy(tx_id, file_path, reason)` | WAL ROLLBACK (ancienne API) |
| `restore(tx_id, path)` | Restaure depuis snapshot |

---

## Tests

Fichier : `tests/test_transaction_manager.py`
**9/9 PASSED** — Sprint 02 + corrections Sprint 07.

Cas couverts :
- `begin()` + `commit()` — flux normal
- `begin()` + `rollback()` — restauration fichier
- `log_operation()` — snapshot avant/après + WAL complet
- `log_operation()` — crash dans `execute_func` → restauration auto
- Transaction déjà active → `RuntimeError`
- `archive_old_wal_entries()` — filtrage par date
- `recover_incomplete()` — détection BEGIN sans COMMIT
