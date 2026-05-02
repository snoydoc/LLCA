# -*- coding: utf-8-sig -*-
"""
mcp_handlers_spec.py — REFACTO-10
Extrait de mcp_tool_handlers.py : handlers generate_spec et validate_spec.

Responsabilité unique : Spec Layer MCP (Sprint 15 / Sprint 22 / CTX-03/04).

McpHandlersSpec est un mixin pur : aucun __init__, aucun lifecycle.
Suppose que self._memory, self._get_spec_generator(), self._get_spec_validator()
sont définis par McpServer, et que les méthodes _build_spec_rag_context()
sont apportées par McpContextBuilders (via MRO).
"""
from __future__ import annotations

import logging
from typing import Dict

log = logging.getLogger("lcca.mcp_handlers_spec")


class McpHandlersSpec:
    """
    Mixin portant les 2 handlers tools de la Spec Layer.

    Attributs attendus du parent McpServer :
        self._memory, self._get_spec_generator(), self._get_spec_validator()
    Méthodes attendues (via McpContextBuilders dans le MRO) :
        self._build_spec_rag_context(intent, domain) -> str
    """

    def _tool_generate_spec(self, args: Dict) -> Dict:
        intent  = str(args.get("intent", "")).strip()
        domain  = str(args.get("domain", "global")).strip()
        context = str(args.get("context", ""))
        if not intent:
            raise ValueError("'intent' est requis")
        from core.spec_entry import VALID_DOMAINS
        if domain not in VALID_DOMAINS:
            domain = "global"

        # Sprint CTX-03 — enrichissement RAG : inject specs similaires mémorisées
        spec_rag = self._build_spec_rag_context(intent, domain)
        if spec_rag:
            log.debug(
                "generate_spec RAG enrichi — %d chars de specs injectés", len(spec_rag)
            )
        enriched_context = f"domain:{domain}\n{context}{spec_rag}".strip()

        generator = self._get_spec_generator()
        validator = self._get_spec_validator()
        try:
            spec = generator.generate(
                prompt=intent,
                context=enriched_context,
                domain=domain,
            )
        except Exception as e:
            raise ValueError("Erreur génération spec : %s" % e) from e
        val        = validator.validate(spec)
        violations = val["violations"]

        # Sprint CTX-04 — auto-stockage dans lcca_specs si spec valide
        if val["valid"]:
            try:
                self._memory.store(
                    collection="lcca_specs",
                    payload=spec.to_dict(),
                )
                log.info(
                    "generate_spec CTX-04 — spec stockée automatiquement : "
                    "%s (domain=%s, score=%.2f)",
                    spec.spec_id, spec.domain, val["score"],
                )
            except Exception as _store_exc:
                log.debug(
                    "generate_spec CTX-04 — stockage silencieux ignoré : %s", _store_exc
                )

        return {
            "spec_id":          spec.spec_id,
            "domain":           spec.domain,
            "version":          spec.version,
            "title":            spec.title,
            "abstract":         spec.abstract,
            "body_md":          spec.body_md,
            "complexity_score": spec.complexity_score,
            "validated":        val["valid"],
            "score":            val["score"],
            "violations":       violations,
            "validation_notes": val["validation_notes"] if val["validation_notes"] else "OK",
            "auto_stored":      val["valid"],
        }

    def _tool_validate_spec(self, args: Dict) -> Dict:
        spec_id = str(args.get("spec_id", "")).strip()
        body_md = str(args.get("body_md", "")).strip()
        if not spec_id and not body_md:
            raise ValueError("'spec_id' ou 'body_md' est requis")
        from core.spec_entry import SpecEntry, make_spec_id  # noqa: F401
        if body_md:
            spec = SpecEntry(
                spec_id=SpecEntry.make_spec_id(body_md),
                title="direct_validation",
                abstract=body_md[:200],
                body_md=body_md,
            )
        else:
            if len(spec_id) != 12 or not all(c in "0123456789abcdef" for c in spec_id):
                raise ValueError(
                    "spec_id invalide : '%s' (doit être 12 chars hex)" % spec_id
                )
            results = self._memory.search(query=spec_id, wing="lcca", n=5)
            found = None
            for entries in results.values():
                for e in entries:
                    meta = e.metadata if hasattr(e, "metadata") else {}
                    if meta.get("spec_id") == spec_id:
                        found = meta
                        break
                if found:
                    break
            if found is None:
                raise KeyError("spec_id introuvable : '%s'" % spec_id)
            try:
                spec = SpecEntry.from_dict(found)
            except Exception as e:
                raise ValueError("Impossible de reconstruire la spec : %s" % e) from e
        validator  = self._get_spec_validator()
        val        = validator.validate(spec)
        violations = val["violations"]
        blocking   = sum(
            1 for v in violations
            if isinstance(v, dict) and v.get("severity") == "blocking"
        )
        return {
            "spec_id":          spec.spec_id,
            "valid":            val["valid"],
            "score":            val["score"],
            "blocking":         blocking,
            "violations":       violations,
            "validation_notes": val["validation_notes"] if val["validation_notes"] else "OK",
        }
