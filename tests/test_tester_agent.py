# -*- coding: utf-8-sig -*-
"""
Tests Sprint V8-04 -- TesterAgent.

8 tests couvrant :
  - run_once() avec/sans message
  - receipt cree et signature valide
  - code invalide (sandbox=False) -> rejection architect
  - quality < seuil -> rejection architect
  - skill_lib.extract_and_store appele si succes + qualite OK
  - reflection presente dans rejection payload
  - AgentResult retourne succes/echec coherent
"""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.agents.a2a_bus import A2ALocalBus, TaskContract
from core.agents.tester_agent import TesterAgent, _hash, _run_sandbox_safe
from core.receipt_store import verify_receipt, load_receipt, RECEIPTS_DIR


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus():
    b = A2ALocalBus(db_path=":memory:")
    yield b
    b.purge()


@pytest.fixture
def sandbox_ok():
    """SandboxEngine mock qui retourne succes."""
    s = MagicMock()
    s.run.return_value = (True, "ok", "", 0)
    return s


@pytest.fixture
def sandbox_fail():
    """SandboxEngine mock qui retourne echec."""
    s = MagicMock()
    s.run.return_value = (False, "", "NameError: x not defined", 1)
    return s


@pytest.fixture
def evaluator_high():
    """CodeEvaluator mock qui retourne un score eleve (> 70)."""
    e = MagicMock()
    result = MagicMock()
    result.score = 85
    e.evaluate.return_value = result
    return e


@pytest.fixture
def evaluator_low():
    """CodeEvaluator mock qui retourne un score bas (< 70)."""
    e = MagicMock()
    result = MagicMock()
    result.score = 30
    e.evaluate.return_value = result
    return e


def _make_tester(bus, sandbox=None, evaluator=None, skill_library=None):
    """Factory helper pour TesterAgent avec injections optionnelles."""
    card_kwargs = dict(
        sandbox=sandbox,
        evaluator=evaluator,
        skill_library=skill_library,
    )
    t = TesterAgent.create(bus=bus)
    if sandbox is not None:
        t._sandbox = sandbox
    if evaluator is not None:
        t._evaluator = evaluator
    if skill_library is not None:
        t._skill_lib = skill_library
    return t


def _send_to_tester(bus: A2ALocalBus, code: str, task_id: str = "t_test_001") -> None:
    """Helper : simule l'envoi du ReviewerAgent vers le TesterAgent."""
    bus.send(
        to="tester",
        from_="reviewer",
        task_id=task_id,
        payload={
            "code": code,
            "task_id": task_id,
            "reviewer_ok": True,
            "contract": {
                "task_id": task_id,
                "intent": "add feature",
                "domain": "global",
                "source_agent": "architect",
                "target_agent": "coder",
                "context": {},
                "constraints": [],
                "spec_id": None,
                "parent_task_id": None,
            },
        },
        receipt_hash="prev_hash",
    )


# ---------------------------------------------------------------------------
# 1. Helpers unitaires
# ---------------------------------------------------------------------------

class TestHelpers:

    def test_hash_returns_12_chars(self):
        h = _hash("hello world")
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_run_sandbox_safe_success(self):
        mock_sb = MagicMock()
        mock_sb.run.return_value = (True, "out", "", 0)
        result = _run_sandbox_safe(mock_sb, "x=1")
        assert result["success"] is True

    def test_run_sandbox_safe_exception(self):
        """Si sandbox.run() leve une exception, retourner success=False sans lever."""
        mock_sb = MagicMock()
        mock_sb.run.side_effect = RuntimeError("crash")
        result = _run_sandbox_safe(mock_sb, "x=1")
        assert result["success"] is False
        assert "crash" in result["stderr"]


# ---------------------------------------------------------------------------
# 2. TesterAgent
# ---------------------------------------------------------------------------

