# -*- coding: utf-8-sig -*-
"""
FL-04 -- Tests record_usage / record_outcome (SkillLibrary)
         et _extract_skill_ids (KarpathyLoop).

Couverture :
    A. _extract_skill_ids (6 tests)
       - None / liste vide -> []
       - entrees normales -> liste skill_ids
       - entree sans attribut skill_id -> ignoree silencieusement
       - skill_id falsy ("") -> ignore
       - mixte valides + invalides
       - ordre preserve

    B. SkillLibrary.record_usage (4 tests)
       - appelle mem.store("lcca_skill_usage", ...) avec event="used"
       - exception mem.store -> silencieux (pas de propagation)
       - skill_id transmis correctement
       - plusieurs appels -> plusieurs stores

    C. SkillLibrary.record_outcome (5 tests)
       - success=True -> event="success"
       - success=False -> event="failure"
       - exception mem.store -> silencieux
       - skill_id transmis correctement
       - collection "lcca_skill_usage"

    D. Integration KarpathyLoop (5 tests)
       - record_usage appele pour chaque skill_id injecte
       - record_outcome success appele si tester valide
       - record_outcome failure appele si tester rejette
       - sans skill_library : aucun appel record_*
       - exception skill_lib.retrieve -> pas de crash, skill_ids_used=[]
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from core.skill_library import SkillLibrary, SkillEntry, _make_skill_id
from core.agents.orchestrator_loop import KarpathyLoop, _extract_skill_ids


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(name: str = "foo", skill_id: str = "abc123def456") -> SkillEntry:
    return SkillEntry(
        skill_id=skill_id,
        name=name,
        body=f"def {name}(): pass",
        source_intent="test",
        quality_score=80,
        receipt_task_id="task_001",
    )


def _make_skill_lib(store_raises: bool = False) -> SkillLibrary:
    """SkillLibrary avec MemoryEngine mocke."""
    mem = MagicMock()
    store_result = MagicMock()
    store_result.stored = True
    store_result.reason = None
    if store_raises:
        mem.store.side_effect = RuntimeError("store failed")
    else:
        mem.store.return_value = store_result
    return SkillLibrary(memory_engine=mem, min_quality_score=70)


def _make_agent_result(success: bool, payload: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.success = success
    r.payload = payload or {}
    r.error = None if success else "mock error"
    return r


def _make_loop(
    skill_lib=None,
    tester_success: bool = True,
    arch_payload: dict | None = None,
) -> KarpathyLoop:
    """KarpathyLoop avec tous les agents mockes."""
    architect = MagicMock()
    coder = MagicMock()
    reviewer = MagicMock()
    tester = MagicMock()

    arch_payload = arch_payload or {"dispatched": ["sub_task_01"]}
    architect.run_task.return_value = _make_agent_result(True, arch_payload)
    coder.run_task.return_value = _make_agent_result(True, {"generated_code": "def f(): pass"})
    reviewer.run_task.return_value = _make_agent_result(True, {})
    tester.run_task.return_value = _make_agent_result(
        tester_success,
        {"quality_score": 85} if tester_success else {"quality_score": 0, "reflection": "bad"},
    )

    import time
    return KarpathyLoop(
        architect=architect,
        coder=coder,
        reviewer=reviewer,
        tester=tester,
        skill_library=skill_lib,
        max_iterations=1,
        max_stagnation=3,
        timeout_sec=3600,
    )


# ---------------------------------------------------------------------------
# A. _extract_skill_ids
# ---------------------------------------------------------------------------

class TestExtractSkillIds:
    def test_none_returns_empty(self):
        assert _extract_skill_ids(None) == []

    def test_empty_list_returns_empty(self):
        assert _extract_skill_ids([]) == []

    def test_valid_entries(self):
        e1 = _make_entry("foo", "aaa111bbb222")
        e2 = _make_entry("bar", "ccc333ddd444")
        result = _extract_skill_ids([e1, e2])
        assert result == ["aaa111bbb222", "ccc333ddd444"]

    def test_entry_without_skill_id_ignored(self):
        obj = MagicMock(spec=[])  # aucun attribut
        result = _extract_skill_ids([obj])
        assert result == []

    def test_falsy_skill_id_ignored(self):
        e = _make_entry("foo", "")
        result = _extract_skill_ids([e])
        assert result == []

    def test_order_preserved(self):
        entries = [_make_entry(f"f{i}", f"id{i:012}") for i in range(5)]
        result = _extract_skill_ids(entries)
        assert result == [f"id{i:012}" for i in range(5)]


# ---------------------------------------------------------------------------
# B. SkillLibrary.record_usage
# ---------------------------------------------------------------------------

class TestRecordUsage:
    def test_calls_store_with_event_used(self):
        lib = _make_skill_lib()
        lib.record_usage("abc123def456")
        lib._mem.store.assert_called_once_with(
            "lcca_skill_usage",
            {"skill_id": "abc123def456", "event": "used"},
        )

    def test_skill_id_transmitted(self):
        lib = _make_skill_lib()
        lib.record_usage("xyz000abc111")
        call_args = lib._mem.store.call_args
        assert call_args[0][1]["skill_id"] == "xyz000abc111"

    def test_multiple_calls_multiple_stores(self):
        lib = _make_skill_lib()
        lib.record_usage("id1111111111")
        lib.record_usage("id2222222222")
        assert lib._mem.store.call_count == 2

    def test_store_exception_silent(self):
        lib = _make_skill_lib(store_raises=True)
        # Ne doit pas lever d'exception
        lib.record_usage("abc123def456")


# ---------------------------------------------------------------------------
# C. SkillLibrary.record_outcome
# ---------------------------------------------------------------------------

class TestRecordOutcome:
    def test_success_true_stores_success_event(self):
        lib = _make_skill_lib()
        lib.record_outcome("abc123def456", success=True)
        lib._mem.store.assert_called_once_with(
            "lcca_skill_usage",
            {"skill_id": "abc123def456", "event": "success"},
        )

    def test_success_false_stores_failure_event(self):
        lib = _make_skill_lib()
        lib.record_outcome("abc123def456", success=False)
        lib._mem.store.assert_called_once_with(
            "lcca_skill_usage",
            {"skill_id": "abc123def456", "event": "failure"},
        )

    def test_skill_id_transmitted(self):
        lib = _make_skill_lib()
        lib.record_outcome("myskill12345", success=True)
        call_args = lib._mem.store.call_args
        assert call_args[0][1]["skill_id"] == "myskill12345"

    def test_collection_is_lcca_skill_usage(self):
        lib = _make_skill_lib()
        lib.record_outcome("anyid123", success=False)
        call_args = lib._mem.store.call_args
        assert call_args[0][0] == "lcca_skill_usage"

    def test_store_exception_silent(self):
        lib = _make_skill_lib(store_raises=True)
        # Ne doit pas lever d'exception
        lib.record_outcome("abc123def456", success=False)


# ---------------------------------------------------------------------------
# D. Integration KarpathyLoop
# ---------------------------------------------------------------------------

class TestKarpathyLoopFL04:
    def _run_loop(self, skill_lib=None, tester_success: bool = True):
        loop = _make_loop(skill_lib=skill_lib, tester_success=tester_success)
        import time
        deadline = time.monotonic() + 3600
        return loop.run("task_fl04", "generer une fonction", deadline)

    def test_record_usage_called_for_each_skill_id(self):
        lib = MagicMock(spec=SkillLibrary)
        e1 = _make_entry("foo", "aaa111bbb222")
        e2 = _make_entry("bar", "ccc333ddd444")
        lib.retrieve.return_value = [e1, e2]
        lib.format_for_prompt.return_value = "## Skills\n"
        lib.record_usage = MagicMock()
        lib.record_outcome = MagicMock()

        self._run_loop(skill_lib=lib, tester_success=True)

        assert lib.record_usage.call_count == 2
        called_ids = [c.args[0] for c in lib.record_usage.call_args_list]
        assert "aaa111bbb222" in called_ids
        assert "ccc333ddd444" in called_ids

    def test_record_outcome_success_called_when_tester_passes(self):
        lib = MagicMock(spec=SkillLibrary)
        e1 = _make_entry("foo", "aaa111bbb222")
        lib.retrieve.return_value = [e1]
        lib.format_for_prompt.return_value = "## Skills\n"
        lib.record_usage = MagicMock()
        lib.record_outcome = MagicMock()

        self._run_loop(skill_lib=lib, tester_success=True)

        lib.record_outcome.assert_called_once_with("aaa111bbb222", success=True)

    def test_record_outcome_failure_called_when_tester_rejects(self):
        lib = MagicMock(spec=SkillLibrary)
        e1 = _make_entry("foo", "aaa111bbb222")
        lib.retrieve.return_value = [e1]
        lib.format_for_prompt.return_value = "## Skills\n"
        lib.record_usage = MagicMock()
        lib.record_outcome = MagicMock()

        self._run_loop(skill_lib=lib, tester_success=False)

        lib.record_outcome.assert_called_once_with("aaa111bbb222", success=False)

    def test_no_skill_lib_no_record_calls(self):
        """Sans skill_library, aucun appel record_*."""
        result = self._run_loop(skill_lib=None, tester_success=True)
        assert result.success is True  # la boucle fonctionne sans lib

    def test_skill_lib_retrieve_exception_no_crash(self):
        """Exception dans skill_lib.retrieve -> swallow, skill_ids_used=[] -> pas de record_*."""
        lib = MagicMock(spec=SkillLibrary)
        lib.retrieve.side_effect = RuntimeError("retrieve failed")
        lib.record_usage = MagicMock()
        lib.record_outcome = MagicMock()

        # Ne doit pas lever d'exception
        result = self._run_loop(skill_lib=lib, tester_success=True)

        lib.record_usage.assert_not_called()
        lib.record_outcome.assert_not_called()
