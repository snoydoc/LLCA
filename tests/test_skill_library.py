# -*- coding: utf-8-sig -*-
"""
Tests Sprint V8-05 -- SkillLibrary

Couverture :
    A. Helpers module-level (4 tests)
        - _make_skill_id
        - _truncate_body (court / long)
        - extract_top_level (valide / invalide / vide / imbriquee)
    B. SkillLibrary.extract_and_store (4 tests)
        - receipt invalide -> aucun stockage
        - quality_score sous seuil -> skip
        - code sans top-level -> []
        - code valide -> stored_ids non vides
    C. SkillLibrary.retrieve (3 tests)
        - memory_engine non disponible -> []
        - resultats normalises en SkillEntry
        - max_per_prompt respecte
    D. SkillLibrary.format_for_prompt (3 tests)
        - liste vide -> ""
        - format attendu (## Skill: + ```python)
        - troncature body dans le prompt
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest

from core.skill_library import (
    SkillEntry,
    SkillLibrary,
    _make_skill_id,
    _truncate_body,
    extract_top_level,
)
from core.receipt_store import ExecutionReceipt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _valid_receipt(task_id: str = "task_abc") -> ExecutionReceipt:
    """Cree et signe un receipt valide."""
    from core.receipt_store import sign_receipt
    output_hash = "hash_out_001"
    return ExecutionReceipt(
        task_id=task_id,
        agent="tester",
        input_hash="hash_in_001",
        output_hash=output_hash,
        sandbox_passed=True,
        tests_passed=1,
        tests_failed=0,
        tx_id=None,
        signature=sign_receipt(task_id, output_hash),
    )


def _tampered_receipt() -> ExecutionReceipt:
    """Receipt dont la signature ne correspond pas."""
    r = _valid_receipt()
    r.signature = "deadbeef00000000000000000000000000000000000000000000000000000000"
    return r


_SIMPLE_CODE = (
    "def add(a, b):\n"
    "    return a + b\n"
    "\n"
    "class Foo:\n"
    "    pass\n"
)

_NESTED_CODE = (
    "def outer():\n"
    "    def inner():\n"
    "        pass\n"
)


# ---------------------------------------------------------------------------
# A. Helpers module-level
# ---------------------------------------------------------------------------

class TestMakeSkillId:
    def test_is_12_chars(self):
        sid = _make_skill_id("def foo(): pass")
        assert len(sid) == 12

    def test_deterministic(self):
        body = "def bar():\n    return 42\n"
        assert _make_skill_id(body) == _make_skill_id(body)

    def test_different_bodies(self):
        assert _make_skill_id("a") != _make_skill_id("b")


class TestTruncateBody:
    def test_short_body_unchanged(self):
        body = "def f():\n    return 1\n"
        assert _truncate_body(body, max_lines=10) == body

    def test_long_body_truncated(self):
        body = "\n".join([f"line_{i}" for i in range(30)])
        result = _truncate_body(body, max_lines=5)
        lines = result.splitlines()
        # 5 lignes + 1 ligne "# ..."
        assert len(lines) == 6
        assert lines[-1] == "# ..."

    def test_exact_max_lines_not_truncated(self):
        body = "\n".join([f"x_{i}" for i in range(5)])
        result = _truncate_body(body, max_lines=5)
        assert "# ..." not in result


class TestExtractTopLevel:
    def test_extracts_function_and_class(self):
        result = extract_top_level(_SIMPLE_CODE)
        names = [name for name, _ in result]
        assert "add" in names
        assert "Foo" in names

    def test_invalid_syntax_returns_empty(self):
        assert extract_top_level("def broken(:\n    pass") == []

    def test_empty_code_returns_empty(self):
        assert extract_top_level("") == []
        assert extract_top_level("   \n  ") == []

    def test_nested_function_not_extracted(self):
        result = extract_top_level(_NESTED_CODE)
        names = [name for name, _ in result]
        assert "outer" in names
        # "inner" a col_offset != 0 -> non extrait
        assert "inner" not in names


# ---------------------------------------------------------------------------
# B. SkillLibrary.extract_and_store
# ---------------------------------------------------------------------------

class TestExtractAndStore:
    def _make_lib(self, mem_available=True, stored=True):
        """SkillLibrary avec MemoryEngine mocke."""
        mem = MagicMock()
        mem.is_available = mem_available
        store_result = MagicMock()
        store_result.stored = stored
        store_result.reason = None if stored else "unavailable"
        mem.store.return_value = store_result
        return SkillLibrary(memory_engine=mem, min_quality_score=70)

    def test_invalid_receipt_stores_nothing(self):
        lib = self._make_lib()
        ids = lib.extract_and_store(
            _SIMPLE_CODE, _tampered_receipt(), quality_score=90
        )
        assert ids == []
        lib._mem.store.assert_not_called()

    def test_low_quality_score_skips(self):
        lib = self._make_lib()
        ids = lib.extract_and_store(
            _SIMPLE_CODE, _valid_receipt(), quality_score=50
        )
        assert ids == []
        lib._mem.store.assert_not_called()

    def test_code_without_top_level_returns_empty(self):
        lib = self._make_lib()
        simple_expr = "x = 1\ny = 2\n"
        ids = lib.extract_and_store(simple_expr, _valid_receipt(), quality_score=80)
        assert ids == []

    def test_valid_code_stores_skills(self):
        lib = self._make_lib(stored=True)
        ids = lib.extract_and_store(
            _SIMPLE_CODE, _valid_receipt(), source_intent="math ops", quality_score=85
        )
        # add + Foo -> 2 skills
        assert len(ids) == 2
        assert lib._mem.store.call_count == 2
        # Verifier que "lcca_skills" est la collection ciblee
        call_args = lib._mem.store.call_args_list[0]
        assert call_args[0][0] == "lcca_skills"


# ---------------------------------------------------------------------------
# C. SkillLibrary.retrieve
# ---------------------------------------------------------------------------

class TestRetrieve:
    def _make_mem_with_skills(self, entries):
        """Cree un MemoryEngine mock retournant `entries` sous 'skills'."""
        from core.memory_engine import MemoryEntry
        mem = MagicMock()
        mem.is_available = True
        mem.search.return_value = {
            "solutions": [], "failures": [], "context": [], "specs": [], "skills": entries
        }
        return mem

    def test_empty_when_no_skills(self):
        mem = self._make_mem_with_skills([])
        lib = SkillLibrary(memory_engine=mem)
        assert lib.retrieve("anything") == []

    def test_returns_skill_entries(self):
        from core.memory_engine import MemoryEntry
        fake = MemoryEntry(
            id="sk1",
            collection="lcca_skills",
            content="def foo(): pass",
            metadata={"name": "foo", "skill_id": "abc123def456", "quality_score": "85",
                      "source_intent": "test", "receipt_task_id": "task_01"},
        )
        mem = self._make_mem_with_skills([fake])
        lib = SkillLibrary(memory_engine=mem)
        result = lib.retrieve("foo function")
        assert len(result) == 1
        assert isinstance(result[0], SkillEntry)
        assert result[0].name == "foo"
        assert result[0].quality_score == 85

    def test_max_per_prompt_respected(self):
        from core.memory_engine import MemoryEntry
        entries = [
            MemoryEntry(id=f"sk{i}", collection="lcca_skills", content=f"def f{i}(): pass",
                        metadata={"name": f"f{i}", "skill_id": f"id{i:012}", "quality_score": "80",
                                  "source_intent": "", "receipt_task_id": "t"})
            for i in range(10)
        ]
        mem = self._make_mem_with_skills(entries)
        lib = SkillLibrary(memory_engine=mem, max_per_prompt=2)
        result = lib.retrieve("anything")
        assert len(result) <= 2


# ---------------------------------------------------------------------------
# D. SkillLibrary.format_for_prompt
# ---------------------------------------------------------------------------

class TestFormatForPrompt:
    def _entry(self, name="foo", body="def foo(): pass", score=80) -> SkillEntry:
        return SkillEntry(
            skill_id=_make_skill_id(body),
            name=name,
            body=body,
            source_intent="test",
            quality_score=score,
            receipt_task_id="task_001",
        )

    def test_empty_list_returns_empty_string(self):
        lib = SkillLibrary.__new__(SkillLibrary)
        lib._max_per_prompt = 3
        lib._max_body_lines = 20
        assert lib.format_for_prompt([]) == ""

    def test_format_contains_skill_header(self):
        lib = SkillLibrary.__new__(SkillLibrary)
        lib._max_per_prompt = 3
        lib._max_body_lines = 20
        entry = self._entry("my_func", "def my_func(): return 42", 90)
        result = lib.format_for_prompt([entry])
        assert "## Skill: my_func" in result
        assert "score=90" in result
        assert "```python" in result

    def test_body_truncated_in_prompt(self):
        long_body = "\n".join([f"    x_{i} = {i}" for i in range(40)])
        body = "def big_func():\n" + long_body
        lib = SkillLibrary.__new__(SkillLibrary)
        lib._max_per_prompt = 3
        lib._max_body_lines = 5
        entry = self._entry("big_func", body, 75)
        result = lib.format_for_prompt([entry])
        assert "# ..." in result


# ---------------------------------------------------------------------------
# E. SkillEntry champs ED-03 (source_type, commit_hash)
# ---------------------------------------------------------------------------

class TestSkillEntryED03:
    def test_source_type_default_internal(self):
        entry = SkillEntry(
            skill_id="abc123def456", name="foo",
            body="def foo(): pass", source_intent="test",
            quality_score=80, receipt_task_id="t1",
        )
        assert entry.source_type == "internal"
        assert entry.commit_hash == ""

    def test_roundtrip_with_new_fields(self):
        entry = SkillEntry(
            skill_id="abc123def456", name="bar",
            body="def bar(): pass", source_intent="ext",
            quality_score=90, receipt_task_id="t2",
            source_type="external", commit_hash="abc123def456",
        )
        d = entry.to_dict()
        restored = SkillEntry.from_dict(d)
        assert restored.source_type == "external"
        assert restored.commit_hash == "abc123def456"

    def test_from_dict_legacy_compat(self):
        """Dict sans source_type/commit_hash (format pre-ED-03) doit fonctionner."""
        d = {
            "skill_id": "s3", "name": "baz", "body": "def baz(): pass",
            "source_intent": "old", "quality_score": 75, "receipt_task_id": "t3",
        }
        entry = SkillEntry.from_dict(d)
        assert entry.source_type == "internal"
        assert entry.commit_hash == ""
