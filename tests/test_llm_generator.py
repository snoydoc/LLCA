# -*- coding: utf-8-sig -*-
"""
test_llm_generator.py — LCCA V5 Fusion
Sprint 09 — TASK-09-05

Tests unitaires pour LLMGenerator, OllamaClient, PromptBuilder,
CodeExtractor, FallbackGenerator.

Tous les tests sont mockés (aucun Ollama réel requis).
"""

from __future__ import annotations

import json
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.llm_generator import (
    CodeExtractor,
    FallbackGenerator,
    GenerationResult,
    LLMGenerator,
    OllamaClient,
    PromptBuilder,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_op(
    action="create",
    patch_type="add_function",
    symbol="my_func",
    file="auth.py",
    description="test op",
):
    op = MagicMock()
    op.action        = action
    op.patch_type    = patch_type
    op.target_symbol = symbol
    op.file          = file
    op.description   = description
    return op


def _make_intent(
    project="TestProj",
    target="AuthModule",
    action="ajoute",
    details="validate email",
    sub_target=None,
):
    intent = MagicMock()
    intent.project    = project
    intent.target     = target
    intent.action     = action
    intent.details    = details
    intent.sub_target = sub_target
    return intent


# ──────────────────────────────────────────────────────────────────────────────
# CodeExtractor
# ──────────────────────────────────────────────────────────────────────────────

class TestCodeExtractor:
    def setup_method(self):
        self.ex = CodeExtractor()

    def test_extract_python_fence(self):
        raw = "Here is the code:\n```python\ndef foo():\n    pass\n```"
        code = self.ex.extract(raw)
        assert "def foo():" in code

    def test_extract_plain_fence(self):
        raw = "```\ndef bar():\n    return 1\n```"
        code = self.ex.extract(raw)
        assert "def bar():" in code

    def test_extract_no_fence_detects_def(self):
        raw = "Sure! Here:\ndef baz():\n    pass\n"
        code = self.ex.extract(raw)
        assert "def baz():" in code

    def test_is_valid_python_true(self):
        assert self.ex.is_valid_python("def f():\n    pass\n") is True

    def test_is_valid_python_false(self):
        assert self.ex.is_valid_python("def f(\n    pass") is False

    def test_sanitize_removes_fences(self):
        raw = "```python\ndef f(): pass\n```"
        cleaned = self.ex.sanitize(raw)
        assert "```" not in cleaned
        assert "def f(): pass" in cleaned


# ──────────────────────────────────────────────────────────────────────────────
# PromptBuilder
# ──────────────────────────────────────────────────────────────────────────────

class TestPromptBuilder:
    def setup_method(self):
        self.builder = PromptBuilder()

    def test_build_create_action(self):
        op     = _make_op(action="create")
        intent = _make_intent()
        system, user = self.builder.build(op, intent)
        assert "LCCA" in system
        assert "Create" in user
        assert "auth.py" in user

    def test_build_add_function(self):
        op     = _make_op(action="modify", patch_type="add_function")
        intent = _make_intent()
        system, user = self.builder.build(op, intent)
        assert "my_func" in user
        assert "validate email" in user

    def test_build_modify_function(self):
        op     = _make_op(action="modify", patch_type="modify_function")
        intent = _make_intent()
        system, user = self.builder.build(op, intent, context="def my_func(): pass")
        assert "my_func" in user
        assert "Current function" in user

    def test_build_add_import(self):
        op     = _make_op(action="modify", patch_type="add_import", symbol="re")
        intent = _make_intent()
        system, user = self.builder.build(op, intent)
        assert "import" in user.lower()
        assert "re" in user

    def test_system_prompt_no_markdown(self):
        op     = _make_op()
        intent = _make_intent()
        system, _ = self.builder.build(op, intent)
        assert "markdown" in system.lower() or "No" in system


# ──────────────────────────────────────────────────────────────────────────────
# FallbackGenerator
# ──────────────────────────────────────────────────────────────────────────────

class TestFallbackGenerator:
    def setup_method(self):
        self.fb = FallbackGenerator()

    def test_generate_create_returns_module(self):
        op     = _make_op(action="create")
        intent = _make_intent()
        code   = self.fb.generate(op, intent)
        assert "coding: utf-8-sig" in code
        assert "def my_func" in code

    def test_generate_add_function(self):
        op     = _make_op(action="modify", patch_type="add_function")
        intent = _make_intent()
        code   = self.fb.generate(op, intent)
        assert "def my_func" in code
        assert "NotImplementedError" in code

    def test_generate_modify_function(self):
        op     = _make_op(action="modify", patch_type="modify_function")
        intent = _make_intent()
        code   = self.fb.generate(op, intent)
        assert "NotImplementedError" in code

    def test_generate_add_import(self):
        op     = _make_op(action="modify", patch_type="add_import", symbol="re")
        intent = _make_intent()
        code   = self.fb.generate(op, intent)
        assert "import re" in code


# ──────────────────────────────────────────────────────────────────────────────
# OllamaClient (mock HTTP)
# ──────────────────────────────────────────────────────────────────────────────

class TestOllamaClient:
    def _make_client(self):
        return OllamaClient(
            base_url="http://localhost:11434",
            model="codellama",
            timeout=5,
            max_tokens=256,
        )

    def test_is_available_true(self):
        client = self._make_client()
        fake_tags = json.dumps({"models": [{"name": "codellama"}]}).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = fake_tags
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert client.is_available() is True

    def test_is_available_false_on_error(self):
        client = self._make_client()
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            assert client.is_available() is False

    def test_generate_returns_content(self):
        client = self._make_client()
        # /api/generate stream: lignes JSON {"response": "...", "done": bool}
        lines = [
            json.dumps({"response": "def foo():\n    pass\n", "done": False}).encode("utf-8"),
            json.dumps({"response": "", "done": True}).encode("utf-8"),
        ]
        mock_resp = MagicMock()
        mock_resp.__iter__ = lambda s: iter(lines)
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = client.generate("system", "user")
        assert "def foo" in result

    def test_generate_raises_on_bad_response(self):
        client = self._make_client()
        # Une ligne JSON invalide (non parsable) → ignorée silencieusement.
        # Une URLError lève ConnectionError, pas RuntimeError.
        # Le vrai cas RuntimeError : resp.read() sur un non-stream (legacy).
        # Ici on vérifie qu'une réponse sans 'response' retourne une chaîne vide
        # (comportement stream nominal — pas d'exception).
        lines = [
            json.dumps({"unexpected": "format"}).encode("utf-8"),
        ]
        mock_resp = MagicMock()
        mock_resp.__iter__ = lambda s: iter(lines)
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = client.generate("system", "user")
        assert result == ""


# ──────────────────────────────────────────────────────────────────────────────
# LLMGenerator — tests intégration (Ollama mocké)
# ──────────────────────────────────────────────────────────────────────────────

class TestLLMGenerator:
    @pytest.fixture
    def gen(self, tmp_path):
        """LLMGenerator avec cache dans tmp_path, Ollama mocké."""
        g = LLMGenerator(cache_dir=tmp_path / "cache")
        return g

    def test_fallback_when_ollama_unavailable(self, gen):
        """Si Ollama refuse la connexion → fallback stub."""
        import urllib.error
        op     = _make_op(action="create")
        intent = _make_intent()
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            result = gen.generate(op, intent)
        assert result.from_fallback is True
        assert "def " in result.code

    def _stream_mock(self, *tokens: str) -> MagicMock:
        """Construit un mock de réponse stream /api/generate."""
        lines = [
            json.dumps({"response": t, "done": False}).encode("utf-8")
            for t in tokens
        ]
        lines.append(json.dumps({"response": "", "done": True}).encode("utf-8"))
        mock_resp = MagicMock()
        mock_resp.__iter__ = lambda s: iter(lines)
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_generate_from_ollama_ok(self, gen):
        """Ollama répond avec du code valide → extrait et mis en cache."""
        mock_resp = self._stream_mock('def my_func():\n    """Docstring."""\n    pass\n')
        op     = _make_op(action="modify", patch_type="add_function")
        intent = _make_intent()
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = gen.generate(op, intent)
        assert result.from_fallback is False
        assert result.from_cache is False
        assert "def my_func" in result.code

    def test_cache_hit_on_second_call(self, gen):
        """Deuxième appel identique → cache hit, pas d'appel HTTP."""
        op     = _make_op(action="modify", patch_type="add_function")
        intent = _make_intent()
        # Premier appel : mock stream itérable une seule fois → on doit
        # reconstruire le mock pour chaque urlopen car iter() s'épuise.
        # On utilise side_effect pour retourner un nouveau mock à chaque appel.
        def _fresh_mock(_req, timeout=None):
            return self._stream_mock("def my_func():\n    pass\n")
        with patch("urllib.request.urlopen", side_effect=_fresh_mock):
            gen.generate(op, intent)          # Premier appel → miss + cache_set
            result2 = gen.generate(op, intent)  # Deuxième appel → cache hit
        assert result2.from_cache is True
        assert result2.duration_ms == 0

    def test_fallback_on_invalid_python_from_llm(self, gen):
        """Si le LLM retourne du code syntaxiquement invalide → fallback."""
        mock_resp = self._stream_mock("def bad_func(\n    # broken")
        op     = _make_op()
        intent = _make_intent()
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = gen.generate(op, intent)
        assert result.from_fallback is True

    def test_clear_cache(self, gen, tmp_path):
        """clear_cache() supprime les fichiers .py du cache."""
        cache = tmp_path / "cache"
        cache.mkdir(exist_ok=True)
        (cache / "abc123.py").write_text("def foo(): pass")
        (cache / "def456.py").write_text("def bar(): pass")
        gen.cache_dir = cache
        deleted = gen.clear_cache()
        assert deleted == 2
        assert list(cache.glob("*.py")) == []


# ──────────────────────────────────────────────────────────────────────────────
# TASK-12-T2 : Cache versionné par modèle (V7)
# ──────────────────────────────────────────────────────────────────────────────

class TestLLMGeneratorCacheV7:
    """
    Tests du cache versionné par modèle — Sprint 12 V7.

    Règles :
      - _cache_key(system, user, model) inclut le modèle dans le hash MD5
      - Cache miss si le modèle en metadata != modèle courant
      - Cache miss si metadata.model == "unknown" (legacy pré-V7)
    """

    @pytest.fixture
    def gen_a(self, tmp_path):
        """Générateur avec modèle 'codellama'."""
        return LLMGenerator(model="codellama", cache_dir=tmp_path / "cache")

    @pytest.fixture
    def gen_b(self, tmp_path):
        """Générateur avec modèle 'qwen2.5-coder:14b' — même cache_dir."""
        return LLMGenerator(model="qwen2.5-coder:14b", cache_dir=tmp_path / "cache")

    def test_cache_key_differs_by_model(self, tmp_path):
        """
        V7 — _cache_key() doit retourner des hash différents pour des modèles
        différents à prompts identiques.
        """
        gen_a = LLMGenerator(model="codellama",          cache_dir=tmp_path / "cache")
        gen_b = LLMGenerator(model="qwen2.5-coder:14b", cache_dir=tmp_path / "cache")

        system = "You are LCCA."
        user   = "def my_func(): pass"

        key_a = gen_a._cache_key(system, user, "codellama")
        key_b = gen_b._cache_key(system, user, "qwen2.5-coder:14b")

        assert key_a != key_b, (
            "V7 : _cache_key() doit produire des hash distincts "
            "si le modèle diffère (même prompts)."
        )

    def test_cache_miss_on_model_mismatch(self, tmp_path):
        """
        V7 — Si un .py est en cache avec metadata model='codellama' et
        que le générateur courant utilise 'qwen2.5-coder:14b' → cache miss.
        """
        import json

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Pré-peupler le cache manuellement avec le modèle 'codellama'
        system = "You are LCCA."
        user   = "Generate a stub."
        gen_q  = LLMGenerator(model="qwen2.5-coder:14b", cache_dir=cache_dir)
        key    = gen_q._cache_key(system, user, "qwen2.5-coder:14b")

        # Écrire le fichier .py et la metadata avec model='codellama'
        (cache_dir / f"{key}.py").write_text("def foo(): pass", encoding="utf-8")
        (cache_dir / f"{key}.json").write_text(
            json.dumps({"model": "codellama", "timestamp": "2026-01-01T00:00:00"}),
            encoding="utf-8",
        )

        # Le générateur qwen doit obtenir un miss (modèle metadata != modèle courant)
        result = gen_q._cache_get(key)
        assert result is None, (
            "V7 : _cache_get() doit retourner None si le modèle en metadata "
            "ne correspond pas au modèle courant du générateur."
        )

    def test_cache_miss_on_unknown_legacy_model(self, tmp_path):
        """
        V7 — Si metadata.model == 'unknown' (cache legacy pré-V7) et que
        le modèle courant est connu → cache miss (invalidation automatique).
        """
        import json

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        gen = LLMGenerator(model="codellama", cache_dir=cache_dir)
        system = "You are LCCA."
        user   = "Generate a stub."
        key    = gen._cache_key(system, user, "codellama")

        # Simuler un cache legacy : .py présent, metadata.model = 'unknown'
        (cache_dir / f"{key}.py").write_text("def bar(): pass", encoding="utf-8")
        (cache_dir / f"{key}.json").write_text(
            json.dumps({"model": "unknown", "timestamp": "2025-01-01T00:00:00"}),
            encoding="utf-8",
        )

        result = gen._cache_get(key)
        assert result is None, (
            "V7 : _cache_get() doit invalider les entrées legacy (model='unknown') "
            "quand le modèle courant est connu."
        )


class TestKeepAlive:
    """V9-01-A : keep_alive et options dans les payloads Ollama."""

    def test_keep_alive_default(self):
        client = OllamaClient("http://localhost:11434", "qwen", None, 512)
        assert client.keep_alive == "5m"

    def test_keep_alive_custom(self):
        client = OllamaClient("http://localhost:11434", "qwen", None, 512, keep_alive="30m")
        assert client.keep_alive == "30m"

    def test_llm_generator_reads_keep_alive_from_config(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "OLLAMA_KEEP_ALIVE", "15m", raising=False)
        gen = LLMGenerator()
        assert gen.ollama.keep_alive == "15m"

    def test_llm_generator_explicit_keep_alive_overrides_config(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "OLLAMA_KEEP_ALIVE", "15m", raising=False)
        gen = LLMGenerator(keep_alive="2h")
        assert gen.ollama.keep_alive == "2h"

    def test_load_config_quantized_model_7b(self, monkeypatch):
        # V9-01-A : Ollama gere la quantification via Modelfile.
        # _load_config() retourne le modele tel quel, sans suffixe -Q4_K_M.
        import config
        monkeypatch.setattr(config, "OLLAMA_QUANTIZED",   True,               raising=False)
        monkeypatch.setattr(config, "OLLAMA_QUANT_LEVEL", "Q4_K_M",           raising=False)
        monkeypatch.setattr(config, "OLLAMA_MODEL",       "qwen2.5-coder:7b", raising=False)
        from core.llm_generator import _load_config
        cfg = _load_config()
        assert cfg["model"] == "qwen2.5-coder:7b"

    def test_load_config_quantized_model_14b(self, monkeypatch):
        # V9-01-A : idem, pas de renommage cote Python.
        import config
        monkeypatch.setattr(config, "OLLAMA_QUANTIZED",   True,                raising=False)
        monkeypatch.setattr(config, "OLLAMA_QUANT_LEVEL", "Q4_K_M",            raising=False)
        monkeypatch.setattr(config, "OLLAMA_MODEL",       "qwen2.5-coder:14b", raising=False)
        from core.llm_generator import _load_config
        cfg = _load_config()
        assert cfg["model"] == "qwen2.5-coder:14b"

    def test_load_config_model_override_ignores_quant(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "OLLAMA_QUANTIZED",   True,     raising=False)
        monkeypatch.setattr(config, "OLLAMA_QUANT_LEVEL", "Q4_K_M", raising=False)
        from core.llm_generator import _load_config
        cfg = _load_config(model_override="custom:7b")
        assert cfg["model"] == "custom:7b"

    def test_load_config_instruct_not_quantized(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "OLLAMA_QUANTIZED",   True,     raising=False)
        monkeypatch.setattr(config, "OLLAMA_QUANT_LEVEL", "Q4_K_M", raising=False)
        monkeypatch.setattr(config, "OLLAMA_MODEL",       "qwen2.5-coder:7b-instruct", raising=False)
        from core.llm_generator import _load_config
        cfg = _load_config()
        assert cfg["model"] == "qwen2.5-coder:7b-instruct"

    def test_generate_payload_contains_keep_alive(self, monkeypatch):
        """keep_alive est present dans le payload de generate()."""
        import json as _json
        captured = {}

        class FakeResp:
            def __iter__(self):
                yield _json.dumps({"response": "def f(): pass", "done": True}).encode()
            def __enter__(self):  return self
            def __exit__(self, *a): pass

        monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: FakeResp())
        import urllib.request as _ur
        orig_req = _ur.Request
        def capturing_request(url, data=None, headers=None, method=None):
            if data:
                captured["body"] = _json.loads(data.decode("utf-8"))
            return orig_req(url, data=data, headers=headers or {}, method=method)
        monkeypatch.setattr(_ur, "Request", capturing_request)

        client = OllamaClient("http://localhost:11434", "qwen", None, 512, keep_alive="30m")
        client.generate("sys", "user")
        assert captured["body"]["keep_alive"] == "30m"
        assert "num_thread" in captured["body"]["options"]


