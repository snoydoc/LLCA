# -*- coding: utf-8-sig -*-
"""
Tests V8-08 -- Integration LLMGenerator dans CoderAgent.

Regles :
- 0 dependance Ollama reelle : LLMGenerator mocke via injection.
- 0 dependance SQLite reelle : bus en memoire (:memory:).
- 10 tests couvrant :
    - _build_coder_prompt (prompt structure)
    - _format_skills_context (skills list -> str)
    - _build_patch V8-08 (generated_code -> edits)
    - CoderAgent._generate_code (llm=None, llm ok, llm invalide, llm exception)
    - CoderAgent.run_task (sans llm, avec llm, skills injected)
    - CoderAgent.create (factory sans Ollama)
    - payload "generated_code" + "llm_used" present dans AgentResult
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from core.agents.a2a_bus import A2ALocalBus, TaskContract
from core.agents.coder_agent import (
    CoderAgent,
    _build_coder_prompt,
    _build_patch,
    _format_skills_context,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus():
    b = A2ALocalBus(db_path=":memory:")
    yield b
    b.purge()


def _make_contract(intent="add a parse_json function", domain="global", task_id="t_v808"):
    return TaskContract(
        task_id=task_id,
        intent=intent,
        domain=domain,
        source_agent="architect",
        target_agent="coder",
    )


def _mock_llm(response: str = "def parse_json(s: str) -> dict:\n    return {}\n"):
    """Retourne un LLMGenerator mocke dont generate_text retourne response."""
    llm = MagicMock()
    llm.ollama = MagicMock()
    llm.ollama.model = "qwen2.5-coder:7b"
    llm.generate_text = MagicMock(return_value=response)
    return llm


# ---------------------------------------------------------------------------
# 1. _build_coder_prompt
# ---------------------------------------------------------------------------

class TestBuildCoderPrompt:
    def test_contains_domain_and_intent(self):
        prompt = _build_coder_prompt("add login", "ui", "")
        assert "Domain: ui" in prompt
        assert "Task: add login" in prompt

    def test_skills_ctx_injected_when_present(self):
        prompt = _build_coder_prompt("add login", "ui", "[skill 1] def foo(): pass")
        assert "Available skills" in prompt
        assert "[skill 1]" in prompt

    def test_no_skills_section_when_empty(self):
        prompt = _build_coder_prompt("add login", "ui", "")
        assert "Available skills" not in prompt


# ---------------------------------------------------------------------------
# 2. _format_skills_context
# ---------------------------------------------------------------------------

class TestFormatSkillsContext:
    def test_dict_skill_uses_content_key(self):
        skills = [{"content": "def foo(): pass", "id": "s1"}]
        result = _format_skills_context(skills)
        assert "def foo(): pass" in result
        assert "[skill 1]" in result

    def test_dict_skill_falls_back_to_body(self):
        skills = [{"body": "def bar(): pass"}]
        result = _format_skills_context(skills)
        assert "def bar(): pass" in result

    def test_str_skill(self):
        skills = ["def baz(): pass"]
        result = _format_skills_context(skills)
        assert "def baz(): pass" in result

    def test_max_3_skills(self):
        skills = [{"content": f"skill_{i}"} for i in range(6)]
        result = _format_skills_context(skills)
        assert "[skill 3]" in result
        assert "[skill 4]" not in result

    def test_empty_list_returns_empty(self):
        assert _format_skills_context([]) == ""


# ---------------------------------------------------------------------------
# 3. _build_patch V8-08
# ---------------------------------------------------------------------------

class TestBuildPatchV808:
    def test_generated_code_in_patch(self):
        contract = _make_contract("add parse_json", "global")
        patch = _build_patch(contract, skills=[], generated_code="def f(): pass")
        assert patch["generated_code"] == "def f(): pass"

    def test_edits_empty_when_no_code(self):
        contract = _make_contract()
        patch = _build_patch(contract, skills=[], generated_code="")
        assert patch["files"] == []

    def test_edits_contains_create_when_code_present(self):
        contract = _make_contract("add a parser", "global")
        patch = _build_patch(contract, skills=[], generated_code="def p(): pass")
        assert len(patch["files"]) == 1
        edit = patch["files"][0]
        assert edit["action"] == "create"
        assert edit["code"] == "def p(): pass"
        assert edit["path"].endswith(".py")

    def test_required_keys_present(self):
        contract = _make_contract()
        patch = _build_patch(contract, skills=[])
        for key in ("task_id", "intent", "domain", "skills", "generated_code", "files"):
            assert key in patch


# ---------------------------------------------------------------------------
# 4. CoderAgent._generate_code
# ---------------------------------------------------------------------------

class TestCoderGenerateCode:
    def test_llm_none_returns_empty(self, bus):
        coder = CoderAgent.create(bus=bus, llm_generator=None)
        result = coder._generate_code(_make_contract(), skills_ctx="")
        assert result == ""

    def test_llm_valid_code_returned(self, bus):
        valid_code = "def parse_json(s: str) -> dict:\n    return {}\n"
        coder = CoderAgent.create(bus=bus, llm_generator=_mock_llm(valid_code))
        result = coder._generate_code(_make_contract(), skills_ctx="")
        assert result == valid_code.strip()

    def test_llm_invalid_syntax_returns_empty(self, bus):
        bad_code = "def broken(:\n    pass"
        coder = CoderAgent.create(bus=bus, llm_generator=_mock_llm(bad_code))
        result = coder._generate_code(_make_contract(), skills_ctx="")
        assert result == ""

    def test_llm_exception_returns_empty(self, bus):
        llm = _mock_llm()
        llm.generate_text.side_effect = ConnectionError("Ollama down")
        coder = CoderAgent.create(bus=bus, llm_generator=llm)
        result = coder._generate_code(_make_contract(), skills_ctx="")
        assert result == ""

    def test_llm_empty_response_returns_empty(self, bus):
        coder = CoderAgent.create(bus=bus, llm_generator=_mock_llm(""))
        result = coder._generate_code(_make_contract(), skills_ctx="")
        assert result == ""


# ---------------------------------------------------------------------------
# 5. CoderAgent.run_task
# ---------------------------------------------------------------------------

class TestCoderRunTaskV808:
    def test_run_task_without_llm_still_succeeds(self, bus):
        """Mode test : llm force a None via __init__ direct (bypass auto-instanciation)."""
        from core.agents.agent_card import AgentCard, CODER_POLICY, AGENT_MCP_ALLOWLIST
        card = AgentCard(
            name="coder",
            version="8.0.0",
            capabilities=["code_generation", "ast_patching", "skill_injection", "llm_generation"],
            mcp_tools=AGENT_MCP_ALLOWLIST["coder"],
            recovery_policy=CODER_POLICY,
        )
        coder = CoderAgent(card=card, bus=bus, mcp_caller=None, llm_generator=None)
        result = coder.run_task(_make_contract())
        assert result.success is True
        assert result.payload["generated_code"] == ""
        assert result.payload["llm_used"] is False

    def test_run_task_with_llm_populates_generated_code(self, bus):
        valid_code = "def parse_json(s: str) -> dict:\n    import json\n    return json.loads(s)\n"
        coder = CoderAgent.create(bus=bus, llm_generator=_mock_llm(valid_code))
        result = coder.run_task(_make_contract("add parse_json function"))
        assert result.success is True
        assert result.payload["generated_code"] == valid_code.strip()
        assert result.payload["llm_used"] is True

    def test_run_task_payload_has_all_keys(self, bus):
        coder = CoderAgent.create(bus=bus, llm_generator=None)
        result = coder.run_task(_make_contract())
        for key in ("task_id", "patch", "edit_result", "generated_code", "skills_used", "llm_used"):
            assert key in result.payload

    def test_run_task_skills_from_context_passed_to_llm(self, bus):
        """Les skills injectes par orchestrateur (context['available_skills']) sont passes au LLM."""
        llm = _mock_llm("def f(): pass\n")
        coder = CoderAgent.create(bus=bus, llm_generator=llm)
        contract = _make_contract()
        contract.context["available_skills"] = "[skill 1] def helper(): pass"
        coder.run_task(contract)
        # generate_text doit avoir ete appele avec le contexte skill dans le prompt user
        call_args = llm.generate_text.call_args
        assert call_args is not None
        # Recupere l'argument 'user' (positionnel ou keyword)
        if call_args.kwargs.get("user"):
            user_prompt = call_args.kwargs["user"]
        elif len(call_args.args) > 1:
            user_prompt = call_args.args[1]
        else:
            user_prompt = ""
        assert "[skill 1]" in user_prompt

    def test_run_task_mcp_violation_propagates(self, bus):
        coder = CoderAgent.create(bus=bus, llm_generator=None)
        with pytest.raises(PermissionError):
            coder._call_mcp("sandbox_run", {})

    def test_create_factory_llm_none_produces_valid_agent(self, bus):
        """
        Factory avec llm_generator=None tente une auto-instanciation LLMGenerator.
        Ollama disponible -> _llm non None ; Ollama absent -> _llm None.
        Dans les deux cas le pipeline doit reussir.
        """
        coder = CoderAgent.create(bus=bus, llm_generator=None)
        assert coder is not None
        # _llm peut etre None (Ollama absent) ou LLMGenerator (Ollama present) -- les deux sont valides
        assert coder._llm is None or hasattr(coder._llm, "generate_text")
        result = coder.run_task(_make_contract())
        assert result.success is True
