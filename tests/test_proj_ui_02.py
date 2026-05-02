# -*- coding: utf-8-sig -*-
"""
test_proj_ui_02.py — PROJ-UI-02 : InspirationEngine

Tests unitaires sur _tool_inspiration_generate et ses helpers :
- _inspiration_fallback : 3 templates, structure, types
- _inspiration_call_llm : parsing JSON, normalisation, erreurs
- _tool_inspiration_generate : routage LLM→fallback, keyword, output

Suite : 10 tests
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.mcp_handlers_projects import McpHandlersProjects


# ── Fixture minimale (mixin pur, pas d'__init__) ────────────────────────────

class _ConcreteHandler(McpHandlersProjects):
    """Implémentation minimale testable du mixin."""
    pass


def _make_handler() -> _ConcreteHandler:
    h = _ConcreteHandler()
    h._project_manager = None
    h._project_lock    = None
    h._project_orch    = None
    return h


# ── TestFallback ──────────────────────────────────────────────────────────────

class TestInspirationFallback:

    def test_fallback_returns_3_ideas(self):
        ideas = McpHandlersProjects._inspiration_fallback("robotique")
        assert len(ideas) == 3

    def test_fallback_structure(self):
        ideas = McpHandlersProjects._inspiration_fallback("audio")
        required = {"title", "description", "domain", "tech_stack",
                    "difficulty", "estimated_sprints", "tags", "quality_score"}
        for idea in ideas:
            assert required <= set(idea.keys()), f"Cles manquantes : {required - set(idea.keys())}"

    def test_fallback_types(self):
        ideas = McpHandlersProjects._inspiration_fallback("iot")
        for idea in ideas:
            assert isinstance(idea["title"], str)
            assert isinstance(idea["tech_stack"], list)
            assert isinstance(idea["estimated_sprints"], int)
            assert isinstance(idea["quality_score"], float)
            assert isinstance(idea["tags"], list)

    def test_fallback_difficulty_values(self):
        ideas = McpHandlersProjects._inspiration_fallback("data")
        valid = {"debutant", "intermediaire", "avance"}
        difficulties = {idea["difficulty"] for idea in ideas}
        assert difficulties <= valid

    def test_fallback_keyword_in_domain(self):
        ideas = McpHandlersProjects._inspiration_fallback("SECURITE")
        for idea in ideas:
            assert "securite" in idea["domain"].lower()


# ── TestCallLlm ──────────────────────────────────────────────────────────────

class TestInspirationCallLlm:

    def _fake_gen(self, raw_output: str):
        """Cree un mock LLMGenerator.generate_text retournant raw_output."""
        mock = MagicMock()
        mock.generate_text.return_value = raw_output
        return mock

    def test_call_llm_parses_clean_json(self):
        h = _make_handler()
        ideas_raw = [
            {"title": "Idea 1", "description": "Desc 1", "domain": "test",
             "tech_stack": ["Python"], "difficulty": "debutant",
             "estimated_sprints": 5, "tags": ["t1"], "quality_score": 0.75},
            {"title": "Idea 2", "description": "Desc 2", "domain": "test",
             "tech_stack": ["Go"], "difficulty": "intermediaire",
             "estimated_sprints": 8, "tags": ["t2"], "quality_score": 0.72},
            {"title": "Idea 3", "description": "Desc 3", "domain": "test",
             "tech_stack": ["Rust"], "difficulty": "avance",
             "estimated_sprints": 12, "tags": ["t3"], "quality_score": 0.70},
        ]
        fake = self._fake_gen(json.dumps(ideas_raw))
        with patch("core.llm_generator.LLMGenerator", return_value=fake):
            result = h._inspiration_call_llm("test")
        assert len(result) == 3
        assert result[0]["title"] == "Idea 1"

    def test_call_llm_strips_markdown_fence(self):
        h = _make_handler()
        raw = "```json\n[{\"title\":\"T\",\"description\":\"D\",\"domain\":\"x\",\"tech_stack\":[],\"difficulty\":\"debutant\",\"estimated_sprints\":4,\"tags\":[],\"quality_score\":0.7}]\n```"
        fake = self._fake_gen(raw)
        with patch("core.llm_generator.LLMGenerator", return_value=fake):
            result = h._inspiration_call_llm("x")
        assert result[0]["title"] == "T"

    def test_call_llm_raises_if_not_list(self):
        h = _make_handler()
        fake = self._fake_gen('{"error": "oops"}')
        with patch("core.llm_generator.LLMGenerator", return_value=fake):
            with pytest.raises(ValueError, match="liste"):
                h._inspiration_call_llm("x")

    def test_call_llm_normalizes_missing_fields(self):
        h = _make_handler()
        # Objet minimal — champs manquants completes par defaut
        raw = json.dumps([{"title": "Minimal"}])
        fake = self._fake_gen(raw)
        with patch("core.llm_generator.LLMGenerator", return_value=fake):
            result = h._inspiration_call_llm("test")
        assert result[0]["difficulty"] == "intermediaire"
        assert result[0]["estimated_sprints"] == 8
        assert result[0]["quality_score"] == 0.70


# ── TestToolInspirationGenerate ───────────────────────────────────────────────

class TestToolInspirationGenerate:

    def test_keyword_required(self):
        h = _make_handler()
        with pytest.raises(ValueError, match="keyword"):
            h._tool_inspiration_generate({})

    def test_keyword_empty_raises(self):
        h = _make_handler()
        with pytest.raises(ValueError):
            h._tool_inspiration_generate({"keyword": "   "})

    def test_llm_success_returns_source_llm(self):
        h = _make_handler()
        fake_ideas = [
            {"title": "A", "description": "D", "domain": "d",
             "tech_stack": [], "difficulty": "debutant",
             "estimated_sprints": 3, "tags": [], "quality_score": 0.7},
        ]
        with patch.object(h, "_inspiration_call_llm", return_value=fake_ideas):
            result = h._tool_inspiration_generate({"keyword": "medical"})
        assert result["source"] == "llm"
        assert result["keyword"] == "medical"
        assert len(result["ideas"]) == 1

    def test_llm_failure_falls_back(self):
        h = _make_handler()
        with patch.object(h, "_inspiration_call_llm", side_effect=RuntimeError("Ollama down")):
            result = h._tool_inspiration_generate({"keyword": "audio"})
        assert result["source"] == "fallback"
        assert len(result["ideas"]) == 3

    def test_keyword_truncated_at_120(self):
        h = _make_handler()
        long_kw = "x" * 200
        with patch.object(h, "_inspiration_call_llm", return_value=[]):
            # LLM retourne [] -> ValueError -> fallback active
            # On patche la classe (staticmethod) pour capter l'appel
            with patch.object(McpHandlersProjects, "_inspiration_fallback", return_value=[]) as mock_fb:
                h._tool_inspiration_generate({"keyword": long_kw})
                called_kw = mock_fb.call_args[0][0]
                assert len(called_kw) == 120
