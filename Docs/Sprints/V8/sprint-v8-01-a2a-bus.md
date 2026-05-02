# Sprint V8-01 — A2A Bus SQLite3 + TaskContract
<!-- AI-READY | Sprint V8 | Phase alpha | 2026-04-20 -->

## Objectif

Poser la fondation de communication inter-agent : un bus de messages local, atomique, isolé.  
Tout le reste de la V8 repose sur ce module — il doit être parfait.

> **Principe** : pas de fichiers JSON partagés, pas de HTTP. SQLite3 avec `BEGIN IMMEDIATE` = atomicité garantie sans dépendance externe.

---

## Fichiers à créer / modifier

| # | Fichier | Opération |
|---|---------|-----------|
| 1 | `core/agents/__init__.py` | CREATE — package agents |
| 2 | `core/agents/a2a_bus.py` | CREATE — A2ALocalBus + A2AMessage |
| 3 | `core/receipt_store.py` | CREATE — HMAC + sign/verify/rotate |
| 4 | `config.py` | PATCH — ajouter `A2A_DB_PATH`, `SECRET_DIR`, `A2A_RECEIPTS_DIR` |
| 5 | `core/__init__.py` | PATCH — version `8.0.0-alpha`, exporter `A2ALocalBus`, `A2AMessage` |
| 6 | `tests/test_a2a_bus.py` | CREATE — 12 tests (voir checklist) |
| 7 | `tests/test_receipt_store.py` | CREATE — 6 tests |
| 8 | `.gitignore` | PATCH — ajouter `.secret/` |

---

## Spécification : `core/agents/a2a_bus.py`

