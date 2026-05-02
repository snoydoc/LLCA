# -*- coding: utf-8-sig -*-
"""
test_v9_01_a.py — Sprint V9-01-A : keep_alive + options GPU/threads/mmap
Verifie que OllamaClient transmet correctement keep_alive et les options
GPU/threads/mmap dans tous les payloads envoyes a Ollama.
Aucune dependance Ollama reelle (mocks uniquement).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Ajout du chemin racine pour l'import de config et core
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from core.llm_generator import (
    OllamaClient,
    LLMGenerator,
    _load_config,
    _cfg_read,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _stream_lines(*tokens: str, done_token: str = "") -> list[bytes]:
    """Construit une liste de lignes JSON simulant un stream Ollama /api/generate."""
    lines = [json.dumps({"response": t, "done": False}).encode() for t in tokens]
    lines.append(json.dumps({"response": done_token, "done": True}).encode())
    return lines


def _chat_stream_lines(*tokens: str) -> list[bytes]:
    """Construit des lignes JSON simulant un stream Ollama /api/chat."""
    lines = [json.dumps({"message": {"content": t}, "done": False}).encode() for t in tokens]
    lines.append(json.dumps({"message": {"content": ""}, "done": True}).encode())
    return lines


def _make_stream_mock(lines: list[bytes]) -> MagicMock:
    mock = MagicMock()
    mock.__iter__ = lambda s: iter(lines)
    mock.__enter__ = lambda s: mock
    mock.__exit__ = MagicMock(return_value=False)
    return mock


# ── Tests OllamaClient._ollama_options ───────────────────────────────────────

class TestOllamaOptions(unittest.TestCase):
    """_ollama_options() doit lire config et retourner le bon dict."""

    def _client(self, **kw) -> OllamaClient:
        defaults = dict(base_url="http://localhost:11434", model="qwen2.5-coder:7b",
                        timeout=None, max_tokens=800, keep_alive="30m")
        defaults.update(kw)
        return OllamaClient(**defaults)

    def test_options_keys_present(self):
        """Toutes les cles requises sont presentes."""
        c = self._client()
        opts = c._ollama_options()
        self.assertIn("num_predict", opts)
        self.assertIn("num_thread", opts)
        self.assertIn("num_gpu", opts)
        self.assertIn("use_mmap", opts)

    def test_num_predict_equals_max_tokens(self):
        """num_predict == max_tokens passe au constructeur."""
        c = self._client(max_tokens=500)
        self.assertEqual(c._ollama_options()["num_predict"], 500)

    def test_num_gpu_from_config(self):
        """num_gpu lit OLLAMA_NUM_GPU depuis config (valeur 99 en V9)."""
        c = self._client()
        opts = c._ollama_options()
        # config.OLLAMA_NUM_GPU = 99 en V9 ; si config absent -> 0 (defaut)
        self.assertIn(opts["num_gpu"], (0, 99))  # accepte les deux selon env

    def test_use_mmap_is_bool(self):
        """use_mmap retourne un booleen."""
        c = self._client()
        self.assertIsInstance(c._ollama_options()["use_mmap"], bool)

    def test_options_without_config(self):
        """Sans config importable, les valeurs par defaut sont utilisees."""
        c = self._client(max_tokens=256)
        with patch("core.ollama_client.cfg_read", side_effect=lambda k, d=None: d):
            opts = c._ollama_options()
        self.assertEqual(opts["num_thread"], 4)
        self.assertEqual(opts["num_gpu"], 0)
        self.assertTrue(opts["use_mmap"])
        self.assertEqual(opts["num_predict"], 256)


# ── Tests keep_alive dans les payloads ───────────────────────────────────────

class TestKeepAlivePayload(unittest.TestCase):
    """keep_alive doit apparaitre dans les payloads /api/generate et /api/chat."""

    def _client(self, keep_alive: str = "30m") -> OllamaClient:
        return OllamaClient(
            base_url="http://localhost:11434",
            model="qwen2.5-coder:7b",
            timeout=None,
            max_tokens=800,
            keep_alive=keep_alive,
        )

    def test_generate_payload_contains_keep_alive(self):
        """OllamaClient.generate() transmet keep_alive dans le payload."""
        captured = {}

        def fake_urlopen(req, timeout=None):
            body = json.loads(req.data.decode("utf-8"))
            captured["keep_alive"] = body.get("keep_alive")
            return _make_stream_mock(_stream_lines("def foo(): pass"))

        c = self._client(keep_alive="20m")
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            c.generate("sys", "user")

        self.assertEqual(captured.get("keep_alive"), "20m")

    def test_chat_payload_contains_keep_alive(self):
        """OllamaClient.chat() transmet keep_alive dans le payload."""
        captured = {}

        def fake_urlopen(req, timeout=None):
            body = json.loads(req.data.decode("utf-8"))
            captured["keep_alive"] = body.get("keep_alive")
            return _make_stream_mock(_chat_stream_lines("ok"))

        c = self._client(keep_alive="15m")
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            c.chat("sys", [{"role": "user", "content": "hello"}])

        self.assertEqual(captured.get("keep_alive"), "15m")

    def test_generate_stream_payload_contains_keep_alive(self):
        """OllamaClient.generate_stream() transmet keep_alive."""
        captured = {}

        def fake_urlopen(req, timeout=None):
            body = json.loads(req.data.decode("utf-8"))
            captured["keep_alive"] = body.get("keep_alive")
            return _make_stream_mock(_stream_lines("token"))

        c = self._client(keep_alive="5m")
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            c.generate_stream("sys", "user", lambda t: None)

        self.assertEqual(captured.get("keep_alive"), "5m")


# ── Tests _load_config (plus de renommage fantome) ───────────────────────────

class TestLoadConfig(unittest.TestCase):
    """_load_config() ne doit plus renommer :7b en :7b-Q4_K_M."""

    def test_model_unchanged_when_quantized_true(self):
        """OLLAMA_QUANTIZED=True ne doit pas modifier le nom du modele."""
        fake_cfg = SimpleNamespace(
            OLLAMA_MODEL="qwen2.5-coder:7b",
            OLLAMA_URL="http://localhost:11434",
            OLLAMA_TIMEOUT=None,
            OLLAMA_MAX_TOKENS=800,
            LLM_CACHE_DIR=Path("/tmp/cache"),
            OLLAMA_QUANTIZED=True,
            OLLAMA_QUANT_LEVEL="Q4_K_M",
        )
        with patch.dict("sys.modules", {"config": fake_cfg}):
            cfg = _load_config()
        self.assertEqual(cfg["model"], "qwen2.5-coder:7b")

    def test_model_unchanged_with_override(self):
        """model_override passe tel quel, sans renommage."""
        fake_cfg = SimpleNamespace(
            OLLAMA_MODEL="qwen2.5-coder:7b",
            OLLAMA_URL="http://localhost:11434",
            OLLAMA_TIMEOUT=None,
            OLLAMA_MAX_TOKENS=800,
            LLM_CACHE_DIR=Path("/tmp/cache"),
        )
        with patch.dict("sys.modules", {"config": fake_cfg}):
            cfg = _load_config(model_override="qwen2.5-coder:3b")
        self.assertEqual(cfg["model"], "qwen2.5-coder:3b")

    def test_fallback_without_config(self):
        """Sans config, _load_config() retourne les valeurs par defaut."""
        import sys as _sys
        saved = _sys.modules.pop("config", None)
        try:
            cfg = _load_config()
            self.assertIn("url", cfg)
            self.assertIn("model", cfg)
            self.assertIn("timeout", cfg)
        finally:
            if saved is not None:
                _sys.modules["config"] = saved


# ── Tests LLMGenerator.keep_alive transmis a OllamaClient ────────────────────

class TestLLMGeneratorKeepAlive(unittest.TestCase):
    """LLMGenerator doit lire OLLAMA_KEEP_ALIVE et le passer a OllamaClient."""

    def test_keep_alive_from_config(self):
        """LLMGenerator lit OLLAMA_KEEP_ALIVE depuis config."""
        fake_cfg = SimpleNamespace(
            OLLAMA_MODEL="qwen2.5-coder:7b",
            OLLAMA_URL="http://localhost:11434",
            OLLAMA_TIMEOUT=None,
            OLLAMA_MAX_TOKENS=800,
            LLM_CACHE_DIR=Path("/tmp/lcca_cache_test"),
            OLLAMA_KEEP_ALIVE="30m",
            OLLAMA_THREADS=4,
            OLLAMA_NUM_GPU=99,
            OLLAMA_MMAP=True,
        )
        with patch.dict("sys.modules", {"config": fake_cfg}):
            gen = LLMGenerator()
        self.assertEqual(gen.ollama.keep_alive, "30m")

    def test_keep_alive_explicit_overrides_config(self):
        """Le parametre keep_alive explicite prime sur config."""
        fake_cfg = SimpleNamespace(
            OLLAMA_MODEL="qwen2.5-coder:7b",
            OLLAMA_URL="http://localhost:11434",
            OLLAMA_TIMEOUT=None,
            OLLAMA_MAX_TOKENS=800,
            LLM_CACHE_DIR=Path("/tmp/lcca_cache_test"),
            OLLAMA_KEEP_ALIVE="30m",
            OLLAMA_THREADS=4,
            OLLAMA_NUM_GPU=99,
            OLLAMA_MMAP=True,
        )
        with patch.dict("sys.modules", {"config": fake_cfg}):
            gen = LLMGenerator(keep_alive="2h")
        self.assertEqual(gen.ollama.keep_alive, "2h")

    def test_default_keep_alive_if_no_config(self):
        """Sans config, keep_alive vaut '5m' (valeur defaut OllamaClient).
        Note : config est deja importe par le processus pytest, donc on utilise
        monkeypatch via un attribut temporaire plutot que de depoper sys.modules.
        """
        import config as _cfg
        import sys as _sys
        # Supprimer temporairement OLLAMA_KEEP_ALIVE de config
        had_attr = hasattr(_cfg, "OLLAMA_KEEP_ALIVE")
        original = getattr(_cfg, "OLLAMA_KEEP_ALIVE", None)
        if had_attr:
            delattr(_cfg, "OLLAMA_KEEP_ALIVE")
        try:
            gen = LLMGenerator()
            self.assertEqual(gen.ollama.keep_alive, "5m")
        finally:
            if had_attr:
                setattr(_cfg, "OLLAMA_KEEP_ALIVE", original)


if __name__ == "__main__":
    unittest.main()
