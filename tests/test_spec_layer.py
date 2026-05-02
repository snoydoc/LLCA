# -*- coding: utf-8-sig -*-
"""test_spec_layer.py — Tests Sprint 14-22 (V7.2 complet).

Sprint 22 — Réécriture V7.2 :
            - Suppression imports legacy (RULE_REGISTRY_LEGACY, _LegacyRuleChecker,
              ValidationResult, validate_compat).
            - Suppression TestRuleRegistryLegacy (R01-R15 sur champs SpecEntry supprimés).
            - Suppression TestRuleRegistry (alias legacy, fusionné dans TestRuleRegistryV72).
            - Suppression TestSpecValidatorServiceV72.test_validate_compat_returns_validation_result.
            - Mise à jour _make_spec() : suppression champ complexity (supprimé de SpecEntry).
            - TestSpecGeneratorService : suppression test_generate_sets_score (complexity_score
              remplace complexity dans les assertions d'état).
            - ~30 tests PASSED cible.
"""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock

from core.spec_entry import SpecEntry, make_spec_id, VALID_DOMAINS, VALID_GENERATED_BY
from core.cognitive_patterns import DeepReasoningPattern, SpecFormatterPattern, SpecValidatorPattern
from core.spec_validator import (
    RULE_REGISTRY, RuleChecker,
    SpecValidatorService, _format_notes,
)
from core.spec_generator import SpecGeneratorService


def _make_spec(**kwargs) -> SpecEntry:
    defaults = dict(
        spec_id="a" * 12,
        title="Titre test",
        abstract="Abstract de test pour la spec.",
        body_md="## Corps\n\nContenu suffisamment long pour passer R10 cinquante chars min.\n",
        # Champs V7.2
        domain="global",
        version="7.2.0",
    )
    defaults.update(kwargs)
    return SpecEntry(**defaults)


def _mock_generator(response: str = "reponse LLM") -> MagicMock:
    """
    Crée un mock de LLMGenerator.
    configure generate_text() (interface basse pour CognitivePatterns)
    EN PLUS de generate() (interface haute pour le pipeline TX).
    _call_llm() utilise generate_text() en priorité si callable.
    """
    gen = MagicMock()
    gen.generate_text.return_value = response
    result = MagicMock()
    result.code = response
    result.explanation = response
    gen.generate.return_value = result
    return gen


# ════════════════════════════════════════════════════════════════════════════
# SpecEntry V7.2
# ════════════════════════════════════════════════════════════════════════════

class TestSpecEntry:

    def test_make_spec_id_deterministic(self):
        id1 = make_spec_id("Titre A", "Abstract A")
        id2 = make_spec_id("Titre A", "Abstract A")
        assert id1 == id2
        assert len(id1) == 12

    def test_make_spec_id_different_inputs(self):
        id1 = make_spec_id("Titre A", "Abstract A")
        id2 = make_spec_id("Titre B", "Abstract B")
        assert id1 != id2

    def test_to_dict_from_dict_roundtrip(self):
        """Sprint 20 : roundtrip vérifie les champs V7.2."""
        spec = _make_spec(domain="mcp", validated=True, superseded_by=None)
        restored = SpecEntry.from_dict(spec.to_dict())
        assert restored.spec_id == spec.spec_id
        assert restored.title == spec.title
        assert restored.body_md == spec.body_md
        assert restored.domain == "mcp"
        assert restored.validated is True
        assert restored.superseded_by is None
        assert restored.deprecated is False
        assert restored.version == "7.2.0"

    def test_is_usable(self):
        """Sprint 20 : is_usable() requiert validated=True (Règle 11 V7.2)."""
        assert _make_spec(score=0.9, validated=True).is_usable(min_score=0.8)
        assert not _make_spec(score=0.5, validated=True).is_usable(min_score=0.8)
        assert not _make_spec(score=0.9, validated=False).is_usable()


