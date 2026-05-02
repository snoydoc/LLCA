# -*- coding: utf-8-sig -*-
"""
test_v9_03.py -- Sprint V9-03 : modele par defaut qwen2.5-coder:3b

Verifie que config.py declare le bon modele apres le benchmark 21/04/2026 :
  - OLLAMA_MODEL       = "qwen2.5-coder:3b"
  - OLLAMA_MODEL_LIGHT = "qwen2.5-coder:3b"
  - NL_MODEL           = "qwen2.5-coder:3b"
  - OLLAMA_MODEL et OLLAMA_MODEL_LIGHT pointent vers le meme modele
  - apply_hardware_profile(ram_gb=16) conserve le 3b (tier low)
  - apply_hardware_profile(ram_gb=24) utilise OLLAMA_MODEL (doit pointer 3b aussi sur P50)

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

import config
from core.hardware_profile import apply_hardware_profile


# ── Constantes attendues ───────────────────────────────────────────────────

_MODEL_3B = "qwen2.5-coder:3b"
_MODEL_7B = "qwen2.5-coder:7b"


# ── Tests config.py ───────────────────────────────────────────────────────

class TestConfigModeleParDefaut(unittest.TestCase):
    """config.py doit declarer qwen2.5-coder:3b comme modele principal."""

    def test_ollama_model_is_3b(self):
        """OLLAMA_MODEL = qwen2.5-coder:3b (benchmark 21/04/2026 : 10.87 tok/s)."""
        self.assertEqual(config.OLLAMA_MODEL, _MODEL_3B)

    def test_nl_model_is_3b(self):
        """NL_MODEL = qwen2.5-coder:3b (coherence pipeline NL)."""
        self.assertEqual(config.NL_MODEL, _MODEL_3B)

    def test_ollama_model_light_is_3b(self):
        """OLLAMA_MODEL_LIGHT = qwen2.5-coder:3b (tier low full-VRAM)."""
        self.assertEqual(config.OLLAMA_MODEL_LIGHT, _MODEL_3B)

    def test_ollama_model_light_equals_ollama_model(self):
        """OLLAMA_MODEL et OLLAMA_MODEL_LIGHT sont synchronises (pas de desync)."""
        self.assertEqual(config.OLLAMA_MODEL, config.OLLAMA_MODEL_LIGHT)

    def test_ollama_model_heavy_unchanged(self):
        """OLLAMA_MODEL_HEAVY reste qwen2.5-coder:14b (specs longues)."""
        self.assertEqual(config.OLLAMA_MODEL_HEAVY, "qwen2.5-coder:14b")

    def test_ollama_model_not_7b(self):
        """OLLAMA_MODEL n'est plus 7b (ecarte apres benchmark : 4.01 tok/s)."""
        self.assertNotEqual(config.OLLAMA_MODEL, _MODEL_7B)

    def test_ollama_model_is_string(self):
        """OLLAMA_MODEL est une chaine non vide."""
        self.assertIsInstance(config.OLLAMA_MODEL, str)
        self.assertTrue(len(config.OLLAMA_MODEL) > 0)

    def test_keep_alive_defined(self):
        """OLLAMA_KEEP_ALIVE defini (V9-01-A)."""
        self.assertTrue(hasattr(config, "OLLAMA_KEEP_ALIVE"))
        self.assertIsInstance(config.OLLAMA_KEEP_ALIVE, str)

    def test_num_gpu_is_99(self):
        """OLLAMA_NUM_GPU = 99 (force toutes les couches sur GPU)."""
        self.assertEqual(config.OLLAMA_NUM_GPU, 99)


# ── Tests apply_hardware_profile avec config reel ────────────────────────

class TestApplyProfileConserve3b(unittest.TestCase):
    """apply_hardware_profile() doit conserver ou choisir qwen2.5-coder:3b sur P50."""

    def setUp(self):
        """Sauvegarde OLLAMA_MODEL avant chaque test pour restauration."""
        self._original_model    = config.OLLAMA_MODEL
        self._original_nl_model = config.NL_MODEL

    def tearDown(self):
        """Restaure config apres chaque test pour eviter les effets de bord."""
        config.OLLAMA_MODEL = self._original_model
        config.NL_MODEL     = self._original_nl_model

    def test_low_tier_model_is_3b(self):
        """Tier low (16 Go RAM / P50) -> OLLAMA_MODEL = qwen2.5-coder:3b."""
        profile = apply_hardware_profile(ram_gb=16)
        self.assertEqual(config.OLLAMA_MODEL, _MODEL_3B)
        self.assertEqual(profile["tier"], "low")

    def test_low_tier_nl_model_is_3b(self):
        """Tier low -> NL_MODEL = qwen2.5-coder:3b."""
        apply_hardware_profile(ram_gb=16)
        self.assertEqual(config.NL_MODEL, _MODEL_3B)

    def test_profile_ollama_model_field_is_3b_on_low(self):
        """HardwareProfile.ollama_model = qwen2.5-coder:3b pour tier low."""
        profile = apply_hardware_profile(ram_gb=16)
        self.assertEqual(profile["ollama_model"], _MODEL_3B)


if __name__ == "__main__":
    unittest.main()