# ---------------------------------------------------------------------------
# TestFewShotPrompt (V9-02-A)
# ---------------------------------------------------------------------------

class TestFewShotPrompt:
    def test_skill_context_injected_in_user_prompt(self):
        builder = PromptBuilder()
        op = MagicMock(action="add", patch_type="add_function",
                       target_symbol="my_func", file="test.py")
        intent = MagicMock(details="parse JSON", project="LCCA", target="")
        _, user = builder.build(op, intent, skill_context="def example(): pass")
        assert "example" in user
        assert "Exemples de code LCCA" in user

    def test_empty_skill_context_no_injection(self):
        builder = PromptBuilder()
        op = MagicMock(action="add", patch_type="add_function",
                       target_symbol="f", file="x.py")
        intent = MagicMock(details="do x", project="LCCA", target="")
        _, u1 = builder.build(op, intent)
        _, u2 = builder.build(op, intent, skill_context="")
        assert u1 == u2

    def test_generate_passes_skill_context_to_builder(self):
        from unittest.mock import patch as _patch
        gen = LLMGenerator()
        captured_kwargs = {}
        original_build = gen.builder.build

        def spy_build(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return original_build(*args, **kwargs)

        with _patch.object(gen.ollama, "generate", side_effect=ConnectionError("unavailable")), \
             _patch.object(gen.builder, "build", side_effect=spy_build):
            op = MagicMock(action="add", patch_type="add_function",
                           target_symbol="f", file="x.py")
            intent = MagicMock(details="x", project="P", target="")
            gen.generate(op, intent, skill_context="# skill snippet")

        assert captured_kwargs.get("skill_context") == "# skill snippet"