class TestSpecEntryV72:
    """Tests Sprint 20 couvrant les champs et la logique V7.2 de SpecEntry."""

    def test_make_spec_id_classmethod_from_body(self):
        body = "## Titre\nContenu de la spec pour test V7.2."
        id1 = SpecEntry.make_spec_id(body)
        id2 = SpecEntry.make_spec_id(body)
        assert id1 == id2
        assert len(id1) == 12
        assert all(c in "0123456789abcdef" for c in id1)

    def test_is_usable_requires_validated(self):
        spec = _make_spec(score=0.9, validated=False)
        assert not spec.is_usable()

    def test_is_usable_requires_not_deprecated(self):
        spec = _make_spec(score=0.9, validated=True, deprecated=True)
        assert not spec.is_usable()

    def test_is_usable_requires_not_superseded(self):
        spec = _make_spec(score=0.9, validated=True, superseded_by="aabbccddeeff")
        assert not spec.is_usable()

    def test_is_usable_all_conditions_met(self):
        spec = _make_spec(score=0.9, validated=True, deprecated=False, superseded_by=None)
        assert spec.is_usable()

    def test_domain_defaults_to_global(self):
        spec = _make_spec()
        assert spec.domain == "global"

    def test_to_dict_includes_v72_fields(self):
        spec = _make_spec(domain="mcp", validated=True, generated_by="hybrid")
        d = spec.to_dict()
        assert "domain" in d
        assert d["domain"] == "mcp"
        assert "validated" in d
        assert d["validated"] is True
        assert "superseded_by" in d
        assert "deprecated" in d
        assert "generated_by" in d
        assert d["generated_by"] == "hybrid"
        assert "complexity_score" in d
        assert "version" in d
        assert "validation_notes" in d

    def test_from_dict_retrocompat_sans_champs_v72(self):
        d = {
            "spec_id": "a" * 12,
            "title": "Test rétrocompat",
            "abstract": "Abstract rétrocompat.",
            "body_md": "## Corps\n" + "x" * 60,
        }
        spec = SpecEntry.from_dict(d)
        assert spec.domain == "global"
        assert spec.version == "7.2.0"
        assert spec.validated is False
        assert spec.superseded_by is None
        assert spec.deprecated is False
        assert spec.generated_by == "manual"
        assert spec.complexity_score == 0
        assert spec.validation_notes == ""


# ════════════════════════════════════════════════════════════════════════════
# RULE_REGISTRY V7.2 (15 règles sur body_md)
# ════════════════════════════════════════════════════════════════════════════

class TestRuleRegistryV72:
    """Tests RULE_REGISTRY V7.2 — règles sur body_md."""

    def test_registry_has_15_v72_rules(self):
        assert len(RULE_REGISTRY) == 15

    def test_all_v72_rules_are_rule_checker_abc(self):
        for k, v in RULE_REGISTRY.items():
            assert isinstance(v, RuleChecker), "%s n'est pas un RuleChecker" % k

    def test_rule1_detects_direct_write_after_patch(self):
        body = "Appeler apply_patch() puis write_text() directement."
        violations = RULE_REGISTRY["rule_1_smartpatcher_str"].analyze(body)
        assert any(v["severity"] == "blocking" for v in violations)

    def test_rule3_detects_4_files_per_tx(self):
        body = "Modifier 4 fichiers par transaction dans le pipeline."
        violations = RULE_REGISTRY["rule_3_max_files"].analyze(body)
        assert violations

    def test_rule8_detects_hardcoded_python_in_subprocess(self):
        body = "Appeler subprocess.run(['python', 'script.py']) pour exécuter."
        violations = RULE_REGISTRY["rule_8_sys_executable"].analyze(body)
        assert any(v["severity"] == "blocking" for v in violations)

    def test_rule10_warns_json_utf8_sig(self):
        body = "Écrire les fichiers JSON en utf-8-sig pour Windows."
        violations = RULE_REGISTRY["rule_10_utf8_sig"].analyze(body)
        assert violations

    def test_clean_body_has_no_violations(self):
        body = "## Spec propre\n\nAucune violation architecturale attendue ici.\n\n## Critères\n- OK"
        for rule in RULE_REGISTRY.values():
            found = rule.analyze(body)
            assert found == [], "Faux positif règle %s" % rule.rule_id

    def test_rule_ids_are_strings_prefixed_rule(self):
        for rule_id in RULE_REGISTRY:
            assert rule_id.startswith("rule_"), "rule_id sans préfixe 'rule_' : %s" % rule_id

    def test_each_rule_returns_list(self):
        body = "## Spec test\n\nContenu neutre."
        for rule in RULE_REGISTRY.values():
            result = rule.analyze(body)
            assert isinstance(result, list), "rule %s ne retourne pas une liste" % rule.rule_id


