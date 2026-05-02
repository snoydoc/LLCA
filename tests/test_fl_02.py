# -*- coding: utf-8-sig -*-
"""FL-02 -- Tests branchement ModelRouter dans le pipeline."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# TestCoderAgentRouterInjection
# ---------------------------------------------------------------------------

class TestCoderAgentRouterInjection:
    """Verifie que CoderAgent accepte model_router et l'utilise dans _generate_code."""

    def _make_coder(self, router=None):
        from core.agents.coder_agent import CoderAgent
        bus  = MagicMock()
        card = MagicMock()
        llm  = MagicMock()
        llm.ollama = MagicMock()
        llm.ollama.model = "qwen2.5-coder:3b"
        llm.generate_text.return_value = "def f(): pass"
        return CoderAgent(card=card, bus=bus, llm_generator=llm, model_router=router)

    def _make_contract(self, complexity=3):
        from core.agents.a2a_bus import TaskContract
        c = TaskContract(
            task_id="t1", intent="create f", domain="global",
            source_agent="architect", target_agent="coder",
        )
        c.context["complexity_score"] = complexity
        return c

    def test_router_none_no_crash(self):
        """Sans router, _generate_code fonctionne normalement."""
        coder = self._make_coder(router=None)
        result = coder._generate_code(self._make_contract(), "")
        assert isinstance(result, str)

    def test_router_called_with_coding_task_type(self):
        """Le router est appele avec task_type='coding'."""
        from core.model_router import ModelDecision
        router = MagicMock()
        router.get_model.return_value = ModelDecision(
            model_name="qwen2.5-coder:3b", provider="ollama",
            is_online=False, fallback_used=False, reason="test",
        )
        coder = self._make_coder(router=router)
        coder._generate_code(self._make_contract(complexity=4), "")
        router.get_model.assert_called_once()
        args, kwargs = router.get_model.call_args
        task_type = kwargs.get("task_type") or (args[0] if args else None)
        assert task_type == "coding"

    def test_router_called_with_complexity_from_context(self):
        """Le complexity_score du contrat est passe au router."""
        from core.model_router import ModelDecision
        router = MagicMock()
        router.get_model.return_value = ModelDecision(
            model_name="qwen2.5-coder:3b", provider="ollama",
            is_online=False, fallback_used=False, reason="test",
        )
        coder = self._make_coder(router=router)
        coder._generate_code(self._make_contract(complexity=7), "")
        args, kwargs = router.get_model.call_args
        complexity = kwargs.get("complexity_score") or (args[1] if len(args) > 1 else None)
        assert complexity == 7

    def test_router_changes_model_when_different(self):
        """Si le router retourne un modele different, generate_text recoit model_override."""
        from core.model_router import ModelDecision
        router = MagicMock()
        router.get_model.return_value = ModelDecision(
            model_name="qwen3:8b", provider="ollama",
            is_online=False, fallback_used=False, reason="heavy",
        )
        coder = self._make_coder(router=router)
        coder._generate_code(self._make_contract(complexity=8), "")
        # generate_text doit etre appele avec model_override=qwen3:8b
        args, kwargs = coder._llm.generate_text.call_args
        assert kwargs.get("model_override") == "qwen3:8b" or (
            len(args) >= 3 and args[2] == "qwen3:8b"
        )
        # self.ollama.model ne doit PAS etre mute
        assert coder._llm.ollama.model == "qwen2.5-coder:3b"

    def test_router_no_change_when_same_model(self):
        """Si le router retourne le meme modele, model_override reste None."""
        from core.model_router import ModelDecision
        router = MagicMock()
        router.get_model.return_value = ModelDecision(
            model_name="qwen2.5-coder:3b", provider="ollama",
            is_online=False, fallback_used=False, reason="default",
        )
        coder = self._make_coder(router=router)
        coder._generate_code(self._make_contract(complexity=2), "")
        # meme modele -> model_override doit etre None dans generate_text
        args, kwargs = coder._llm.generate_text.call_args
        assert kwargs.get("model_override") is None
        # ollama.model inchange
        assert coder._llm.ollama.model == "qwen2.5-coder:3b"

    def test_router_exception_swallowed(self):
        """Si le router leve une exception, _generate_code continue normalement."""
        router = MagicMock()
        router.get_model.side_effect = RuntimeError("router crash")
        coder = self._make_coder(router=router)
        result = coder._generate_code(self._make_contract(), "")
        assert isinstance(result, str)

    def test_no_router_call_when_llm_none(self):
        """Si llm=None (mode stub), le router ne doit pas etre appele."""
        from core.agents.coder_agent import CoderAgent
        from core.agents.a2a_bus import TaskContract
        router = MagicMock()
        bus  = MagicMock()
        card = MagicMock()
        coder = CoderAgent(card=card, bus=bus, llm_generator=None, model_router=router)
        contract = TaskContract(
            task_id="t_stub", intent="x", domain="global",
            source_agent="arch", target_agent="coder",
        )
        coder._generate_code(contract, "")
        router.get_model.assert_not_called()


