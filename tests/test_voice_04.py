# tests/test_voice_04.py
# VOICE-04 -- Tests PiperTTSEngine
# _piper_factory injectable : 0 subprocess reel, 0 binaire piper requis

from __future__ import annotations

import os
import sys
import struct

import pytest

_VOICE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Voice")
if _VOICE_DIR not in sys.path:
    sys.path.insert(0, _VOICE_DIR)

from tts_engine_piper import (
    PiperTTSEngine,
    SynthesisResult,
    TTS_SAMPLE_RATE,
    TTS_CHANNELS,
    TTS_SAMPWIDTH,
    _apply_volume,
    _pcm_duration_ms,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pcm(num_samples: int = 1600) -> bytes:
    """Genere un PCM int16 LE de silence (0x0000)."""
    return b"\x00\x00" * num_samples


def _make_engine(text_response: bytes = b"", fail: bool = False) -> PiperTTSEngine:
    """
    Fabrique un PiperTTSEngine avec _piper_factory injectable.
    Si fail=True, le factory leve RuntimeError.
    """
    def _factory(text, model_path, sample_rate):
        if fail:
            raise RuntimeError("piper crash")
        return text_response if text_response else _make_pcm()

    return PiperTTSEngine(
        model_path="fake/model.onnx",
        _piper_factory=_factory,
    )


# ---------------------------------------------------------------------------
# 1. SynthesisResult
# ---------------------------------------------------------------------------

class TestSynthesisResult:
    def test_to_dict_success(self):
        pcm = _make_pcm(1000)
        r = SynthesisResult(pcm_bytes=pcm, sample_rate=22050, duration_ms=45, success=True)
        d = r.to_dict()
        assert d["success"] is True
        assert d["pcm_bytes_len"] == len(pcm)
        assert d["sample_rate"] == 22050
        assert d["duration_ms"] == 45
        assert d["error"] == ""

    def test_failure_constructor(self):
        r = SynthesisResult.failure("erreur test")
        assert r.success is False
        assert r.pcm_bytes == b""
        assert r.error == "erreur test"
        assert r.duration_ms == 0

    def test_to_dict_failure(self):
        r = SynthesisResult.failure("boom")
        d = r.to_dict()
        assert d["success"] is False
        assert d["pcm_bytes_len"] == 0


# ---------------------------------------------------------------------------
# 2. Helpers module-level
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_pcm_duration_ms_zero_on_empty(self):
        assert _pcm_duration_ms(b"") == 0

    def test_pcm_duration_ms_basic(self):
        # 22050 samples * 2 bytes = 44100 bytes -> 1000 ms
        pcm = b"\x00\x00" * 22050
        assert _pcm_duration_ms(pcm, sample_rate=22050) == 1000

    def test_pcm_duration_ms_half_second(self):
        pcm = b"\x00\x00" * 11025
        assert _pcm_duration_ms(pcm, sample_rate=22050) == 500

    def test_pcm_duration_ms_zero_sample_rate(self):
        assert _pcm_duration_ms(b"\x00\x00", sample_rate=0) == 0

    def test_apply_volume_unity(self):
        pcm = _make_pcm(100)
        result = _apply_volume(pcm, 1.0)
        assert result == pcm

    def test_apply_volume_zero_returns_bytes(self):
        pcm = _make_pcm(100)
        result = _apply_volume(pcm, 0.0)
        assert isinstance(result, bytes)
        assert len(result) == len(pcm)

    def test_apply_volume_empty(self):
        result = _apply_volume(b"", 0.5)
        assert result == b""

    def test_apply_volume_half_reduces_amplitude(self):
        pytest.importorskip("numpy")
        import numpy as np
        # PCM avec valeur max int16
        arr = np.array([32000, 16000, -16000], dtype=np.int16)
        pcm = arr.tobytes()
        result = _apply_volume(pcm, 0.5)
        arr_out = np.frombuffer(result, dtype=np.int16)
        assert abs(int(arr_out[0]) - 16000) <= 1
        assert abs(int(arr_out[1]) - 8000) <= 1


# ---------------------------------------------------------------------------
# 3. Proprietes et init
# ---------------------------------------------------------------------------

class TestInit:
    def test_default_sample_rate(self):
        engine = _make_engine()
        assert engine.sample_rate == TTS_SAMPLE_RATE

    def test_model_path_stored(self):
        engine = PiperTTSEngine(model_path="mon/model.onnx", _piper_factory=lambda *a: b"")
        assert engine.model_path == "mon/model.onnx"

    def test_volume_clamped_above(self):
        engine = PiperTTSEngine(volume=2.0, _piper_factory=lambda *a: b"")
        assert engine._volume == 1.0

    def test_volume_clamped_below(self):
        engine = PiperTTSEngine(volume=-0.5, _piper_factory=lambda *a: b"")
        assert engine._volume == 0.0

    def test_info_dict(self):
        engine = PiperTTSEngine(
            model_path="m.onnx",
            piper_exe="piper",
            sample_rate=16000,
            volume=0.7,
            _piper_factory=lambda *a: b"",
        )
        info = engine.info()
        assert info["engine"] == "piper"
        assert info["model_path"] == "m.onnx"
        assert info["sample_rate"] == 16000
        assert abs(info["volume"] - 0.7) < 1e-6


# ---------------------------------------------------------------------------
# 4. is_available
# ---------------------------------------------------------------------------

class TestIsAvailable:
    def test_always_true_with_factory(self):
        engine = _make_engine()
        assert engine.is_available() is True

    def test_false_without_binary_and_model(self):
        """Sans factory et sans binaire reel -> False."""
        engine = PiperTTSEngine(
            model_path="inexistant.onnx",
            piper_exe="piper_inexistant_xyz",
        )
        assert engine.is_available() is False

    def test_cached_after_first_call(self):
        engine = PiperTTSEngine(
            model_path="inexistant.onnx",
            piper_exe="piper_inexistant_xyz",
        )
        r1 = engine.is_available()
        r2 = engine.is_available()
        assert r1 == r2  # meme valeur, calcul cached


# ---------------------------------------------------------------------------
# 5. Synthese -- cas nominaux
# ---------------------------------------------------------------------------

class TestSynthesizeSuccess:
    def test_returns_synthesis_result(self):
        engine = _make_engine()
        result = engine.synthesize("Bonjour le monde")
        assert isinstance(result, SynthesisResult)

    def test_success_true(self):
        engine = _make_engine()
        result = engine.synthesize("test")
        assert result.success is True

    def test_pcm_bytes_non_empty(self):
        engine = _make_engine()
        result = engine.synthesize("Bonjour")
        assert len(result.pcm_bytes) > 0

    def test_duration_ms_calculated(self):
        # 22050 samples -> 1000 ms
        pcm = _make_pcm(22050)
        engine = _make_engine(text_response=pcm)
        result = engine.synthesize("test")
        assert result.duration_ms == 1000

    def test_sample_rate_preserved(self):
        engine = PiperTTSEngine(
            sample_rate=16000,
            _piper_factory=lambda *a: _make_pcm(8000),
        )
        result = engine.synthesize("test")
        assert result.sample_rate == 16000

    def test_factory_receives_text(self):
        received = {}

        def _factory(text, model_path, sample_rate):
            received["text"] = text
            return _make_pcm()

        engine = PiperTTSEngine(_piper_factory=_factory)
        engine.synthesize("bonjour monde")
        assert received["text"] == "bonjour monde"

    def test_text_stripped(self):
        """Le texte est strip() avant d'etre passe au factory."""
        received = {}

        def _factory(text, model_path, sample_rate):
            received["text"] = text
            return _make_pcm()

        engine = PiperTTSEngine(_piper_factory=_factory)
        engine.synthesize("  espaces  ")
        assert received["text"] == "espaces"


# ---------------------------------------------------------------------------
# 6. Synthese -- cas d'erreur
# ---------------------------------------------------------------------------

class TestSynthesizeErrors:
    def test_empty_text_returns_failure(self):
        engine = _make_engine()
        result = engine.synthesize("")
        assert result.success is False
        assert "vide" in result.error

    def test_whitespace_only_returns_failure(self):
        engine = _make_engine()
        result = engine.synthesize("   ")
        assert result.success is False

    def test_factory_exception_swallowed(self):
        engine = _make_engine(fail=True)
        result = engine.synthesize("test")
        assert result.success is False
        assert "piper crash" in result.error

    def test_factory_non_bytes_returns_failure(self):
        engine = PiperTTSEngine(
            _piper_factory=lambda *a: "pas des bytes",
        )
        result = engine.synthesize("test")
        assert result.success is False

    def test_unavailable_without_factory_returns_failure(self):
        engine = PiperTTSEngine(
            model_path="inexistant.onnx",
            piper_exe="piper_xyz_inexistant",
        )
        result = engine.synthesize("test")
        assert result.success is False
        assert result.pcm_bytes == b""

    def test_no_exception_propagated(self):
        engine = _make_engine(fail=True)
        try:
            engine.synthesize("test")
        except Exception:
            pytest.fail("synthesize ne doit pas propager les exceptions")


# ---------------------------------------------------------------------------
# 7. Volume
# ---------------------------------------------------------------------------

class TestVolume:
    def test_volume_applied_to_pcm(self):
        pytest.importorskip("numpy")
        import numpy as np

        # PCM avec valeurs connues
        arr = np.array([10000, 20000, -10000], dtype=np.int16)
        raw_pcm = arr.tobytes()

        engine = PiperTTSEngine(
            volume=0.5,
            _piper_factory=lambda *a: raw_pcm,
        )
        result = engine.synthesize("test")
        assert result.success is True
        arr_out = np.frombuffer(result.pcm_bytes, dtype=np.int16)
        assert abs(int(arr_out[0]) - 5000) <= 1

    def test_volume_one_preserves_pcm(self):
        raw_pcm = _make_pcm(500)
        engine = PiperTTSEngine(
            volume=1.0,
            _piper_factory=lambda *a: raw_pcm,
        )
        result = engine.synthesize("test")
        assert result.pcm_bytes == raw_pcm
