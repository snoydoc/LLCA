# -*- coding: utf-8-sig -*-
"""FL-01 -- Tests reflexion structuree Tester -> Architect."""
import pytest
import time
from dataclasses import asdict
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# TestStructuredReflection
# ---------------------------------------------------------------------------

class TestStructuredReflection:
    def test_fields_present(self):
        from core.agents.tester_runner import StructuredReflection
        sr = StructuredReflection(
            sandbox_passed=False, quality_score=40,
            quality_criteria=[], stderr_short="err", fix_hints=["fix A"], iteration=1,
        )
        assert sr.sandbox_passed is False
        assert sr.quality_score == 40
        assert sr.fix_hints == ["fix A"]

    def test_to_dict_serializable(self):
        from core.agents.tester_runner import StructuredReflection
        sr = StructuredReflection(
            sandbox_passed=True, quality_score=85,
            quality_criteria=[{"name": "Type hints", "score": 15, "max": 20, "details": ""}],
            stderr_short="", fix_hints=[], iteration=0,
        )
        d = sr.to_dict()
        assert isinstance(d, dict)
        assert d["quality_score"] == 85

    def test_eval_result_none_gives_empty_hints(self):
        from core.agents.tester_runner import _build_reflection
        receipt = MagicMock()
        receipt.tests_failed = 1
        sr = _build_reflection({"success": False, "stderr": "oops"}, receipt)
        assert sr.fix_hints == []
        assert sr.quality_criteria == []
        assert sr.quality_score == 0


# ---------------------------------------------------------------------------
# TestCriteriaToFixHints
# ---------------------------------------------------------------------------

class TestCriteriaToFixHints:
    def _make_criterion(self, name, score, max_s, details=""):
        c = MagicMock()
        c.name = name
        c.score = score
        c.max = max_s
        c.details = details
        return c

    def test_full_criterion_ignored(self):
        from core.agents.tester_runner import _criteria_to_fix_hints
        c = self._make_criterion("Type hints", 20, 20)
        assert _criteria_to_fix_hints([c]) == []

    def test_type_hints_mapped(self):
        from core.agents.tester_runner import _criteria_to_fix_hints
        c = self._make_criterion("Type hints", 5, 20)
        hints = _criteria_to_fix_hints([c])
        assert any("type annotation" in h.lower() for h in hints)

    def test_max_5_hints(self):
        from core.agents.tester_runner import _criteria_to_fix_hints
        criteria = [self._make_criterion(f"X{i}", 0, 10, f"detail {i}") for i in range(10)]
        hints = _criteria_to_fix_hints(criteria)
        assert len(hints) <= 5

    def test_details_included(self):
        from core.agents.tester_runner import _criteria_to_fix_hints
        c = self._make_criterion("Anti-patterns", 0, 15, "bare_except at line 12")
        hints = _criteria_to_fix_hints([c])
        assert any("bare_except" in h for h in hints)

    def test_empty_criteria_returns_empty(self):
        from core.agents.tester_runner import _criteria_to_fix_hints
        assert _criteria_to_fix_hints([]) == []


# ---------------------------------------------------------------------------
# TestBuildReflectionEnriched
# ---------------------------------------------------------------------------

class TestBuildReflectionEnriched:
    def _make_eval_result(self, score, criteria_list):
        er = MagicMock()
        er.score = score
        er.criteria = criteria_list
        return er

    def test_with_eval_result_populates_score(self):
        from core.agents.tester_runner import _build_reflection
        receipt = MagicMock()
        receipt.tests_failed = 1
        er = self._make_eval_result(45, [])
        sr = _build_reflection({"success": False, "stderr": ""}, receipt, eval_result=er)
        assert sr.quality_score == 45

    def test_stderr_truncated_200(self):
        from core.agents.tester_runner import _build_reflection
        receipt = MagicMock()
        receipt.tests_failed = 1
        long_err = "E" * 500
        sr = _build_reflection({"success": False, "stderr": long_err}, receipt)
        assert len(sr.stderr_short) <= 200

    def test_iteration_stored(self):
        from core.agents.tester_runner import _build_reflection
        receipt = MagicMock()
        receipt.tests_failed = 0
        sr = _build_reflection({"success": True, "stderr": ""}, receipt, iteration=3)
        assert sr.iteration == 3


# ---------------------------------------------------------------------------
# TestOrchestratorContextInjection
# ---------------------------------------------------------------------------

