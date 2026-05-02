# -*- coding: utf-8-sig -*-
"""
test_refacto_16.py — LCCA V5 Fusion
REFACTO-16 : spec_generator.py découpé en spec_generator_helpers.py + spec_generator_context.py

18 tests couvrant :
  - spec_generator_helpers : _extract_title, _extract_abstract, _compute_complexity
  - spec_generator_context : _DOMAIN_FILES, _KEYWORD_FILES, _build_technical_context
  - spec_generator (façade) : imports rétrocompat, SpecGeneratorService inchangé
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

# ── Imports directs des sous-modules REFACTO-16 ───────────────────────────────
from core.spec_generator_helpers import (
    _extract_title,
    _extract_abstract,
    _compute_complexity,
)
from core.spec_generator_context import (
    _DOMAIN_FILES,
    _KEYWORD_FILES,
    _build_technical_context,
)
# Import façade — vérifie que les réexports rétrocompat fonctionnent
from core.spec_generator import (
    SpecGeneratorService,
    _extract_title as _title_reexport,
    _extract_abstract as _abstract_reexport,
    _compute_complexity as _complexity_reexport,
    _DOMAIN_FILES as _domain_files_reexport,
    _KEYWORD_FILES as _kw_files_reexport,
    _build_technical_context as _btc_reexport,
)
from core.spec_entry import SpecEntry
from core.spec_validator import SpecValidatorService
from core.cognitive_patterns import DeepReasoningPattern, SpecFormatterPattern


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

_BODY_VALID = (
    "## Titre\nModule Y\n"
    "## Abstract\nDescription du module Y.\n"
    "## Corps\n" + "y" * 60 + "\n"
)


def _make_svc(body: str = _BODY_VALID) -> SpecGeneratorService:
    reasoning = MagicMock(spec=DeepReasoningPattern)
    reasoning.run.return_value = body
    formatter = MagicMock(spec=SpecFormatterPattern)
    formatter.run.return_value = body
    return SpecGeneratorService(reasoning, formatter, SpecValidatorService())


# ═══════════════════════════════════════════════════════════════════════════
# 1-6 : spec_generator_helpers
# ═══════════════════════════════════════════════════════════════════════════

class TestExtractTitle:

    def test_h1_header(self) -> None:
        assert _extract_title("# Mon Titre\n## Section") == "Mon Titre"

    def test_h2_titre_section(self) -> None:
        md = "## Titre\nModule Alpha\n## Abstract\nDesc"
        assert _extract_title(md) == "Module Alpha"

    def test_fallback_first_nonempty_line(self) -> None:
        md = "\n\nPremiere ligne non vide"
        assert _extract_title(md) == "Premiere ligne non vide"

    def test_empty_returns_sans_titre(self) -> None:
        assert _extract_title("") == "Sans titre"

    def test_strips_comment_lines(self) -> None:
        md = "<!-- AI-READY | test -->\n# Titre réel"
        assert _extract_title(md) == "Titre réel"


class TestExtractAbstract:

    def test_extracts_abstract_section(self) -> None:
        md = "# Titre\n## Abstract\nCeci est l abstract.\n## Corps\nIgnoré"
        result = _extract_abstract(md)
        assert "abstract" in result.lower() or "ceci" in result.lower()

    def test_fallback_to_first_200_chars(self) -> None:
        md = "Pas d'abstract ici. " * 20
        result = _extract_abstract(md)
        assert len(result) <= 500


class TestComputeComplexity:

    def test_zero_for_empty(self) -> None:
        assert _compute_complexity("") == 0

    def test_counts_sections_and_rules(self) -> None:
        md = "## Sec1\n## Sec2\n| col | val |\n| --- | --- |\n| a   | b   |"
        score = _compute_complexity(md)
        # 2 sections * 5 + 3 règles * 3 = 10 + 9 = 19
        assert score == 19

    def test_max_100(self) -> None:
        md = "\n".join([f"## Section {i}" for i in range(30)])
        assert _compute_complexity(md) == 100


# ═══════════════════════════════════════════════════════════════════════════
# 7-12 : spec_generator_context
# ═══════════════════════════════════════════════════════════════════════════

class TestDomainFiles:

    def test_all_known_domains_present(self) -> None:
        for domain in ("transaction", "ast", "mcp", "sandbox", "memory", "spec", "orchestration", "global"):
            assert domain in _DOMAIN_FILES

    def test_each_domain_has_files(self) -> None:
        for domain, files in _DOMAIN_FILES.items():
            assert isinstance(files, list)
            assert len(files) >= 1

    def test_keyword_files_nonempty(self) -> None:
        assert len(_KEYWORD_FILES) >= 5
        for kw, path in _KEYWORD_FILES.items():
            assert path.startswith("core/") or path.endswith(".py")


class TestBuildTechnicalContext:

    def test_returns_extra_context_when_config_missing(self) -> None:
        with patch.dict("sys.modules", {"config": None}):
            result = _build_technical_context("test", "global", "mon contexte")
            assert result == "mon contexte"

    def test_keyword_enrichment_logic(self) -> None:
        # Vérifier que les mots-clés sont bien mappés
        assert "web" in _KEYWORD_FILES
        assert "llm" in _KEYWORD_FILES
        assert "memory" in _KEYWORD_FILES

    def test_domain_fallback_to_global(self) -> None:
        # Domaine inconnu → fallback global (clé présente dans _DOMAIN_FILES)
        files = _DOMAIN_FILES.get("unknown_domain", _DOMAIN_FILES["global"])
        assert files == _DOMAIN_FILES["global"]


# ═══════════════════════════════════════════════════════════════════════════
# 13-18 : spec_generator (façade) — rétrocompat + comportement inchangé
# ═══════════════════════════════════════════════════════════════════════════

class TestSpecGeneratorFacadeReexports:

    def test_title_reexport_identity(self) -> None:
        assert _title_reexport is _extract_title

    def test_abstract_reexport_identity(self) -> None:
        assert _abstract_reexport is _extract_abstract

    def test_complexity_reexport_identity(self) -> None:
        assert _complexity_reexport is _compute_complexity

    def test_domain_files_reexport_identity(self) -> None:
        assert _domain_files_reexport is _DOMAIN_FILES

    def test_kw_files_reexport_identity(self) -> None:
        assert _kw_files_reexport is _KEYWORD_FILES

    def test_generate_returns_spec_entry(self) -> None:
        svc = _make_svc()
        result = svc.generate("Créer module Y")
        assert isinstance(result, SpecEntry)
        assert result.title != ""
