# tests/test_voice_01.py
# VOICE-01 — Tests voice_capture.py : VAD, buffer PCM, machine a etats
# Isolation : webrtcvad mocke via _vad_factory injectable

from __future__ import annotations

import os
import sys
import pytest

_VOICE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Voice")
if _VOICE_DIR not in sys.path:
    sys.path.insert(0, _VOICE_DIR)

from voice_capture import (
    VoiceCapture,
    CaptureResult,
    _DummyVad,
    make_silent_chunk,
    make_speech_chunk,
    CHUNK_BYTES,
    CHUNK_MS,
    SAMPLE_RATE,
    SILENCE_THRESHOLD_MS,
    MAX_UTTERANCE_MS,
)


# ---------------------------------------------------------------------------
# Helpers de test
# ---------------------------------------------------------------------------

class _FakeVad:
    """VAD injectable : retourne is_speech selon une liste de booleens."""
    def __init__(self, sequence: list[bool], default: bool = False):
        self._seq = list(sequence)
        self._idx = 0
        self._default = default

    def is_speech(self, pcm_chunk: bytes, sample_rate: int) -> bool:
        if self._idx < len(self._seq):
            val = self._seq[self._idx]
            self._idx += 1
            return val
        return self._default


def _make_capture(
    speech_sequence: list[bool] | None = None,
    silence_threshold_ms: int = SILENCE_THRESHOLD_MS,
    max_utterance_ms: int = MAX_UTTERANCE_MS,
    on_utterance=None,
    default_is_speech: bool = False,
) -> VoiceCapture:
    """Cree un VoiceCapture avec un VAD fake injectable."""
    seq = speech_sequence or []
    vad_factory = lambda agg: _FakeVad(seq, default=default_is_speech)  # noqa: E731
    return VoiceCapture(
        aggressiveness=2,
        silence_threshold_ms=silence_threshold_ms,
        max_utterance_ms=max_utterance_ms,
        on_utterance=on_utterance,
        _vad_factory=vad_factory,
    )


def _feed(capture: VoiceCapture, is_speech_list: list[bool]) -> list[CaptureResult]:
    """Injecte des chunks (parole ou silence) et collecte les resultats."""
    results = []
    for speech in is_speech_list:
        chunk = make_speech_chunk() if speech else make_silent_chunk()
        r = capture.process_chunk(chunk)
        if r is not None:
            results.append(r)
    return results


# ===========================================================================
# 1. Constantes et utilitaires
# ===========================================================================

class TestConstants:
    def test_chunk_bytes_correct(self):
        # 16000 Hz * 30ms / 1000 * 2 bytes = 960
        assert CHUNK_BYTES == 960

    def test_sample_rate(self):
        assert SAMPLE_RATE == 16_000

    def test_chunk_ms(self):
        assert CHUNK_MS == 30

    def test_make_silent_chunk_size(self):
        chunk = make_silent_chunk()
        assert len(chunk) == CHUNK_BYTES

    def test_make_silent_chunk_multi(self):
        chunk = make_silent_chunk(num_chunks=3)
        assert len(chunk) == CHUNK_BYTES * 3

    def test_make_speech_chunk_size(self):
        chunk = make_speech_chunk()
        assert len(chunk) == CHUNK_BYTES

    def test_make_speech_chunk_non_zero(self):
        chunk = make_speech_chunk(amplitude=8000)
        assert any(b != 0 for b in chunk)


# ===========================================================================
# 2. _DummyVad
# ===========================================================================

class TestDummyVad:
    def test_always_returns_false(self):
        vad = _DummyVad()
        chunk = make_silent_chunk()
        assert vad.is_speech(chunk, SAMPLE_RATE) is False
        assert vad.is_speech(chunk, SAMPLE_RATE) is False


# ===========================================================================
# 3. Cycle de vie start / stop
# ===========================================================================

