# -*- coding: utf-8-sig -*-
"""
nl_parser.py — LCCA V5 Fusion
Sprint 10 — TASK-10-01

Traduit une commande en langage naturel vers un Intent structuré,
via Qwen2.5-Coder (ou tout modèle Ollama compatible).

Sprint REFACTO-01 — NLIntent extrait dans nl_intent.py,
                    NLPromptBuilder + NLIntentExtractor extraits dans nl_intent_builder.py.
                    Rétrocompat : tous les types restent importables depuis ce module.

ED-04 — Ajout patterns regex Educator (EDUCATOR_RUN, EDUCATOR_DIFF)
         + méthode parse_nl_intent() pour routing enum NlIntent
         + alias NlParser = NLParser pour rétrocompat tests ED-04

Architecture :
    NLParser          — Interface publique : phrase → NLIntent (dataclass LLM)
    parse_nl_intent() — Routing regex → NlIntent (enum ED-04)
    NLIntentExtractor — (dans nl_intent_builder.py) — parse le JSON du LLM
    NLPromptBuilder   — (dans nl_intent_builder.py) — construit le prompt
"""

from __future__ import annotations

import logging
import re
import unicodedata
import urllib.request
import urllib.error
from typing import Optional, Tuple

# Types + builders (re-exportes pour retrocompat)
from core.nl_intent import NLIntent, NlIntent, VALID_ACTIONS  # noqa: F401
from core.nl_intent_builder import NLPromptBuilder, NLIntentExtractor  # noqa: F401

log = logging.getLogger("lcca.nl_parser")

# ---------------------------------------------------------------------------
# Patterns regex Educator (ED-04)
# CES PATTERNS DOIVENT RESTER AVANT LES PATTERNS GENERAUX (ordre critique)
# ---------------------------------------------------------------------------
_EDUCATOR_RUN_RE = re.compile(
    r"(?:lance|demarre|run|start|execute)\s+(?:l[ae]\s+)?(?:curator|educator|curation)",
    re.IGNORECASE,
)
_EDUCATOR_DIFF_RE = re.compile(
    r"(?:diff|rapport|preview|apercu)\s+(?:educator|curator|curation)",
    re.IGNORECASE,
)

# Constantes par defaut
_DEFAULT_OLLAMA_URL = "http://localhost:11434"
_DEFAULT_NL_MODEL   = "qwen2.5-coder:7b"
_DEFAULT_TIMEOUT    = 90
_DEFAULT_MAX_TOKENS = 256


def _load_nl_config() -> dict:
    """Charge la config depuis config.py si disponible, sinon utilise les defauts."""
    try:
        import config  # type: ignore
        return {
            "url":        getattr(config, "OLLAMA_URL",     _DEFAULT_OLLAMA_URL),
            "model":      getattr(config, "NL_MODEL", getattr(config, "OLLAMA_MODEL", _DEFAULT_NL_MODEL)),
            "timeout":    getattr(config, "OLLAMA_TIMEOUT", _DEFAULT_TIMEOUT),
            "max_tokens": getattr(config, "NL_MAX_TOKENS",  _DEFAULT_MAX_TOKENS),
        }
    except ImportError:
        return {
            "url":        _DEFAULT_OLLAMA_URL,
            "model":      _DEFAULT_NL_MODEL,
            "timeout":    _DEFAULT_TIMEOUT,
            "max_tokens": _DEFAULT_MAX_TOKENS,
        }


def parse_nl_intent(text: str) -> Tuple[Optional[NlIntent], dict]:
    """
    ED-04 — Routing regex vers NlIntent enum (patterns specifiques avant generaux).

    Returns:
        (NlIntent, params) si un pattern specifique est reconnu,
        (None, {}) sinon (deleguer au pipeline LLM classique).
    """
    # Normalisation NFD pour les accents (regle LCCA patterns NL francais)
    src = unicodedata.normalize("NFD", text)
    # Educator patterns — ordre: diff AVANT run pour eviter faux positifs
    if _EDUCATOR_DIFF_RE.search(src):
        return NlIntent.EDUCATOR_DIFF, {}
    if _EDUCATOR_RUN_RE.search(src):
        return NlIntent.EDUCATOR_RUN, {}
    return None, {}


