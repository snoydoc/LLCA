# -*- coding: utf-8-sig -*-
"""
test_v9_01_b.py -- Sprint V9-01-B : selection modele qwen2.5-coder:3b full-VRAM
Verifie que HardwareProfile inclut ollama_model et qu'apply_hardware_profile()
patche config.OLLAMA_MODEL selon le tier RAM.
0 dependance Ollama reelle.
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from core.hardware_profile import get_profile, apply_hardware_profile, HardwareProfile


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fake_config(model="qwen2.5-coder:7b", model_light="qwen2.5-coder:3b"):
    """Retourne un module config minimal pour les tests."""
    cfg = types.ModuleType("config")
    cfg.OLLAMA_MODEL             = model
    cfg.OLLAMA_MODEL_LIGHT       = model_light
    cfg.LLM_POOL_MAX_LOADED      = 3
    cfg.OLLAMA_QUANT_LEVEL_HEAVY = "Q4_K_M"
    cfg.TTS_ENGINE               = "kokoro"
    cfg.AST_INDEX_CACHE_TTL      = 3600
    cfg.GRPO_EXPERIMENTAL_ENABLED = False
    cfg.NL_MODEL                 = model
    return cfg


# ── Tests HardwareProfile.ollama_model ───────────────────────────────────────

class TestHardwareProfileOllamaModel(unittest.TestCase):
    """Le champ ollama_model doit etre present dans HardwareProfile."""

    def test_profile_has_ollama_model_key(self):
        """get_profile() retourne un dict avec la cle ollama_model."""
        profile = get_profile(ram_gb=16)
        self.assertIn("ollama_model", profile)

    def test_low_tier_uses_model_light(self):
        """Tier low (< 24 Go) -> OLLAMA_MODEL_LIGHT (3b full-GPU)."""
        cfg = _fake_config()
        with patch.dict("sys.modules", {"config": cfg}):
            profile = get_profile(ram_gb=16)
        self.assertEqual(profile["ollama_model"], "qwen2.5-coder:3b")
        self.assertEqual(profile["tier"], "low")

    def test_mid_tier_uses_model_main(self):
        """Tier mid (>= 24 Go) -> OLLAMA_MODEL (7b)."""
        cfg = _fake_config()
        with patch.dict("sys.modules", {"config": cfg}):
            profile = get_profile(ram_gb=24)
        self.assertEqual(profile["ollama_model"], "qwen2.5-coder:7b")
        self.assertEqual(profile["tier"], "mid")

    def test_high_tier_uses_model_main(self):
        """Tier high (>= 32 Go) -> OLLAMA_MODEL (7b)."""
        cfg = _fake_config()
        with patch.dict("sys.modules", {"config": cfg}):
            profile = get_profile(ram_gb=32)
        self.assertEqual(profile["ollama_model"], "qwen2.5-coder:7b")
        self.assertEqual(profile["tier"], "high")

    def test_boundary_23_low(self):
        """23 Go -> tier low -> 3b."""
        cfg = _fake_config()
        with patch.dict("sys.modules", {"config": cfg}):
            profile = get_profile(ram_gb=23)
        self.assertEqual(profile["tier"], "low")
        self.assertEqual(profile["ollama_model"], "qwen2.5-coder:3b")

    def test_boundary_24_mid(self):
        """24 Go -> tier mid -> 7b."""
        cfg = _fake_config()
        with patch.dict("sys.modules", {"config": cfg}):
            profile = get_profile(ram_gb=24)
        self.assertEqual(profile["tier"], "mid")
        self.assertEqual(profile["ollama_model"], "qwen2.5-coder:7b")

    def test_fallback_without_config(self):
        """Sans config, ollama_model prend la valeur par defaut ('qwen2.5-coder:3b' pour low)."""
        saved = sys.modules.pop("config", None)
        try:
            profile = get_profile(ram_gb=16)
            self.assertIn("ollama_model", profile)
            self.assertEqual(profile["ollama_model"], "qwen2.5-coder:3b")
        finally:
            if saved is not None:
                sys.modules["config"] = saved


# ── Tests apply_hardware_profile patches config.OLLAMA_MODEL ─────────────────

class TestApplyHardwareProfileModel(unittest.TestCase):
    """apply_hardware_profile() doit patcher config.OLLAMA_MODEL et NL_MODEL."""

    def test_apply_low_patches_model_to_3b(self):
        """Sur P50 (16 Go), apply_hardware_profile() -> config.OLLAMA_MODEL = 3b."""
        cfg = _fake_config()
        with patch.dict("sys.modules", {"config": cfg}):
            apply_hardware_profile(ram_gb=16)
        self.assertEqual(cfg.OLLAMA_MODEL, "qwen2.5-coder:3b")

    def test_apply_low_patches_nl_model_to_3b(self):
        """Sur P50 (16 Go), apply_hardware_profile() -> config.NL_MODEL = 3b."""
        cfg = _fake_config()
        with patch.dict("sys.modules", {"config": cfg}):
            apply_hardware_profile(ram_gb=16)
        self.assertEqual(cfg.NL_MODEL, "qwen2.5-coder:3b")

    def test_apply_mid_keeps_model_7b(self):
        """Sur machine 24 Go, apply_hardware_profile() -> config.OLLAMA_MODEL = 7b."""
        cfg = _fake_config()
        with patch.dict("sys.modules", {"config": cfg}):
            apply_hardware_profile(ram_gb=24)
        self.assertEqual(cfg.OLLAMA_MODEL, "qwen2.5-coder:7b")

    def test_apply_high_keeps_model_7b(self):
        """Sur machine 32 Go, apply_hardware_profile() -> config.OLLAMA_MODEL = 7b."""
        cfg = _fake_config()
        with patch.dict("sys.modules", {"config": cfg}):
            apply_hardware_profile(ram_gb=32)
        self.assertEqual(cfg.OLLAMA_MODEL, "qwen2.5-coder:7b")

    def test_apply_returns_profile(self):
        """apply_hardware_profile() retourne le HardwareProfile applique."""
        cfg = _fake_config()
        with patch.dict("sys.modules", {"config": cfg}):
            profile = apply_hardware_profile(ram_gb=16)
        self.assertIsInstance(profile, dict)
        self.assertIn("ollama_model", profile)

    def test_apply_silent_on_missing_config(self):
        """Sans config importable, apply_hardware_profile() ne leve pas d'exception."""
        saved = sys.modules.pop("config", None)
        try:
            profile = apply_hardware_profile(ram_gb=16)
            self.assertEqual(profile["tier"], "low")
        finally:
            if saved is not None:
                sys.modules["config"] = saved


if __name__ == "__main__":
    unittest.main()
