# tests/test_voice_02.py
# VOICE-02 -- Tests VoiceTranscriber (faster-whisper wrapper)
# WhisperModel mocke via _model_factory injectable

from __future__ import annotations

import math
import os
import sys

import pytest

_VOICE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Voice")
if _VOICE_DIR not in sys.path:
    sys.path.insert(0, _VOICE_DIR)

from voice_transcriber import (
    VoiceTranscriber,
    TranscriptionResult,
    _write_wav_temp,
    _pcm_duration_ms,
    STT_SAMPLE_RATE,
    STT_SAMPWIDTH,
)
from voice_capture import make_silent_chunk, make_speech_chunk, CHUNK_BYTES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pcm(num_chunks: int = 10) -> bytes:
    return make_speech_chunk(num_chunks=num_chunks)


def _make_segment(text: str = "bonjour", avg_logprob: float = -0.2):
    from unittest.mock import MagicMock
    seg = MagicMock()
    seg.text = text
    seg.avg_logprob = avg_logprob
    return seg


def _make_info(language: str = "fr"):
    from unittest.mock import MagicMock
    info = MagicMock()
    info.language = language
    return info


def _make_model(segments=None, language: str = "fr", raises=None):
    """Fabrique un mock WhisperModel."""
    from unittest.mock import MagicMock
    model = MagicMock()
    if raises:
        model.transcribe.side_effect = raises
    else:
        segs = segments if segments is not None else [_make_segment("bonjour")]
        info = _make_info(language)
        model.transcribe.return_value = (iter(segs), info)
    return model


def _make_transcriber(segments=None, language: str = "fr", raises=None) -> VoiceTranscriber:
    """Transcriber avec model_factory mocke."""
    model = _make_model(segments=segments, language=language, raises=raises)
    factory = lambda name, device, compute_type: model  # noqa: E731
    t = VoiceTranscriber(model="small", language="fr", _model_factory=factory)
    return t


# ===========================================================================
# 1. TranscriptionResult
# ===========================================================================

class TestTranscriptionResult:
    def test_to_dict_keys(self):
        r = TranscriptionResult(text="hello", confidence=0.9, language="fr", duration_ms=500)
        d = r.to_dict()
        for k in ("text", "confidence", "language", "duration_ms", "success", "error"):
            assert k in d

    def test_from_dict_roundtrip(self):
        r = TranscriptionResult(text="bonjour", confidence=0.85, language="fr", duration_ms=300)
        r2 = TranscriptionResult.from_dict(r.to_dict())
        assert r2.text == "bonjour"
        assert r2.language == "fr"

    def test_failure_factory(self):
        r = TranscriptionResult.failure("erreur test", duration_ms=100)
        assert r.success is False
        assert r.text == ""
        assert r.error == "erreur test"
        assert r.duration_ms == 100

    def test_confidence_rounded_in_dict(self):
        r = TranscriptionResult(text="x", confidence=0.123456789)
        d = r.to_dict()
        assert len(str(d["confidence"]).split(".")[-1]) <= 4

    def test_default_success_true(self):
        r = TranscriptionResult(text="ok")
        assert r.success is True


# ===========================================================================
# 2. Helpers module-level
# ===========================================================================

