# tests/test_voice_00.py
# VOICE-00 — Tests voice_types.py : dataclasses, enums, config loader, helpers
# 8 classes de test, ~30 assertions

from __future__ import annotations

import json
import os
import sys
import tempfile
import pytest

# ---------------------------------------------------------------------------
# Ajout du chemin Voice/ au sys.path pour permettre l'import sans package
# ---------------------------------------------------------------------------
_VOICE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Voice")
if _VOICE_DIR not in sys.path:
    sys.path.insert(0, _VOICE_DIR)

from voice_types import (
    # Enums
    VoiceState,
    TTSEngine,
    STTDevice,
    STTComputeType,
    VoiceMode,
    MessageType,
    TTSMessageType,
    # Messages WS
    PartialTranscript,
    FinalTranscript,
    StatusMessage,
    # Configs
    STTConfig,
    PiperConfig,
    KokoroConfig,
    TTSConfig,
    UIConfig,
    VoiceConfig,
    load_voice_config,
    # VRAM helpers
    VRAMInfo,
    resolve_stt_device,
    resolve_tts_engine,
    VRAM_MIN_MB_FOR_CUDA,
    # Beep
    BeepSpec,
    BEEP_START,
    BEEP_STOP,
)


# ===========================================================================
# 1. Enums
# ===========================================================================

class TestEnums:
    def test_voice_state_values(self):
        assert VoiceState.IDLE.value == "idle"
        assert VoiceState.LISTENING.value == "listening"
        assert VoiceState.PROCESSING.value == "processing"
        assert VoiceState.ERROR.value == "error"

    def test_tts_engine_values(self):
        assert TTSEngine.PIPER.value == "piper"
        assert TTSEngine.KOKORO.value == "kokoro"
        assert TTSEngine.AUTO.value == "auto"

    def test_stt_device_values(self):
        assert STTDevice.AUTO.value == "auto"
        assert STTDevice.CUDA.value == "cuda"
        assert STTDevice.CPU.value == "cpu"

    def test_message_type_values(self):
        assert MessageType.PARTIAL.value == "partial"
        assert MessageType.FINAL.value == "final"
        assert MessageType.STATUS.value == "status"

    def test_voice_mode_values(self):
        assert VoiceMode.PUSH_TO_TALK.value == "push_to_talk"
        assert VoiceMode.CONTINUOUS.value == "continuous"


# ===========================================================================
# 2. PartialTranscript
# ===========================================================================

class TestPartialTranscript:
    def test_to_dict_type_field(self):
        pt = PartialTranscript(text="bonjour", confidence=0.82)
        d = pt.to_dict()
        assert d["type"] == "partial"
        assert d["text"] == "bonjour"
        assert d["confidence"] == 0.82

    def test_from_dict_roundtrip(self):
        original = PartialTranscript(text="test partiel", confidence=0.75)
        restored = PartialTranscript.from_dict(original.to_dict())
        assert restored.text == original.text
        assert abs(restored.confidence - original.confidence) < 1e-4

    def test_from_dict_defaults(self):
        pt = PartialTranscript.from_dict({})
        assert pt.text == ""
        assert pt.confidence == 0.0

    def test_confidence_rounded(self):
        pt = PartialTranscript(text="x", confidence=0.123456789)
        assert len(str(pt.to_dict()["confidence"])) <= 8  # max 4 decimales


# ===========================================================================
# 3. FinalTranscript
# ===========================================================================

class TestFinalTranscript:
    def test_to_dict_type_field(self):
        ft = FinalTranscript(text="phrase complete", confidence=0.91, duration_ms=3200)
        d = ft.to_dict()
        assert d["type"] == "final"
        assert d["duration_ms"] == 3200

    def test_from_dict_roundtrip(self):
        original = FinalTranscript(text="bonjour monde", confidence=0.88, duration_ms=1500)
        restored = FinalTranscript.from_dict(original.to_dict())
        assert restored.text == original.text
        assert restored.duration_ms == original.duration_ms

    def test_from_dict_defaults(self):
        ft = FinalTranscript.from_dict({})
        assert ft.text == ""
        assert ft.duration_ms == 0


# ===========================================================================
# 4. StatusMessage
# ===========================================================================