```python
# core/agents/a2a_bus.py
"""
Bus A2A local via SQLite3.
Garantit : atomicité lecture/écriture (BEGIN IMMEDIATE),
consommation unique (DELETE après lecture), pas de fichier partiel.
"""
import sqlite3
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone
from config import A2A_DB_PATH

A2A_AGENTS = frozenset({"architect", "coder", "reviewer", "tester", "observer", "nl_adapter"})

@dataclass
class A2AMessage:
    id: Optional[int]
    to_agent: str
    from_agent: str
    task_id: str
    payload: dict
    receipt_hash: Optional[str]
    created_at: str
    consumed_at: Optional[str] = None

    def __post_init__(self):
        assert self.to_agent in A2A_AGENTS, f"Agent inconnu: {self.to_agent}"
        assert isinstance(self.payload, dict)

@dataclass
class TaskContract:
    """Contrat structuré entre agents."""
    task_id: str
    intent: str
    domain: str
    source_agent: str
    target_agent: str
    context: dict = field(default_factory=dict)   # Résultats précédents
    constraints: list = field(default_factory=list)  # ["max_files=3", ...]
    spec_id: Optional[str] = None                 # SpecEntry associée
    parent_task_id: Optional[str] = None          # Pour sous-tâches

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "intent": self.intent,
            "domain": self.domain,
            "source_agent": self.source_agent,
            "target_agent": self.target_agent,
            "context": self.context,
            "constraints": self.constraints,
            "spec_id": self.spec_id,
            "parent_task_id": self.parent_task_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TaskContract":
        return cls(
            task_id=d["task_id"],
            intent=d["intent"],
            domain=d.get("domain", "global"),
            source_agent=d["source_agent"],
            target_agent=d["target_agent"],
            context=d.get("context", {}),
            constraints=d.get("constraints", []),
            spec_id=d.get("spec_id"),
            parent_task_id=d.get("parent_task_id"),
        )

class A2ALocalBus:
    """
    Bus A2A thread-safe via SQLite3.
    V8-Règle-21 : Toute communication inter-agent passe par ce bus.
    """
    _lock = threading.Lock()

    def __init__(self, db_path=None):
        self.db_path = db_path or A2A_DB_PATH
        self._init_db()

    def _init_db(self):
        """Initialise le schéma si nécessaire. Idempotent."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS a2a_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    to_agent TEXT NOT NULL,
                    from_agent TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    receipt_hash TEXT,
                    created_at TEXT NOT NULL,
                    consumed_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_to_agent_consumed
                ON a2a_messages(to_agent, consumed_at)
            """)
            conn.commit()

    def send(self, to: str, from_: str, task_id: str, payload: dict,
             receipt_hash: Optional[str] = None) -> int:
        """
        Envoie un message. Atomique. Retourne l'id du message.
        """
        created_at = datetime.now(timezone.utc).isoformat()
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO a2a_messages
                   (to_agent, from_agent, task_id, payload, receipt_hash, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (to, from_, task_id,
                 json.dumps(payload, ensure_ascii=False),
                 receipt_hash, created_at)
            )
            conn.commit()
            return cursor.lastrowid

    def receive(self, agent: str, timeout_sec: int = 0) -> Optional[A2AMessage]:
        """
        Consommation unique : DELETE immédiat après lecture.
        Si timeout_sec > 0, polling jusqu'à message ou timeout.
        Retourne None si pas de message.
        """
        start = time.monotonic()
        while True:
            with self._lock, sqlite3.connect(self.db_path) as conn:
                conn.isolation_level = "IMMEDIATE"
                cursor = conn.execute(
                    """SELECT id, from_agent, task_id, payload, receipt_hash, created_at
                       FROM a2a_messages
                       WHERE to_agent = ? AND consumed_at IS NULL
                       ORDER BY id ASC LIMIT 1""",
                    (agent,)
                )
                row = cursor.fetchone()
                if row:
                    msg = A2AMessage(
                        id=row[0], to_agent=agent, from_agent=row[1],
                        task_id=row[2], payload=json.loads(row[3]),
                        receipt_hash=row[4], created_at=row[5]
                    )
                    conn.execute("DELETE FROM a2a_messages WHERE id = ?", (msg.id,))
                    conn.commit()
                    return msg

            if timeout_sec > 0 and (time.monotonic() - start) < timeout_sec:
                time.sleep(0.05)
                continue
            return None

    def peek(self, agent: str) -> int:
        """Observabilité : messages en attente pour un agent."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM a2a_messages WHERE to_agent = ? AND consumed_at IS NULL",
                (agent,)
            )
            return cursor.fetchone()[0]

    def purge(self):
        """Vide toutes les messages. Usage tests uniquement."""
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM a2a_messages")
            conn.commit()

    def make_task_id(self, intent: str) -> str:
        """Génère un task_id stable depuis un intent. Format : a2a_{hash12}."""
        import hashlib
        return "a2a_" + hashlib.md5(intent.encode()).hexdigest()[:12]
```

---

## Spécification : `core/receipt_store.py`

```python
# core/receipt_store.py
"""
Audit trail A2A avec HMAC local.
Clé stockée dans .secret/a2a_key (hors git, chmod 600).
V8-Règle-17 : Aucun skill stocké sans ExecutionReceipt valide.
"""
import hmac
import hashlib
import json
import secrets
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from config import BASE_DIR

SECRET_DIR = BASE_DIR / ".secret"
KEY_PATH = SECRET_DIR / "a2a_key"
RECEIPTS_DIR = BASE_DIR / "memory" / "receipts"

@dataclass
class ExecutionReceipt:
    task_id: str
    agent: str
    input_hash: str
    output_hash: str
    sandbox_passed: bool
    tests_passed: int
    tests_failed: int
    tx_id: Optional[str]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    signature: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ExecutionReceipt":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})

def _ensure_key() -> bytes:
    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    if not KEY_PATH.exists():
        key = secrets.token_hex(32).encode()
        KEY_PATH.write_bytes(key)
        import os, sys
        if sys.platform != "win32":
            os.chmod(KEY_PATH, 0o600)
    return KEY_PATH.read_bytes()

def sign_receipt(task_id: str, output_hash: str) -> str:
    key = _ensure_key()
    payload = f"{task_id}:{output_hash}".encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

def verify_receipt(receipt: ExecutionReceipt) -> bool:
    expected = sign_receipt(receipt.task_id, receipt.output_hash)
    return hmac.compare_digest(expected, receipt.signature)

def store_receipt(receipt: ExecutionReceipt):
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RECEIPTS_DIR / f"{receipt.task_id}.json"
    path.write_text(json.dumps(receipt.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

def load_receipt(task_id: str) -> Optional[ExecutionReceipt]:
    path = RECEIPTS_DIR / f"{task_id}.json"
    if not path.exists():
        return None
    return ExecutionReceipt.from_dict(json.loads(path.read_text(encoding="utf-8")))

def rotate_key() -> int:
    """Régénère la clé HMAC. Invalide tous les receipts existants."""
    count = 0
    if RECEIPTS_DIR.exists():
        for f in RECEIPTS_DIR.glob("*.json"):
            f.rename(f.with_suffix(".invalid"))
            count += 1
    KEY_PATH.unlink(missing_ok=True)
    _ensure_key()
    return count
```

