# Voice/voice_transcriber.py
# VOICE-02 -- Transcription PCM -> texte via faster-whisper
# Isolation totale : 0 import depuis core/
# Encodage : utf-8-sig (BOM Windows)

from __future__ import annotations

import logging
import os
import sys
import tempfile
import wave
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("lcca.voice.transcriber")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

STT_SAMPLE_RATE: int = 16_000   # Hz -- impose par webrtcvad + faster-whisper
STT_CHANNELS: int = 1           # mono
STT_SAMPWIDTH: int = 2          # int16 little-endian


# ---------------------------------------------------------------------------
# TranscriptionResult
# ---------------------------------------------------------------------------

@dataclass
class TranscriptionResult:
    """
    Resultat d'une transcription STT.

    Attributes:
        text        : Texte transcrit (vide si echec ou silence).
        confidence  : Score de confiance moyen (0.0 -- 1.0).
        language    : Langue detectee (ex: "fr", "en").
        duration_ms : Duree audio traitee en millisecondes.
        success     : False si le moteur a leve une exception.
        error       : Message d'erreur si success=False.
    """
    text: str
    confidence: float = 0.0
    language: str = "fr"
    duration_ms: int = 0
    success: bool = True
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "language": self.language,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TranscriptionResult":
        return cls(
            text=d.get("text", ""),
            confidence=float(d.get("confidence", 0.0)),
            language=d.get("language", "fr"),
            duration_ms=int(d.get("duration_ms", 0)),
            success=bool(d.get("success", True)),
            error=d.get("error", ""),
        )

    @classmethod
    def failure(cls, error: str, duration_ms: int = 0) -> "TranscriptionResult":
        """Construit un resultat d'echec."""
        return cls(
            text="",
            confidence=0.0,
            duration_ms=duration_ms,
            success=False,
            error=error,
        )


# ---------------------------------------------------------------------------
# VoiceTranscriber
# ---------------------------------------------------------------------------

