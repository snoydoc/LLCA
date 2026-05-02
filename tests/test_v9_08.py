# -*- coding: utf-8-sig -*-
"""
Tests Sprint V9-08 -- ReviewerAgent LLM Integration.

12 tests couvrant :
  1. retrocompat llm=None (reviewer.create() sans llm_generator) -- AgentResult retourne
  2. llm=None -> _analyze_with_llm retourne valeurs neutres (-1, [], [])
  3. llm=None -> llm_used=False dans payload succes
  4. llm=None -> llm_used=False dans payload echec
  5. mock LLM JSON valide -> quality_score extrait correctement
  6. mock LLM JSON valide -> suggestions extraites dans review_notes (payload tester)
  7. mock LLM JSON valide -> llm_used=True dans payload succes
  8. mock LLM JSON invalide (non-JSON) -> swallow silencieux, quality_score=-1
  9. mock LLM exception -> swallow silencieux, quality_score=-1
 10. quality_score dans AgentResult.payload["llm_review"]
 11. llm_review dict present dans payload forward tester (code valide)
 12. llm_review dict present dans payload rejection architect (code invalide)
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch

from core.agents.a2a_bus import A2ALocalBus, TaskContract
from core.agents.reviewer_agent import ReviewerAgent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus():
    b = A2ALocalBus(db_path=":memory:")
    yield b
    b.purge()


@pytest.fixture
def reviewer_no_llm(bus):
    """ReviewerAgent sans LLM -- retrocompat totale."""
    return ReviewerAgent.create(bus=bus, llm_generator=None)


def _make_mock_llm(quality_score: int = 72,
                   issues: list | None = None,
                   suggestions: list | None = None,
                   raise_exc: Exception | None = None,
                   raw_response: str | None = None) -> MagicMock:
    """Fabrique un mock LLMGenerator pour les tests V9-08."""
    mock = MagicMock()
    if raise_exc is not None:
        mock.generate_text.side_effect = raise_exc
    elif raw_response is not None:
        mock.generate_text.return_value = raw_response
    else:
        payload = {
            "quality_score": quality_score,
            "issues": issues or [],
            "suggestions": suggestions or ["Ajouter des type hints"],
        }
        mock.generate_text.return_value = json.dumps(payload)
    return mock


def _make_contract(task_id: str = "t_v908_001",
                   code: str = "def add(a, b): return a + b",
                   intent: str = "add two numbers",
                   domain: str = "global") -> TaskContract:
    """Fabrique un TaskContract minimal pour run_task."""
    contract = TaskContract(
        task_id=task_id,
        intent=intent,
        domain=domain,
        source_agent="coder",
        target_agent="reviewer",
    )
    contract.context["code"] = code
    contract.context["original_payload"] = {}
    contract.context["receipt_hash"] = "hash_v908"
    return contract


# ---------------------------------------------------------------------------
# 1. Retrocompat llm=None
# ---------------------------------------------------------------------------

class TestRetroCompatNoLlm:

    def test_create_without_llm_returns_agent(self, bus):
        """reviewer.create() sans llm_generator doit retourner un ReviewerAgent."""
        agent = ReviewerAgent.create(bus=bus, llm_generator=None)
        assert isinstance(agent, ReviewerAgent)

    def test_run_task_valid_code_no_llm(self, reviewer_no_llm, bus):
        """run_task avec code valide et llm=None -> AgentResult(success=True)."""
        contract = _make_contract(code="x = 1 + 2")
        result = reviewer_no_llm.run_task(contract)
        assert result.success is True

    def test_llm_used_false_in_success_payload(self, reviewer_no_llm, bus):
        """Payload succes doit contenir llm_used=False quand llm=None."""
        contract = _make_contract(code="result = 42")
        result = reviewer_no_llm.run_task(contract)
        assert result.payload.get("llm_used") is False

    def test_llm_used_false_in_failure_payload(self, reviewer_no_llm, bus):
        """Payload echec doit contenir llm_used=False quand llm=None."""
        contract = _make_contract(code="def broken(: pass")
        result = reviewer_no_llm.run_task(contract)
        assert result.success is False
        assert result.payload.get("llm_used") is False


# ---------------------------------------------------------------------------
# 2. _analyze_with_llm -- valeurs neutres si llm=None
# ---------------------------------------------------------------------------

class TestAnalyzeWithLlmNoLlm:

    def test_analyze_returns_minus_one_quality_score(self, reviewer_no_llm):
        """_analyze_with_llm sans LLM -> quality_score=-1."""
        result = reviewer_no_llm._analyze_with_llm("x=1", "test", "global")
        assert result["quality_score"] == -1

    def test_analyze_returns_empty_issues(self, reviewer_no_llm):
        """_analyze_with_llm sans LLM -> issues=[]."""
        result = reviewer_no_llm._analyze_with_llm("x=1", "test", "global")
        assert result["issues"] == []

    def test_analyze_returns_empty_suggestions(self, reviewer_no_llm):
        """_analyze_with_llm sans LLM -> suggestions=[]."""
        result = reviewer_no_llm._analyze_with_llm("x=1", "test", "global")
        assert result["suggestions"] == []


# ---------------------------------------------------------------------------
# 3. Mock LLM JSON valide
# ---------------------------------------------------------------------------

class TestMockLlmValidJson:

    def test_quality_score_extracted(self, bus):
        """Mock LLM JSON valide -> quality_score correctement extrait."""
        mock_llm = _make_mock_llm(quality_score=85)
        agent = ReviewerAgent(
            card=ReviewerAgent.create(bus=bus).card,
            bus=bus,
            llm_generator=mock_llm,
        )
        result = agent._analyze_with_llm("def f(): pass", "intent", "global")
        assert result["quality_score"] == 85

    def test_suggestions_in_review_notes(self, bus):
        """Suggestions LLM doivent se retrouver dans review_notes du payload tester."""
        mock_llm = _make_mock_llm(
            quality_score=70,
            suggestions=["Utiliser pathlib", "Ajouter docstring"],
        )
        agent = ReviewerAgent(
            card=ReviewerAgent.create(bus=bus).card,
            bus=bus,
            llm_generator=mock_llm,
        )
        contract = _make_contract(code="import os\nf = open('x')")
        agent.run_task(contract)
        msg = bus.receive("tester")
        assert msg is not None
        notes = msg.payload.get("review_notes", [])
        assert "Utiliser pathlib" in notes or "Ajouter docstring" in notes

    def test_llm_used_true_in_success_payload(self, bus):
        """Payload succes doit contenir llm_used=True quand LLM fourni."""
        mock_llm = _make_mock_llm(quality_score=90)
        agent = ReviewerAgent(
            card=ReviewerAgent.create(bus=bus).card,
            bus=bus,
            llm_generator=mock_llm,
        )
        contract = _make_contract(code="def ok(): return True")
        result = agent.run_task(contract)
        assert result.payload.get("llm_used") is True


# ---------------------------------------------------------------------------
# 4. Mock LLM -- erreurs silencieuses
# ---------------------------------------------------------------------------

class TestMockLlmErrorHandling:

    def test_invalid_json_swallowed(self, bus):
        """LLM retournant du texte non-JSON -> swallow, quality_score=-1."""
        mock_llm = _make_mock_llm(raw_response="Ce n'est pas du JSON")
        agent = ReviewerAgent(
            card=ReviewerAgent.create(bus=bus).card,
            bus=bus,
            llm_generator=mock_llm,
        )
        result = agent._analyze_with_llm("x=1", "test", "global")
        assert result["quality_score"] == -1

    def test_exception_swallowed(self, bus):
        """LLM levant une exception -> swallow, quality_score=-1."""
        mock_llm = _make_mock_llm(raise_exc=RuntimeError("Ollama down"))
        agent = ReviewerAgent(
            card=ReviewerAgent.create(bus=bus).card,
            bus=bus,
            llm_generator=mock_llm,
        )
        result = agent._analyze_with_llm("x=1", "test", "global")
        assert result["quality_score"] == -1

    def test_exception_does_not_propagate_in_run_task(self, bus):
        """Exception LLM ne doit pas faire echouer run_task (code valide)."""
        mock_llm = _make_mock_llm(raise_exc=ConnectionError("timeout"))
        agent = ReviewerAgent(
            card=ReviewerAgent.create(bus=bus).card,
            bus=bus,
            llm_generator=mock_llm,
        )
        contract = _make_contract(code="y = 2 + 2")
        result = agent.run_task(contract)
        # Le code est syntaxiquement valide -> succes malgre erreur LLM
        assert result.success is True


# ---------------------------------------------------------------------------
# 5. llm_review dans AgentResult.payload
# ---------------------------------------------------------------------------

class TestLlmReviewInPayload:

    def test_llm_review_in_success_payload(self, bus):
        """AgentResult.payload doit contenir 'llm_review' dict sur code valide."""
        mock_llm = _make_mock_llm(quality_score=60)
        agent = ReviewerAgent(
            card=ReviewerAgent.create(bus=bus).card,
            bus=bus,
            llm_generator=mock_llm,
        )
        contract = _make_contract(code="a = 1")
        result = agent.run_task(contract)
        assert "llm_review" in result.payload
        assert isinstance(result.payload["llm_review"], dict)

    def test_llm_review_in_failure_payload(self, bus):
        """AgentResult.payload doit contenir 'llm_review' dict sur code invalide."""
        mock_llm = _make_mock_llm(quality_score=10)
        agent = ReviewerAgent(
            card=ReviewerAgent.create(bus=bus).card,
            bus=bus,
            llm_generator=mock_llm,
        )
        contract = _make_contract(code="def bad(: pass")
        result = agent.run_task(contract)
        assert result.success is False
        assert "llm_review" in result.payload
        assert isinstance(result.payload["llm_review"], dict)

    def test_llm_review_forwarded_to_tester(self, bus):
        """llm_review doit etre present dans le message forward vers tester."""
        mock_llm = _make_mock_llm(quality_score=75)
        agent = ReviewerAgent(
            card=ReviewerAgent.create(bus=bus).card,
            bus=bus,
            llm_generator=mock_llm,
        )
        contract = _make_contract(code="n = 99")
        agent.run_task(contract)
        msg = bus.receive("tester")
        assert msg is not None
        assert "llm_review" in msg.payload

    def test_llm_review_in_rejection_to_architect(self, bus):
        """llm_review doit etre present dans le message de rejection vers architect."""
        mock_llm = _make_mock_llm(quality_score=5)
        agent = ReviewerAgent(
            card=ReviewerAgent.create(bus=bus).card,
            bus=bus,
            llm_generator=mock_llm,
        )
        contract = _make_contract(code="def oops(:")
        agent.run_task(contract)
        msg = bus.receive("architect")
        assert msg is not None
        assert "llm_review" in msg.payload