# ════════════════════════════════════════════════════════════════════════════
# SpecValidatorService V7.2
# ════════════════════════════════════════════════════════════════════════════

class TestSpecValidatorService:
    """Tests SpecValidatorService — interface V7.2 pure (validate() → dict)."""

    def _valid_spec(self) -> SpecEntry:
        sid = make_spec_id("Titre test", "Abstract de test pour la spec.")
        return _make_spec(spec_id=sid)

    def test_validate_returns_dict(self):
        spec = _make_spec()
        result = SpecValidatorService().validate(spec)
        assert isinstance(result, dict)
        assert "valid" in result
        assert "score" in result
        assert "violations" in result
        assert "validation_notes" in result

    def test_validate_sets_validated_on_spec(self):
        """validate() doit mettre à jour spec.validated (effet de bord V7.2)."""
        spec = _make_spec(validated=False)
        svc = SpecValidatorService()
        result = svc.validate(spec)
        assert spec.validated == result["valid"]

    def test_valid_spec_passes(self):
        result = SpecValidatorService().validate(self._valid_spec())
        assert result["valid"]

    def test_score_perfect_on_clean_spec(self):
        result = SpecValidatorService().validate(self._valid_spec())
        assert result["score"] == 1.0

    def test_llm_failure_is_silent(self):
        pattern = MagicMock(spec=SpecValidatorPattern)
        pattern.run.side_effect = RuntimeError("LLM down")
        result = SpecValidatorService(llm_pattern=pattern).validate(self._valid_spec())
        assert isinstance(result["violations"], list)

    def test_format_notes_empty(self):
        assert _format_notes([]) == ""

    def test_format_notes_with_violations(self):
        violations = [
            {"rule": "rule_1", "severity": "blocking", "location": "body_md", "fix_suggestion": "fix X"},
            {"rule": "rule_3", "severity": "warning", "location": "body_md", "fix_suggestion": "fix Y"},
        ]
        notes = _format_notes(violations)
        assert "BLOCKING" in notes
        assert "WARNING" in notes
        assert "rule_1" in notes

    def test_empty_title_returns_dict(self):
        """validate() retourne dict même si le titre est vide (règles V7.2 analysent body_md)."""
        result = SpecValidatorService().validate(_make_spec(title=""))
        assert isinstance(result["valid"], bool)


# ════════════════════════════════════════════════════════════════════════════
# CognitivePatterns V7.2
# ════════════════════════════════════════════════════════════════════════════

class TestCognitivePatterns:

    def test_deep_reasoning_calls_generator(self):
        gen = _mock_generator("raisonnement profond")
        out = DeepReasoningPattern(gen).run("Analyser X")
        assert out == "raisonnement profond"
        gen.generate_text.assert_called_once()

    def test_spec_formatter_calls_generator(self):
        gen = _mock_generator("## Titre\nFormate")
        out = SpecFormatterPattern(gen).run("contenu brut", context="ctx")
        assert out == "## Titre\nFormate"

    def test_spec_validator_pattern_calls_generator(self):
        resp = '{"violations": [], "blocking": 0, "score": 1.0}'
        gen = _mock_generator(resp)
        out = SpecValidatorPattern(gen).run("spec body")
        assert "violations" in out

    def test_run_with_empty_context(self):
        gen = _mock_generator("ok")
        assert DeepReasoningPattern(gen).run("prompt", context="") == "ok"

    def test_deep_reasoning_has_enriched_prompt_v72(self):
        """Sprint 21 : le system prompt V7.2 doit mentionner les contraintes LCCA."""
        assert "sys.executable" in DeepReasoningPattern._SYSTEM
        assert "Regle 11" in DeepReasoningPattern._SYSTEM  # prompt sans accents (style LCCA)

    def test_spec_formatter_has_ai_ready_template(self):
        """Sprint 21 : le formatter V7.2 doit mentionner le bloc AI-READY."""
        assert "AI-READY" in SpecFormatterPattern._SYSTEM

    def test_spec_validator_pattern_returns_json_guidance(self):
        """Sprint 21 : le validator V7.2 demande un JSON strict."""
        assert "JSON strict" in SpecValidatorPattern._SYSTEM


