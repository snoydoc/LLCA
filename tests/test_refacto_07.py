# -*- coding: utf-8-sig -*-
"""
Tests REFACTO-07 -- CoderBuilder : prompt + format + patch.

18 tests couvrant :
  TestBuildCoderPrompt (4)      : domain/task present, skills injectes, skills vides, structure lignes
  TestFormatSkillsContext (4)   : liste vide, 1 skill dict, 1 skill str, troncature 3 max + 200 chars
  TestBuildPatch (4)            : sans code (edits=[]), avec code (edits=[create]), champs requis, slug filename
  TestCoderBuilder (3)          : CODER_SYSTEM non vide, aliases _prives retrocompat, import direct
  TestCoderDelegates (3)        : builder appele dans run_task, _build_coder_prompt via agent,
                                  _format_skills_context via agent
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from core.agents.coder_builder import (
    CODER_SYSTEM,
    build_coder_prompt,
    format_skills_context,
    build_patch,
    _CODER_SYSTEM,
    _build_coder_prompt,
    _format_skills_context,
    _build_patch,
)
from core.agents.a2a_bus import A2ALocalBus, TaskContract


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_contract(intent: str = "add a parse_json function", task_id: str = "t_r07") -> TaskContract:
    return TaskContract(
        task_id=task_id,
        intent=intent,
        domain="api",
        source_agent="orchestrator",
        target_agent="coder",
    )


# ---------------------------------------------------------------------------
# TestBuildCoderPrompt
# ---------------------------------------------------------------------------

class TestBuildCoderPrompt:
    def test_domain_present(self):
        prompt = build_coder_prompt("add func", "api", "")
        assert "Domain: api" in prompt

    def test_task_present(self):
        prompt = build_coder_prompt("add func", "api", "")
        assert "Task: add func" in prompt

    def test_skills_injected_when_provided(self):
        prompt = build_coder_prompt("add func", "api", "skill1 content")
        assert "skill1 content" in prompt
        assert "Available skills" in prompt

    def test_skills_absent_when_empty(self):
        prompt = build_coder_prompt("add func", "api", "")
        assert "Available skills" not in prompt

    def test_output_only_instruction_present(self):
        prompt = build_coder_prompt("add func", "api", "")
        assert "Output ONLY the Python code" in prompt


# ---------------------------------------------------------------------------
# TestFormatSkillsContext
# ---------------------------------------------------------------------------

class TestFormatSkillsContext:
    def test_empty_list_returns_empty_string(self):
        assert format_skills_context([]) == ""

    def test_dict_skill_uses_content_key(self):
        skills = [{"content": "def foo(): pass"}]
        result = format_skills_context(skills)
        assert "def foo(): pass" in result
        assert "[skill 1]" in result

    def test_dict_skill_fallback_body_key(self):
        skills = [{"body": "def bar(): pass"}]
        result = format_skills_context(skills)
        assert "def bar(): pass" in result

    def test_str_skill(self):
        skills = ["def baz(): pass"]
        result = format_skills_context(skills)
        assert "def baz(): pass" in result

    def test_truncates_to_3_skills(self):
        skills = [{"content": f"skill{i}"} for i in range(5)]
        result = format_skills_context(skills)
        assert "[skill 4]" not in result
        assert "[skill 3]" in result

    def test_truncates_content_to_200_chars(self):
        long_content = "x" * 300
        skills = [{"content": long_content}]
        result = format_skills_context(skills)
        # 200 chars max + "[skill 1] " prefix
        assert len(result) <= 215


# ---------------------------------------------------------------------------
# TestBuildPatch
# ---------------------------------------------------------------------------

class TestBuildPatch:
    def test_no_code_gives_empty_edits(self):
        contract = _make_contract()
        patch = build_patch(contract, [], generated_code="")
        assert patch["files"] == []  # FIX-EDITBATCH-01 : "edits" renomme en "files"

    def test_with_code_gives_create_edit(self):
        contract = _make_contract()
        patch = build_patch(contract, [], generated_code="def foo(): pass")
        assert len(patch["files"]) == 1
        assert patch["files"][0]["action"] == "create"  # FIX-EDITBATCH-01 : "mode" -> "action"

    def test_required_fields_present(self):
        contract = _make_contract()
        patch = build_patch(contract, [], "")
        for key in ("task_id", "intent", "domain", "skills", "generated_code", "files", "context", "constraints"):
            assert key in patch  # FIX-EDITBATCH-01 : "edits" -> "files"

    def test_slug_filename_in_workspace(self):
        contract = _make_contract(intent="add a parse json function")
        patch = build_patch(contract, [], generated_code="def foo(): pass")
        filename = patch["files"][0]["path"]  # FIX-EDITBATCH-01 : "edits"->"files", "file"->"path"
        assert filename.endswith(".py")

    def test_generated_code_stored_in_patch(self):
        contract = _make_contract()
        code = "def hello(): return 42"
        patch = build_patch(contract, [], code)
        assert patch["generated_code"] == code


# ---------------------------------------------------------------------------
# TestCoderBuilder
# ---------------------------------------------------------------------------

class TestCoderBuilder:
    def test_coder_system_not_empty(self):
        assert CODER_SYSTEM and len(CODER_SYSTEM) > 20

    def test_private_aliases_retrocompat(self):
        """Les alias _ doivent pointer vers les memes fonctions."""
        assert _CODER_SYSTEM == CODER_SYSTEM
        assert _build_coder_prompt is build_coder_prompt
        assert _format_skills_context is format_skills_context
        assert _build_patch is build_patch

    def test_import_direct_depuis_coder_agent(self):
        """coder_agent doit re-exporter les symboles depuis coder_builder."""
        from core.agents.coder_agent import (
            _CODER_SYSTEM as CS,
            _build_coder_prompt as BP,
            _format_skills_context as FS,
            _build_patch as BPatch,
        )
        assert CS == CODER_SYSTEM
        assert BP is build_coder_prompt
        assert FS is format_skills_context
        assert BPatch is build_patch


# ---------------------------------------------------------------------------
# TestCoderDelegates
# ---------------------------------------------------------------------------

class TestCoderDelegates:
    """Verifie que CoderAgent delegue bien vers coder_builder."""

    def _make_agent(self):
        from core.agents.coder_agent import CoderAgent
        from core.agents.agent_card import AgentCard, AGENT_MCP_ALLOWLIST
        from core.agents.agent_card import CODER_POLICY

        bus = MagicMock(spec=A2ALocalBus)
        mcp = MagicMock(return_value={"results": []})
        card = AgentCard(
            name="coder",
            version="8.0.0",
            capabilities=["code_generation"],
            mcp_tools=AGENT_MCP_ALLOWLIST["coder"],
            recovery_policy=CODER_POLICY,
            description="test",
        )
        agent = CoderAgent(card=card, bus=bus, mcp_caller=mcp, llm_generator=None)
        return agent, mcp

    def test_build_coder_prompt_called_via_agent(self):
        agent, _ = self._make_agent()
        contract = _make_contract()
        with patch("core.agents.coder_agent._build_coder_prompt", wraps=_build_coder_prompt) as mock_bp:
            # llm=None => _build_coder_prompt pas appele (pas de LLM)
            # on verifie juste que l'import est correct (pas d'erreur)
            result = agent._generate_code(contract, "")
            assert result == ""  # llm=None -> stub vide

    def test_format_skills_context_called_in_run_task(self):
        agent, mcp = self._make_agent()
        contract = _make_contract()
        with patch("core.agents.coder_agent._format_skills_context", wraps=_format_skills_context) as mock_fs:
            agent.run_task(contract)
            mock_fs.assert_called_once()

    def test_build_patch_called_in_run_task(self):
        agent, mcp = self._make_agent()
        contract = _make_contract()
        with patch("core.agents.coder_agent._build_patch", wraps=_build_patch) as mock_bp:
            agent.run_task(contract)
            mock_bp.assert_called_once()
