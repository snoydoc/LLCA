# -*- coding: utf-8-sig -*-
"""
Tests Sprint V8-04 -- ReviewerAgent.

8 tests couvrant :
  - run_once() avec/sans message
  - code valide -> forward tester
  - code SyntaxError -> rejection architect
  - code vide -> rejected
  - flags reviewer_ok dans les payloads
  - receipt_hash propage
  - run_task retourne AgentResult
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from core.agents.a2a_bus import A2ALocalBus, TaskContract
from core.agents.reviewer_agent import ReviewerAgent, _check_syntax, _build_reflection


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus():
    b = A2ALocalBus(db_path=":memory:")
    yield b
    b.purge()


@pytest.fixture
def reviewer(bus):
    return ReviewerAgent.create(bus=bus)


def _send_to_reviewer(bus: A2ALocalBus, code: str, task_id: str = "t_rev_001",
                       receipt_hash: str = "hash_abc") -> None:
    """Helper : envoie un message simule depuis le Coder vers le Reviewer."""
    bus.send(
        to="reviewer",
        from_="coder",
        task_id=task_id,
        payload={
            "code": code,
            "task_id": task_id,
            "contract": {
                "task_id": task_id,
                "intent": "add login",
                "domain": "ui",
                "source_agent": "architect",
                "target_agent": "coder",
                "context": {},
                "constraints": [],
                "spec_id": None,
                "parent_task_id": None,
            },
        },
        receipt_hash=receipt_hash,
    )


# ---------------------------------------------------------------------------
# 1. Helpers unitaires
# ---------------------------------------------------------------------------

class TestCheckSyntax:

    def test_valid_code_returns_true(self):
        ok, issues = _check_syntax("def hello(): return 42")
        assert ok is True
        assert issues == []

    def test_syntax_error_returns_false(self):
        ok, issues = _check_syntax("def broken(: pass")
        assert ok is False
        assert len(issues) > 0
        assert "SyntaxError" in issues[0]

    def test_empty_code_returns_false(self):
        ok, issues = _check_syntax("")
        assert ok is False
        assert "Code vide" in issues[0]

    def test_whitespace_only_returns_false(self):
        ok, issues = _check_syntax("   \n  ")
        assert ok is False


class TestBuildReflection:

    def test_with_issues_and_suggestion(self):
        r = _build_reflection(["SyntaxError ligne 3: invalid"], "Corriger X")
        assert "Reviewer:" in r
        assert "Suggestion:" in r

    def test_without_suggestion(self):
        r = _build_reflection(["probleme Y"])
        assert "Reviewer:" in r
        assert "probleme Y" in r


# ---------------------------------------------------------------------------
# 2. ReviewerAgent
# ---------------------------------------------------------------------------

class TestReviewerAgent:

    def test_run_once_returns_none_if_no_message(self, reviewer):
        """Bus vide -> None."""
        result = reviewer.run_once(timeout_sec=0)
        assert result is None

    def test_run_once_returns_result_if_message(self, reviewer, bus):
        """Message present -> AgentResult (succes ou echec)."""
        _send_to_reviewer(bus, "x = 1")
        result = reviewer.run_once(timeout_sec=0)
        assert result is not None

    def test_valid_code_forwarded_to_tester(self, reviewer, bus):
        """Code Python valide -> message dans la queue 'tester'."""
        _send_to_reviewer(bus, "def add(a, b): return a + b")
        reviewer.run_once(timeout_sec=0)
        assert bus.peek("tester") == 1, "Un message doit etre en attente chez le tester"

    def test_invalid_code_rejected_to_architect(self, reviewer, bus):
        """Code avec SyntaxError -> rejection dans la queue 'architect'."""
        _send_to_reviewer(bus, "def broken(: pass")
        reviewer.run_once(timeout_sec=0)
        assert bus.peek("architect") == 1, "Un rejection doit etre envoye a l'architect"

    def test_empty_code_rejected(self, reviewer, bus):
        """Code vide -> rejected=True vers architect."""
        _send_to_reviewer(bus, "")
        reviewer.run_once(timeout_sec=0)
        assert bus.peek("architect") == 1

    def test_reviewer_ok_true_in_tester_payload(self, reviewer, bus):
        """Payload vers tester doit contenir reviewer_ok=True."""
        _send_to_reviewer(bus, "result = 42")
        reviewer.run_once(timeout_sec=0)
        msg = bus.receive("tester")
        assert msg is not None
        assert msg.payload.get("reviewer_ok") is True

    def test_reflection_present_in_reject_payload(self, reviewer, bus):
        """Payload rejection vers architect doit contenir 'reflection'."""
        _send_to_reviewer(bus, "def bad(: pass")
        reviewer.run_once(timeout_sec=0)
        msg = bus.receive("architect")
        assert msg is not None
        assert "reflection" in msg.payload
        assert msg.payload["reflection"] != ""

    def test_receipt_hash_propagated_to_tester(self, reviewer, bus):
        """receipt_hash du Coder doit etre transmis dans le payload vers tester."""
        _send_to_reviewer(bus, "x = 1", receipt_hash="test_hash_xyz")
        reviewer.run_once(timeout_sec=0)
        msg = bus.receive("tester")
        assert msg is not None
        # Le receipt_hash doit etre dans le payload ou dans msg.receipt_hash
        in_payload = msg.payload.get("receipt_hash") == "test_hash_xyz"
        in_msg = msg.receipt_hash == "test_hash_xyz"
        assert in_payload or in_msg, (
            f"receipt_hash non propage. payload={msg.payload}, msg.receipt_hash={msg.receipt_hash}"
        )
