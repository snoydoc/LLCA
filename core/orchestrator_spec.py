# -*- coding: utf-8-sig -*-
"""
orchestrator_spec.py — Mixin Spec Layer pour LCCAV5Fusion (Sprint REFACTO-01).

Extrait de orchestrator.py pour réduire sa taille de 19.1 KB à < 12 KB.

OrchestratorSpecMixin fournit _run_spec_layer() et les helpers lazy
_get_spec_generator() / _get_spec_validator().

Suppose que self._memory, self._complexity, self._spec_generator,
self._spec_validator, self.llm sont définis par LCCAV5Fusion.__init__().
"""
from __future__ import annotations

import logging

log = logging.getLogger("lcca.orchestrator_spec")


class OrchestratorSpecMixin:
    """
    Mixin Spec Layer pour LCCAV5Fusion.

    Méthodes :
        _run_spec_layer(intent) → bool
        _get_spec_generator()   → SpecGeneratorService (lazy)
        _get_spec_validator()   → SpecValidatorService (lazy)
    """

    def _get_spec_validator(self):
        if self._spec_validator is None:
            from core.spec_validator import SpecValidatorService
            self._spec_validator = SpecValidatorService()
        return self._spec_validator

    def _get_spec_generator(self):
        if self._spec_generator is None:
            from core.llm_generator import LLMGenerator
            from core.cognitive_patterns import DeepReasoningPattern, SpecFormatterPattern
            from core.spec_generator import SpecGeneratorService
            # Réutilise self.llm si disponible (LCCAV5Fusion), sinon instancie un nouveau
            llm = getattr(self, "llm", None) or LLMGenerator()
            self._spec_generator = SpecGeneratorService(
                reasoning=DeepReasoningPattern(llm),
                formatter=SpecFormatterPattern(llm),
                validator=self._get_spec_validator(),
            )
        return self._spec_generator

    def _run_spec_layer(self, intent) -> bool:
        """
        Phase adaptative Sprint 15 : décide, génère et valide une spec.

        Sprint 22 : accès dict val["valid"]/val["violations"] (plus val.valid),
        domain propagé dans generate().

        Returns:
            True  → pipeline peut continuer.
            False → spec invalide après auto-fix → exécution bloquée.
        """
        import config as _config
        from core.spec_entry import SpecEntry
        from core.spec_complexity import _infer_domain

        # Instanciation lazy des dépendances Spec Layer
        if self._memory is None:
            from core.memory_engine import MemoryEngine
            self._memory = MemoryEngine()

        if self._complexity is None:
            from core.spec_complexity import SpecComplexityEstimator
            self._complexity = SpecComplexityEstimator(self._memory)

        # 1. Estimation de la complexité
        need_spec, score = self._complexity.estimate(intent)
        log.info("Spec Layer — score=%d need_spec=%s", score, need_spec)

        if not need_spec:
            return True

        # 2. Recherche spec existante en mémoire
        collection = getattr(_config, "SPEC_MEMORY_COLLECTION", "lcca_specs")
        existing = self._memory.search(query=intent.raw, wing="lcca", n=3)
        usable_entries = []
        for entries in existing.values():
            for e in entries:
                try:
                    s = SpecEntry.from_dict(e.metadata if hasattr(e, "metadata") else e)
                    if s.is_usable():
                        usable_entries.append(s)
                except Exception:
                    pass

        if usable_entries:
            spec = usable_entries[0]
            spec.usage_count += 1
            log.info("Spec réutilisée depuis mémoire : %s", spec.spec_id)
            return True

        # 3. Génération nouvelle spec avec domain propagé (Sprint 22)
        domain = _infer_domain(intent)
        try:
            spec = self._get_spec_generator().generate(
                prompt=intent.raw,
                context=f"domain:{domain}",
                domain=domain,
            )
        except Exception as exc:
            log.error("Erreur génération spec : %s", exc)
            return False

        # 4. Validation + auto-fix — accès dict V7.2 (Sprint 22)
        val = self._get_spec_validator().validate(spec)
        if not val["valid"]:
            spec = self._get_spec_generator().auto_fix(spec)
            val = self._get_spec_validator().validate(spec)

        if not val["valid"]:
            try:
                self._memory.store(
                    collection="lcca_failures",
                    payload={
                        **spec.to_dict(),
                        "failure_reason": str(val["violations"]),
                    },
                )
            except Exception:
                pass
            log.error(
                "Spec non validable après auto-fix — arrêt. Violations: %s",
                val["violations"],
            )
            return False

        # 5. Spec valide → stockage lcca_specs
        try:
            self._memory.store(collection=collection, payload=spec.to_dict())
        except Exception:
            pass
        log.info(
            "Nouvelle spec générée et stockée : %s (domain=%s, validated=%s)",
            spec.spec_id, spec.domain, spec.validated,
        )
        return True
