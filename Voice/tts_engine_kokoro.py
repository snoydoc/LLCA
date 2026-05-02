# Voice/tts_engine_kokoro.py
# VOICE-05 -- Moteur TTS Kokoro (synthese vocale, fallback CPU)
# Isolation totale : 0 import depuis core/
# Encodage : utf-8-sig (BOM Windows)

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("lcca.voice.tts_kokoro")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

TTS_SAMPLE_RATE: int = 24_000   # Hz -- Kokoro 24000 Hz
TTS_SAMPWIDTH: int = 2          # int16 little-endian

# Re-exporte SynthesisResult depuis tts_engine_piper pour partage de type
# (evite la duplication de la dataclass entre les deux moteurs)
try:
    import sys as _sys
    import os as _os
    _VOICE_DIR = _os.path.dirname(_os.path.abspath(__file__))
    if _VOICE_DIR not in _sys.path:
        _sys.path.insert(0, _VOICE_DIR)
    from tts_engine_piper import SynthesisResult, _apply_volume, _pcm_duration_ms as _piper_pcm_duration_ms
except ImportError:
    # Fallback si tts_engine_piper absent (tests isoles)
    from dataclasses import dataclass

    @dataclass
    class SynthesisResult:  # type: ignore[no-redef]
        pcm_bytes: bytes
        sample_rate: int = TTS_SAMPLE_RATE
        duration_ms: int = 0
        success: bool = True
        error: str = ""

        def to_dict(self) -> dict:
            return {
                "pcm_bytes_len": len(self.pcm_bytes),
                "sample_rate": self.sample_rate,
                "duration_ms": self.duration_ms,
                "success": self.success,
                "error": self.error,
            }

        @classmethod
        def failure(cls, error: str) -> "SynthesisResult":
            return cls(pcm_bytes=b"", duration_ms=0, success=False, error=error)

    def _apply_volume(pcm_bytes: bytes, volume: float) -> bytes:
        return pcm_bytes


def _pcm_duration_ms(pcm_bytes: bytes, sample_rate: int = TTS_SAMPLE_RATE) -> int:
    """Calcule la duree en ms d'un buffer PCM mono int16."""
    if not pcm_bytes or sample_rate <= 0:
        return 0
    num_samples = len(pcm_bytes) // TTS_SAMPWIDTH
    return int(num_samples * 1000 / sample_rate)


# ---------------------------------------------------------------------------
# KokoroTTSEngine
# ---------------------------------------------------------------------------

