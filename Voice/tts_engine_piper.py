# Voice/tts_engine_piper.py
# VOICE-04 -- Moteur TTS Piper ONNX (synthese vocale offline)
# Isolation totale : 0 import depuis core/
# Encodage : utf-8-sig (BOM Windows)

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("lcca.voice.tts_piper")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

TTS_SAMPLE_RATE: int = 22_050   # Hz -- Piper 22050 Hz par defaut (certains modeles 16kHz)
TTS_CHANNELS: int = 1           # mono
TTS_SAMPWIDTH: int = 2          # int16 little-endian


# ---------------------------------------------------------------------------
# SynthesisResult
# ---------------------------------------------------------------------------

@dataclass
class SynthesisResult:
    """
    Resultat d'une synthese TTS.

    Attributes:
        pcm_bytes   : Donnees PCM brutes (int16 LE, mono).
        sample_rate : Taux d'echantillonnage effectif (Hz).
        duration_ms : Duree audio en millisecondes.
        success     : False si le moteur a leve une exception.
        error       : Message d'erreur si success=False.
    """
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
        """Construit un resultat d'echec."""
        return cls(
            pcm_bytes=b"",
            duration_ms=0,
            success=False,
            error=error,
        )


# ---------------------------------------------------------------------------
# PiperTTSEngine
# ---------------------------------------------------------------------------

class PiperTTSEngine:
    """
    Wrapper Piper ONNX pour la synthese vocale offline.

    Piper est un binaire CLI + modele ONNX. Ce moteur l'appelle via subprocess :
        echo "texte" | piper --model model.onnx --output_raw > pcm_raw

    La sortie est du PCM brut int16 LE (pas de header WAV).

    Usage::

        engine = PiperTTSEngine(model_path="models/tts/piper/fr_FR-mls-medium.onnx")
        result = engine.synthesize("Bonjour le monde")
        # result.pcm_bytes contient le PCM brut

    Isolation :
        - _piper_factory injectable pour les tests (remplace subprocess.run)
        - 0 import depuis core/

    Args:
        model_path      : Chemin vers le fichier .onnx Piper.
        piper_exe       : Chemin vers le binaire piper (defaut: "piper" dans PATH).
        sample_rate     : Taux d'echantillonnage du modele (defaut: 22050).
        volume          : Multiplicateur de volume (0.0-1.0, defaut 0.85).
        _piper_factory  : Injectable pour les tests -- remplace subprocess.run.
    """

    def __init__(
        self,
        model_path: str = "",
        piper_exe: str = "piper",
        sample_rate: int = TTS_SAMPLE_RATE,
        volume: float = 0.85,
        _piper_factory=None,
    ) -> None:
        self._model_path = model_path
        self._piper_exe = piper_exe
        self._sample_rate = sample_rate
        self._volume = max(0.0, min(1.0, volume))
        self._piper_factory = _piper_factory
        self._available: Optional[bool] = None   # None = non encore verifie

    # ------------------------------------------------------------------
    # Proprietes
    # ------------------------------------------------------------------

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def model_path(self) -> str:
        return self._model_path

    # ------------------------------------------------------------------
    # Disponibilite
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """
        Verifie que le binaire piper est accessible et que le modele existe.
        Resultat mis en cache apres le premier appel.
        Si _piper_factory injecte -> disponible par definition.
        """
        if self._piper_factory is not None:
            return True

        if self._available is not None:
            return self._available

        # Verifier le binaire
        try:
            result = subprocess.run(
                [self._piper_exe, "--version"],
                capture_output=True,
                timeout=3,
            )
            binary_ok = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            binary_ok = False

        # Verifier le modele
        model_ok = bool(self._model_path) and os.path.isfile(self._model_path)

        self._available = binary_ok and model_ok
        if not self._available:
            logger.warning(
                "[piper] non disponible -- binaire=%s modele=%s",
                binary_ok,
                model_ok,
            )
        return self._available

    # ------------------------------------------------------------------
    # Synthese
    # ------------------------------------------------------------------

    def synthesize(self, text: str) -> SynthesisResult:
        """
        Synthetise le texte en PCM brut via Piper.

        Args:
            text : Texte a synthetiser (UTF-8).

        Returns:
            SynthesisResult. success=False si Piper est indisponible
            ou si une exception est levee.
        """
        if not text or not text.strip():
            return SynthesisResult.failure("texte vide")

        text = text.strip()

        if self._piper_factory is not None:
            # Mode test : appel via le factory injectable
            try:
                raw_pcm = self._piper_factory(text, self._model_path, self._sample_rate)
                if not isinstance(raw_pcm, bytes):
                    return SynthesisResult.failure("piper_factory doit retourner bytes")
                pcm = _apply_volume(raw_pcm, self._volume)
                duration_ms = _pcm_duration_ms(pcm, self._sample_rate)
                return SynthesisResult(
                    pcm_bytes=pcm,
                    sample_rate=self._sample_rate,
                    duration_ms=duration_ms,
                    success=True,
                )
            except Exception as exc:
                logger.warning("[piper] erreur factory : %s", exc)
                return SynthesisResult.failure(str(exc))

        # Mode normal : subprocess piper
        if not self.is_available():
            return SynthesisResult.failure("Piper non disponible (binaire ou modele manquant)")

        try:
            raw_pcm = _run_piper(
                text=text,
                model_path=self._model_path,
                piper_exe=self._piper_exe,
            )
            pcm = _apply_volume(raw_pcm, self._volume)
            duration_ms = _pcm_duration_ms(pcm, self._sample_rate)
            return SynthesisResult(
                pcm_bytes=pcm,
                sample_rate=self._sample_rate,
                duration_ms=duration_ms,
                success=True,
            )
        except Exception as exc:
            logger.warning("[piper] erreur synthese : %s", exc)
            return SynthesisResult.failure(str(exc))

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def info(self) -> dict:
        """Retourne les parametres courants du moteur."""
        return {
            "engine": "piper",
            "model_path": self._model_path,
            "piper_exe": self._piper_exe,
            "sample_rate": self._sample_rate,
            "volume": self._volume,
        }