class TestLifecycle:
    def test_inactive_by_default(self):
        cap = _make_capture()
        assert cap.is_active is False

    def test_active_after_start(self):
        cap = _make_capture()
        cap.start()
        assert cap.is_active is True

    def test_inactive_after_stop(self):
        cap = _make_capture()
        cap.start()
        cap.stop()
        assert cap.is_active is False

    def test_process_chunk_ignored_if_not_active(self):
        cap = _make_capture(speech_sequence=[True] * 20)
        chunk = make_speech_chunk()
        result = cap.process_chunk(chunk)
        assert result is None

    def test_stop_without_start_returns_none(self):
        cap = _make_capture()
        result = cap.stop()
        assert result is None


# ===========================================================================
# 4. Machine a etats VAD — cas nominaux
# ===========================================================================

class TestVADStateMachine:
    def test_silence_only_no_result(self):
        cap = _make_capture(speech_sequence=[False] * 50)
        cap.start()
        results = _feed(cap, [False] * 50)
        assert results == []

    def test_speech_then_silence_produces_result(self):
        """10 chunks parole + silence threshold -> CaptureResult."""
        n_silence = SILENCE_THRESHOLD_MS // CHUNK_MS  # 800/30 = 26 chunks
        speech_seq = [True] * 10 + [False] * n_silence
        cap = _make_capture(speech_sequence=speech_seq)
        cap.start()
        results = _feed(cap, speech_seq)
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, CaptureResult)
        assert r.duration_ms > 0
        assert len(r.pcm_bytes) > 0

    def test_result_pcm_length_consistent(self):
        """La longueur PCM correspond au nombre de chunks accumules."""
        n_silence = SILENCE_THRESHOLD_MS // CHUNK_MS + 1
        speech_seq = [True] * 5 + [False] * n_silence
        cap = _make_capture(speech_sequence=speech_seq)
        cap.start()
        results = _feed(cap, speech_seq)
        assert len(results) == 1
        # 5 speech + n_silence chunks dans le buffer (silence inclus apres parole)
        assert results[0].num_samples > 0
        assert len(results[0].pcm_bytes) % 2 == 0  # toujours pair (int16)

    def test_two_utterances_two_results(self):
        """Deux utterances separees par un long silence -> 2 resultats."""
        n_silence = SILENCE_THRESHOLD_MS // CHUNK_MS + 1
        seq = [True] * 5 + [False] * n_silence + [True] * 5 + [False] * n_silence
        cap = _make_capture(speech_sequence=seq)
        cap.start()
        results = _feed(cap, seq)
        assert len(results) == 2

    def test_not_in_speech_during_silence(self):
        cap = _make_capture(speech_sequence=[False] * 10)
        cap.start()
        _feed(cap, [False] * 10)
        assert cap.is_in_speech is False

    def test_in_speech_during_speech(self):
        # Uniquement parole, pas de silence -> in_speech reste True
        cap = _make_capture(speech_sequence=[True] * 10)
        cap.start()
        _feed(cap, [True] * 10)
        assert cap.is_in_speech is True

    def test_partial_silence_does_not_flush(self):
        """Silence partiel (< threshold) ne declenche pas de flush."""
        n_partial = (SILENCE_THRESHOLD_MS // CHUNK_MS) - 2  # sous le seuil
        seq = [True] * 5 + [False] * n_partial + [True] * 3
        cap = _make_capture(speech_sequence=seq)
        cap.start()
        results = _feed(cap, seq)
        assert len(results) == 0  # pas encore flush


# ===========================================================================
# 5. Chunk de mauvaise taille
# ===========================================================================

class TestBadChunk:
    def test_wrong_size_ignored(self):
        cap = _make_capture()
        cap.start()
        bad_chunk = b"\x00" * 100  # pas CHUNK_BYTES
        result = cap.process_chunk(bad_chunk)
        assert result is None
        assert cap.stats()["total_chunks"] == 0  # non compte

    def test_empty_chunk_ignored(self):
        cap = _make_capture()
        cap.start()
        result = cap.process_chunk(b"")
        assert result is None


# ===========================================================================
# 6. Max utterance (securite anti-blocage)
# ===========================================================================

class TestMaxUtterance:
    def test_max_utterance_flushes(self):
        """Parole continue > max_utterance_ms -> flush force."""
        max_ms = 3 * CHUNK_MS  # 3 chunks = 90ms max
        n_chunks = 5           # 5 chunks -> depasse le max
        cap = _make_capture(
            speech_sequence=[True] * n_chunks,
            max_utterance_ms=max_ms,
        )
        cap.start()
        results = _feed(cap, [True] * n_chunks)
        # Doit avoir flush au moins une fois
        assert len(results) >= 1


# ===========================================================================
# 7. Stop flush utterance en cours
# ===========================================================================

class TestStopFlush:
    def test_stop_flushes_partial_utterance(self):
        """stop() avec parole en cours -> retourne le CaptureResult partiel."""
        cap = _make_capture(speech_sequence=[True] * 10)
        cap.start()
        _feed(cap, [True] * 10)  # parole, pas encore de silence
        assert cap.is_in_speech is True
        result = cap.stop()
        # Le buffer avait du contenu -> flush retourne un resultat
        assert result is not None
        assert len(result.pcm_bytes) > 0

    def test_stop_empty_buffer_returns_none(self):
        """stop() sans parole -> None."""
        cap = _make_capture(speech_sequence=[False] * 5)
        cap.start()
        _feed(cap, [False] * 5)
        result = cap.stop()
        assert result is None


# ===========================================================================
# 8. Callback on_utterance
# ===========================================================================

class TestCallback:
    def test_callback_called_on_utterance(self):
        received = []
        n_silence = SILENCE_THRESHOLD_MS // CHUNK_MS + 1
        seq = [True] * 5 + [False] * n_silence

        cap = _make_capture(speech_sequence=seq, on_utterance=received.append)
        cap.start()
        _feed(cap, seq)
        assert len(received) == 1
        assert isinstance(received[0], CaptureResult)

    def test_callback_exception_does_not_crash(self):
        """Un callback qui leve une exception ne doit pas propager."""
        def bad_callback(r):
            raise RuntimeError("callback crash")

        n_silence = SILENCE_THRESHOLD_MS // CHUNK_MS + 1
        seq = [True] * 5 + [False] * n_silence
        cap = _make_capture(speech_sequence=seq, on_utterance=bad_callback)
        cap.start()
        results = _feed(cap, seq)  # ne doit pas lever
        # Le CaptureResult est quand meme retourne par process_chunk
        assert len(results) == 1


# ===========================================================================
# 9. Stats
# ===========================================================================

class TestStats:
    def test_stats_initial(self):
        cap = _make_capture()
        s = cap.stats()
        assert s["total_chunks"] == 0
        assert s["total_utterances"] == 0
        assert s["active"] is False

    def test_stats_after_chunks(self):
        n_silence = SILENCE_THRESHOLD_MS // CHUNK_MS + 1
        seq = [True] * 5 + [False] * n_silence
        cap = _make_capture(speech_sequence=seq)
        cap.start()
        _feed(cap, seq)
        s = cap.stats()
        assert s["total_chunks"] == len(seq)
        assert s["total_utterances"] == 1
        assert s["active"] is True

    def test_stats_aggressiveness_reflected(self):
        cap = VoiceCapture(aggressiveness=3, _vad_factory=lambda agg: _DummyVad())
        assert cap.stats()["aggressiveness"] == 3


# ===========================================================================
# 10. CaptureResult
# ===========================================================================

class TestCaptureResult:
    def test_num_samples(self):
        chunk = make_silent_chunk(3)
        r = CaptureResult(pcm_bytes=chunk, duration_ms=90)
        assert r.num_samples == (CHUNK_BYTES * 3) // 2

    def test_to_dict(self):
        chunk = make_silent_chunk()
        r = CaptureResult(pcm_bytes=chunk, duration_ms=30)
        d = r.to_dict()
        assert d["pcm_bytes_len"] == CHUNK_BYTES
        assert d["duration_ms"] == 30
        assert "num_samples" in d

    def test_aggressiveness_validation(self):
        with pytest.raises(ValueError):
            VoiceCapture(aggressiveness=5, _vad_factory=lambda a: _DummyVad())

    def test_aggressiveness_zero_valid(self):
        cap = VoiceCapture(aggressiveness=0, _vad_factory=lambda a: _DummyVad())
        assert cap.stats()["aggressiveness"] == 0