class TestOrchestratorContextInjection:
    """Verifie que fix_hints et last_quality_score remontent dans arch_context."""

    def _make_loop(self):
        from core.agents.orchestrator_loop import KarpathyLoop
        arch = MagicMock()
        arch.run_task.return_value = MagicMock(
            success=True,
            payload={"dispatched": ["sub_001"]},
        )
        coder = MagicMock()
        coder.run_task.return_value = MagicMock(
            success=True,
            payload={"generated_code": "def f(): pass"},
        )
        reviewer = MagicMock()
        reviewer.run_task.return_value = MagicMock(success=True, payload={})
        tester_fail = MagicMock(
            success=False,
            payload={
                "quality_score": 42,
                "reflection": "err",
                "reflection_structured": {
                    "fix_hints": ["Add type hints", "Remove bare except"],
                    "quality_score": 42,
                    "sandbox_passed": False,
                    "quality_criteria": [],
                    "stderr_short": "",
                    "iteration": 0,
                },
            },
        )
        tester_ok = MagicMock(
            success=True,
            payload={"quality_score": 88, "tester_ok": True},
        )
        tester = MagicMock()
        tester.run_task.side_effect = [tester_fail, tester_ok]
        return KarpathyLoop(arch, coder, reviewer, tester, max_iterations=3, timeout_sec=3600)

    def test_fix_hints_injected_on_second_iteration(self):
        loop = self._make_loop()
        deadline = time.monotonic() + 3600
        loop.run("t001", "create a function", deadline)
        calls = loop._architect.run_task.call_args_list
        assert len(calls) >= 2
        second_ctx = calls[1][0][0].context
        assert "fix_hints" in second_ctx
        assert "Add type hints" in second_ctx["fix_hints"]

    def test_no_fix_hints_on_first_iteration(self):
        loop = self._make_loop()
        deadline = time.monotonic() + 3600
        loop.run("t001", "create a function", deadline)
        first_ctx = loop._architect.run_task.call_args_list[0][0][0].context
        assert "fix_hints" not in first_ctx

    def test_dedup_hints_across_iterations(self):
        """Deux iterations avec le meme hint -> hint deduplique."""
        from core.agents.orchestrator_loop import KarpathyLoop
        arch = MagicMock()
        arch.run_task.return_value = MagicMock(success=True, payload={"dispatched": ["s1"]})
        coder = MagicMock()
        coder.run_task.return_value = MagicMock(
            success=True, payload={"generated_code": "def f(): pass"})
        reviewer = MagicMock()
        reviewer.run_task.return_value = MagicMock(success=True, payload={})
        same_sr = {
            "fix_hints": ["Add type hints"],
            "quality_score": 30,
            "sandbox_passed": False,
            "quality_criteria": [], "stderr_short": "", "iteration": 0,
        }
        tester = MagicMock()
        tester.run_task.side_effect = [
            MagicMock(success=False, payload={"quality_score": 30, "reflection": "x",
                                               "reflection_structured": same_sr}),
            MagicMock(success=False, payload={"quality_score": 30, "reflection": "x",
                                               "reflection_structured": same_sr}),
            MagicMock(success=True,  payload={"quality_score": 80, "tester_ok": True}),
        ]
        loop = KarpathyLoop(arch, coder, reviewer, tester, max_iterations=5, timeout_sec=3600)
        loop.run("t002", "test dedup", time.monotonic() + 3600)
        third_ctx = loop._architect.run_task.call_args_list[2][0][0].context
        assert third_ctx.get("fix_hints", []).count("Add type hints") == 1


# ---------------------------------------------------------------------------
# TestCoderPromptWithHints
# ---------------------------------------------------------------------------

class TestCoderPromptWithHints:
    def test_prompt_without_hints(self):
        from core.agents.coder_builder import build_coder_prompt
        p = build_coder_prompt("create parse_json", "api", "")
        assert "Required fixes" not in p
        assert "quality score" not in p

    def test_prompt_with_hints_contains_them(self):
        from core.agents.coder_builder import build_coder_prompt
        p = build_coder_prompt(
            "create parse_json", "api", "",
            fix_hints=["Add type hints", "Remove bare except"],
            last_quality_score=45,
        )
        assert "Add type hints" in p
        assert "Remove bare except" in p
        assert "45/100" in p

    def test_prompt_no_score_when_first_iteration(self):
        from core.agents.coder_builder import build_coder_prompt
        p = build_coder_prompt("create f", "global", "", fix_hints=None, last_quality_score=None)
        assert "quality score" not in p.lower()


# ---------------------------------------------------------------------------
# TestTesterRejectPayload
# ---------------------------------------------------------------------------

class TestTesterRejectPayload:
    """Verifie que TesterAgent.run_task() inclut reflection_structured dans le payload."""

    def _make_agent(self):
        from core.agents.tester_agent import TesterAgent
        from core.agents.a2a_bus import A2ALocalBus
        bus = MagicMock(spec=A2ALocalBus)
        card = MagicMock()
        sandbox = MagicMock()
        sandbox.run.return_value = (False, "", "err", 1)
        evaluator = MagicMock()
        evaluator.evaluate.return_value = MagicMock(score=30, criteria=[])
        return TesterAgent(card=card, bus=bus, sandbox=sandbox, evaluator=evaluator)

    def _make_contract(self):
        from core.agents.a2a_bus import TaskContract
        contract = TaskContract(
            task_id="t1", intent="x", domain="global",
            source_agent="reviewer", target_agent="tester",
        )
        contract.context["code"] = "def f(): pass"
        contract.context["original_payload"] = {}
        return contract

    def test_reflection_str_retrocompat(self):
        """La cle 'reflection' reste une str pour retrocompat."""
        agent = self._make_agent()
        result = agent.run_task(self._make_contract())
        assert isinstance(result.payload.get("reflection"), str)

    def test_reflection_structured_present(self):
        """La cle 'reflection_structured' est presente et est un dict."""
        agent = self._make_agent()
        result = agent.run_task(self._make_contract())
        assert isinstance(result.payload.get("reflection_structured"), dict)

    def test_fix_hints_key_present(self):
        """La cle 'fix_hints' est presente dans le payload."""
        agent = self._make_agent()
        result = agent.run_task(self._make_contract())
        assert "fix_hints" in result.payload
        assert isinstance(result.payload["fix_hints"], list)
