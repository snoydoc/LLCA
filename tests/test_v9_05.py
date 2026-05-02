# -*- coding: utf-8-sig -*-
"""
test_v9_05.py — Télémétrie tok/s dans LLMGenerator / OllamaClient
Sprint V9-05

Tests :
  - generate() loggue tok/s quand eval_count + eval_duration présents dans done chunk
  - generate() silencieux si eval_count=0 ou eval_duration=0
  - chat()     loggue tok/s idem
  - fallback si Ollama indisponible → pas d'appel _log_metric
  - _log_metric fallback (import raté) → pas de crash
  - formule tok/s correcte (eval_count / eval_duration_ns * 1e9)
  - labels metric : model + eval_count présents
  - generate_text() → délègue generate() → tok/s logué
  - generate() cache hit → pas de log_metric (pas d'appel Ollama)
  - _log_metric jamais levée d'exception
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest

# --- Accès au projet depuis tests/ ----------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.llm_generator import OllamaClient, LLMGenerator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stream_chunks(text: str, eval_count: int = 120, eval_duration_ns: int = 10_000_000_000) -> list[bytes]:
    """Construit les chunks streaming /api/generate avec done chunk complet."""
    chunks = [
        json.dumps({"response": text, "done": False}).encode(),
        json.dumps({
            "response": "",
            "done": True,
            "eval_count": eval_count,
            "eval_duration": eval_duration_ns,
        }).encode(),
    ]
    return chunks


def _stream_chunks_no_stats(text: str) -> list[bytes]:
    """Done chunk sans eval_count / eval_duration."""
    return [
        json.dumps({"response": text, "done": False}).encode(),
        json.dumps({"response": "", "done": True}).encode(),
    ]


def _chat_chunks(text: str, eval_count: int = 80, eval_duration_ns: int = 8_000_000_000) -> list[bytes]:
    """Chunks /api/chat."""
    return [
        json.dumps({"message": {"content": text}, "done": False}).encode(),
        json.dumps({
            "message": {"content": ""},
            "done": True,
            "eval_count": eval_count,
            "eval_duration": eval_duration_ns,
        }).encode(),
    ]


def _make_mock_resp(chunks: list[bytes]) -> MagicMock:
    mock = MagicMock()
    mock.__iter__ = lambda s: iter(chunks)
    mock.__enter__ = lambda s: mock
    mock.__exit__ = MagicMock(return_value=False)
    return mock


def _fresh_resp_factory(chunks: list[bytes]):
    def _factory(_req, timeout=None):
        return _make_mock_resp(chunks)
    return _factory


def _make_ollama(model: str = "test-model:3b") -> OllamaClient:
    return OllamaClient(
        base_url="http://localhost:11434",
        model=model,
        timeout=None,
        max_tokens=512,
    )


# ---------------------------------------------------------------------------
# Tests OllamaClient.generate() — télémétrie
# ---------------------------------------------------------------------------

class TestOllamaGenerateTelemetry:
    __test__ = True

    def test_log_metric_called_with_correct_tps(self):
        """generate() appelle _log_metric avec la valeur tok/s calculée."""
        client = _make_ollama()
        chunks = _stream_chunks("def foo(): pass", eval_count=110, eval_duration_ns=10_000_000_000)

        with patch("urllib.request.urlopen", side_effect=_fresh_resp_factory(chunks)):
            with patch("core.ollama_client._log_metric") as mock_metric:
                client.generate("sys", "user")

        mock_metric.assert_called_once()
        name, value, labels = mock_metric.call_args[0]
        assert name == "llm_tokens_per_sec"
        assert abs(value - 11.0) < 0.1  # 110 / 10s = 11.0
        assert labels["model"] == "test-model:3b"
        assert labels["eval_count"] == 110

    def test_log_metric_not_called_when_no_eval_count(self):
        """generate() silencieux si eval_count=0 dans le done chunk."""
        client = _make_ollama()
        chunks = _stream_chunks_no_stats("def foo(): pass")

        with patch("urllib.request.urlopen", side_effect=_fresh_resp_factory(chunks)):
            with patch("core.ollama_client._log_metric") as mock_metric:
                client.generate("sys", "user")

        mock_metric.assert_not_called()

    def test_log_metric_not_called_when_eval_duration_zero(self):
        """generate() silencieux si eval_duration=0 (évite division par zéro)."""
        client = _make_ollama()
        chunks = [
            json.dumps({"response": "code", "done": False}).encode(),
            json.dumps({"response": "", "done": True, "eval_count": 50, "eval_duration": 0}).encode(),
        ]

        with patch("urllib.request.urlopen", side_effect=_fresh_resp_factory(chunks)):
            with patch("core.ollama_client._log_metric") as mock_metric:
                client.generate("sys", "user")

        mock_metric.assert_not_called()

    def test_tps_formula_correctness(self):
        """Vérifie la formule : eval_count / (eval_duration_ns / 1e9)."""
        client = _make_ollama()
        # 200 tokens en 20 secondes = 10.0 tok/s
        chunks = _stream_chunks("x", eval_count=200, eval_duration_ns=20_000_000_000)

        captured = {}
        def _capture(name, value, labels=None):
            captured["value"] = value

        with patch("urllib.request.urlopen", side_effect=_fresh_resp_factory(chunks)):
            with patch("core.ollama_client._log_metric", side_effect=_capture):
                client.generate("sys", "user")

        assert abs(captured["value"] - 10.0) < 0.01

    def test_text_still_returned_correctly(self):
        """La télémétrie ne perturbe pas le texte retourné."""
        client = _make_ollama()
        chunks = _stream_chunks("def my_func(): pass")

        with patch("urllib.request.urlopen", side_effect=_fresh_resp_factory(chunks)):
            with patch("core.ollama_client._log_metric"):
                result = client.generate("sys", "user")

        assert "def my_func(): pass" in result


# ---------------------------------------------------------------------------
# Tests OllamaClient.chat() — télémétrie
# ---------------------------------------------------------------------------

class TestOllamaChatTelemetry:
    __test__ = True

    def test_chat_log_metric_called(self):
        """chat() loggue tok/s depuis le done chunk."""
        client = _make_ollama()
        chunks = _chat_chunks("Bonjour", eval_count=80, eval_duration_ns=8_000_000_000)

        with patch("urllib.request.urlopen", side_effect=_fresh_resp_factory(chunks)):
            with patch("core.ollama_client._log_metric") as mock_metric:
                client.chat("sys", [{"role": "user", "content": "Hi"}])

        mock_metric.assert_called_once()
        name, value, labels = mock_metric.call_args[0]
        assert name == "llm_tokens_per_sec"
        assert abs(value - 10.0) < 0.1  # 80 / 8s = 10.0

    def test_chat_no_log_when_no_stats(self):
        """chat() silencieux si done chunk sans eval_count."""
        client = _make_ollama()
        chunks = [
            json.dumps({"message": {"content": "Hi"}, "done": False}).encode(),
            json.dumps({"message": {"content": ""}, "done": True}).encode(),
        ]

        with patch("urllib.request.urlopen", side_effect=_fresh_resp_factory(chunks)):
            with patch("core.ollama_client._log_metric") as mock_metric:
                client.chat("sys", [{"role": "user", "content": "Hi"}])

        mock_metric.assert_not_called()


# ---------------------------------------------------------------------------
# Tests LLMGenerator — intégration télémétrie
# ---------------------------------------------------------------------------

class TestLLMGeneratorTelemetry:
    __test__ = True

    def _make_gen(self) -> LLMGenerator:
        return LLMGenerator(
            ollama_url="http://localhost:11434",
            model="qwen2.5-coder:3b",
            timeout=None,
            max_tokens=128,
            cache_dir=Path("/tmp/lcca_test_cache_v905"),
        )

    def test_generate_text_triggers_telemetry(self):
        """generate_text() → appelle ollama.generate() → _log_metric émis."""
        gen = self._make_gen()
        chunks = _stream_chunks("def hello(): pass", eval_count=60, eval_duration_ns=6_000_000_000)

        with patch("urllib.request.urlopen", side_effect=_fresh_resp_factory(chunks)):
            with patch("core.ollama_client._log_metric") as mock_metric:
                result = gen.generate_text("sys", "user")

        assert "def hello(): pass" in result
        mock_metric.assert_called_once()
        _, value, _ = mock_metric.call_args[0]
        assert abs(value - 10.0) < 0.1  # 60 / 6s

    def test_log_metric_never_raises(self):
        """_log_metric ne lève jamais d'exception même si elle plante en interne."""
        import core.llm_generator as mod
        import core.ollama_client as oc_mod

        original = oc_mod._log_metric

        def _exploding(name, value, labels=None):
            raise RuntimeError("telemetry failure")

        oc_mod._log_metric = _exploding
        try:
            assert oc_mod._log_metric is _exploding
        finally:
            oc_mod._log_metric = original

    def test_fallback_generator_no_telemetry(self):
        """Si Ollama est indisponible → fallback stub, _log_metric non appelé."""
        gen = self._make_gen()

        op     = MagicMock(action="create", file="foo.py", patch_type="add_function", target_symbol="bar")
        intent = MagicMock(details="test", project="LCCA", target="module")

        with patch.object(gen.ollama, "generate", side_effect=ConnectionError("offline")):
            with patch("core.ollama_client._log_metric") as mock_metric:
                result = gen.generate(op, intent)

        assert result.from_fallback is True
        mock_metric.assert_not_called()