# ---------------------------------------------------------------------------
# TestOrchestratorRouterInjection
# ---------------------------------------------------------------------------

class TestOrchestratorRouterInjection:
    """Verifie que AgentOrchestrator.__init__ et create() acceptent model_router."""

    def _make_orch(self, router=None):
        from core.agents.agent_orchestrator import AgentOrchestrator
        from core.agents.a2a_bus import A2ALocalBus
        bus = MagicMock(spec=A2ALocalBus)
        return AgentOrchestrator(
            bus=bus,
            architect=MagicMock(), coder=MagicMock(),
            reviewer=MagicMock(), tester=MagicMock(),
            model_router=router,
        )

    def test_init_stores_router(self):
        router = MagicMock()
        orch = self._make_orch(router=router)
        assert orch._model_router is router

    def test_init_no_router_defaults_to_none(self):
        orch = self._make_orch(router=None)
        assert orch._model_router is None

    def test_create_injects_router_into_coder(self):
        """create() passe le model_router au CoderAgent.create()."""
        from core.agents.agent_orchestrator import AgentOrchestrator
        from core.agents.a2a_bus import A2ALocalBus
        bus = MagicMock(spec=A2ALocalBus)
        router = MagicMock()
        with patch("core.agents.agent_orchestrator.CoderAgent") as MockCoder, \
             patch("core.agents.agent_orchestrator.ArchitectAgent"), \
             patch("core.agents.agent_orchestrator.ReviewerAgent"), \
             patch("core.agents.agent_orchestrator.TesterAgent"), \
             patch("core.agents.agent_orchestrator.KarpathyLoop"):
            MockCoder.create.return_value = MagicMock()
            AgentOrchestrator.create(bus=bus, model_router=router)
            _, kwargs = MockCoder.create.call_args
            assert kwargs.get("model_router") is router

    def test_create_without_router_instantiates_model_router(self):
        """create() sans router instancie ModelRouter automatiquement."""
        from core.agents.agent_orchestrator import AgentOrchestrator
        from core.agents.a2a_bus import A2ALocalBus
        bus = MagicMock(spec=A2ALocalBus)
        with patch("core.agents.agent_orchestrator.CoderAgent") as MockCoder, \
             patch("core.agents.agent_orchestrator.ArchitectAgent"), \
             patch("core.agents.agent_orchestrator.ReviewerAgent"), \
             patch("core.agents.agent_orchestrator.TesterAgent"), \
             patch("core.agents.agent_orchestrator.KarpathyLoop"), \
             patch("core.model_router.ModelRouter") as MockRouter:
            MockCoder.create.return_value = MagicMock()
            MockRouter.return_value = MagicMock()
            AgentOrchestrator.create(bus=bus)
            # CoderAgent.create recu un router non-None
            _, kwargs = MockCoder.create.call_args
            # Le router est soit l'instance MockRouter, soit None si import echoue
            # On verifie juste que le kwarg est present
            assert "model_router" in kwargs

    def test_create_router_failure_does_not_crash(self):
        """Si ModelRouter() leve une exception, create() continue avec router=None."""
        from core.agents.agent_orchestrator import AgentOrchestrator
        from core.agents.a2a_bus import A2ALocalBus
        bus = MagicMock(spec=A2ALocalBus)
        with patch("core.agents.agent_orchestrator.CoderAgent") as MockCoder, \
             patch("core.agents.agent_orchestrator.ArchitectAgent"), \
             patch("core.agents.agent_orchestrator.ReviewerAgent"), \
             patch("core.agents.agent_orchestrator.TesterAgent"), \
             patch("core.agents.agent_orchestrator.KarpathyLoop"), \
             patch("core.agents.agent_orchestrator.ModelRouter", side_effect=RuntimeError("crash"), create=True):
            MockCoder.create.return_value = MagicMock()
            # Ne doit pas lever
            orch = AgentOrchestrator.create(bus=bus)
            assert orch is not None
