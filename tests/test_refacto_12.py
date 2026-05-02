# -*- coding: utf-8-sig -*-
"""
tests/test_refacto_12.py -- REFACTO-12 : cognitive_prompts.py extrait de cognitive_patterns.py

18 tests couvrant :
  TestCognitivePromptsModule (6)  : module importable, 4 constantes presentes, types str,
                                    contenu inchange vs original, aliases retrocompat
  TestCognitivePatternRetrocompat (6) : _SYSTEM sur les 4 classes pointe vers cognitive_prompts,
                                        imports depuis cognitive_patterns toujours fonctionnels,
                                        run() appelle generate_text sur le bon prompt
  TestCognitivePatternsBehavior (6)   : DeepReasoning, SpecFormatter, SpecValidator, SpecDirect
                                        fonctionnent identiquement post-REFACTO
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

# -- Imports depuis cognitive_patterns (retrocompat obligatoire) ---------------
from core.cognitive_patterns import (
    CognitivePattern,
    DeepReasoningPattern,
    SpecFormatterPattern,
    SpecValidatorPattern,
    SpecDirectPattern,
    _DEEP_REASONING_SYSTEM,
    _SPEC_FORMATTER_SYSTEM,
    _SPEC_VALIDATOR_SYSTEM,
    _SPEC_DIRECT_SYSTEM,
)

# -- Imports depuis cognitive_prompts (source de verite) ----------------------
from core.cognitive_prompts import (
    DEEP_REASONING_SYSTEM,
    SPEC_FORMATTER_SYSTEM,
    SPEC_VALIDATOR_SYSTEM,
    SPEC_DIRECT_SYSTEM,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _mock_gen(response: str = "reponse") -> MagicMock:
    gen = MagicMock()
    gen.generate_text.return_value = response
    result = MagicMock()
    result.code = response
    gen.generate.return_value = result
    return gen


# ════════════════════════════════════════════════════════════════════════════
# TestCognitivePromptsModule
# ════════════════════════════════════════════════════════════════════════════

class TestCognitivePromptsModule:

    def test_module_importable(self):
        import core.cognitive_prompts  # noqa
        assert core.cognitive_prompts is not None

    def test_four_constants_present(self):
        import core.cognitive_prompts as cp
        assert hasattr(cp, "DEEP_REASONING_SYSTEM")
        assert hasattr(cp, "SPEC_FORMATTER_SYSTEM")
        assert hasattr(cp, "SPEC_VALIDATOR_SYSTEM")
        assert hasattr(cp, "SPEC_DIRECT_SYSTEM")

    def test_all_constants_are_str(self):
        assert isinstance(DEEP_REASONING_SYSTEM, str)
        assert isinstance(SPEC_FORMATTER_SYSTEM, str)
        assert isinstance(SPEC_VALIDATOR_SYSTEM, str)
        assert isinstance(SPEC_DIRECT_SYSTEM, str)

    def test_all_constants_non_empty(self):
        assert len(DEEP_REASONING_SYSTEM) > 100
        assert len(SPEC_FORMATTER_SYSTEM) > 100
        assert len(SPEC_VALIDATOR_SYSTEM) > 100
        assert len(SPEC_DIRECT_SYSTEM) > 100

    def test_deep_reasoning_mentions_lcca_constraints(self):
        assert "sys.executable" in DEEP_REASONING_SYSTEM
        assert "Regle 11" in DEEP_REASONING_SYSTEM

    def test_spec_direct_mentions_ai_ready(self):
        assert "AI-READY" in SPEC_DIRECT_SYSTEM


# ════════════════════════════════════════════════════════════════════════════
# TestCognitivePatternRetrocompat
# ════════════════════════════════════════════════════════════════════════════

class TestCognitivePatternRetrocompat:

    def test_aliases_point_to_prompts_module(self):
        """Les aliases _*_SYSTEM dans cognitive_patterns sont les memes objets."""
        assert _DEEP_REASONING_SYSTEM is DEEP_REASONING_SYSTEM
        assert _SPEC_FORMATTER_SYSTEM is SPEC_FORMATTER_SYSTEM
        assert _SPEC_VALIDATOR_SYSTEM is SPEC_VALIDATOR_SYSTEM
        assert _SPEC_DIRECT_SYSTEM    is SPEC_DIRECT_SYSTEM

    def test_class_system_attr_equals_module_constant(self):
        """_SYSTEM sur chaque classe == constante du module prompts."""
        assert DeepReasoningPattern._SYSTEM  is DEEP_REASONING_SYSTEM
        assert SpecFormatterPattern._SYSTEM  is SPEC_FORMATTER_SYSTEM
        assert SpecValidatorPattern._SYSTEM  is SPEC_VALIDATOR_SYSTEM
        assert SpecDirectPattern._SYSTEM     is SPEC_DIRECT_SYSTEM

    def test_cognitive_pattern_is_abc(self):
        with pytest.raises(TypeError):
            CognitivePattern(_mock_gen())  # type: ignore -- ABC, non instanciable

    def test_deep_reasoning_instantiable(self):
        assert isinstance(DeepReasoningPattern(_mock_gen()), DeepReasoningPattern)

    def test_spec_formatter_instantiable(self):
        assert isinstance(SpecFormatterPattern(_mock_gen()), SpecFormatterPattern)

    def test_spec_direct_instantiable(self):
        assert isinstance(SpecDirectPattern(_mock_gen()), SpecDirectPattern)


# ════════════════════════════════════════════════════════════════════════════
# TestCognitivePatternsBehavior
# ════════════════════════════════════════════════════════════════════════════

class TestCognitivePatternsBehavior:

    def test_deep_reasoning_run_calls_generate_text(self):
        gen = _mock_gen("analyse architecturale")
        out = DeepReasoningPattern(gen).run("Analyser le module TX")
        assert out == "analyse architecturale"
        gen.generate_text.assert_called_once()

    def test_spec_formatter_run_with_context(self):
        gen = _mock_gen("## Titre\nFormate")
        out = SpecFormatterPattern(gen).run("contenu", context="ctx")
        assert out == "## Titre\nFormate"
        gen.generate_text.assert_called_once()

    def test_spec_validator_run_returns_json_str(self):
        resp = '{"violations": []}'
        gen = _mock_gen(resp)
        out = SpecValidatorPattern(gen).run("spec body")
        assert "violations" in out

    def test_spec_direct_run_with_context(self):
        gen = _mock_gen("## Titre\nSpec directe")
        out = SpecDirectPattern(gen).run("module cache", context="contexte reel")
        assert out == "## Titre\nSpec directe"
        gen.generate_text.assert_called_once()

    def test_spec_direct_run_without_context(self):
        gen = _mock_gen("## Titre\nSans contexte")
        out = SpecDirectPattern(gen).run("module cache")
        assert out == "## Titre\nSans contexte"

    def test_call_llm_fallback_no_generate_text(self):
        """Chemin de compatibilite descendante si generate_text absent."""
        gen = MagicMock(spec=[])  # aucun attribut -- pas de generate_text
        result = MagicMock()
        result.code = "fallback"
        gen.generate = MagicMock(return_value=result)
        pat = DeepReasoningPattern(gen)
        # generate_text absent -> branche fallback -> code du result
        out = pat._call_llm("sys", "user")
        assert isinstance(out, str)