class TestHelpers:
    def test_write_wav_temp_creates_file(self):
        pcm = _make_pcm(5)
        path = _write_wav_temp(pcm)
        assert os.path.isfile(path)
        assert path.endswith(".wav")
        os.unlink(path)

    def test_write_wav_temp_readable(self):
        import wave
        pcm = _make_pcm(10)
        path = _write_wav_temp(pcm)
        with wave.open(path, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getframerate() == STT_SAMPLE_RATE
            assert wf.getsampwidth() == STT_SAMPWIDTH
        os.unlink(path)

    def test_pcm_duration_ms_correct(self):
        # 1 seconde de PCM = 16000 samples * 2 bytes = 32000 bytes -> 1000ms
        pcm = b"\x00" * (STT_SAMPLE_RATE * STT_SAMPWIDTH)
        assert _pcm_duration_ms(pcm) == 1000

    def test_pcm_duration_ms_empty(self):
        assert _pcm_duration_ms(b"") == 0

    def test_pcm_duration_ms_partial(self):
        pcm = _make_pcm(10)
        ms = _pcm_duration_ms(pcm)
        assert ms > 0
        assert ms == int(len(pcm) // STT_SAMPWIDTH * 1000 / STT_SAMPLE_RATE)


# ===========================================================================
# 3. Chargement du modele
# ===========================================================================

class TestModelLoading:
    def test_not_loaded_by_default(self):
        t = VoiceTranscriber(_model_factory=lambda *a, **kw: _make_model())
        assert t.is_loaded is False

    def test_load_returns_true_with_factory(self):
        t = _make_transcriber()
        assert t.load() is True
        assert t.is_loaded is True

    def test_load_idempotent(self):
        t = _make_transcriber()
        assert t.load() is True
        assert t.load() is True  # deuxieme appel : OK sans recharger

    def test_load_false_on_import_error(self):
        def bad_factory(name, device, compute_type):
            raise ImportError("faster-whisper absent")
        t = VoiceTranscriber(_model_factory=bad_factory)
        assert t.load() is False
        assert t.is_loaded is False

    def test_load_false_on_generic_exception(self):
        def bad_factory(name, device, compute_type):
            raise RuntimeError("CUDA error")
        t = VoiceTranscriber(_model_factory=bad_factory)
        assert t.load() is False

    def test_factory_receives_correct_args(self):
        calls = []
        def spy_factory(name, device, compute_type):
            calls.append((name, device, compute_type))
            return _make_model()
        t = VoiceTranscriber(
            model="tiny", device="cpu", compute_type="float32",
            _model_factory=spy_factory,
        )
        t.load()
        assert calls == [("tiny", "cpu", "float32")]


# ===========================================================================
# 4. Transcription nominale
# ===========================================================================

class TestTranscribeNominal:
    def test_returns_transcription_result(self):
        t = _make_transcriber(segments=[_make_segment("bonjour")])
        r = t.transcribe(_make_pcm())
        assert isinstance(r, TranscriptionResult)
        assert r.success is True

    def test_text_aggregated_from_segments(self):
        segs = [_make_segment("bonjour"), _make_segment("monde")]
        t = _make_transcriber(segments=segs)
        r = t.transcribe(_make_pcm())
        assert "bonjour" in r.text
        assert "monde" in r.text

    def test_empty_segments_returns_empty_text(self):
        t = _make_transcriber(segments=[])
        r = t.transcribe(_make_pcm())
        assert r.text == ""
        assert r.success is True

    def test_language_from_info(self):
        t = _make_transcriber(language="en")
        r = t.transcribe(_make_pcm())
        assert r.language == "en"

    def test_confidence_between_0_and_1(self):
        segs = [_make_segment("test", avg_logprob=-0.5)]
        t = _make_transcriber(segments=segs)
        r = t.transcribe(_make_pcm())
        assert 0.0 <= r.confidence <= 1.0

    def test_duration_ms_positive(self):
        t = _make_transcriber()
        r = t.transcribe(_make_pcm(20))
        assert r.duration_ms > 0

    def test_tmp_wav_cleaned_up(self):
        """Le fichier WAV temporaire est supprime apres transcription."""
        created_paths = []
        original_write = __import__("voice_transcriber")._write_wav_temp

        def spy_write(pcm):
            path = original_write(pcm)
            created_paths.append(path)
            return path

        import voice_transcriber
        orig = voice_transcriber._write_wav_temp
        voice_transcriber._write_wav_temp = spy_write

        try:
            t = _make_transcriber()
            t.transcribe(_make_pcm())
        finally:
            voice_transcriber._write_wav_temp = orig

        for path in created_paths:
            assert not os.path.isfile(path), f"WAV temporaire non supprime : {path}"

    def test_load_called_automatically(self):
        """transcribe() charge le modele si pas encore fait."""
        t = _make_transcriber()
        assert t.is_loaded is False
        r = t.transcribe(_make_pcm())
        assert t.is_loaded is True
        assert r.success is True


# ===========================================================================
# 5. Cas d'erreur
# ===========================================================================

class TestTranscribeErrors:
    def test_empty_pcm_returns_failure(self):
        t = _make_transcriber()
        r = t.transcribe(b"")
        assert r.success is False
        assert "vide" in r.error

    def test_model_load_failure_returns_failure(self):
        def bad_factory(name, device, compute_type):
            raise ImportError("no faster-whisper")
        t = VoiceTranscriber(_model_factory=bad_factory)
        r = t.transcribe(_make_pcm())
        assert r.success is False
        assert r.text == ""

    def test_transcribe_exception_returns_failure(self):
        t = _make_transcriber(raises=RuntimeError("decode error"))
        r = t.transcribe(_make_pcm())
        assert r.success is False
        assert "decode error" in r.error

    def test_transcribe_exception_no_propagation(self):
        """Une exception interne ne doit pas se propager hors de transcribe()."""
        t = _make_transcriber(raises=RuntimeError("crash"))
        try:
            t.transcribe(_make_pcm())
        except Exception:
            pytest.fail("transcribe() ne doit pas propager les exceptions")

    def test_failure_duration_ms_present(self):
        """Meme en cas d'echec, duration_ms est calcule."""
        t = _make_transcriber(raises=RuntimeError("err"))
        r = t.transcribe(_make_pcm(10))
        assert r.duration_ms > 0


# ===========================================================================
# 6. Methode info()
# ===========================================================================

class TestInfo:
    def test_info_keys(self):
        t = VoiceTranscriber(
            model="base", language="en", device="cpu",
            compute_type="float32", beam_size=3,
            _model_factory=lambda *a, **kw: _make_model(),
        )
        info = t.info()
        assert info["model"] == "base"
        assert info["language"] == "en"
        assert info["device"] == "cpu"
        assert info["compute_type"] == "float32"
        assert info["beam_size"] == 3
        assert info["loaded"] is False

    def test_info_loaded_true_after_load(self):
        t = _make_transcriber()
        t.load()
        assert t.info()["loaded"] is True


# ===========================================================================
# 7. Logprob -> confidence conversion
# ===========================================================================

class TestLogprobConversion:
    def test_logprob_zero_gives_confidence_1(self):
        """avg_logprob=0.0 -> exp(0)=1.0."""
        segs = [_make_segment("x", avg_logprob=0.0)]
        t = _make_transcriber(segments=segs)
        r = t.transcribe(_make_pcm())
        assert abs(r.confidence - 1.0) < 0.01

    def test_logprob_negative_gives_less_than_1(self):
        segs = [_make_segment("x", avg_logprob=-1.0)]
        t = _make_transcriber(segments=segs)
        r = t.transcribe(_make_pcm())
        assert r.confidence < 1.0
        assert r.confidence > 0.0

    def test_very_negative_logprob_clamped_to_0(self):
        segs = [_make_segment("x", avg_logprob=-100.0)]
        t = _make_transcriber(segments=segs)
        r = t.transcribe(_make_pcm())
        assert r.confidence >= 0.0
