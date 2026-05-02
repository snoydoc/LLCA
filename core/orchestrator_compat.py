# -*- coding: utf-8-sig -*-
"""
orchestrator_compat.py — Alias rétrocompat Orchestrator = LCCAV5Fusion (Sprint REFACTO-01).

Extrait de orchestrator.py.
L'ancienne classe Orchestrator (alias legacy Sprint 01) est conservée ici
pour que `from core.orchestrator import Orchestrator` continue de fonctionner.

Note : LCCAV5Fusion est maintenant dans orchestrator.py (inchangé côté import).
"""
from __future__ import annotations

from typing import Optional

from core.orchestrator import LCCAV5Fusion


class Orchestrator:
    """Alias legacy vers LCCAV5Fusion pour rétrocompatibilité Sprint 01."""

    def __init__(self) -> None:
        self._fusion: Optional[LCCAV5Fusion] = None

    def _get_fusion(self) -> LCCAV5Fusion:
        if self._fusion is None:
            self._fusion = LCCAV5Fusion()
        return self._fusion

    def execute_plan(self, plan) -> bool:
        if isinstance(plan, str):
            return self._get_fusion().execute(plan)
        label = getattr(plan, "task_label", str(plan))
        return self._get_fusion().execute(label)
