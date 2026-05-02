# tests/test_voice_05.py
# VOICE-05 -- Tests KokoroTTSEngine
# _kokoro_factory injectable : 0 import kokoro reel requis

from __future__ import annotations

import os
import sys

import pytest

_VOICE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Voice")
if _VOICE_DIR not in sys.path:
    sys.path.insert(0, _VOICE_DIR)

from tts_engine_kokoro import (
    KokoroTTSEngine,
    TTS_SAMPLE_RATE,
    TTS_SAMPWIDTH,
    _float32_to_int16,
    _pcm_duration_ms,
)
from tts_engine_piper import SynthesisResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_float32_pcm(num_samples: int = 2400) -> bytes:
    """Genere du PCM float32 silence (0.0)."""
    return b"\x00\x00\x00\x00" * num_samples  # 4 bytes par float32


def _make_int16_pcm(num_samples: int = 1200) -> bytes:
    """Genere du PCM int16 silence."""
    return b"\x00\x00" * num_samples


def _make_engine(
    samples: bytes = b"",
    sample_rate: int = TTS_SAMPLE_RATE,
    fail: bool = False,
) -> KokoroTTSEngine:
    """
    Fabrique un KokoroTTSEngine avec _kokoro_factory injectable.
    Le factory retourne (float32_bytes, sample_rate).
    """
    def _factory(text, voice, lang, speed):
        if fail:
            raise RuntimeError("kokoro crash")
        pcm = samples if samples else _make_float32_pcm()
        return pcm, sample_rate

    return KokoroTTSEngine(_kokoro_factory=_factory)


# ---------------------------------------------------------------------------
# 1. Helpers module-level
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_pcm_duration_ms_zero_empty(self):
        assert _pcm_duration_ms(b"") == 0

    def test_pcm_duration_ms_one_second(self):
        # 24000 samples * 2 bytes = 48000 bytes -> 1000 ms
        pcm = b"\x00\x00" * 24000
        assert _pcm_duration_ms(pcm, sample_rate=24000) == 1000

    def test_pcm_duration_ms_half_second(self):
        pcm = b"\x00\x00" * 12000
        assert _pcm_duration_ms(pcm, sample_rate=24000) == 500

    def test_pcm_duration_ms_zero_rate(self):
        assert _pcm_duration_ms(b"\x00\x00", sample_rate=0) == 0

    def test_float32_to_int16_empty(self):
        assert _float32_to_int16(b"") == b""

    def test_float32_to_int16_silence(self):
        pytest.importorskip("numpy")
        import numpy as np
        silence = np.zeros(100, dtype=np.float32).tobytes()
        result = _float32_to_int16(silence)
        assert len(result) == 100 * 2  # 100 samples * 2 bytes int16
        arr = np.frombuffer(result, dtype=np.int16)
        assert (arr == 0).all()

    def test_float32_to_int16_max(self):
        pytest.importorskip("numpy")
        import numpy as np
        # 1.0 float32 -> 32767 int16 | -1.0 -> -32767 | 0.5 -> ~16383
        data = np.array([1.0, -1.0, 0.5], dtype=np.float32).tobytes()
        result = _float32_to_int16(data)
        arr = np.frombuffer(result, dtype=np.int16)
        assert arr[0] == 32767
        assert arr[1] == -32767  # -1.0 * 32767 = -32767 (pas de clip)
        assert abs(int(arr[2]) - 16383) <= 1

    def test_float32_to_int16_clipping(self):
        pytest.importorskip("numpy")
        import numpy as np
        # Valeurs hors [-1, 1] doivent etre clippees
        data = np.array([2.0, -2.0], dtype=np.float32).tobytes()
        result = _float32_to_int16(data)
        arr = np.frombuffer(result, dtype=np.int16)
        assert arr[0] == 32767
        assert arr[1] == -32768

    def test_float32_to_int16_accepts_ndarray(self):
        pytest.importorskip("numpy")
        import numpy as np
        arr = np.array([0.5, -0.5], dtype=np.float32)
        result = _float32_to_int16(arr)
        assert isinstance(result, bytes)
        assert len(result) == 4  # 2 samples * 2 bytes