class TestStatusMessage:
    def test_to_dict_type_field(self):
        sm = StatusMessage(state="listening", msg="")
        d = sm.to_dict()
        assert d["type"] == "status"
        assert d["state"] == "listening"

    def test_from_dict_roundtrip(self):
        sm = StatusMessage(state="error", msg="timeout")
        restored = StatusMessage.from_dict(sm.to_dict())
        assert restored.state == "error"
        assert restored.msg == "timeout"

    def test_from_dict_defaults(self):
        sm = StatusMessage.from_dict({})
        assert sm.state == VoiceState.IDLE.value


# ===========================================================================
# 5. STTConfig
# ===========================================================================

class TestSTTConfig:
    def test_defaults(self):
        cfg = STTConfig()
        assert cfg.language == "fr"
        assert cfg.model == "small"
        assert cfg.device == STTDevice.AUTO.value
        assert cfg.compute_type == STTComputeType.INT8.value
        assert cfg.port == 8765
        assert cfg.continuous_mode is False
        assert cfg.auto_submit is False if hasattr(cfg, "auto_submit") else True

    def test_roundtrip(self):
        cfg = STTConfig(language="en", model="medium", port=9000)
        restored = STTConfig.from_dict(cfg.to_dict())
        assert restored.language == "en"
        assert restored.model == "medium"
        assert restored.port == 9000

    def test_from_dict_bool_coercion(self):
        cfg = STTConfig.from_dict({"continuous_mode": 1, "enabled": 0})
        assert cfg.continuous_mode is True
        assert cfg.enabled is False


# ===========================================================================
# 6. VoiceConfig (config racine)
# ===========================================================================

class TestVoiceConfig:
    def test_defaults(self):
        cfg = VoiceConfig()
        assert isinstance(cfg.stt, STTConfig)
        assert isinstance(cfg.tts, TTSConfig)
        assert isinstance(cfg.ui, UIConfig)

    def test_nested_roundtrip(self):
        cfg = VoiceConfig()
        cfg.stt.language = "en"
        cfg.tts.volume = 0.5
        cfg.ui.auto_submit = True
        d = cfg.to_dict()
        restored = VoiceConfig.from_dict(d)
        assert restored.stt.language == "en"
        assert abs(restored.tts.volume - 0.5) < 1e-6
        assert restored.ui.auto_submit is True

    def test_ui_defaults(self):
        ui = UIConfig()
        assert ui.auto_submit is False
        assert ui.audio_feedback is True
        assert ui.shortcut_scope == "local"

    def test_piper_defaults(self):
        p = PiperConfig()
        assert "fr_FR" in p.model_fr
        assert "en_US" in p.model_en

    def test_kokoro_defaults(self):
        k = KokoroConfig()
        assert k.voice == "af_heart"
        assert k.lang == "a"


# ===========================================================================
# 7. load_voice_config
# ===========================================================================

class TestLoadVoiceConfig:
    def test_load_absent_returns_defaults(self, tmp_path):
        cfg = load_voice_config(config_path=str(tmp_path / "absent.toml"))
        assert isinstance(cfg, VoiceConfig)
        assert cfg.stt.language == "fr"

    def test_load_valid_toml(self, tmp_path):
        toml_content = (
            "[stt]\n"
            'language = "en"\n'
            'model = "tiny"\n'
            "port = 9999\n"
            "[tts]\n"
            "volume = 0.5\n"
            "[ui]\n"
            "auto_submit = true\n"
        )
        p = tmp_path / "voice_config.toml"
        p.write_text(toml_content, encoding="utf-8")
        cfg = load_voice_config(config_path=str(p))
        assert cfg.stt.language == "en"
        assert cfg.stt.model == "tiny"
        assert cfg.stt.port == 9999
        assert abs(cfg.tts.volume - 0.5) < 1e-6
        assert cfg.ui.auto_submit is True

    def test_load_corrupted_toml_returns_defaults(self, tmp_path):
        p = tmp_path / "bad.toml"
        p.write_bytes(b"\xff\xfe broken toml !!!")
        cfg = load_voice_config(config_path=str(p))
        assert isinstance(cfg, VoiceConfig)

    def test_load_partial_toml_keeps_defaults(self, tmp_path):
        """Sections manquantes -> valeurs par defaut preservees."""
        p = tmp_path / "partial.toml"
        p.write_text("[stt]\nlanguage = \"en\"\n", encoding="utf-8")
        cfg = load_voice_config(config_path=str(p))
        assert cfg.stt.language == "en"
        # TTS non specifie -> defaults
        assert cfg.tts.volume == pytest.approx(0.85)


