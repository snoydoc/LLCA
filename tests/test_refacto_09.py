# -*- coding: utf-8-sig -*-
"""
Tests REFACTO-09 -- Decomposition reviewer_agent.py.

18 tests couvrant :
  ReviewerValidator    -- _check_syntax (4), _build_reflection (3)
  ReviewerLlmAnalyzer  -- analyze() sans LLM (3), avec mock LLM (4), erreurs (2)
  Integration          -- ReviewerAgent delegue correctement (4)
                          import retrocompat depuis reviewer_agent (1)
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock

from core.agents.a2a_bus import A2ALocalBus, TaskContract
from core.agents.reviewer_agent import ReviewerAgent, _check_syntax, _build_reflection
from core.agents.reviewer_validator import _check_syntax as _cs_direct, _build_reflection as _br_direct
from core.agents.reviewer_analyzer import ReviewerLlmAnalyzer, REVIEWER_SYSTEM, REVIEWER_USER_TMPL


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus():
    b = A2ALocalBus(db_path=":memory:")
    yield b
    b.purge()


def _make_contract(task_id: str = "t_r09_001",
                   code: str = "def f(): return 1",
                   intent: str = "test",
                   domain: str = "global") -> TaskContract:
    c = TaskContract(
        task_id=task_id, intent=intent, domain=domain,
        source_agent="coder", target_agent="reviewer",
    )
    c.context["code"] = code
    c.context["original_payload"] = {}
    c.context["receipt_hash"] = "hash_r09"
    return c


def _make_mock_llm(quality_score: int = 80,
                   suggestions: list | None = None,
                   raise_exc: Exception | None = None,
                   raw: str | None = None) -> MagicMock:
    m = MagicMock()
    if raise_exc:
        m.generate_text.side_effect = raise_exc
    elif raw is not None:
        m.generate_text.return_value = raw
    else:
        m.generate_text.return_value = json.dumps({
            "quality_score": quality_score,
            "issues": [],
            "suggestions": suggestions or ["Ajouter des type hints"],
        })
    return m


# ---------------------------------------------------------------------------
# 1. ReviewerValidator -- _check_syntax
# ---------------------------------------------------------------------------

class TestReviewerValidatorSyntax:

    def test_valid_code_ok(self):
        ok, issues = _cs_direct("x = 1 + 2")
        assert ok is True
        assert issues == []

    def test_syntax_error_detected(self):
        ok, issues = _cs_direct("def bad(: pass")
        assert ok is False
        assert any("SyntaxError" in i for i in issues)

    def test_empty_string_rejected(self):
        ok, issues = _cs_direct("")
        assert ok is False
        assert "Code vide" in issues[0]

    def test_whitespace_only_rejected(self):
        ok, issues = _cs_direct("   \n  \t  ")
        assert ok is False


# ---------------------------------------------------------------------------
# 2. ReviewerValidator -- _build_reflection
# ---------------------------------------------------------------------------

class TestReviewerValidatorReflection:

    def test_with_issues_and_suggestion(self):
        r = _br_direct(["SyntaxError ligne 5: invalid syntax"], "Corriger X")
        assert r.startswith("Reviewer:")
        assert "Suggestion:" in r
        assert "Corriger X" in r

    def test_without_suggestion(self):
        r = _br_direct(["probleme detecte"])
        assert "Reviewer:" in r
        assert "probleme detecte" in r
        assert "Suggestion:" not in r

    def test_empty_issues_uses_fallback(self):
        r = _br_direct([])
        assert "Reviewer:" in r
        assert "probleme inconnu" in r


# ---------------------------------------------------------------------------
# 3. ReviewerLlmAnalyzer -- sans LLM
# ---------------------------------------------------------------------------

class TestReviewerLlmAnalyzerNoLlm:

    def setup_method(self):
        self.analyzer = ReviewerLlmAnalyzer(llm_generator=None)

    def test_quality_score_minus_one(self):
        result = self.analyzer.analyze("x=1", "test", "global")
        assert result["quality_score"] == -1

    def test_issues_empty(self):
        result = self.analyzer.analyze("x=1", "test", "global")
        assert result["issues"] == []

    def test_suggestions_empty(self):
        result = self.analyzer.analyze("x=1", "test", "global")
        assert result["suggestions"] == []


# ---------------------------------------------------------------------------
# 4. ReviewerLlmAnalyzer -- avec mock LLM valide
# ---------------------------------------------------------------------------

class TestReviewerLlmAnalyzerWithMock:

    def test_quality_score_extracted(self):
        analyzer = ReviewerLlmAnalyzer(_make_mock_llm(quality_score=92))
        r = analyzer.analyze("def f(): pass", "intent", "global")
        assert r["quality_score"] == 92

    def test_suggestions_extracted(self):
        analyzer = ReviewerLlmAnalyzer(_make_mock_llm(suggestions=["Utiliser pathlib"]))
        r = analyzer.analyze("import os", "intent", "global")
        assert "Utiliser pathlib" in r["suggestions"]

    def test_invalid_json_returns_neutral(self):
        analyzer = ReviewerLlmAnalyzer(_make_mock_llm(raw="ce n'est pas du json"))
        r = analyzer.analyze("x=1", "test", "global")
        assert r["quality_score"] == -1

    def test_exception_returns_neutral(self):
        analyzer = ReviewerLlmAnalyzer(_make_mock_llm(raise_exc=RuntimeError("down")))
        r = analyzer.analyze("x=1", "test", "global")
        assert r["quality_score"] == -1


# ---------------------------------------------------------------------------
# 5. Integration -- ReviewerAgent delegue correctement
# ---------------------------------------------------------------------------

class TestReviewerDelegates:

    def test_check_syntax_imported_from_validator(self):
        """_check_syntax importable depuis reviewer_agent (retrocompat)."""
        ok, _ = _check_syntax("a = 1")
        assert ok is True

    def test_build_reflection_imported_from_validator(self):
        """_build_reflection importable depuis reviewer_agent (retrocompat)."""
        r = _build_reflection(["err"])
        assert "Reviewer:" in r

    def test_analyzer_instance_created_in_init(self, bus):
        """ReviewerAgent.__init__ instancie self._analyzer."""
        agent = ReviewerAgent.create(bus=bus, llm_generator=None)
        assert hasattr(agent, "_analyzer")
        assert isinstance(agent._analyzer, ReviewerLlmAnalyzer)

    def test_analyze_with_llm_delegates_to_analyzer(self, bus):
        """_analyze_with_llm delegue a self._analyzer.analyze() (wrapper)."""
        mock_llm = _make_mock_llm(quality_score=77)
        agent = ReviewerAgent(
            card=ReviewerAgent.create(bus=bus).card,
            bus=bus,
            llm_generator=mock_llm,
        )
        result = agent._analyze_with_llm("def ok(): pass", "intent", "global")
        assert result["quality_score"] == 77

    def test_run_task_valid_code_success(self, bus):
        """run_task code valide -> AgentResult(success=True) meme apres refacto."""
        agent = ReviewerAgent.create(bus=bus, llm_generator=None)
        result = agent.run_task(_make_contract(code="x = 42"))
        assert result.success is True

    def test_run_task_invalid_code_failure(self, bus):
        """run_task code invalide -> AgentResult(success=False) meme apres refacto."""
        agent = ReviewerAgent.create(bus=bus, llm_generator=None)
        result = agent.run_task(_make_contract(code="def bad(: pass"))
        assert result.success is False