# ---------------------------------------------------------------------------
# 2. Proprietes et init
# ---------------------------------------------------------------------------

class TestInit:
    def test_default_sample_rate(self):
        engine = _make_engine()
        assert engine.sample_rate == TTS_SAMPLE_RATE

    def test_volume_clamped_above(self):
        engine = KokoroTTSEngine(volume=5.0, _kokoro_factory=lambda *a: (b"", 24000))
        assert engine._volume == 1.0

    def test_volume_clamped_below(self):
        engine = KokoroTTSEngine(volume=-1.0, _kokoro_factory=lambda *a: (b"", 24000))
        assert engine._volume == 0.0

    def test_speed_clamped_above(self):
        engine = KokoroTTSEngine(speed=10.0, _kokoro_factory=lambda *a: (b"", 24000))
        assert engine._speed == 3.0

    def test_speed_clamped_below(self):
        engine = KokoroTTSEngine(speed=0.1, _kokoro_factory=lambda *a: (b"", 24000))
        assert engine._speed == 0.5

    def test_not_loaded_by_default(self):
        engine = KokoroTTSEngine()
        assert engine.is_loaded is False

    def test_info_dict(self):
        engine = KokoroTTSEngine(
            lang="f",
            voice="ff_siwis",
            models_dir="models/kokoro",
            volume=0.8,
            speed=1.2,
            _kokoro_factory=lambda *a: (b"", 24000),
        )
        info = engine.info()
        assert info["engine"] == "kokoro"
        assert info["lang"] == "f"
        assert info["voice"] == "ff_siwis"
        assert info["sample_rate"] == TTS_SAMPLE_RATE
        assert abs(info["volume"] - 0.8) < 1e-6
        assert abs(info["speed"] - 1.2) < 1e-6


# ---------------------------------------------------------------------------
# 3. load() et is_available()
# ---------------------------------------------------------------------------

class TestLoad:
    def test_load_true_with_factory(self):
        engine = _make_engine()
        assert engine.load() is True

    def test_is_loaded_after_load(self):
        engine = _make_engine()
        engine.load()
        assert engine.is_loaded is True

    def test_load_idempotent(self):
        engine = _make_engine()
        engine.load()
        assert engine.load() is True  # deuxieme appel

    def test_is_available_with_factory(self):
        engine = _make_engine()
        assert engine.is_available() is True

    def test_is_available_without_kokoro(self):
        """Sans factory et kokoro absent -> False."""
        engine = KokoroTTSEngine()  # pas de factory, kokoro pas installe
        # Ne pas assert la valeur car kokoro pourrait etre installe
        # On verifie juste que l'appel ne leve pas d'exception
        result = engine.is_available()
        assert isinstance(result, bool)

    def test_load_false_without_kokoro(self):
        """Sans factory et kokoro absent -> False (si non installe)."""
        import sys
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "kokoro":
                raise ImportError("kokoro absent")
            return real_import(name, *args, **kwargs)

        engine = KokoroTTSEngine()
        builtins.__import__ = mock_import
        try:
            result = engine.load()
        finally:
            builtins.__import__ = real_import

        assert result is False
        assert engine.is_loaded is False


# ---------------------------------------------------------------------------
# 4. Synthese -- cas nominaux
# ---------------------------------------------------------------------------

