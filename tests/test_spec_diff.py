# -*- coding: utf-8-sig -*-
"""
test_spec_diff.py — LCCA V5 Fusion
V9-09 — Tests SpecEntry.diff() + SpecDiff dataclass

6 tests.
"""
from __future__ import annotations

import pytest
from core.spec_entry import SpecEntry, SpecDiff


def _make(spec_id="a" * 12, title="T", abstract="A", body_md="## Corps\nOK\n",
          validation_notes="", **kwargs) -> SpecEntry:
    return SpecEntry(
        spec_id=spec_id,
        title=title,
        abstract=abstract,
        body_md=body_md,
        validation_notes=validation_notes,
        **kwargs,
    )


class TestSpecDiff:

    def test_diff_identical_specs_all_empty(self) -> None:
        """Deux specs identiques → added=[], removed=[], stable=[], changed_fields=[]."""
        s1 = _make(validation_notes="BLOCKING: rule_1\nWARNING: rule_3")
        s2 = _make(validation_notes="BLOCKING: rule_1\nWARNING: rule_3")
        d = s1.diff(s2)
        assert isinstance(d, SpecDiff)
        assert d.added == []
        assert d.removed == []
        assert len(d.stable) == 2
        assert d.changed_fields == []

    def test_diff_added_violation(self) -> None:
        """Une violation présente dans other mais pas dans self → dans added."""
        s1 = _make(validation_notes="BLOCKING: rule_1")
        s2 = _make(validation_notes="BLOCKING: rule_1\nWARNING: rule_8")
        d = s1.diff(s2)
        assert any("rule_8" in a for a in d.added)
        assert d.removed == []

    def test_diff_removed_violation(self) -> None:
        """Une violation corrigée dans other → dans removed."""
        s1 = _make(validation_notes="BLOCKING: rule_1\nWARNING: rule_8")
        s2 = _make(validation_notes="BLOCKING: rule_1")
        d = s1.diff(s2)
        assert any("rule_8" in r for r in d.removed)
        assert d.added == []

    def test_diff_changed_fields_detected(self) -> None:
        """Champs modifiés entre deux versions → dans changed_fields."""
        s1 = _make(domain="global", validated=False)
        s2 = _make(domain="mcp", validated=True)
        d = s1.diff(s2)
        assert "domain" in d.changed_fields
        assert "validated" in d.changed_fields

    def test_diff_spec_ids_recorded(self) -> None:
        """spec_id_before et spec_id_after sont correctement renseignés."""
        s1 = _make(spec_id="a" * 12)
        s2 = _make(spec_id="b" * 12)
        d = s1.diff(s2)
        assert d.spec_id_before == "a" * 12
        assert d.spec_id_after  == "b" * 12

    def test_diff_empty_notes_no_crash(self) -> None:
        """diff() sur deux specs sans validation_notes → pas d'erreur."""
        s1 = _make(validation_notes="")
        s2 = _make(validation_notes="")
        d = s1.diff(s2)
        assert d.added == []
        assert d.removed == []
        assert d.stable == []
