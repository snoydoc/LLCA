# -*- coding: utf-8-sig -*-
"""test_spec_promoter.py — 6 tests Sprint 15 (SpecPromoter).
Sprint 19 — Dette 15 : memory_layer est maintenant un champ SpecEntry.
            _make_spec() passe memory_layer=layer au constructeur (plus d'assignment direct).
"""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock

import config
from core.spec_promoter import SpecPromoter, _LAYER_2_TO_1_THRESHOLD, _LAYER_1_TO_0_THRESHOLD
from core.spec_entry import SpecEntry, make_spec_id


def _make_spec(usage_count: int = 0, layer: int = 2, score: float = 1.0) -> SpecEntry:
    sid = make_spec_id(f"titre{usage_count}{layer}", "abstract test")
    return SpecEntry(
        spec_id=sid,
        title="Titre test",
        abstract="Abstract test suffisant.",
        body_md="## Corps\n\n" + "x" * 60,
        score=score,
        usage_count=usage_count,
        memory_layer=layer,  # Sprint 19 : champ officiel SpecEntry (plus de setattr)
    )


def _make_formatter(response: str = "Abstract enrichi en 500 chars.") -> MagicMock:
    fmt = MagicMock()
    fmt.run.return_value = response
    return fmt


class TestSpecPromoter:

    def test_no_promotion_below_threshold(self):
        """usage_count < 5 → layer inchangé."""
        promoter = SpecPromoter(_make_formatter())
        spec = _make_spec(usage_count=3, layer=2)
        result = promoter.maybe_promote(spec)
        assert result.memory_layer == 2

    def test_promote_layer2_to_1_at_threshold(self):
        """usage_count == 5 → layer 2 → 1."""
        promoter = SpecPromoter(_make_formatter("Abstract enrichi."))
        spec = _make_spec(usage_count=_LAYER_2_TO_1_THRESHOLD, layer=2)
        result = promoter.maybe_promote(spec)
        assert result.memory_layer == 1

    def test_promote_layer1_to_0_at_threshold(self):
        """usage_count == 10 → layer 1 → 0."""
        promoter = SpecPromoter(_make_formatter())
        spec = _make_spec(usage_count=_LAYER_1_TO_0_THRESHOLD, layer=1)
        result = promoter.maybe_promote(spec)
        assert result.memory_layer == 0

    def test_layer0_abstract_added_to_config(self):
        """Promotion layer 0 → abstract ajouté dans config.SPEC_IDENTITY_ABSTRACTS."""
        # Nettoie avant le test
        if hasattr(config, "SPEC_IDENTITY_ABSTRACTS"):
            config.SPEC_IDENTITY_ABSTRACTS = []

        promoter = SpecPromoter(_make_formatter())
        spec = _make_spec(usage_count=_LAYER_1_TO_0_THRESHOLD, layer=1)
        abstract_before = spec.abstract
        promoter.maybe_promote(spec)

        assert hasattr(config, "SPEC_IDENTITY_ABSTRACTS")
        assert abstract_before in config.SPEC_IDENTITY_ABSTRACTS

    def test_abstract_enriched_on_layer1_promotion(self):
        """Le formatter LLM est appelé lors de la promotion vers layer 1."""
        fmt = _make_formatter("Nouvel abstract enrichi par LLM.")
        promoter = SpecPromoter(fmt)
        spec = _make_spec(usage_count=_LAYER_2_TO_1_THRESHOLD, layer=2)
        result = promoter.maybe_promote(spec)
        fmt.run.assert_called_once()
        assert result.abstract == "Nouvel abstract enrichi par LLM."

    def test_already_layer0_not_repromoted(self):
        """Idempotence : spec déjà layer=0 → maybe_promote() ne change rien."""
        fmt = _make_formatter()
        promoter = SpecPromoter(fmt)
        spec = _make_spec(usage_count=100, layer=0)
        result = promoter.maybe_promote(spec)
        assert result.memory_layer == 0
        fmt.run.assert_not_called()