# ---------------------------------------------------------------------------
# NLParser — Interface publique
# ---------------------------------------------------------------------------

class NLParser:
    """
    Traduit une commande en langage naturel vers un NLIntent structure.

    Usage :
        parser = NLParser()
        intent = parser.parse("Ajoute une fonction validate_phone dans core/utils.py")
        print(intent.action)        # "add_function"
        print(intent.target_file)   # "core/utils.py"
        print(intent.confidence)    # 0.95

    Si Ollama est indisponible :
        intent.from_fallback == True
        intent.confidence <= 0.3
    """

    def __init__(
        self,
        ollama_url:  str | None = None,
        model:       str | None = None,
        timeout:     int | None = None,
        max_tokens:  int | None = None,
    ) -> None:
        cfg = _load_nl_config()

        self._url        = ollama_url or cfg["url"]
        self._model      = model      or cfg["model"]
        self._timeout    = timeout    or cfg["timeout"]
        self._max_tokens = max_tokens or cfg["max_tokens"]

        self._prompt_builder = NLPromptBuilder()
        self._extractor      = NLIntentExtractor()

        log.info(
            "NLParser init — model=%s url=%s timeout=%ds",
            self._model, self._url, self._timeout
        )

    def parse(
        self,
        command:       str,
        project_files: list[str] | None = None,
    ) -> NLIntent:
        """
        Parse une commande NL -> NLIntent (dataclass).

        Args:
            command       : Commande en langage naturel.
            project_files : Liste optionnelle des fichiers du projet.

        Returns:
            NLIntent structure. Toujours retourne quelque chose (jamais d'exception).
        """
        if not command.strip():
            return NLIntent(
                action        = "unknown",
                description   = "",
                raw_command   = command,
                confidence    = 0.0,
                from_fallback = True,
            )

        system, user = self._prompt_builder.build(command, project_files)

        try:
            raw = self._call_ollama(system, user)
            intent = self._extractor.extract(raw, command)
            log.info(
                "NLParser resultat — action=%s file=%s symbol=%s conf=%.2f fallback=%s",
                intent.action, intent.target_file, intent.symbol,
                intent.confidence, intent.from_fallback,
            )
            return intent

        except ConnectionError as exc:
            log.warning("Ollama inaccessible pour NLParser (%s) — fallback heuristique", exc)
            return self._extractor._heuristic_fallback(command)

    def parse_intent(self, text: str) -> Tuple[Optional[NlIntent], dict]:
        """
        ED-04 — Methode d'instance delegant vers parse_nl_intent() module-level.
        Retourne (NlIntent, params) ou (None, {}) si pas de pattern specifique.
        """
        return parse_nl_intent(text)

    def is_available(self) -> bool:
        """Verifie si Ollama est accessible."""
        try:
            url = f"{self._url}/api/tags"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _call_ollama(self, system: str, user: str) -> str:
        """
        Appel HTTP vers /api/chat d'Ollama.
        Utilise uniquement urllib.request (stdlib, pas de requests/httpx).

        Returns:
            Reponse brute du modele (str).

        Raises:
            ConnectionError : Si Ollama est inaccessible.
            RuntimeError    : Si la reponse est malformee.
        """
        import json as _json

        url = f"{self._url}/api/chat"
        payload = {
            "model":  self._model,
            "stream": False,
            "options": {
                "num_predict": self._max_tokens,
                "temperature": 0.1,
                "top_p":       0.9,
            },
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        }

        data = _json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            url,
            data    = data,
            headers = {"Content-Type": "application/json"},
            method  = "POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise ConnectionError(f"Ollama inaccessible ({self._url}): {exc}") from exc

        try:
            parsed = _json.loads(body)
            return parsed["message"]["content"]
        except (KeyError, _json.JSONDecodeError) as exc:
            raise RuntimeError(f"Reponse Ollama malformee: {body[:200]}") from exc


# ED-04 : alias pour rétrocompat tests (NlParser = NLParser)
NlParser = NLParser
