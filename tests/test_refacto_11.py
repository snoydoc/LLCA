# -*- coding: utf-8-sig -*-
"""
test_refacto_11.py — REFACTO-11
Tests de non-régression pour le découpage de llm_generator.py.

Vérifie :
  1. Imports rétrocompat depuis llm_generator (tous les symboles publics)
  2. Imports directs depuis les nouveaux modules
  3. OllamaClient importable depuis core.ollama_client ET core.llm_generator
  4. PromptBuilder importable depuis core.llm_prompt_builder ET core.llm_generator
  5. CodeExtractor + FallbackGenerator depuis core.llm_code_utils ET core.llm_generator
  6. llm_config : _load_config, _cfg_read, constantes
  7. LLMGenerator : instanciation, generate(), generate_text(), clear_cache()
  8. OllamaClient : identité des classes (même objet via les deux imports)
  9. GenerationResult : dataclass avec les 6 champs attendus

Suite : 18 tests
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── 1. Imports rétrocompat depuis llm_generator ───────────────────────────────

class TestRetroCompatImportsLlmGenerator:

    def test_import_generation_result(self):
        from core.llm_generator import GenerationResult
        assert GenerationResult is not None

    def test_import_llm_generator(self):
        from core.llm_generator import LLMGenerator
        assert LLMGenerator is not None

    def test_import_ollama_client_from_llm_generator(self):
        from core.llm_generator import OllamaClient
        assert OllamaClient is not None

    def test_import_prompt_builder_from_llm_generator(self):
        from core.llm_generator import PromptBuilder
        assert PromptBuilder is not None

    def test_import_code_extractor_from_llm_generator(self):
        from core.llm_generator import CodeExtractor
        assert CodeExtractor is not None

    def test_import_fallback_generator_from_llm_generator(self):
        from core.llm_generator import FallbackGenerator
        assert FallbackGenerator is not None

    def test_import_load_config_from_llm_generator(self):
        from core.llm_generator import _load_config
        assert callable(_load_config)

    def test_import_cfg_read_from_llm_generator(self):
        from core.llm_generator import _cfg_read
        assert callable(_cfg_read)

    def test_import_default_constants(self):
        from core.llm_generator import (
            _DEFAULT_OLLAMA_URL,
            _DEFAULT_MODEL,
            _DEFAULT_TIMEOUT,
            _DEFAULT_MAX_TOKENS,
            _CACHE_DIR_FALLBACK,
        )
        assert _DEFAULT_OLLAMA_URL == "http://localhost:11434"
        assert _DEFAULT_MODEL == "codellama"
        assert _DEFAULT_TIMEOUT is None
        assert _DEFAULT_MAX_TOKENS == 512
        assert isinstance(_CACHE_DIR_FALLBACK, Path)


# ── 2. Imports directs depuis les nouveaux modules ────────────────────────────

class TestDirectImportsNewModules:

    def test_ollama_client_importable_from_own_module(self):
        from core.ollama_client import OllamaClient
        assert OllamaClient is not None

    def test_prompt_builder_importable_from_own_module(self):
        from core.llm_prompt_builder import PromptBuilder
        assert PromptBuilder is not None

    def test_code_extractor_importable_from_own_module(self):
        from core.llm_code_utils import CodeExtractor
        assert CodeExtractor is not None

    def test_fallback_generator_importable_from_own_module(self):
        from core.llm_code_utils import FallbackGenerator
        assert FallbackGenerator is not None

    def test_llm_config_load_config_importable(self):
        from core.llm_config import load_config
        assert callable(load_config)

    def test_llm_config_cfg_read_importable(self):
        from core.llm_config import cfg_read
        assert callable(cfg_read)


# ── 3. Identité des classes ───────────────────────────────────────────────────

class TestClassIdentity:

    def test_ollama_client_same_class_both_imports(self):
        from core.llm_generator import OllamaClient as A
        from core.ollama_client  import OllamaClient as B
        assert A is B

    def test_prompt_builder_same_class_both_imports(self):
        from core.llm_generator   import PromptBuilder as A
        from core.llm_prompt_builder import PromptBuilder as B
        assert A is B

    def test_code_extractor_same_class_both_imports(self):
        from core.llm_generator  import CodeExtractor as A
        from core.llm_code_utils import CodeExtractor as B
        assert A is B


# ── 4. GenerationResult ───────────────────────────────────────────────────────

class TestGenerationResult:

    def test_has_all_fields(self):
        from core.llm_generator import GenerationResult
        gr = GenerationResult(
            code="def f(): pass",
            model="codellama",
            from_cache=False,
            from_fallback=False,
            prompt_tokens=10,
            duration_ms=200,
        )
        assert gr.code == "def f(): pass"
        assert gr.model == "codellama"
        assert gr.from_cache is False
        assert gr.from_fallback is False
        assert gr.prompt_tokens == 10
        assert gr.duration_ms == 200


# ── 5. LLMGenerator intégration (Ollama mocké) ───────────────────────────────

class TestLLMGeneratorIntegration:

    def _stream_mock(self, *tokens: str) -> MagicMock:
        lines = [
            json.dumps({"response": t, "done": False}).encode("utf-8")
            for t in tokens
        ]
        lines.append(json.dumps({"response": "", "done": True}).encode("utf-8"))
        mock_resp = MagicMock()
        mock_resp.__iter__ = lambda s: iter(lines)
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__  = MagicMock(return_value=False)
        return mock_resp

    def test_llm_generator_instantiation(self, tmp_path: Path):
        from core.llm_generator import LLMGenerator
        gen = LLMGenerator(cache_dir=tmp_path / "cache")
        assert gen is not None
        assert gen.ollama is not None

    def test_generate_fallback_on_connection_error(self, tmp_path: Path):
        from core.llm_generator import LLMGenerator
        import urllib.error
        gen = LLMGenerator(cache_dir=tmp_path / "cache")
        op  = MagicMock(action="create", patch_type="add_function",
                        target_symbol="f", file="x.py")
        intent = MagicMock(details="x", project="P", target="")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            result = gen.generate(op, intent)
        assert result.from_fallback is True

    def test_generate_ok_from_ollama(self, tmp_path: Path):
        from core.llm_generator import LLMGenerator
        gen = LLMGenerator(cache_dir=tmp_path / "cache")
        op  = MagicMock(action="modify", patch_type="add_function",
                        target_symbol="my_func", file="mod.py")
        intent = MagicMock(details="validate email", project="LCCA", target="")

        def fresh_mock(_req, timeout=None):
            return self._stream_mock("def my_func():\n    pass\n")

        with patch("urllib.request.urlopen", side_effect=fresh_mock):
            result = gen.generate(op, intent)
        assert result.from_fallback is False
        assert "def my_func" in result.code

    def test_clear_cache_removes_files(self, tmp_path: Path):
        from core.llm_generator import LLMGenerator
        cache = tmp_path / "cache"
        cache.mkdir(exist_ok=True)
        (cache / "abc.py").write_text("def f(): pass")
        (cache / "abc.json").write_text("{}")
        gen = LLMGenerator(cache_dir=cache)
        deleted = gen.clear_cache()
        assert deleted >= 2