class VoiceTranscriber:
    """
    Wrapper faster-whisper pour la transcription PCM -> texte.

    Usage::

        transcriber = VoiceTranscriber(model="small", language="fr")
        result = transcriber.transcribe(pcm_bytes)
        print(result.text)

    Isolation :
        - WhisperModel importe en lazy dans load() (testable sans faster-whisper)
        - _model_factory injectable pour les tests
        - 0 import depuis core/

    Args:
        model          : Nom du modele faster-whisper ("tiny", "base", "small", etc.)
        language       : Langue de transcription ("fr", "en", ...). None = auto-detect.
        device         : "cpu", "cuda" ou "auto" (resolu via resolve_stt_device si "auto")
        compute_type   : "int8", "float16", "float32"
        beam_size      : Taille de faisceau pour le decodage (1 = greedy, defaut 5)
        _model_factory : Injectable pour les tests -- remplace WhisperModel(...)
    """

    def __init__(
        self,
        model: str = "small",
        language: Optional[str] = "fr",
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 5,
        _model_factory=None,
    ) -> None:
        self._model_name = model
        self._language = language
        self._device = device
        self._compute_type = compute_type
        self._beam_size = beam_size
        self._model_factory = _model_factory
        self._model = None          # charge en lazy via load()
        self._loaded = False

    # ------------------------------------------------------------------
    # Chargement du modele
    # ------------------------------------------------------------------

    def load(self) -> bool:
        """
        Charge le modele faster-whisper.
        Retourne True si succes, False si faster-whisper est absent ou erreur.
        Idempotent : un second appel retourne True sans recharger.
        """
        if self._loaded:
            return True

        try:
            if self._model_factory is not None:
                self._model = self._model_factory(
                    self._model_name,
                    device=self._device,
                    compute_type=self._compute_type,
                )
            else:
                from faster_whisper import WhisperModel  # type: ignore
                self._model = WhisperModel(
                    self._model_name,
                    device=self._device,
                    compute_type=self._compute_type,
                )
            self._loaded = True
            logger.info(
                "[transcriber] modele '%s' charge (device=%s compute_type=%s)",
                self._model_name, self._device, self._compute_type,
            )
            return True
        except ImportError:
            logger.warning("[transcriber] faster-whisper absent -- transcription desactivee")
            return False
        except Exception as exc:
            logger.warning("[transcriber] erreur chargement modele : %s", exc)
            return False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    def transcribe(self, pcm_bytes: bytes) -> TranscriptionResult:
        """
        Transcrit un buffer PCM brut (16kHz mono int16 LE) en texte.

        1. Ecrit un fichier WAV temporaire (faster-whisper attend un fichier).
        2. Appelle WhisperModel.transcribe().
        3. Aggrège les segments -> texte + confiance moyenne.
        4. Supprime le fichier temporaire.

        Args:
            pcm_bytes : Donnees PCM brutes issues de VoiceCapture.

        Returns:
            TranscriptionResult. success=False si le modele n'est pas charge
            ou si une exception est levee.
        """
        if not pcm_bytes:
            return TranscriptionResult.failure("pcm_bytes vide")

        duration_ms = _pcm_duration_ms(pcm_bytes)

        if not self._loaded:
            ok = self.load()
            if not ok:
                return TranscriptionResult.failure(
                    "Modele non disponible (faster-whisper absent ou erreur chargement)",
                    duration_ms=duration_ms,
                )

        wav_path: Optional[str] = None
        try:
            wav_path = _write_wav_temp(pcm_bytes)
            segments, info = self._model.transcribe(
                wav_path,
                beam_size=self._beam_size,
                language=self._language,
                condition_on_previous_text=False,
            )

            # Aggrège les segments
            texts: list[str] = []
            confidences: list[float] = []
            for segment in segments:
                t = (segment.text or "").strip()
                if t:
                    texts.append(t)
                avg_logprob = getattr(segment, "avg_logprob", 0.0) or 0.0
                # Conversion logprob -> probabilite bornee [0, 1]
                import math
                conf = max(0.0, min(1.0, math.exp(avg_logprob)))
                confidences.append(conf)

            full_text = " ".join(texts).strip()
            avg_conf = (sum(confidences) / len(confidences)) if confidences else 0.0
            detected_lang = getattr(info, "language", None) or self._language or "fr"

            return TranscriptionResult(
                text=full_text,
                confidence=avg_conf,
                language=detected_lang,
                duration_ms=duration_ms,
                success=True,
            )

        except Exception as exc:
            logger.warning("[transcriber] erreur transcription : %s", exc)
            return TranscriptionResult.failure(str(exc), duration_ms=duration_ms)

        finally:
            if wav_path and os.path.isfile(wav_path):
                try:
                    os.unlink(wav_path)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def info(self) -> dict:
        """Retourne les parametres courants du transcriber."""
        return {
            "model": self._model_name,
            "language": self._language,
            "device": self._device,
            "compute_type": self._compute_type,
            "beam_size": self._beam_size,
            "loaded": self._loaded,
        }


# ---------------------------------------------------------------------------
# Helpers module-level
# ---------------------------------------------------------------------------

def _write_wav_temp(pcm_bytes: bytes) -> str:
    """
    Ecrit pcm_bytes dans un fichier WAV temporaire (16kHz mono int16).
    Retourne le chemin absolu du fichier. Appelant responsable de la suppression.
    """
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="lcca_stt_")
    os.close(fd)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(STT_CHANNELS)
        wf.setsampwidth(STT_SAMPWIDTH)
        wf.setframerate(STT_SAMPLE_RATE)
        wf.writeframes(pcm_bytes)
    return path


def _pcm_duration_ms(pcm_bytes: bytes) -> int:
    """Calcule la duree en ms d'un buffer PCM 16kHz mono int16."""
    if not pcm_bytes:
        return 0
    num_samples = len(pcm_bytes) // STT_SAMPWIDTH
    return int(num_samples * 1000 / STT_SAMPLE_RATE)
