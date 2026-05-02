# -*- coding: utf-8-sig -*-
"""
probe_engine.py — EVAL-02
Moteur de probe : soumet une question a OllamaClient et retourne la reponse brute.

Responsabilite unique : appel Ollama -> ProbeResponse.
Pas de logique de scoring ici.

INVARIANT TIMEOUT : timeout=OLLAMA_TIMEOUT=None -> attente infinie.
Ne jamais passer une valeur entiere a OllamaClient.timeout.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Iterator

from config import OLLAMA_MAX_TOKENS, OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_URL
from core.ollama_client import OllamaClient
from EvalLoop.evalloop_types import BenchQuestion, ProbeResponse

log = logging.getLogger("lcca.evalloop.probe")

_SYSTEM_PROMPT = (
    "Tu es un assistant technique expert en Python et en architecture logicielle. "
    "Reponds de facon precise et structuree."
)
# PAS de "Tu es LCCA" -- incorrect conceptuellement (LCCA est le systeme, pas le modele)


class ProbeEngine:
    """Soumet les questions curriculum a Ollama et collecte les reponses brutes."""

    def __init__(
        self,
        model:    str = None,
        base_url: str = None,
    ) -> None:
        _model    = model    or OLLAMA_MODEL
        _base_url = base_url or OLLAMA_URL
        self._client = OllamaClient(
            base_url   = _base_url,
            model      = _model,
            timeout    = OLLAMA_TIMEOUT,     # None -- INVARIANT ABSOLU
            max_tokens = OLLAMA_MAX_TOKENS,
        )
        self._model = _model

    def probe(self, question: BenchQuestion) -> ProbeResponse:
        """Soumet une question a Ollama et retourne la reponse brute."""
        log.info("probe -- question_id=%s domain=%s palier=%d",
                 question.id, question.domain, question.palier)
        t0 = time.monotonic()
        response = self._client.generate(
            system = _SYSTEM_PROMPT,
            user   = question.question,
        )
        duration = time.monotonic() - t0

        return ProbeResponse(
            question_id  = question.id,
            question     = question,
            response     = response,
            model        = self._model,
            duration_sec = round(duration, 2),
            timestamp    = datetime.now(timezone.utc).isoformat(),
        )

    def probe_batch(
        self,
        questions:    list[BenchQuestion],
        cooldown_sec: float = 0.0,
    ) -> Iterator[ProbeResponse]:
        """
        Probe une liste de questions avec pause optionnelle entre chaque.
        cooldown_sec=0 par defaut (pas de pause).
        Augmenter a 2.0 si contention GPU observee (SYS-03).
        """
        for q in questions:
            yield self.probe(q)
            if cooldown_sec > 0:
                time.sleep(cooldown_sec)
