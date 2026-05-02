# -*- coding: utf-8-sig -*-
"""spec_generator.py - SpecGeneratorService (Sprint 14).

REFACTO-16 : orchestration légère.
  - Helpers Markdown extraction → spec_generator_helpers.py
  - Contexte technique SPEC-02  → spec_generator_context.py

Sprint 18 — Dette 10 : auto_fix() court-circuit si score stable entre 2 iter.
Sprint 21 — Migration V7.2 : generate(domain=), _compute_complexity(), validated.
SPEC-01   — SpecDirectPattern (1 appel LLM) prioritaire sur pipeline 2 appels.
SPEC-02   — _build_technical_context() injecte le code source LCCA réel.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.spec_entry import SpecEntry
    from core.cognitive_patterns import SpecDirectPattern
    from core.spec_validator import SpecValidatorService

# ── Imports REFACTO-16 (réexportés pour rétrocompat) ─────────────────────────
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


# ════════════════════════════════════════════════════════════════════════════
# SpecGeneratorService
# ════════════════════════════════════════════════════════════════════════════

class SpecGeneratorService:
    """
    Service de génération de specs techniques LCCA.

    SPEC-01 : si direct_pattern est fourni, utilise 1 seul appel LLM
    (SpecDirectPattern — ~120s) au lieu du pipeline 2 appels (~360s).

    Rétrocompat : si reasoning + formatter sont fournis sans direct_pattern,
    bascule sur l'ancien comportement (tests avec mocks).

    SPEC-02 : _build_technical_context() injecte le code source réel des fichiers
    LCCA pertinents dans le prompt pour des specs ancrées, non génériques.
    """

    def __init__(
        self,
        reasoning=None,
        formatter=None,
        validator: "SpecValidatorService | None" = None,
        direct_pattern: "SpecDirectPattern | None" = None,
    ) -> None:
        self._reasoning = reasoning
        self._formatter = formatter
        self._direct    = direct_pattern

        if validator is None:
            from core.spec_validator import SpecValidatorService
            validator = SpecValidatorService()
        self._validator = validator

    def generate(self, prompt: str, context: str = "", domain: str = "global") -> "SpecEntry":
        """
        Génère une SpecEntry complète à partir d'un prompt.

        SPEC-01 : utilise SpecDirectPattern (1 LLM) si disponible.
        SPEC-02 : enrichit le contexte avec _build_technical_context().

        Args:
            prompt  : description de la tâche à spécifier.
            context : contexte additionnel (specs RAG, contraintes user).
            domain  : domaine V7.2 (défaut : "global").

        Returns:
            SpecEntry complète avec score, validated, domain, generated_by.
        """
        from core.spec_entry import SpecEntry

        technical_context = _build_technical_context(prompt, domain, context)

        if self._direct is not None:
            body_md = self._direct.run(prompt, technical_context)
        else:
            reasoned = self._reasoning.run(prompt, technical_context) if self._reasoning else prompt
            body_md  = self._formatter.run(reasoned, technical_context) if self._formatter else reasoned

        if not body_md or not body_md.strip():
            body_md = (
                f"<!-- AI-READY | {prompt[:60]} | Version 7.2.0 -->\n\n"
                f"## Titre\n{prompt[:100]}\n\n"
                f"## Abstract\nSpec pour : {prompt}\n\n"
                f"## Corps\n[Génération LLM indisponible — compléter manuellement]\n\n"
                f"## Interfaces et Contrats\nN/A — génération LLM indisponible\n\n"
                f"## Règles Invariantes LCCA\n1. Règle 11 : spec non validée → pas de génération de code.\n\n"
                f"## Critères d'Acceptation\n- [ ] Compléter manuellement\n\n"
                f"## Risques et Mitigations\n| Risque | Probabilité | Mitigation |\n"
                f"|--------|-------------|------------|\n| LLM indisponible | haute | Compléter manuellement |\n"
            )

        title            = _extract_title(body_md)
        abstract         = _extract_abstract(body_md)
        complexity_score = _compute_complexity(body_md)

        spec = SpecEntry(
            spec_id          = SpecEntry.make_spec_id(body_md),
            title            = title,
            abstract         = abstract,
            body_md          = body_md,
            complexity_score = complexity_score,
            domain           = domain,
            generated_by     = "hybrid",
        )

        result = self._validator.validate(spec)
        spec.score            = result["score"]
        spec.validated        = result["valid"]
        spec.validation_notes = result.get("validation_notes", "")

        return spec

    def auto_fix(self, spec: "SpecEntry", max_iter: int | None = None) -> "SpecEntry":
        """
        Tente d'améliorer la spec via le LLM jusqu'à ce qu'elle soit valide.

        Court-circuit (Sprint 18 — Dette 10) :
          Si le score ne progresse pas d'au moins 0.05, arrêt immédiat.

        SPEC-01 : utilise self._direct pour auto_fix si disponible.

        Args:
            spec     : SpecEntry à corriger (modifiée en place).
            max_iter : Override config.SPEC_AUTO_FIX_MAX_ITERATIONS.

        Returns:
            La spec potentiellement améliorée.
        """
        import config
        iterations = max_iter if max_iter is not None else config.SPEC_AUTO_FIX_MAX_ITERATIONS

        _MIN_SCORE_DELTA = 0.05
        previous_score: float | None = None

        for _ in range(iterations):
            result = self._validator.validate(spec)

            result_valid      = result["valid"]
            result_score      = result["score"]
            result_violations = result.get("violations", [])

            if result_valid:
                spec.score     = result_score
                spec.validated = True
                break

            if previous_score is not None:
                if result_score - previous_score < _MIN_SCORE_DELTA:
                    spec.score = result_score
                    break

            previous_score = result_score

            if result_violations:
                if isinstance(result_violations[0], dict):
                    violations_text = "\n".join(
                        v.get("fix_suggestion", str(v)) for v in result_violations
                    )
                else:
                    violations_text = "\n".join(str(v) for v in result_violations)
            else:
                violations_text = "(aucune violation listée)"

            fix_context = f"Violations à corriger :\n{violations_text}"

            if self._direct is not None:
                new_body = self._direct.run(spec.body_md, fix_context)
            elif self._formatter is not None:
                new_body = self._formatter.run(spec.body_md, context=fix_context)
            else:
                break

            if not new_body or not new_body.strip():
                break

            from core.spec_entry import SpecEntry as _SE
            spec.body_md          = new_body
            spec.title            = _extract_title(new_body)
            spec.abstract         = _extract_abstract(new_body)
            spec.spec_id          = _SE.make_spec_id(new_body)
            spec.complexity_score = _compute_complexity(new_body)

            final_result = self._validator.validate(spec)
            spec.score   = final_result["score"]

        return spec

    def generate_with_retry(self, prompt: str, context: str = "", domain: str = "global") -> "SpecEntry":
        """
        V9-09 — Adaptive Spec Retry.

        Génère une spec puis, si elle n'est pas usable, tente UNE correction via auto_fix().
        Configurable par config.SPEC_RETRY_ON_FAIL (défaut True).

        Args:
            prompt  : description de la tâche à spécifier.
            context : contexte additionnel.
            domain  : domaine V7.2.

        Returns:
            SpecEntry validée ou mieux-scorée disponible.
        """
        import config
        spec = self.generate(prompt, context, domain)
        if spec.is_usable():
            return spec
        retry_enabled = getattr(config, "SPEC_RETRY_ON_FAIL", True)
        if not retry_enabled:
            return spec
        return self.auto_fix(spec, max_iter=1)
