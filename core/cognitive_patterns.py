# -*- coding: utf-8-sig -*-
"""cognitive_patterns.py - CognitivePattern ABC + 4 implementations (Sprint 14).

Sprint 16 -- bugfix : _call_llm utilisait des kwargs inexistants sur LLMGenerator.
Sprint 17 -- bugfix : _call_llm garantit toujours un retour str (compatible mocks et prod).
Sprint 18 -- Dette 12 : utilise generate_text() quand disponible (interface basse propre).
Sprint 21 -- Migration V7.2 : prompts longs et detailles conformes a la spec V7.2.
SPEC-01   -- SpecDirectPattern : 1 seul appel LLM (fusion DeepReasoning+SpecFormatter).
             Evite le timeout de 360s (2x180s) sur CPU. timeout_override ajoute a _call_llm.
SPEC-02   -- Prompt _SPEC_DIRECT_SYSTEM : sections techniques obligatoires (Signatures,
             Dependances, Sequence d'Implementation, Criteres d'Acceptation verifiables).
REFACTO-12 -- Prompts extraits dans cognitive_prompts.py.
              Retrocompat : _DEEP_REASONING_SYSTEM etc. aliases vers cognitive_prompts.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.llm_generator import LLMGenerator

# Prompts -- source de verite dans cognitive_prompts.py
from core.cognitive_prompts import (
    DEEP_REASONING_SYSTEM,
    SPEC_FORMATTER_SYSTEM,
    SPEC_VALIDATOR_SYSTEM,
    SPEC_DIRECT_SYSTEM,
)

# Aliases retrocompat (tests accedent a DeepReasoningPattern._SYSTEM etc.)
_DEEP_REASONING_SYSTEM  = DEEP_REASONING_SYSTEM
_SPEC_FORMATTER_SYSTEM  = SPEC_FORMATTER_SYSTEM
_SPEC_VALIDATOR_SYSTEM  = SPEC_VALIDATOR_SYSTEM
_SPEC_DIRECT_SYSTEM     = SPEC_DIRECT_SYSTEM


# ════════════════════════════════════════════════════════════════════════════
# Classe de base
# ════════════════════════════════════════════════════════════════════════════

class CognitivePattern(ABC):
    """
    Classe de base pour les patterns cognitifs LCCA.

    Injection de dependances : recoit un LLMGenerator au __init__.

    _call_llm(system, user) est l'unique point d'entree vers le LLM.
    Il utilise generate_text() si disponible (Sprint 18),
    ou le chemin de compatibilite descendante sinon.

    Sprint 21 : self._gen ajoute comme alias de self._generator (spec V7.2).
    SPEC-01   : timeout_override permet de passer un timeout dedie pour les appels
                longs (generate_spec -- config.SPEC_TIMEOUT = 240s).
    """

    def __init__(self, generator: "LLMGenerator") -> None:
        self._generator = generator
        self._gen = generator  # alias V7.2 -- interne uniquement

    @abstractmethod
    def run(self, prompt: str, context: str = "") -> str: ...

    def _call_llm(self, system: str, user: str, timeout_override: "int | None" = None) -> str:
        """
        Appelle le LLM via le generateur injecte. Garantit toujours un retour str.

        SPEC-01 : timeout_override permet de surcharger temporairement ollama.timeout
        pour les appels longs (ex: generate_spec avec SPEC_TIMEOUT=240s).
        Le timeout original est restaure apres l'appel (finally).

        Strategie :
          1. Chemin propre (prod) : generate_text(system, user) -- interface basse officielle.
          2. Chemin compatibilite descendante (mocks/tests) : generator.generate().
        Regle invariante : retourne toujours une str, jamais un objet opaque.
        """
        if callable(getattr(self._generator, "generate_text", None)):
            try:
                if timeout_override is not None:
                    _ollama = getattr(self._generator, "ollama", None)
                    _orig   = getattr(_ollama, "timeout", None)
                    if _orig is not None:
                        _ollama.timeout = timeout_override
                    try:
                        result = self._generator.generate_text(system, user)
                    finally:
                        if _orig is not None:
                            _ollama.timeout = _orig
                else:
                    result = self._generator.generate_text(system, user)
                return result if isinstance(result, str) else ""
            except Exception:
                return ""

        # Chemin compatibilite descendante : mock/stub sans generate_text()
        try:
            result = self._generator.generate(system, user)
            if hasattr(result, "code"):
                val = result.code
                return val if isinstance(val, str) else str(val) if val else ""
            return result if isinstance(result, str) else ""
        except Exception:
            return ""


# ════════════════════════════════════════════════════════════════════════════
# Implementations
# ════════════════════════════════════════════════════════════════════════════

class DeepReasoningPattern(CognitivePattern):
    """
    Pattern d'analyse architecturale approfondie.
    Conserve pour retrocompat -- en prod, SpecDirectPattern le remplace (SPEC-01).
    """
    _SYSTEM = DEEP_REASONING_SYSTEM

    def run(self, prompt: str, context: str = "") -> str:
        user = (context + "\n\n" + prompt).strip() if context else prompt
        return self._call_llm(self._SYSTEM, user)


class SpecFormatterPattern(CognitivePattern):
    """
    Pattern de formatage Markdown pour les specs LCCA.
    Conserve pour retrocompat -- en prod, SpecDirectPattern le remplace (SPEC-01).
    """
    _SYSTEM = SPEC_FORMATTER_SYSTEM

    def run(self, prompt: str, context: str = "") -> str:
        user = "Contenu a formater :\n" + prompt
        if context:
            user = "Contexte :\n" + context + "\n\n" + user
        return self._call_llm(self._SYSTEM, user)


class SpecValidatorPattern(CognitivePattern):
    """
    Pattern de validation semantique des specs.
    Retourne un JSON strict avec violations detectees par le LLM.
    Sprint 21 : prompt V7.2 avec verifications architecturales LCCA.
    """
    _SYSTEM = SPEC_VALIDATOR_SYSTEM

    def run(self, prompt: str, context: str = "") -> str:
        user = "Spec a valider :\n" + prompt
        return self._call_llm(self._SYSTEM, user)


class SpecDirectPattern(CognitivePattern):
    """
    SPEC-01 : Genere une spec technique complete en UN SEUL appel LLM.

    Remplace la chaine DeepReasoningPattern -> SpecFormatterPattern (2 appels LLM,
    ~360s sur CPU) par un prompt fusionne unique (~120s sur 7b).

    SPEC-02 : Le prompt SPEC_DIRECT_SYSTEM force des sections techniques reelles :
      - Signatures de methodes avec types Python corrects
      - Types de donnees (dataclasses)
      - Sequence d'implementation fichier par fichier
      - Criteres d'acceptation verifiables par pytest
      - Risques et mitigations concrets

    Timeout : config.SPEC_TIMEOUT (240s) via timeout_override dans _call_llm.
    """
    _SYSTEM = SPEC_DIRECT_SYSTEM

    def run(self, prompt: str, context: str = "") -> str:
        """
        Genere la spec en 1 appel.

        Args:
            prompt  : intent utilisateur (ex: "module cache TTL adaptatif")
            context : contexte enrichi (domaine + specs RAG + code source reel SPEC-02)

        Returns:
            body_md complet -- spec technique directement exploitable.
        """
        import config
        spec_timeout = getattr(config, "SPEC_TIMEOUT", 240)

        user_parts = []
        if context:
            user_parts.append("## Contexte disponible\n\n" + context)
        user_parts.append("## Demande\n\n" + prompt)
        user_parts.append(
            "\n## Instructions supplementaires\n\n"
            "- Utilise le contexte ci-dessus pour rendre la spec concrete et specifique.\n"
            "- Reference les fichiers LCCA reels fournis (core/*, utils/*, config.py).\n"
            "- Les signatures de methodes doivent etre copiables directement dans le code.\n"
            "- Chaque critere d'acceptation doit etre verifiable par un test pytest.\n"
        )
        user = "\n\n".join(user_parts)

        return self._call_llm(self._SYSTEM, user, timeout_override=spec_timeout)