# ════════════════════════════════════════════════════════════════════════════
# SpecGeneratorService V7.2
# ════════════════════════════════════════════════════════════════════════════

class TestSpecGeneratorService:

    _BODY = (
        "## Titre\nModule X\n"
        "## Abstract\nCeci est l abstract du module.\n"
        "## Corps\n" + "x" * 60 + "\n"
    )

    def _make_svc(self, body: str | None = None) -> SpecGeneratorService:
        b = body or self._BODY
        reasoning = MagicMock(spec=DeepReasoningPattern)
        reasoning.run.return_value = b
        formatter = MagicMock(spec=SpecFormatterPattern)
        formatter.run.return_value = b
        return SpecGeneratorService(reasoning, formatter, SpecValidatorService())

    def test_generate_returns_spec_entry(self):
        assert isinstance(self._make_svc().generate("Creer un module X"), SpecEntry)

    def test_generate_spec_id_is_hex_12(self):
        spec = self._make_svc().generate("Creer un module X")
        assert len(spec.spec_id) == 12
        assert all(c in "0123456789abcdef" for c in spec.spec_id)

    def test_auto_fix_returns_spec_entry(self):
        svc = self._make_svc()
        assert isinstance(svc.auto_fix(svc.generate("Creer module"), max_iter=2), SpecEntry)

    def test_auto_fix_max_iter_respected(self):
        reasoning = MagicMock(spec=DeepReasoningPattern)
        reasoning.run.return_value = self._BODY
        formatter = MagicMock(spec=SpecFormatterPattern)
        formatter.run.return_value = self._BODY
        svc = SpecGeneratorService(reasoning, formatter, SpecValidatorService())
        spec = svc.generate("prompt")
        calls_before = formatter.run.call_count
        svc.auto_fix(spec, max_iter=2)
        assert (formatter.run.call_count - calls_before) <= 2

    def test_generate_sets_domain(self):
        """Sprint 21 : generate(domain=) renseigne SpecEntry.domain."""
        spec = self._make_svc().generate("Créer module X", domain="mcp")
        assert spec.domain == "mcp"

    def test_generate_sets_validated_bool(self):
        """Sprint 21 : spec.validated est un bool après generate()."""
        spec = self._make_svc().generate("Créer module X")
        assert isinstance(spec.validated, bool)

    def test_generate_sets_generated_by_hybrid(self):
        """Sprint 21 : generate() positionne generated_by = 'hybrid'."""
        spec = self._make_svc().generate("Créer module X")
        assert spec.generated_by == "hybrid"

    def test_generate_sets_complexity_score(self):
        """Sprint 22 : complexity_score (V7.2) est renseigné après generate()."""
        spec = self._make_svc().generate("Créer module X")
        assert isinstance(spec.complexity_score, int)
        assert 0 <= spec.complexity_score <= 100

    def test_generate_spec_id_from_body_md_classmethod(self):
        """Sprint 22 : spec_id peut aussi être généré via classmethod V7.2."""
        body = self._BODY
        id1 = SpecEntry.make_spec_id(body)
        assert len(id1) == 12
        assert all(c in "0123456789abcdef" for c in id1)
