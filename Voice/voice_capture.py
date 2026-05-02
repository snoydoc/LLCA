# Voice/voice_capture.py
# VOICE-01 — VAD + buffer PCM + logique utterance
# Isolation totale : 0 import depuis core/
# webrtcvad attend des frames PCM 16kHz mono signees 16-bit (little-endian)

from __future__ import annotations

import collections
import time
from dataclasses import dataclass, field
from typing import Callable, Deque, List, Optional

# ---------------------------------------------------------------------------
# Constantes de capture
# ---------------------------------------------------------------------------

SAMPLE_RATE: int = 16_000          # Hz — impose par webrtcvad
CHUNK_MS: int = 30                 # ms — webrtcvad accepte 10, 20 ou 30
BYTES_PER_SAMPLE: int = 2          # int16 little-endian
CHUNK_BYTES: int = (SAMPLE_RATE * CHUNK_MS // 1000) * BYTES_PER_SAMPLE  # 960 bytes

SILENCE_THRESHOLD_MS: int = 800   # ms silence consecutif -> fin utterance
MAX_UTTERANCE_MS: int = 30_000    # ms max par utterance (securite anti-blocage)
PRE_SPEECH_PADDING_MS: int = 200  # ms de contexte garde avant la parole detectee


# ---------------------------------------------------------------------------
# Resultat de VoiceCapture.process_chunk()
# ---------------------------------------------------------------------------

@dataclass
class CaptureResult:
    """
    Retourne par process_chunk() quand une utterance est complete.
    pcm_bytes : concatenation des chunks PCM bruts (16kHz mono int16 LE)
    duration_ms : duree approximative de l'utterance
    """
    pcm_bytes: bytes
    duration_ms: int

    @property
    def num_samples(self) -> int:
        return len(self.pcm_bytes) // BYTES_PER_SAMPLE

    def to_dict(self) -> dict:
        return {
            "pcm_bytes_len": len(self.pcm_bytes),
            "duration_ms": self.duration_ms,
            "num_samples": self.num_samples,
        }


# ---------------------------------------------------------------------------
# VoiceCapture — VAD + gestion buffer
# ---------------------------------------------------------------------------

class VoiceCapture:
    """
    Gere la detection d'activite vocale (VAD) et l'accumulation des chunks PCM.

    Usage typique (push-to-talk) :
        capture = VoiceCapture(aggressiveness=2)
        capture.start()
        for chunk in audio_source:
            result = capture.process_chunk(chunk)
            if result:
                # utterance complete -> envoyer a VoiceTranscriber
                transcribe(result.pcm_bytes)
        capture.stop()

    Usage avec callback :
        capture = VoiceCapture(on_utterance=my_callback)
        result = capture.process_chunk(chunk)  # callback appele automatiquement

    Isolation : n'importe pas webrtcvad au niveau module (import tardif dans __init__)
    pour permettre les tests sans le package installe.
    """

    def __init__(
        self,
        aggressiveness: int = 2,
        silence_threshold_ms: int = SILENCE_THRESHOLD_MS,
        max_utterance_ms: int = MAX_UTTERANCE_MS,
        pre_speech_padding_ms: int = PRE_SPEECH_PADDING_MS,
        on_utterance: Optional[Callable[[CaptureResult], None]] = None,
        _vad_factory=None,  # injectable pour les tests (remplace webrtcvad.Vad)
    ) -> None:
        if not (0 <= aggressiveness <= 3):
            raise ValueError(f"aggressiveness doit etre entre 0 et 3, recu : {aggressiveness}")

        self._aggressiveness = aggressiveness
        self._silence_threshold_ms = silence_threshold_ms
        self._max_utterance_ms = max_utterance_ms
        self._pre_speech_padding_ms = pre_speech_padding_ms
        self._on_utterance = on_utterance

        # Etat interne
        self._active: bool = False          # True entre start() et stop()
        self._in_speech: bool = False       # True si parole en cours
        self._silence_ms: int = 0           # ms silence accumule depuis fin parole
        self._utterance_ms: int = 0         # ms de l'utterance en cours
        self._speech_buffer: List[bytes] = []
        self._lock_instance = __import__("threading").Lock()

        # Ring buffer pre-speech (contexte avant detection)
        padding_chunks = max(1, pre_speech_padding_ms // CHUNK_MS)
        self._pre_buffer: Deque[bytes] = collections.deque(maxlen=padding_chunks)

        # VAD — import tardif pour testabilite
        if _vad_factory is not None:
            self._vad = _vad_factory(aggressiveness)
        else:
            try:
                import webrtcvad  # type: ignore
                self._vad = webrtcvad.Vad(aggressiveness)
            except ImportError:
                self._vad = _DummyVad()

        # Stats session
        self._total_chunks: int = 0
        self._total_utterances: int = 0
        self._start_time: Optional[float] = None

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Active la capture. Remet l'etat a zero."""
        with self._lock_instance:
            self._active = True
            self._reset_state()
            self._start_time = time.monotonic()

    def stop(self) -> Optional[CaptureResult]:
        """
        Desactive la capture.
        Si une utterance est en cours, la flush et la retourne.
        """
        with self._lock_instance:
            self._active = False
            result = self._flush_utterance()
            self._reset_state()
            return result

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def is_in_speech(self) -> bool:
        return self._in_speech

    # ------------------------------------------------------------------
    # Traitement des chunks
    # ------------------------------------------------------------------

    def process_chunk(self, pcm_chunk: bytes) -> Optional[CaptureResult]:
        """
        Traite un chunk PCM brut (CHUNK_BYTES bytes, 16kHz mono int16 LE).
        Retourne un CaptureResult quand une utterance est complete, None sinon.

        Thread-safe via _lock_instance.
        """
        with self._lock_instance:
            if not self._active:
                return None

            if len(pcm_chunk) != CHUNK_BYTES:
                # Chunk de taille incorrecte — ignore silencieusement
                return None

            self._total_chunks += 1

            # Detection VAD
            try:
                is_speech = self._vad.is_speech(pcm_chunk, SAMPLE_RATE)
            except Exception:
                is_speech = False

            return self._update_state(pcm_chunk, is_speech)

    def _update_state(self, chunk: bytes, is_speech: bool) -> Optional[CaptureResult]:
        """
        Machine a etats VAD :
        IDLE -> SPEECH (debut parole)
        SPEECH -> IDLE (silence >= threshold ou max_utterance atteint)
        """
        if is_speech:
            if not self._in_speech:
                # Debut de parole : inclure le pre-buffer (contexte)
                self._in_speech = True
                self._speech_buffer = list(self._pre_buffer)
            self._speech_buffer.append(chunk)
            self._silence_ms = 0
            self._utterance_ms += CHUNK_MS

            # Securite : utterance trop longue -> flush force
            if self._utterance_ms >= self._max_utterance_ms:
                return self._flush_and_reset()

        else:
            # Pas de parole
            self._pre_buffer.append(chunk)

            if self._in_speech:
                # En cours de silence apres parole
                self._speech_buffer.append(chunk)
                self._silence_ms += CHUNK_MS
                self._utterance_ms += CHUNK_MS

                if self._silence_ms >= self._silence_threshold_ms:
                    return self._flush_and_reset()

        return None

    def _flush_and_reset(self) -> Optional[CaptureResult]:
        """Finalise l'utterance courante et remet l'etat speech a zero."""
        result = self._flush_utterance()
        self._in_speech = False
        self._silence_ms = 0
        self._utterance_ms = 0
        self._speech_buffer = []
        return result

    def _flush_utterance(self) -> Optional[CaptureResult]:
        """
        Construit un CaptureResult depuis le buffer courant.
        Retourne None si le buffer est vide ou trop court (< 1 chunk).
        """
        if not self._speech_buffer:
            return None

        pcm = b"".join(self._speech_buffer)
        if len(pcm) < CHUNK_BYTES:
            return None

        duration_ms = (len(pcm) // CHUNK_BYTES) * CHUNK_MS
        result = CaptureResult(pcm_bytes=pcm, duration_ms=duration_ms)

        if self._on_utterance is not None:
            try:
                self._on_utterance(result)
            except Exception:
                pass  # callback ne doit jamais crasher le pipeline

        self._total_utterances += 1
        return result

    def _reset_state(self) -> None:
        """Remet tous les etats intermediaires a zero (pas les stats session)."""
        self._in_speech = False
        self._silence_ms = 0
        self._utterance_ms = 0
        self._speech_buffer = []
        self._pre_buffer.clear()

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Retourne les statistiques de la session courante."""
        elapsed = (
            time.monotonic() - self._start_time
            if self._start_time is not None
            else 0.0
        )
        return {
            "active": self._active,
            "in_speech": self._in_speech,
            "total_chunks": self._total_chunks,
            "total_utterances": self._total_utterances,
            "elapsed_sec": round(elapsed, 2),
            "aggressiveness": self._aggressiveness,
            "silence_threshold_ms": self._silence_threshold_ms,
            "chunk_ms": CHUNK_MS,
        }


# ---------------------------------------------------------------------------
# _DummyVad — fallback si webrtcvad absent (tests + CI sans le package)
# ---------------------------------------------------------------------------

class _DummyVad:
    """
    VAD de substitution : retourne toujours False (pas de parole).
    Permet d'importer voice_capture.py sans webrtcvad installe.
    """
    def is_speech(self, pcm_chunk: bytes, sample_rate: int) -> bool:  # noqa: ARG002
        return False


# ---------------------------------------------------------------------------
# Helpers audio utilitaires
# ---------------------------------------------------------------------------

def make_silent_chunk(num_chunks: int = 1) -> bytes:
    """Genere num_chunks chunks PCM silencieux (zeros) pour les tests."""
    return b"\x00" * CHUNK_BYTES * num_chunks


def make_speech_chunk(amplitude: int = 8000, num_chunks: int = 1) -> bytes:
    """
    Genere num_chunks chunks PCM avec un signal sinusoidal 440Hz
    pour simuler de la parole dans les tests.
    amplitude : valeur crete int16 (0-32767)
    """
    import struct
    import math
    freq = 440.0
    samples_per_chunk = SAMPLE_RATE * CHUNK_MS // 1000  # 480 samples
    total_samples = samples_per_chunk * num_chunks
    result = bytearray()
    for i in range(total_samples):
        t = i / SAMPLE_RATE
        val = int(amplitude * math.sin(2 * math.pi * freq * t))
        val = max(-32768, min(32767, val))
        result += struct.pack("<h", val)
    return bytes(result)