# ===========================================================================
# 8. VRAMInfo + resolve helpers
# ===========================================================================

class TestVRAMHelpers:
    def test_vram_info_properties(self):
        v = VRAMInfo(total_bytes=4 * 1024**3, free_bytes=2 * 1024**3, cuda_available=True)
        assert abs(v.total_mb - 4096.0) < 1.0
        assert abs(v.free_mb - 2048.0) < 1.0

    def test_vram_info_roundtrip(self):
        v = VRAMInfo(total_bytes=1000, free_bytes=500, cuda_available=True)
        restored = VRAMInfo.from_dict(v.to_dict())
        assert restored.total_bytes == 1000
        assert restored.cuda_available is True

    def test_resolve_stt_explicit_cuda(self):
        cfg = STTConfig(device="cuda")
        assert resolve_stt_device(cfg) == "cuda"

    def test_resolve_stt_explicit_cpu(self):
        cfg = STTConfig(device="cpu")
        assert resolve_stt_device(cfg) == "cpu"

    def test_resolve_stt_auto_cuda_available(self):
        cfg = STTConfig(device="auto")
        vram = VRAMInfo(total_bytes=4 * 1024**3, free_bytes=2 * 1024**3, cuda_available=True)
        assert resolve_stt_device(cfg, vram=vram) == "cuda"

    def test_resolve_stt_auto_no_cuda(self):
        cfg = STTConfig(device="auto")
        vram = VRAMInfo(cuda_available=False)
        assert resolve_stt_device(cfg, vram=vram) == "cpu"

    def test_resolve_stt_auto_low_vram(self):
        cfg = STTConfig(device="auto")
        # Seulement 500 MB libre -> CPU
        vram = VRAMInfo(total_bytes=4 * 1024**3, free_bytes=500 * 1024**2, cuda_available=True)
        assert resolve_stt_device(cfg, vram=vram) == "cpu"

    def test_resolve_tts_explicit_piper(self):
        cfg = TTSConfig(engine="piper")
        assert resolve_tts_engine(cfg) == "piper"

    def test_resolve_tts_auto_kokoro_if_vram(self):
        cfg = TTSConfig(engine="auto")
        vram = VRAMInfo(total_bytes=4 * 1024**3, free_bytes=2 * 1024**3, cuda_available=True)
        assert resolve_tts_engine(cfg, vram=vram) == "kokoro"

    def test_resolve_tts_auto_piper_if_no_vram(self):
        cfg = TTSConfig(engine="auto")
        vram = VRAMInfo(cuda_available=False)
        assert resolve_tts_engine(cfg, vram=vram) == "piper"


# ===========================================================================
# 9. BeepSpec
# ===========================================================================

class TestBeepSpec:
    def test_constants_defined(self):
        assert BEEP_START.frequency_hz == pytest.approx(440.0)
        assert BEEP_START.duration_ms == 80
        assert BEEP_STOP.frequency_hz == pytest.approx(220.0)
        assert BEEP_STOP.duration_ms == 60

    def test_beep_roundtrip(self):
        b = BeepSpec(frequency_hz=880.0, duration_ms=100, amplitude=0.5)
        restored = BeepSpec.from_dict(b.to_dict())
        assert restored.frequency_hz == pytest.approx(880.0)
        assert restored.duration_ms == 100
        assert restored.amplitude == pytest.approx(0.5)

    def test_generate_pcm_with_numpy(self):
        pytest.importorskip("numpy")
        pcm = BEEP_START.generate_pcm()
        assert pcm is not None
        # Duree : 80ms a 44100 Hz = 3528 samples
        expected_len = int(44100 * 0.08)
        assert abs(len(pcm) - expected_len) <= 2

    def test_generate_pcm_amplitude(self):
        pytest.importorskip("numpy")
        import numpy as np
        b = BeepSpec(frequency_hz=440.0, duration_ms=200, amplitude=0.3)
        pcm = b.generate_pcm()
        assert pcm is not None
        # Peak amplitude <= 0.3 + epsilon (fade peut reduire)
        assert float(np.max(np.abs(pcm))) <= 0.31

    def test_generate_pcm_returns_none_if_numpy_absent(self, monkeypatch):
        """Si numpy est absent, generate_pcm retourne None sans lever d'exception."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "numpy":
                raise ImportError("numpy absent")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        b = BeepSpec(frequency_hz=440.0, duration_ms=80)
        result = b.generate_pcm()
        assert result is None
