# -*- coding: utf-8-sig -*-
"""Tests test_hardware_profile.py -- Sprint V9-00."""
import pytest
from core.hardware_profile import get_profile, apply_hardware_profile


class TestGetProfile:
    def test_high_tier_32gb(self):
        p = get_profile(32)
        assert p["tier"] == "high"
        assert p["pool_max_loaded"] == 3
        assert p["quant_heavy"] == "Q5_K_M"
        assert p["grpo_experimental"] is True

    def test_mid_tier_24gb(self):
        p = get_profile(24)
        assert p["tier"] == "mid"
        assert p["pool_max_loaded"] == 3
        assert p["tts_default"] == "kokoro"
        assert p["grpo_experimental"] is False

    def test_low_tier_16gb(self):
        p = get_profile(16)
        assert p["tier"] == "low"
        assert p["pool_max_loaded"] == 2
        assert p["tts_default"] == "pyttsx3"
        assert p["ast_cache_ttl"] == 300

    def test_low_tier_8gb(self):
        p = get_profile(8)
        assert p["tier"] == "low"
        assert p["pool_max_loaded"] == 2

    def test_boundary_24gb_is_mid_not_low(self):
        assert get_profile(24)["tier"] == "mid"

    def test_boundary_23gb_is_low(self):
        assert get_profile(23)["tier"] == "low"

    def test_boundary_32gb_is_high(self):
        assert get_profile(32)["tier"] == "high"

    def test_boundary_31gb_is_mid(self):
        assert get_profile(31)["tier"] == "mid"

    def test_all_keys_present(self):
        p = get_profile(16)
        required = {"ram_gb", "tier", "pool_max_loaded", "quant_heavy",
                    "tts_default", "ast_cache_ttl", "grpo_experimental"}
        assert required.issubset(p.keys())

    def test_apply_patches_config_low(self, monkeypatch):
        import config
        apply_hardware_profile(ram_gb=16)
        assert config.LLM_POOL_MAX_LOADED == 2

    def test_apply_patches_config_mid(self, monkeypatch):
        import config
        apply_hardware_profile(ram_gb=24)
        assert config.LLM_POOL_MAX_LOADED == 3

    def test_apply_patches_config_high(self, monkeypatch):
        import config
        apply_hardware_profile(ram_gb=32)
        assert config.LLM_POOL_MAX_LOADED == 3
        assert config.GRPO_EXPERIMENTAL_ENABLED is True

    def test_apply_returns_profile(self):
        result = apply_hardware_profile(ram_gb=16)
        assert result["tier"] == "low"

    def test_detect_ram_fallback(self, monkeypatch):
        """detect_ram_gb retourne 16 si psutil absent."""
        import builtins
        real_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == "psutil":
                raise ImportError("psutil not available")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", mock_import)
        from core.hardware_profile import detect_ram_gb
        assert detect_ram_gb() == 16