class TestSynthesizeSuccess:
    def test_returns_synthesis_result(self):
        engine = _make_engine()
        result = engine.synthesize("Bonjour")
        assert isinstance(result, SynthesisResult)

    def test_success_true(self):
        engine = _make_engine()
        result = engine.synthesize("test")
        assert result.success is True

    def test_pcm_bytes_non_empty(self):
        pytest.importorskip("numpy")
        import numpy as np
        samples = np.array([0.5] * 100, dtype=np.float32).tobytes()
        engine = _make_engine(samples=samples)
        result = engine.synthesize("test")
        assert len(result.pcm_bytes) > 0

    def test_sample_rate_from_factory(self):
        engine = _make_engine(sample_rate=16000)
        result = engine.synthesize("test")
        assert result.sample_rate == 16000

    def test_duration_ms_calculated(self):
        pytest.importorskip("numpy")
        import numpy as np
        # 24000 float32 samples -> apres conversion int16 = 24000 int16 -> 1000 ms a 24000 Hz
        samples = np.zeros(24000, dtype=np.float32).tobytes()
        engine = _make_engine(samples=samples, sample_rate=24000)
        result = engine.synthesize("test")
        assert result.duration_ms == 1000

    def test_factory_receives_correct_params(self):
        received = {}

        def _factory(text, voice, lang, speed):
            received.update({"text": text, "voice": voice, "lang": lang, "speed": speed})
            return _make_float32_pcm(), TTS_SAMPLE_RATE

        engine = KokoroTTSEngine(
            lang="f",
            voice="ff_siwis",
            speed=1.5,
            _kokoro_factory=_factory,
        )
        engine.synthesize("bonjour")
        assert received["text"] == "bonjour"
        assert received["voice"] == "ff_siwis"
        assert received["lang"] == "f"
        assert abs(received["speed"] - 1.5) < 1e-6

    def test_text_stripped(self):
        received = {}

        def _factory(text, voice, lang, speed):
            received["text"] = text
            return _make_float32_pcm(), TTS_SAMPLE_RATE

        engine = KokoroTTSEngine(_kokoro_factory=_factory)
        engine.synthesize("  bonjour  ")
        assert received["text"] == "bonjour"

    def test_load_called_automatically(self):
        engine = _make_engine()
        assert engine.is_loaded is False
        engine.synthesize("test")
        assert engine.is_loaded is True


# ---------------------------------------------------------------------------
# 5. Synthese -- cas d'erreur
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
        assert "kokoro crash" in result.error

    def test_no_exception_propagated(self):
        engine = _make_engine(fail=True)
        try:
            engine.synthesize("test")
        except Exception:
            pytest.fail("synthesize ne doit pas propager les exceptions")

    def test_unavailable_without_load_returns_failure(self):
        """Sans factory et kokoro absent -> failure apres tentative de load."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "kokoro":
                raise ImportError("kokoro absent")
            return real_import(name, *args, **kwargs)

        engine = KokoroTTSEngine()
        builtins.__import__ = mock_import
        try:
            result = engine.synthesize("test")
        finally:
            builtins.__import__ = real_import

        assert result.success is False
        assert result.pcm_bytes == b""


# ---------------------------------------------------------------------------
# 6. Volume
# ---------------------------------------------------------------------------

class TestVolume:
    def test_volume_half_reduces_amplitude(self):
        pytest.importorskip("numpy")
        import numpy as np

        # Samples float32 avec amplitude connue : 0.5 -> int16 ~16383
        samples = np.array([0.5] * 100, dtype=np.float32).tobytes()

        engine = KokoroTTSEngine(
            volume=0.5,
            _kokoro_factory=lambda *a: (samples, TTS_SAMPLE_RATE),
        )
        result = engine.synthesize("test")
        assert result.success is True
        arr = np.frombuffer(result.pcm_bytes, dtype=np.int16)
        # 0.5 float32 -> ~16383 int16, puis *0.5 volume -> ~8191
        assert abs(int(arr[0]) - 8191) <= 2

    def test_volume_one_no_loss(self):
        pytest.importorskip("numpy")
        import numpy as np

        samples = np.array([0.3] * 50, dtype=np.float32).tobytes()
        engine_full = KokoroTTSEngine(
            volume=1.0,
            _kokoro_factory=lambda *a: (samples, TTS_SAMPLE_RATE),
        )
        engine_half = KokoroTTSEngine(
            volume=0.5,
            _kokoro_factory=lambda *a: (samples, TTS_SAMPLE_RATE),
        )
        r_full = engine_full.synthesize("test")
        r_half = engine_half.synthesize("test")
        arr_full = np.frombuffer(r_full.pcm_bytes, dtype=np.int16)
        arr_half = np.frombuffer(r_half.pcm_bytes, dtype=np.int16)
        # full > half pour des valeurs non nulles
        assert abs(int(arr_full[0])) > abs(int(arr_half[0]))
