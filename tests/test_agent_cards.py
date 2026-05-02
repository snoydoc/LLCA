# -*- coding: utf-8-sig -*-
"""
Tests Sprint V8-02 -- AgentCard + RecoveryPolicy + AgentRegistry.
10 tests. Aucune dependance externe (pas d'Ollama, pas de SQLite).
"""

import pytest

from core.agents.agent_card import (
    AgentCard,
    AgentRegistry,
    RecoveryPolicy,
    AGENT_MCP_ALLOWLIST,
    CODER_POLICY,
    TESTER_POLICY,
)


# ===========================================================================
# TestRecoveryPolicy
# ===========================================================================
class TestRecoveryPolicy:
    def test_should_retry_on_matching_error(self):
        """SyntaxError + coder policy (on_failure=rollback, retry_conditions=[SyntaxError])
        -> mais CODER_POLICY est rollback donc should_retry doit retourner False.
        On teste un policy retry explicite."""
        policy = RecoveryPolicy(
            max_retries=2,
            on_failure="retry",
            retry_conditions=["SyntaxError"],
        )
        assert policy.should_retry("SyntaxError", attempt=0) is True

    def test_no_retry_if_max_reached(self):
        """attempt >= max_retries -> False meme si l'erreur est dans retry_conditions."""
        policy = RecoveryPolicy(
            max_retries=2,
            on_failure="retry",
            retry_conditions=["SyntaxError"],
        )
        assert policy.should_retry("SyntaxError", attempt=2) is False

    def test_rollback_policy_never_retries(self):
        """on_failure='rollback' -> should_retry toujours False."""
        assert CODER_POLICY.should_retry("SyntaxError", attempt=0) is False

    def test_invalid_on_failure_raises(self):
        """Une valeur inconnue de on_failure doit lever AssertionError."""
        with pytest.raises(AssertionError):
            RecoveryPolicy(on_failure="give_up")

    def test_to_dict_has_all_fields(self):
        """to_dict() doit contenir les 5 cles attendues."""
        d = TESTER_POLICY.to_dict()
        assert set(d.keys()) == {
            "max_retries", "retry_delay_sec", "fallback_agent",
            "on_failure", "retry_conditions",
        }
        assert d["on_failure"] == "retry"
        assert "Timeout" in d["retry_conditions"]


# ===========================================================================
# TestAgentCard
# ===========================================================================
class TestAgentCard:
    def _make_architect_card(self) -> AgentCard:
        return AgentCard(
            name="architect",
            version="8.0.0",
            capabilities=["planning", "decomposition", "memory_search"],
            mcp_tools=AGENT_MCP_ALLOWLIST["architect"],
            recovery_policy=RecoveryPolicy(max_retries=2, on_failure="escalate"),
        )

    def test_agent_card_to_dict(self):
        """to_dict() doit exposer tous les champs attendus."""
        card = self._make_architect_card()
        d = card.to_dict()
        assert d["name"] == "architect"
        assert d["version"] == "8.0.0"
        assert "planning" in d["capabilities"]
        assert isinstance(d["mcp_tools"], list)  # sorted() -> list
        assert "recovery_policy" in d

    def test_unknown_agent_raises(self):
        """Un nom d'agent hors AGENT_MCP_ALLOWLIST doit lever AssertionError."""
        with pytest.raises(AssertionError):
            AgentCard(
                name="ghost_agent",
                version="8.0.0",
                capabilities=["planning"],
                mcp_tools=frozenset(),
                recovery_policy=RecoveryPolicy(),
            )

    def test_unknown_capability_raises(self):
        """Une capability inconnue doit lever AssertionError."""
        with pytest.raises(AssertionError):
            AgentCard(
                name="architect",
                version="8.0.0",
                capabilities=["fly_to_the_moon"],
                mcp_tools=AGENT_MCP_ALLOWLIST["architect"],
                recovery_policy=RecoveryPolicy(),
            )

    def test_can_use_tool(self):
        """architect peut utiliser generate_spec mais pas sandbox_run."""
        card = self._make_architect_card()
        assert card.can_use_tool("generate_spec") is True
        assert card.can_use_tool("sandbox_run") is False


# ===========================================================================
# TestAgentRegistry
# ===========================================================================
class TestAgentRegistry:
    def test_default_registry_has_5_agents(self):
        """AgentRegistry.default() doit enregistrer exactement 5 agents."""
        registry = AgentRegistry.default()
        agents = registry.all_agents()
        assert len(agents) == 5
        for name in ("architect", "coder", "reviewer", "tester", "observer"):
            assert name in agents

    def test_registry_can_use_tool(self):
        """architect peut 'memory_search', coder ne peut pas 'sandbox_run'."""
        registry = AgentRegistry.default()
        assert registry.can_use_tool("architect", "memory_search") is True
        assert registry.can_use_tool("coder", "sandbox_run") is False

    def test_registry_get_unknown_returns_none(self):
        """get() sur un nom inconnu retourne None sans lever d'exception."""
        registry = AgentRegistry.default()
        assert registry.get("ghost") is None

    def test_registry_can_use_tool_unknown_agent_returns_false(self):
        """can_use_tool() sur un agent inexistant retourne False (safe)."""
        registry = AgentRegistry.default()
        assert registry.can_use_tool("unknown_agent", "edit_batch") is False
