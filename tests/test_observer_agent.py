# -*- coding: utf-8-sig -*-
"""
Tests Sprint V8-07 -- ObserverAgent.

Plan :
    A. Helpers module-level (4 tests)
        A1 _make_report_id : deux appels differents -> IDs differents
        A2 _is_duplicate   : corps identiques -> True
        A3 _is_duplicate   : corps distincts  -> False
        A4 _should_archive : date ancienne -> True ; date recente -> False
    B. Snapshot (2 tests)
        B1 _build_snapshot : champs obligatoires presents
        B2 _build_snapshot : listes vides -> counts a 0
    C. create() + run_task nominal (2 tests)
        C1 create() instancie ObserverAgent avec bonne AgentCard
        C2 run_task sans memory_engine ni receipts -> succes + snapshot vide
    D. run_task avec memory_engine mock (2 tests)
        D1 skills low-quality detectes
        D2 doublons detectes (paire retournee)
    E. run_once (2 tests)
        E1 bus vide -> None
        E2 message present -> run_task appele + AgentResult retourne
"""
from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.agents.a2a_bus import A2ALocalBus, TaskContract
from core.agents.observer_agent import (
    ObserverAgent,
    _make_report_id,
    _is_duplicate,
    _should_archive,
    _build_snapshot,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures communes
# ═══════════════════════════════════════════════════════════════

@pytest.fixture()
def bus():
    return A2ALocalBus(db_path=":memory:")


@pytest.fixture()
def observer(bus):
    """ObserverAgent minimal : sans memory_engine, sans receipts_dir."""
    return ObserverAgent.create(bus=bus)


@pytest.fixture()
def contract(bus):
    return TaskContract(
        task_id="obs_task_001",
        intent="observe",
        domain="global",
        source_agent="orchestrator",
        target_agent="observer",
    )


# ═══════════════════════════════════════════════════════════════
# A. Helpers module-level
# ═══════════════════════════════════════════════════════════════

class TestMakeReportId:
    def test_different_inputs_give_different_ids(self):
        id1 = _make_report_id("observer", "2026-04-20T10:00:00")
        id2 = _make_report_id("observer", "2026-04-20T11:00:00")
        assert id1 != id2

    def test_same_inputs_give_same_id(self):
        id1 = _make_report_id("observer", "2026-04-20T10:00:00")
        id2 = _make_report_id("observer", "2026-04-20T10:00:00")
        assert id1 == id2

    def test_id_is_12_chars(self):
        rid = _make_report_id("obs", "ts")
        assert len(rid) == 12


class TestIsDuplicate:
    def test_identical_bodies_are_duplicate(self):
        e = {"body": "def foo(): pass bar baz qux"}
        assert _is_duplicate(e, e, threshold=0.9) is True

    def test_very_different_bodies_not_duplicate(self):
        a = {"body": "def foo(): return 42"}
        b = {"body": "import os sys pathlib logging json yaml"}
        assert _is_duplicate(a, b, threshold=0.9) is False

    def test_empty_body_not_duplicate(self):
        a = {"body": ""}
        b = {"body": "def bar(): pass"}
        assert _is_duplicate(a, b, threshold=0.5) is False

    def test_uses_code_key_fallback(self):
        a = {"code": "def foo(): pass bar baz"}
        b = {"code": "def foo(): pass bar baz"}
        assert _is_duplicate(a, b, threshold=0.9) is True


class TestShouldArchive:
    def test_old_receipt_should_archive(self):
        old_ts = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        assert _should_archive(old_ts, archive_after_days=30) is True

    def test_recent_receipt_not_archived(self):
        recent_ts = datetime.now(timezone.utc).isoformat()
        assert _should_archive(recent_ts, archive_after_days=30) is False

    def test_invalid_ts_returns_false(self):
        assert _should_archive("not-a-date", archive_after_days=30) is False


# ═══════════════════════════════════════════════════════════════
# B. Snapshot
# ═══════════════════════════════════════════════════════════════

class TestBuildSnapshot:
    def test_required_fields_present(self):
        snap = _build_snapshot(
            skills_count=5,
            low_quality=["id1"],
            duplicates=[("id2", "id3")],
            archived=["r1"],
        )
        for key in ("skills_total", "low_quality_ids", "duplicate_pairs",
                    "archived_ids", "low_quality_count", "duplicate_count",
                    "archived_count", "observed_at"):
            assert key in snap, f"Champ manquant : {key}"

    def test_counts_match_lists(self):
        snap = _build_snapshot(
            skills_count=10,
            low_quality=["a", "b"],
            duplicates=[("c", "d"), ("e", "f")],
            archived=[],
        )
        assert snap["low_quality_count"] == 2
        assert snap["duplicate_count"] == 2
        assert snap["archived_count"] == 0

    def test_empty_lists_give_zero_counts(self):
        snap = _build_snapshot(0, [], [], [])
        assert snap["skills_total"] == 0
        assert snap["low_quality_count"] == 0
        assert snap["duplicate_count"] == 0
        assert snap["archived_count"] == 0


# ═══════════════════════════════════════════════════════════════
# C. create() + run_task nominal
# ═══════════════════════════════════════════════════════════════

class TestCreate:
    def test_create_returns_observer_agent(self, bus):
        obs = ObserverAgent.create(bus=bus)
        assert isinstance(obs, ObserverAgent)
        assert obs.card.name == "observer"

    def test_card_capabilities(self, bus):
        obs = ObserverAgent.create(bus=bus)
        assert "maintenance" in obs.card.capabilities
        assert "memory_search" in obs.card.capabilities


class TestRunTaskNominal:
    def test_run_task_no_memory_no_receipts_succeeds(self, observer, contract):
        result = observer.run_task(contract)
        assert result.success is True
        assert "snapshot" in result.payload
        assert "report_id" in result.payload

    def test_snapshot_has_zero_counts_when_empty(self, observer, contract):
        result = observer.run_task(contract)
        snap = result.payload["snapshot"]
        assert snap["skills_total"] == 0
        assert snap["low_quality_count"] == 0
        assert snap["duplicate_count"] == 0


# ═══════════════════════════════════════════════════════════════
# D. run_task avec memory_engine mock
# ═══════════════════════════════════════════════════════════════

def _make_memory_mock(skills: list) -> MagicMock:
    """Fabrique un mock MemoryEngine retournant les skills donnes."""
    from core.memory_engine import MemoryEntry
    entries = [
        MemoryEntry(
            id=s["id"],
            collection="lcca_skills",
            content=s.get("body", ""),
            metadata={"quality_score": str(s.get("score", 0))},
        )
        for s in skills
    ]
    mock = MagicMock()
    mock.search.return_value = {"skills": entries, "solutions": [], "failures": [],
                                "context": [], "specs": []}
    mock.store.return_value = MagicMock(stored=True)
    return mock


class TestRunTaskWithMemory:
    def test_low_quality_skills_detected(self, bus, contract):
        skills = [
            {"id": "s1", "body": "def foo(): pass", "score": 80},
            {"id": "s2", "body": "def bar(): pass", "score": 20},  # low
            {"id": "s3", "body": "def baz(): pass", "score": 15},  # low
        ]
        obs = ObserverAgent.create(bus=bus, memory_engine=_make_memory_mock(skills))
        result = obs.run_task(contract)
        snap = result.payload["snapshot"]
        assert snap["low_quality_count"] == 2
        assert "s2" in snap["low_quality_ids"]
        assert "s3" in snap["low_quality_ids"]

    def test_duplicates_detected(self, bus, contract):
        body = "def compute(): return " + " ".join(f"x{i}" for i in range(30))
        skills = [
            {"id": "s1", "body": body, "score": 80},
            {"id": "s2", "body": body, "score": 75},   # quasi-identique
            {"id": "s3", "body": "def totally_different(): import os sys", "score": 90},
        ]
        obs = ObserverAgent.create(bus=bus, memory_engine=_make_memory_mock(skills))
        result = obs.run_task(contract)
        snap = result.payload["snapshot"]
        assert snap["duplicate_count"] >= 1
        # La paire (s1, s2) doit etre detectee
        pairs_flat = [item for pair in snap["duplicate_pairs"] for item in pair]
        assert "s1" in pairs_flat
        assert "s2" in pairs_flat


# ═══════════════════════════════════════════════════════════════
# E. run_once
# ═══════════════════════════════════════════════════════════════

class TestRunOnce:
    def test_empty_bus_returns_none(self, observer):
        result = observer.run_once(timeout_sec=0)
        assert result is None

    def test_message_triggers_run_task(self, bus):
        obs = ObserverAgent.create(bus=bus)
        # Envoyer un message vers "observer"
        bus.send(
            to="observer",
            from_="orchestrator",
            task_id="obs_run_once_01",
            payload={"intent": "observe", "domain": "global"},
        )
        result = obs.run_once(timeout_sec=1)
        assert result is not None
        assert result.success is True
        assert "snapshot" in result.payload


# ═══════════════════════════════════════════════════════════════
# F. Archivage receipts (avec tmp_path)
# ═══════════════════════════════════════════════════════════════

class TestArchiveReceipts:
    def test_old_receipt_gets_archived(self, bus, tmp_path):
        """Un receipt vieux de 31 jours doit etre archive (.archived)."""
        old_ts = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        receipt = {
            "task_id": "old_task",
            "timestamp": old_ts,
            "sandbox_passed": True,
        }
        receipt_file = tmp_path / "old_task.json"
        receipt_file.write_text(json.dumps(receipt), encoding="utf-8")

        obs = ObserverAgent.create(bus=bus, receipts_dir=tmp_path, archive_after_days=30)
        contract = TaskContract(
            task_id="arch_test",
            intent="observe",
            domain="global",
            source_agent="test",
            target_agent="observer",
        )
        result = obs.run_task(contract)
        snap = result.payload["snapshot"]

        assert snap["archived_count"] == 1
        assert "old_task" in snap["archived_ids"]
        assert not receipt_file.exists()
        assert (tmp_path / "old_task.archived").exists()

    def test_recent_receipt_not_archived(self, bus, tmp_path):
        """Un receipt recent ne doit pas etre archive."""
        recent_ts = datetime.now(timezone.utc).isoformat()
        receipt = {"task_id": "new_task", "timestamp": recent_ts, "sandbox_passed": True}
        (tmp_path / "new_task.json").write_text(json.dumps(receipt), encoding="utf-8")

        obs = ObserverAgent.create(bus=bus, receipts_dir=tmp_path, archive_after_days=30)
        contract = TaskContract(
            task_id="arch_recent",
            intent="observe",
            domain="global",
            source_agent="test",
            target_agent="observer",
        )
        result = obs.run_task(contract)
        snap = result.payload["snapshot"]

        assert snap["archived_count"] == 0
        assert (tmp_path / "new_task.json").exists()