# ---------------------------------------------------------------------------
# Helpers module-level
# ---------------------------------------------------------------------------

def _run_piper(text: str, model_path: str, piper_exe: str = "piper") -> bytes:
    """
    Appelle le binaire Piper en subprocess et retourne le PCM brut.

    Piper lit stdin (texte) et ecrit stdout (PCM raw int16 LE).
    En cas d'erreur subprocess, leve RuntimeError.
    """
    cmd = [
        piper_exe,
        "--model", model_path,
        "--output_raw",
        "--quiet",
    ]
    try:
        result = subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Piper timeout (>30s)")
    except FileNotFoundError:
        raise RuntimeError(f"Binaire piper introuvable : {piper_exe!r}")

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Piper exitcode={result.returncode} : {stderr}")

    if not result.stdout:
        raise RuntimeError("Piper a retourne un flux PCM vide")

    return result.stdout


def _apply_volume(pcm_bytes: bytes, volume: float) -> bytes:
    """
    Applique un multiplicateur de volume sur du PCM int16 LE.
    Si numpy est absent, retourne pcm_bytes inchange.
    volume=1.0 -> aucun changement, volume=0.0 -> silence.
    """
    if abs(volume - 1.0) < 1e-6:
        return pcm_bytes
    try:
        import numpy as np  # type: ignore
        arr = np.frombuffer(pcm_bytes, dtype=np.int16).copy().astype(np.float32)
        arr *= volume
        np.clip(arr, -32768, 32767, out=arr)
        return arr.astype(np.int16).tobytes()
    except Exception:
        return pcm_bytes


def _pcm_duration_ms(pcm_bytes: bytes, sample_rate: int = TTS_SAMPLE_RATE) -> int:
    """Calcule la duree en ms d'un buffer PCM mono int16."""
    if not pcm_bytes or sample_rate <= 0:
        return 0
    num_samples = len(pcm_bytes) // TTS_SAMPWIDTH
    return int(num_samples * 1000 / sample_rate)
