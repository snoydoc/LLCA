# -*- coding: utf-8-sig -*-
"""
test_spec_retry.py — LCCA V5 Fusion
V9-09 — Tests SpecGeneratorService.generate_with_retry()

6 tests.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from core.spec_generator import SpecGeneratorService
from core.spec_entry import SpecEntry
from core.spec_validator import SpecValidatorService
from core.cognitive_patterns import DeepReasoningPattern, SpecFormatterPattern


_BODY_VALID = (
    "## Titre\nModule X\n"
    "## Abstract\nCeci est l abstract.\n"
    "## Corps\n" + "x" * 60 + "\n"
)


def _make_svc(body: str = _BODY_VALID) -> SpecGeneratorService:
    reasoning = MagicMock(spec=DeepReasoningPattern)
    reasoning.run.return_value = body
    formatter = MagicMock(spec=SpecFormatterPattern)
    formatter.run.return_value = body
    return SpecGeneratorService(reasoning, formatter, SpecValidatorService())


class TestSpecRetry:

    def test_generate_with_retry_returns_spec_entry(self) -> None:
        """generate_with_retry() retourne toujours une SpecEntry."""
        svc = _make_svc()
        result = svc.generate_with_retry("Créer module X")
        assert isinstance(result, SpecEntry)

    def test_generate_with_retry_usable_no_autofix(self) -> None:
        """Si la spec est usable dès le premier appel, auto_fix n'est pas appelé."""
        svc = _make_svc()
        # Patcher auto_fix pour vérifier qu'il n'est pas appelé
        with patch.object(svc, "auto_fix", wraps=svc.auto_fix) as mock_af:
            spec = svc.generate_with_retry("Créer module X")
            if spec.is_usable():
                mock_af.assert_not_called()

    def test_generate_with_retry_calls_autofix_when_not_usable(self) -> None:
        """Si la spec n'est pas usable, auto_fix est appelé avec max_iter=1."""
        svc = _make_svc()
        # Forcer is_usable=False sur le premier résultat
        low_score_spec = MagicMock(spec=SpecEntry)
        low_score_spec.is_usable.return_value = False

        with patch.object(svc, "generate", return_value=low_score_spec):
            with patch.object(svc, "auto_fix", return_value=low_score_spec) as mock_af:
                svc.generate_with_retry("Créer module X")
                mock_af.assert_called_once_with(low_score_spec, max_iter=1)

    def test_generate_with_retry_disabled_by_config(self) -> None:
        """Si SPEC_RETRY_ON_FAIL=False, auto_fix n'est jamais appelé."""
        svc = _make_svc()
        low_score_spec = MagicMock(spec=SpecEntry)
        low_score_spec.is_usable.return_value = False

        with patch.object(svc, "generate", return_value=low_score_spec):
            with patch.object(svc, "auto_fix") as mock_af:
                with patch("config.SPEC_RETRY_ON_FAIL", False):
                    result = svc.generate_with_retry("Créer module X")
                    mock_af.assert_not_called()
                    assert result is low_score_spec

    def test_generate_with_retry_passes_domain(self) -> None:
        """generate_with_retry() passe le domain à generate()."""
        svc = _make_svc()
        with patch.object(svc, "generate", wraps=svc.generate) as mock_g:
            svc.generate_with_retry("Créer module X", domain="mcp")
            mock_g.assert_called_once()
            _, kwargs = mock_g.call_args
            called_domain = kwargs.get("domain") or mock_g.call_args[0][2]
            assert called_domain == "mcp"

    def test_generate_with_retry_signature(self) -> None:
        """generate_with_retry() accepte prompt, context et domain."""
        svc = _make_svc()
        result = svc.generate_with_retry(
            "Créer module X", context="contexte", domain="ast"
        )
        assert isinstance(result, SpecEntry)
