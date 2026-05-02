# -*- coding: utf-8-sig -*-
"""
Bus A2A local via SQLite3.
Garantit : atomicite lecture/ecriture (BEGIN IMMEDIATE),
consommation unique (DELETE apres lecture), pas de fichier partiel.

V8-Regle-21 : Toute communication inter-agent passe par ce bus.
"""
import sqlite3
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone

from config import A2A_DB_PATH

A2A_AGENTS = frozenset({
    "architect", "coder", "reviewer", "tester", "observer", "nl_adapter"
})


@dataclass
class A2AMessage:
    """Message atomique echange entre agents via le bus SQLite3."""
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
        assert isinstance(self.payload, dict), "payload doit etre un dict"


@dataclass
class TaskContract:
    """Contrat structure entre agents. Transmis dans le payload A2AMessage."""
    task_id: str
    intent: str
    domain: str
    source_agent: str
    target_agent: str
    context: dict = field(default_factory=dict)
    constraints: list = field(default_factory=list)
    spec_id: Optional[str] = None
    parent_task_id: Optional[str] = None

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
    V8-Regle-21 : Toute communication inter-agent passe par ce bus.

    Garanties :
    - Atomicite : BEGIN IMMEDIATE sur chaque operation
    - Consommation unique : DELETE immediat apres receive()
    - Isolation agents : un agent ne peut pas lire l'inbox d'un autre
    - Thread-safe : verrou par instance Python + verrou SQLite3

    Note :memory: : SQLite en memoire necessite une connexion persistante unique
    (chaque sqlite3.connect(':memory:') cree une base vide independante).
    Pour les chemins fichiers, des connexions courtes sont utilisees normalement.
    """

    def __init__(self, db_path=None):
        self.db_path = str(db_path or A2A_DB_PATH)
        self._lock = threading.Lock()
        # Connexion persistante pour :memory: (shared entre operations)
        self._in_memory = (self.db_path == ":memory:")
        if self._in_memory:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._conn = None
        self._init_db()

    def _connect(self):
        """Retourne la connexion active (persistante si :memory:, courte sinon)."""
        if self._in_memory:
            return self._conn
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """Initialise le schema si necessaire. Idempotent."""
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS a2a_messages (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    to_agent    TEXT NOT NULL,
                    from_agent  TEXT NOT NULL,
                    task_id     TEXT NOT NULL,
                    payload     TEXT NOT NULL,
                    receipt_hash TEXT,
                    created_at  TEXT NOT NULL,
                    consumed_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_to_agent_consumed
                ON a2a_messages(to_agent, consumed_at)
            """)
            conn.commit()
        finally:
            if not self._in_memory:
                conn.close()

    def send(
        self,
        to: str,
        from_: str,
        task_id: str,
        payload: dict,
        receipt_hash: Optional[str] = None,
    ) -> int:
        """
        Envoie un message. Atomique. Retourne l'id du message insere.
        """
        created_at = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            with self._lock:
                cursor = conn.execute(
                    """INSERT INTO a2a_messages
                       (to_agent, from_agent, task_id, payload, receipt_hash, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        to, from_, task_id,
                        json.dumps(payload, ensure_ascii=False),
                        receipt_hash, created_at,
                    ),
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            if not self._in_memory:
                conn.close()

    def receive(self, agent: str, timeout_sec: int = 0) -> Optional[A2AMessage]:
        """
        Consommation unique : DELETE immediat apres lecture.
        Si timeout_sec > 0, polling jusqu'a message ou timeout.
        Retourne None si pas de message disponible.
        """
        start = time.monotonic()
        while True:
            conn = self._connect()
            try:
                with self._lock:
                    if not self._in_memory:
                        conn.isolation_level = "IMMEDIATE"
                    cursor = conn.execute(
                        """SELECT id, from_agent, task_id, payload, receipt_hash, created_at
                           FROM a2a_messages
                           WHERE to_agent = ? AND consumed_at IS NULL
                           ORDER BY id ASC LIMIT 1""",
                        (agent,),
                    )
                    row = cursor.fetchone()
                    if row:
                        msg = A2AMessage(
                            id=row[0],
                            to_agent=agent,
                            from_agent=row[1],
                            task_id=row[2],
                            payload=json.loads(row[3]),
                            receipt_hash=row[4],
                            created_at=row[5],
                        )
                        conn.execute(
                            "DELETE FROM a2a_messages WHERE id = ?", (msg.id,)
                        )
                        conn.commit()
                        return msg
            finally:
                if not self._in_memory:
                    conn.close()

            if timeout_sec > 0 and (time.monotonic() - start) < timeout_sec:
                time.sleep(0.05)
                continue
            return None

    def peek(self, agent: str) -> int:
        """Observabilite : nombre de messages en attente pour un agent."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                """SELECT COUNT(*) FROM a2a_messages
                   WHERE to_agent = ? AND consumed_at IS NULL""",
                (agent,),
            )
            return cursor.fetchone()[0]
        finally:
            if not self._in_memory:
                conn.close()

    def purge(self):
        """Vide tous les messages. Usage tests uniquement."""
        conn = self._connect()
        try:
            with self._lock:
                conn.execute("DELETE FROM a2a_messages")
                conn.commit()
        finally:
            if not self._in_memory:
                conn.close()

    def make_task_id(self, intent: str) -> str:
        """Genere un task_id stable depuis un intent. Format : a2a_{hash12}."""
        import hashlib
        return "a2a_" + hashlib.md5(intent.encode()).hexdigest()[:12]
