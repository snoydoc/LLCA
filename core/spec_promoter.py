# -*- coding: utf-8-sig -*-
"""
spec_promoter.py — LCCA V7
Sprint 15 — TASK-15-04
Sprint 16 — logique Regle 19 affinée (score=0.0 ne bloque plus)
Sprint 19 — Dette 15 : spec.memory_layer est un champ SpecEntry officiel →
            getattr(spec, "memory_layer", 2) remplacé par spec.memory_layer direct.

Gestion de la promotion mémoire des specs.
Layer 2 (scoped) → Layer 1 (compressed) → Layer 0 (identity)

Déclenchement : après chaque usage réussi dans un pipeline TX.
Règle 18 : maybe_promote() est idempotente si spec déjà layer=0.
Règle 19 : spec stockée dans lcca_failures → jamais promouvable.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.cognitive_patterns import SpecFormatterPattern

import config

# Seuils de promotion
_LAYER_2_TO_1_THRESHOLD = 5   # 5 usages → compression abstract
_LAYER_1_TO_0_THRESHOLD = 10  # 10 usages → intégration identity


class SpecPromoter:
    """
    Évalue et exécute la promotion mémoire d'une SpecEntry.
    Injecté dans l'orchestrateur, appelé après chaque réutilisation TX.
    """

    def __init__(self, formatter: "SpecFormatterPattern") -> None:
        self._formatter = formatter

    def maybe_promote(self, spec) -> object:
        """
        Tente de promouvoir la spec si les seuils sont atteints.

        Règle 18 : idempotente — layer=0 déjà → retourne spec inchangée.
        Règle 19 : spec en lcca_failures → pas de promotion.

        Sprint 19 — Dette 15 :
          spec.memory_layer est maintenant un champ officiel de SpecEntry (défaut=2).
          On accède directement à spec.memory_layer sans getattr fragile.

        Returns:
            La spec potentiellement avec un nouveau memory_layer.
        """
        # Idempotence layer 0 — accès direct au champ SpecEntry (Sprint 19)
        if spec.memory_layer == 0:
            return spec

        # Regle 19 : specs non usables (score < 0.5) ne sont pas promues.
        # is_usable() filtre déjà les specs avec score < min_score au moment
        # de leur réutilisation — maybe_promote() ne devrait pas être appelée
        # sur une spec invalide, mais on garde la garde explicite ici.
        # spec.score est un champ officiel SpecEntry (défaut 0.0) — accès direct.
        if spec.score < 0.5:
            return spec

        if spec.memory_layer == 2 and spec.usage_count >= _LAYER_2_TO_1_THRESHOLD:
            return self._promote_to_layer1(spec)
        if spec.memory_layer == 1 and spec.usage_count >= _LAYER_1_TO_0_THRESHOLD:
            return self._promote_to_layer0(spec)
        return spec

    def _promote_to_layer1(self, spec) -> object:
        """Layer 2 → 1 : enrichissement de l'abstract par le LLM."""
        enriched_abstract = self._formatter.run(
            prompt=f"Resume cette spec en 500 caracteres max :\n{spec.body_md}",
            context="abstract_compression",
        )[:500]
        spec.abstract = enriched_abstract
        spec.memory_layer = 1
        return spec

    def _promote_to_layer0(self, spec) -> object:
        """Layer 1 → 0 : intégration dans config.SPEC_IDENTITY_ABSTRACTS."""
        identity_abstracts = getattr(config, "SPEC_IDENTITY_ABSTRACTS", [])
        if spec.abstract not in identity_abstracts:
            identity_abstracts.append(spec.abstract)
            config.SPEC_IDENTITY_ABSTRACTS = identity_abstracts
        spec.memory_layer = 0
        return spec