class KokoroTTSEngine:
    """
    Wrapper Kokoro pour la synthese vocale offline (fallback CPU).

    Kokoro est une librairie Python qui genere du PCM float32 (normalise -1..1).
    Ce moteur convertit la sortie en int16 LE avant de la retourner.

    Usage::

        engine = KokoroTTSEngine(lang="a", voice="af_heart")
        result = engine.synthesize("Hello world")
        # result.pcm_bytes contient du PCM int16 LE 24kHz

    Isolation :
        - KokoroEngine importe en lazy dans load() (testable sans kokoro)
        - _kokoro_factory injectable pour les tests
        - 0 import depuis core/

    Args:
        lang            : Code langue Kokoro ("a"=american-en, "b"=british-en, "f"=french).
        voice           : Voix Kokoro (ex: "af_heart", "ff_siwis").
        models_dir      : Dossier contenant les weights Kokoro.
        volume          : Multiplicateur de volume (0.0-1.0, defaut 0.85).
        speed           : Vitesse de parole (defaut 1.0).
        _kokoro_factory : Injectable pour les tests -- retourne (samples_float32, sr).
    """

    def __init__(
        self,
        lang: str = "a",
        voice: str = "af_heart",
        models_dir: str = "models/tts/kokoro",
        volume: float = 0.85,
        speed: float = 1.0,
        _kokoro_factory=None,
    ) -> None:
        self._lang = lang
        self._voice = voice
        self._models_dir = models_dir
        self._volume = max(0.0, min(1.0, volume))
        self._speed = max(0.5, min(3.0, speed))
        self._kokoro_factory = _kokoro_factory
        self._pipeline = None       # charge en lazy via load()
        self._loaded = False
        self._sample_rate = TTS_SAMPLE_RATE

    # ------------------------------------------------------------------
    # Proprietes
    # ------------------------------------------------------------------

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    # ------------------------------------------------------------------
    # Chargement
    # ------------------------------------------------------------------

    def load(self) -> bool:
        """
        Charge le pipeline Kokoro (lazy).
        Retourne True si succes, False si kokoro absent ou erreur.
        Idempotent.
        Si _kokoro_factory injecte -> True sans chargement reel.
        """
        if self._loaded:
            return True

        if self._kokoro_factory is not None:
            self._loaded = True
            return True

        try:
            from kokoro import KPipeline  # type: ignore
            self._pipeline = KPipeline(
                lang_code=self._lang,
                repo_id=self._models_dir,
            )
            self._loaded = True
            logger.info(
                "[kokoro] pipeline charge (lang=%s voice=%s)",
                self._lang, self._voice,
            )
            return True
        except ImportError:
            logger.warning("[kokoro] kokoro absent -- TTS Kokoro desactive")
            return False
        except Exception as exc:
            logger.warning("[kokoro] erreur chargement : %s", exc)
            return False

    def is_available(self) -> bool:
        """
        Verifie que Kokoro peut etre charge.
        Si _kokoro_factory injecte -> True.
        Sinon tente un import sans instancier le pipeline.
        """
        if self._kokoro_factory is not None:
            return True
        try:
            import kokoro  # type: ignore  # noqa: F401
            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # Synthese
    # ------------------------------------------------------------------

    def synthesize(self, text: str) -> SynthesisResult:
        """
        Synthetise le texte en PCM int16 LE via Kokoro.

        Args:
            text : Texte a synthetiser.

        Returns:
            SynthesisResult. success=False si Kokoro est indisponible
            ou si une exception est levee.
        """
        if not text or not text.strip():
            return SynthesisResult.failure("texte vide")

        text = text.strip()

        if self._kokoro_factory is not None:
            # Marquer comme charge (load() est instantane avec factory)
            if not self._loaded:
                self.load()
            try:
                samples, sr = self._kokoro_factory(text, self._voice, self._lang, self._speed)
                pcm = _float32_to_int16(samples)
                pcm = _apply_volume(pcm, self._volume)
                effective_sr = sr if sr else self._sample_rate
                duration_ms = _pcm_duration_ms(pcm, effective_sr)
                return SynthesisResult(
                    pcm_bytes=pcm,
                    sample_rate=effective_sr,
                    duration_ms=duration_ms,
                    success=True,
                )
            except Exception as exc:
                logger.warning("[kokoro] erreur factory : %s", exc)
                return SynthesisResult.failure(str(exc))

        # Mode normal
        if not self._loaded:
            ok = self.load()
            if not ok:
                return SynthesisResult.failure("Kokoro non disponible")

        try:
            all_samples = _run_kokoro_pipeline(
                pipeline=self._pipeline,
                text=text,
                voice=self._voice,
                speed=self._speed,
            )
            pcm = _float32_to_int16(all_samples)
            pcm = _apply_volume(pcm, self._volume)
            duration_ms = _pcm_duration_ms(pcm, self._sample_rate)
            return SynthesisResult(
                pcm_bytes=pcm,
                sample_rate=self._sample_rate,
                duration_ms=duration_ms,
                success=True,
            )
        except Exception as exc:
            logger.warning("[kokoro] erreur synthese : %s", exc)
            return SynthesisResult.failure(str(exc))

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def info(self) -> dict:
        """Retourne les parametres courants du moteur."""
        return {
            "engine": "kokoro",
            "lang": self._lang,
            "voice": self._voice,
            "models_dir": self._models_dir,
            "sample_rate": self._sample_rate,
            "volume": self._volume,
            "speed": self._speed,
            "loaded": self._loaded,
        }


# ---------------------------------------------------------------------------
# Helpers module-level
# ---------------------------------------------------------------------------

def _run_kokoro_pipeline(pipeline, text: str, voice: str, speed: float) -> bytes:
    """
    Execute le pipeline Kokoro et concatene tous les segments audio.
    Retourne des bytes float32 bruts (avant conversion int16).
    """
    import numpy as np  # type: ignore

    chunks = []
    generator = pipeline(text, voice=voice, speed=speed)
    for _, _, audio in generator:
        if audio is not None and len(audio) > 0:
            chunks.append(audio)

    if not chunks:
        return b""

    combined = np.concatenate(chunks, axis=0)
    return combined.astype(np.float32).tobytes()


def _float32_to_int16(data) -> bytes:
    """
    Convertit du PCM float32 (-1..1) en int16 LE.
    Accepte bytes (raw float32) ou numpy.ndarray.
    Si numpy est absent et data est bytes, retourne les bytes inchanges (mode degrade).
    """
    if data is None:
        return b""
    # Compatibilite ndarray : tester la longueur plutot que le bool
    try:
        if len(data) == 0:
            return b""
    except TypeError:
        return b""
    try:
        import numpy as np  # type: ignore
        if isinstance(data, (bytes, bytearray)):
            arr = np.frombuffer(data, dtype=np.float32)
        else:
            arr = np.asarray(data, dtype=np.float32)
        arr = np.clip(arr * 32767.0, -32768, 32767)
        return arr.astype(np.int16).tobytes()
    except Exception:
        # Mode degrade : si numpy absent et data est bytes, retourner tel quel
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        return b""