class TestTesterAgent:

    def test_run_once_returns_none_if_no_message(self, bus):
        """Bus vide -> None."""
        tester = _make_tester(bus)
        result = tester.run_once(timeout_sec=0)
        assert result is None

    def test_run_once_returns_result_if_message(self, bus, sandbox_ok, evaluator_high):
        """Message present -> AgentResult."""
        tester = _make_tester(bus, sandbox=sandbox_ok, evaluator=evaluator_high)
        _send_to_tester(bus, "x = 42")
        result = tester.run_once(timeout_sec=0)
        assert result is not None

    def test_receipt_signature_valid(self, bus, sandbox_ok, evaluator_high, tmp_path, monkeypatch):
        """
        Le receipt genere doit passer verify_receipt().
        On redirige RECEIPTS_DIR vers tmp_path pour isoler le test.
        """
        import core.receipt_store as rs
        monkeypatch.setattr(rs, "RECEIPTS_DIR", tmp_path / "receipts")
        monkeypatch.setattr(rs, "SECRET_DIR", tmp_path / ".secret")
        monkeypatch.setattr(rs, "KEY_PATH", tmp_path / ".secret" / "a2a_key")

        tester = _make_tester(bus, sandbox=sandbox_ok, evaluator=evaluator_high)
        _send_to_tester(bus, "def ok(): return True", task_id="receipt_test")
        result = tester.run_once(timeout_sec=0)

        # Charger le receipt depuis le disque
        receipt = rs.load_receipt("receipt_test")
        assert receipt is not None, "Le receipt doit etre persiste sur disque"
        assert verify_receipt(receipt) is True, "Le HMAC du receipt doit etre valide"

    def test_sandbox_failure_rejected(self, bus, sandbox_fail, evaluator_high):
        """sandbox_passed=False -> rejection vers architect."""
        tester = _make_tester(bus, sandbox=sandbox_fail, evaluator=evaluator_high)
        _send_to_tester(bus, "x = broken()")
        result = tester.run_once(timeout_sec=0)
        assert result is not None
        assert result.success is False
        assert bus.peek("architect") == 1, "Un rejection doit etre dans la queue architect"

    def test_low_quality_rejected(self, bus, sandbox_ok, evaluator_low):
        """quality_score < 70 -> rejection vers architect."""
        tester = _make_tester(bus, sandbox=sandbox_ok, evaluator=evaluator_low)
        _send_to_tester(bus, "x = 1")
        result = tester.run_once(timeout_sec=0)
        assert result is not None
        assert result.success is False
        assert bus.peek("architect") == 1

    def test_skill_stored_on_success(self, bus, sandbox_ok, evaluator_high):
        """
        Succes (sandbox OK + quality >= 70) -> skill_lib.extract_and_store appelee.
        """
        skill_lib = MagicMock()
        skill_lib.extract_and_store.return_value = 1
        tester = _make_tester(bus, sandbox=sandbox_ok, evaluator=evaluator_high,
                               skill_library=skill_lib)
        _send_to_tester(bus, "def add(a, b): return a + b")
        result = tester.run_once(timeout_sec=0)
        assert result is not None
        assert result.success is True
        skill_lib.extract_and_store.assert_called_once()

    def test_skill_not_stored_on_failure(self, bus, sandbox_fail, evaluator_high):
        """Echec sandbox -> extract_and_store NOT appelee."""
        skill_lib = MagicMock()
        tester = _make_tester(bus, sandbox=sandbox_fail, evaluator=evaluator_high,
                               skill_library=skill_lib)
        _send_to_tester(bus, "broken code :")
        tester.run_once(timeout_sec=0)
        skill_lib.extract_and_store.assert_not_called()

    def test_reflection_in_reject_payload(self, bus, sandbox_fail, evaluator_low):
        """Payload rejection vers architect doit contenir 'reflection' non vide."""
        tester = _make_tester(bus, sandbox=sandbox_fail, evaluator=evaluator_low)
        _send_to_tester(bus, "bad = broken()")
        tester.run_once(timeout_sec=0)
        msg = bus.receive("architect")
        assert msg is not None
        assert "reflection" in msg.payload
        assert msg.payload["reflection"] != ""