---

## Ajouts dans `config.py`

```python
# Ajouts V8
A2A_DB_PATH = TRANSACTIONS_DIR / "a2a_bus.sqlite"
A2A_RECEIPTS_DIR = BASE_DIR / "memory" / "receipts"
SECRET_DIR = BASE_DIR / ".secret"
```

---

## Checklist des tests (`tests/test_a2a_bus.py`)

### TestA2ABusInit
- [ ] `test_db_created_on_init` — le fichier SQLite est créé
- [ ] `test_init_idempotent` — double init sans erreur

### TestA2ABusSend
- [ ] `test_send_returns_id` — retourne un int positif
- [ ] `test_send_stores_message` — peek() > 0 après send

### TestA2ABusReceive
- [ ] `test_receive_returns_message` — payload intact après roundtrip
- [ ] `test_receive_atomic_consumption` — deux threads consomment, un seul reçoit
- [ ] `test_receive_no_message_returns_none` — None si inbox vide
- [ ] `test_receive_timeout_returns_none` — timeout_sec=0 → retour immédiat

### TestA2ABusIsolation
- [ ] `test_agent_cannot_consume_other_inbox` — agent "coder" ne reçoit pas les messages de "architect"
- [ ] `test_fifo_order` — premier envoyé, premier reçu

### TestTaskContract
- [ ] `test_task_contract_roundtrip` — to_dict + from_dict conserve tous les champs
- [ ] `test_make_task_id_stable` — même intent = même task_id

### TestReceiptStore (`tests/test_receipt_store.py`)
- [ ] `test_sign_and_verify` — round-trip HMAC valide
- [ ] `test_tampered_receipt_fails_verify` — output_hash modifié = False
- [ ] `test_store_and_load` — persiste et relit correctement
- [ ] `test_rotate_key_invalidates_old` — fichiers .invalid créés
- [ ] `test_missing_receipt_returns_none` — load_receipt inconnu = None
- [ ] `test_key_created_on_first_sign` — .secret/a2a_key créé automatiquement

---

## Dépendances
- `sqlite3` — stdlib, zéro dépendance externe ✅
- `hmac`, `hashlib`, `secrets` — stdlib ✅

## Règles V8 applicables
- V8-Règle-21 : isoler par bus (testé par `test_agent_cannot_consume_other_inbox`)
- V8-Règle-17 : Receipt avant skill (ce sprint pose la fondation, utilisé en Sprint V8-04/V8-05)
- Zéro import de `core/` dans `core/agents/a2a_bus.py` (sauf config)

## Anti-patterns interdits
- ❌ `Path.write_text()` dans le bus (risque partiel) — uniquement SQLite
- ❌ Message JSON dans `memory/a2a/inbox/` (le bus fichier est remplacé par SQLite)
- ❌ Import circulaire depuis les agents dans a2a_bus.py
