# -*- coding: utf-8-sig -*-
"""
Tests Sprint V8-01 -- A2ALocalBus + TaskContract.
12 tests couvrant : init, send, receive, isolation, FIFO, TaskContract.
"""
import threading
import time
import pytest
from pathlib import Path

from core.agents.a2a_bus import A2ALocalBus, A2AMessage, TaskContract


@pytest.fixture
def bus(tmp_path):
    """Bus isole par test (db en memoire temporaire)."""
    db = tmp_path / "test_a2a.sqlite"
    b = A2ALocalBus(db_path=db)
    yield b
    b.purge()


# ── TestA2ABusInit ────────────────────────────────────────────────────────────

class TestA2ABusInit:

    def test_db_created_on_init(self, tmp_path):
        db = tmp_path / "new_bus.sqlite"
        assert not db.exists()
        A2ALocalBus(db_path=db)
        assert db.exists(), "Le fichier SQLite doit etre cree a l'init"

    def test_init_idempotent(self, tmp_path):
        db = tmp_path / "idempotent.sqlite"
        A2ALocalBus(db_path=db)
        # Double init sans exception
        A2ALocalBus(db_path=db)


# ── TestA2ABusSend ────────────────────────────────────────────────────────────

class TestA2ABusSend:

    def test_send_returns_id(self, bus):
        msg_id = bus.send(
            to="coder", from_="architect",
            task_id="a2a_abc123", payload={"intent": "test"},
        )
        assert isinstance(msg_id, int) and msg_id > 0

    def test_send_stores_message(self, bus):
        assert bus.peek("coder") == 0
        bus.send(to="coder", from_="architect",
                 task_id="a2a_abc123", payload={"x": 1})
        assert bus.peek("coder") == 1


# ── TestA2ABusReceive ─────────────────────────────────────────────────────────

class TestA2ABusReceive:

    def test_receive_returns_message(self, bus):
        payload = {"intent": "ajouter JWT", "score": 42}
        bus.send(to="coder", from_="architect",
                 task_id="a2a_xyz", payload=payload)
        msg = bus.receive("coder")
        assert msg is not None
        assert msg.payload == payload
        assert msg.task_id == "a2a_xyz"
        assert msg.from_agent == "architect"

    def test_receive_atomic_consumption(self, bus):
        """Deux threads tentent de consommer le meme message -- un seul reussit."""
        bus.send(to="coder", from_="architect",
                 task_id="a2a_race", payload={"n": 1})

        results = []

        def consume():
            msg = bus.receive("coder", timeout_sec=0)
            results.append(msg)

        t1 = threading.Thread(target=consume)
        t2 = threading.Thread(target=consume)
        t1.start(); t2.start()
        t1.join(); t2.join()

        received = [r for r in results if r is not None]
        assert len(received) == 1, "Un seul thread doit consommer le message"

    def test_receive_no_message_returns_none(self, bus):
        result = bus.receive("reviewer", timeout_sec=0)
        assert result is None

    def test_receive_timeout_returns_none(self, bus):
        start = time.monotonic()
        result = bus.receive("tester", timeout_sec=0)
        elapsed = time.monotonic() - start
        assert result is None
        assert elapsed < 1.0, "timeout_sec=0 doit retourner immediatement"


# ── TestA2ABusIsolation ───────────────────────────────────────────────────────

class TestA2ABusIsolation:

    def test_agent_cannot_consume_other_inbox(self, bus):
        """Le Coder ne doit pas recevoir un message destine a l'Architect."""
        bus.send(to="architect", from_="tester",
                 task_id="a2a_iso1", payload={"for": "architect"})
        msg_coder = bus.receive("coder", timeout_sec=0)
        msg_arch  = bus.receive("architect", timeout_sec=0)
        assert msg_coder is None, "Coder ne doit pas voir les messages de l'Architect"
        assert msg_arch is not None

    def test_fifo_order(self, bus):
        """Premier envoye = premier recu."""
        bus.send(to="reviewer", from_="coder",
                 task_id="a2a_fifo1", payload={"order": 1})
        bus.send(to="reviewer", from_="coder",
                 task_id="a2a_fifo2", payload={"order": 2})
        bus.send(to="reviewer", from_="coder",
                 task_id="a2a_fifo3", payload={"order": 3})

        orders = []
        for _ in range(3):
            msg = bus.receive("reviewer")
            orders.append(msg.payload["order"])

        assert orders == [1, 2, 3], f"Ordre FIFO attendu, obtenu: {orders}"


# ── TestTaskContract ──────────────────────────────────────────────────────────

class TestTaskContract:

    def test_task_contract_roundtrip(self, bus):
        """to_dict + from_dict conserve tous les champs."""
        contract = TaskContract(
            task_id="a2a_rt001",
            intent="ajouter validation JWT",
            domain="ast",
            source_agent="architect",
            target_agent="coder",
            context={"reuse_skills": True},
            constraints=["max_files=3"],
            spec_id="spec_abc123",
            parent_task_id=None,
        )
        restored = TaskContract.from_dict(contract.to_dict())
        assert restored.task_id    == contract.task_id
        assert restored.intent     == contract.intent
        assert restored.domain     == contract.domain
        assert restored.context    == contract.context
        assert restored.constraints == contract.constraints
        assert restored.spec_id    == contract.spec_id

    def test_make_task_id_stable(self, bus):
        """Meme intent => meme task_id (deterministe)."""
        intent = "refactoriser le module memory_engine"
        id1 = bus.make_task_id(intent)
        id2 = bus.make_task_id(intent)
        assert id1 == id2
        assert id1.startswith("a2a_")
        assert len(id1) == len("a2a_") + 12
