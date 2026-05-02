# -*- coding: utf-8-sig -*-
"""spec_validator.py — SpecValidatorService V7.2 + helpers.

Sprint 14      — RULE_REGISTRY R01-R15 (règles sur champs SpecEntry) + ValidationResult.
Sprint 19      — Dette 13 : score recalculé APRÈS intégration du feedback LLM.
Sprint 21      — Migration V7.2 :
                 * RULE_REGISTRY V7.2 : RuleChecker ABC + classes concrètes + analyze(body_md).
                 * validate()         : retourne dict (spec V7.2).
                 * _format_notes()    : helper str depuis violations.
Sprint 22      — Cleanup legacy :
                 * Suppression ValidationResult dataclass.
                 * Suppression validate_compat().
Sprint REFACTO-01 — RuleChecker + 15 classes + RULE_REGISTRY extraits dans spec_validator_rules.py.
                    Rétrocompat : RuleChecker et RULE_REGISTRY restent importables depuis ce module.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.spec_entry import SpecEntry
    from core.cognitive_patterns import SpecValidatorPattern

# ── Règles + registre (ré-exportés pour rétrocompat) ─────────────────────
from core.spec_validator_rules import (  # noqa: F401
    RuleChecker,
    Rule1SmartPatcherStr, Rule2AstReadLibcstWrite, Rule3MaxFiles,
    Rule4SnapshotMd5, Rule5WalAppendOnly, Rule6LlmFallback,
    Rule7DependencyInjection, Rule8SysExecutable, Rule9ModuleLevelImports,
    Rule10Utf8Sig, Rule11NoCodeIfInvalidSpec, Rule12ComplexityFirst,
    Rule13SpecVersioned, Rule14InvalidSpecStops, Rule15PatternsConfigurable,
    RULE_REGISTRY,
)


# ════════════════════════════════════════════════════════════════════════════
# Helper
# ════════════════════════════════════════════════════════════════════════════

def _format_notes(violations: list[dict]) -> str:
    """Produit un résumé texte des violations pour validation_notes."""
    if not violations:
        return ""
    lines = []
    for v in violations:
        rule       = v.get("rule", "?")
        severity   = v.get("severity", "warning")
        suggestion = v.get("fix_suggestion", "")
        lines.append("[%s] %s — %s" % (severity.upper(), rule, suggestion))
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════
# SpecValidatorService (interface V7.2 pure)
# ════════════════════════════════════════════════════════════════════════════

class SpecValidatorService:
    """
    Validateur de SpecEntry.

    Sprint 22 — Interface V7.2 pure (validate() dict uniquement).

    Paramètres acceptés :
      llm_pattern       : SpecValidatorPattern injecté (interface V7.2)
      validator_pattern : alias rétrocompat Sprint 14 (mappé vers llm_pattern)
      rules             : liste de rule_id V7.2 à activer (None = toutes les 15 règles)
    """

    def __init__(
        self,
        llm_pattern: "Optional[SpecValidatorPattern]" = None,
        rules: Optional[list[str]] = None,
        validator_pattern: "Optional[SpecValidatorPattern]" = None,
    ) -> None:
        self._llm   = llm_pattern or validator_pattern
        self._rules = rules or list(RULE_REGISTRY.keys())

    def validate(self, spec: "SpecEntry") -> dict:
        """
        Valide une SpecEntry. Retourne un dict V7.2.

        Clés du dict :
          valid             : bool
          score             : float [0.0, 1.0]
          violations        : list[dict]  — chaque dict = rule/severity/location/fix_suggestion
          validation_notes  : str         — résumé humain des violations

        Invariant Sprint 19 : score et valid calculés UNE SEULE FOIS après toutes
        les violations (statiques + LLM).

        Effet de bord : met à jour spec.validated et spec.validation_notes.
        """
        violations: list[dict] = []
        blocking = 0

        # Phase 1 : règles V7.2 sur body_md
        active_rules = {k: v for k, v in RULE_REGISTRY.items() if k in self._rules}
        for checker in active_rules.values():
            found = checker.analyze(spec.body_md)
            violations.extend(found)
            for v in found:
                if v.get("severity") == "blocking":
                    blocking += 1

        # Phase 2 : feedback LLM optionnel (avant calcul final)
        llm_feedback_raw = ""
        if self._llm is not None:
            try:
                raw = self._llm.run(spec.body_md)
                parsed = json.loads(raw)
                llm_violations = parsed.get("violations", [])
                for lv in llm_violations:
                    if isinstance(lv, str):
                        violations.append({
                            "rule": "llm_feedback",
                            "severity": "warning",
                            "location": "body_md",
                            "fix_suggestion": lv,
                        })
                    elif isinstance(lv, dict):
                        violations.append(lv)
                        if lv.get("severity") == "blocking":
                            blocking += 1
                llm_blocking = int(parsed.get("blocking", 0))
                blocking += llm_blocking
                llm_feedback_raw = raw
            except (json.JSONDecodeError, Exception):
                pass  # LLM failure toujours silencieuse

        # Phase 3 : calcul final score + valid
        if not violations:
            score = 1.0
        else:
            score = max(0.0, 1.0 - blocking * 0.3 - len(violations) * 0.05)

        valid = blocking == 0 and score >= 0.8
        notes = _format_notes(violations)

        # Effet de bord V7.2 : propager dans la spec
        spec.validated        = valid
        spec.validation_notes = notes

        return {
            "valid":             valid,
            "score":             score,
            "violations":        violations,
            "validation_notes":  notes,
            "_llm_feedback_raw": llm_feedback_raw,
        }
