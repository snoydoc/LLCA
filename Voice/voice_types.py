# Voice/voice_types.py
# VOICE-00 — Dataclasses + enums du pipeline voix LCCA
# Isolation totale : 0 import depuis core/
# Encodage : utf-8-sig (BOM Windows)

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class VoiceState(str, Enum):
    """Etat du service STT rapporte via WebSocket."""
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    ERROR = "error"


class TTSEngine(str, Enum):
    """Moteur TTS selectionne."""
    PIPER = "piper"
    KOKORO = "kokoro"
    AUTO = "auto"


class STTDevice(str, Enum):
    """Device de calcul faster-whisper."""
    AUTO = "auto"
    CUDA = "cuda"
    CPU = "cpu"


class STTComputeType(str, Enum):
    """Type de calcul faster-whisper."""
    INT8 = "int8"
    FLOAT16 = "float16"
    FLOAT32 = "float32"


class VoiceMode(str, Enum):
    """Mode d'ecoute STT."""
    PUSH_TO_TALK = "push_to_talk"
    CONTINUOUS = "continuous"


class MessageType(str, Enum):
    """Type de message JSON WebSocket STT->Electron."""
    PARTIAL = "partial"
    FINAL = "final"
    STATUS = "status"


class TTSMessageType(str, Enum):
    """Type de message JSON WebSocket TTS."""
    SPEAK = "speak"
    STOP = "stop"
    STATUS = "status"
    CHUNK = "chunk"


# ---------------------------------------------------------------------------
# Messages WebSocket STT -> Electron
# ---------------------------------------------------------------------------

@dataclass
class PartialTranscript:
    """Transcription partielle (live feedback)."""
    text: str
    confidence: float = 0.0
    type: str = field(default=MessageType.PARTIAL.value, init=False)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "text": self.text,
            "confidence": round(self.confidence, 4),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PartialTranscript":
        return cls(
            text=d.get("text", ""),
            confidence=float(d.get("confidence", 0.0)),
        )


@dataclass
class FinalTranscript:
    """Transcription finale (utterance complete)."""
    text: str
    confidence: float = 0.0
    duration_ms: int = 0
    type: str = field(default=MessageType.FINAL.value, init=False)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FinalTranscript":
        return cls(
            text=d.get("text", ""),
            confidence=float(d.get("confidence", 0.0)),
            duration_ms=int(d.get("duration_ms", 0)),
        )


@dataclass
class StatusMessage:
    """Message de statut du service STT ou TTS."""
    state: str  # VoiceState ou etat TTS
    msg: str = ""
    type: str = field(default=MessageType.STATUS.value, init=False)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "state": self.state,
            "msg": self.msg,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StatusMessage":
        return cls(
            state=d.get("state", VoiceState.IDLE.value),
            msg=d.get("msg", ""),
        )


# ---------------------------------------------------------------------------
# Configuration runtime
# ---------------------------------------------------------------------------

@dataclass
class STTConfig:
    """Configuration du service STT (chargee depuis voice_config.toml)."""
    enabled: bool = True
    mode: str = VoiceMode.PUSH_TO_TALK.value
    model: str = "small"
    language: str = "fr"
    device: str = STTDevice.AUTO.value
    compute_type: str = STTComputeType.INT8.value
    port: int = 8765
    vad_aggressiveness: int = 2
    continuous_mode: bool = False
    show_partial_transcript: bool = True

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "model": self.model,
            "language": self.language,
            "device": self.device,
            "compute_type": self.compute_type,
            "port": self.port,
            "vad_aggressiveness": self.vad_aggressiveness,
            "continuous_mode": self.continuous_mode,
            "show_partial_transcript": self.show_partial_transcript,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "STTConfig":
        return cls(
            enabled=bool(d.get("enabled", True)),
            mode=d.get("mode", VoiceMode.PUSH_TO_TALK.value),
            model=d.get("model", "small"),
            language=d.get("language", "fr"),
            device=d.get("device", STTDevice.AUTO.value),
            compute_type=d.get("compute_type", STTComputeType.INT8.value),
            port=int(d.get("port", 8765)),
            vad_aggressiveness=int(d.get("vad_aggressiveness", 2)),
            continuous_mode=bool(d.get("continuous_mode", False)),
            show_partial_transcript=bool(d.get("show_partial_transcript", True)),
        )


@dataclass
class PiperConfig:
    """Configuration Piper TTS."""
    model_fr: str = "fr_FR-mls-medium"
    model_en: str = "en_US-amy-medium"
    models_dir: str = "models/tts/piper"

    def to_dict(self) -> dict:
        return {
            "model_fr": self.model_fr,
            "model_en": self.model_en,
            "models_dir": self.models_dir,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PiperConfig":
        return cls(
            model_fr=d.get("model_fr", "fr_FR-mls-medium"),
            model_en=d.get("model_en", "en_US-amy-medium"),
            models_dir=d.get("models_dir", "models/tts/piper"),
        )


@dataclass
class KokoroConfig:
    """Configuration Kokoro TTS."""
    lang: str = "a"          # a=american-en, b=british-en
    voice: str = "af_heart"
    models_dir: str = "models/tts/kokoro"

    def to_dict(self) -> dict:
        return {
            "lang": self.lang,
            "voice": self.voice,
            "models_dir": self.models_dir,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KokoroConfig":
        return cls(
            lang=d.get("lang", "a"),
            voice=d.get("voice", "af_heart"),
            models_dir=d.get("models_dir", "models/tts/kokoro"),
        )


@dataclass
class TTSConfig:
    """Configuration du service TTS."""
    enabled: bool = True
    engine: str = TTSEngine.AUTO.value
    port: int = 8766
    volume: float = 0.85
    piper: PiperConfig = field(default_factory=PiperConfig)
    kokoro: KokoroConfig = field(default_factory=KokoroConfig)

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "engine": self.engine,
            "port": self.port,
            "volume": self.volume,
            "piper": self.piper.to_dict(),
            "kokoro": self.kokoro.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TTSConfig":
        return cls(
            enabled=bool(d.get("enabled", True)),
            engine=d.get("engine", TTSEngine.AUTO.value),
            port=int(d.get("port", 8766)),
            volume=float(d.get("volume", 0.85)),
            piper=PiperConfig.from_dict(d.get("piper", {})),
            kokoro=KokoroConfig.from_dict(d.get("kokoro", {})),
        )


@dataclass
class UIConfig:
    """Configuration UI voice."""
    shortcut_push_to_talk: str = "Alt+V"
    shortcut_scope: str = "local"
    auto_submit: bool = False
    show_partial_transcript: bool = True
    audio_feedback: bool = True

    def to_dict(self) -> dict:
        return {
            "shortcut_push_to_talk": self.shortcut_push_to_talk,
            "shortcut_scope": self.shortcut_scope,
            "auto_submit": self.auto_submit,
            "show_partial_transcript": self.show_partial_transcript,
            "audio_feedback": self.audio_feedback,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "UIConfig":
        return cls(
            shortcut_push_to_talk=d.get("shortcut_push_to_talk", "Alt+V"),
            shortcut_scope=d.get("shortcut_scope", "local"),
            auto_submit=bool(d.get("auto_submit", False)),
            show_partial_transcript=bool(d.get("show_partial_transcript", True)),
            audio_feedback=bool(d.get("audio_feedback", True)),
        )


@dataclass
class VoiceConfig:
    """Configuration globale du pipeline voix — racine de voice_config.toml."""
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    ui: UIConfig = field(default_factory=UIConfig)

    def to_dict(self) -> dict:
        return {
            "stt": self.stt.to_dict(),
            "tts": self.tts.to_dict(),
            "ui": self.ui.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VoiceConfig":
        return cls(
            stt=STTConfig.from_dict(d.get("stt", {})),
            tts=TTSConfig.from_dict(d.get("tts", {})),
            ui=UIConfig.from_dict(d.get("ui", {})),
        )


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_voice_config(config_path: Optional[str] = None) -> VoiceConfig:
    """
    Charge voice_config.toml depuis config_path ou le dossier courant.
    Retourne VoiceConfig avec les valeurs par defaut si le fichier est absent.
    N'importe JAMAIS depuis core/.
    """
    import os
    import sys

    if config_path is None:
        # Chercher dans le dossier du script (Voice/) puis CWD
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(script_dir, "voice_config.toml"),
            os.path.join(os.getcwd(), "voice_config.toml"),
        ]
        config_path = next((p for p in candidates if os.path.isfile(p)), None)

    if config_path is None or not os.path.isfile(config_path):
        return VoiceConfig()

    try:
        # Python 3.11+ : tomllib stdlib
        if sys.version_info >= (3, 11):
            import tomllib
            with open(config_path, "rb") as f:
                raw = tomllib.load(f)
        else:
            try:
                import tomli as tomllib  # type: ignore
                with open(config_path, "rb") as f:
                    raw = tomllib.load(f)
            except ImportError:
                # Fallback : retourner les defauts si tomli absent
                return VoiceConfig()
        return VoiceConfig.from_dict(raw)
    except Exception:
        return VoiceConfig()


# ---------------------------------------------------------------------------
# Helpers runtime
# ---------------------------------------------------------------------------

@dataclass
class VRAMInfo:
    """Informations VRAM GPU pour le choix auto device/engine."""
    total_bytes: int = 0
    free_bytes: int = 0
    cuda_available: bool = False

    @property
    def free_mb(self) -> float:
        return self.free_bytes / (1024 * 1024)

    @property
    def total_mb(self) -> float:
        return self.total_bytes / (1024 * 1024)

    def to_dict(self) -> dict:
        return {
            "total_bytes": self.total_bytes,
            "free_bytes": self.free_bytes,
            "cuda_available": self.cuda_available,
            "free_mb": round(self.free_mb, 1),
            "total_mb": round(self.total_mb, 1),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VRAMInfo":
        return cls(
            total_bytes=int(d.get("total_bytes", 0)),
            free_bytes=int(d.get("free_bytes", 0)),
            cuda_available=bool(d.get("cuda_available", False)),
        )


def query_vram() -> VRAMInfo:
    """
    Retourne les infos VRAM disponibles.
    Retourne VRAMInfo(cuda_available=False) si torch absent ou pas de GPU.
    """
    try:
        import torch  # type: ignore
        if not torch.cuda.is_available():
            return VRAMInfo(cuda_available=False)
        free_bytes, total_bytes = torch.cuda.mem_get_info(0)
        return VRAMInfo(
            total_bytes=total_bytes,
            free_bytes=free_bytes,
            cuda_available=True,
        )
    except Exception:
        return VRAMInfo(cuda_available=False)


# Seuil VRAM libre minimum pour activer CUDA (STT + TTS ensemble)
VRAM_MIN_MB_FOR_CUDA: float = 1500.0  # 1.5 GB libre minimum


def resolve_stt_device(cfg: STTConfig, vram: Optional[VRAMInfo] = None) -> str:
    """
    Retourne le device effectif pour faster-whisper.
    Si cfg.device != 'auto', retourne directement cfg.device.
    En mode auto : cuda si VRAM libre >= VRAM_MIN_MB_FOR_CUDA, sinon cpu.
    """
    if cfg.device != STTDevice.AUTO.value:
        return cfg.device
    if vram is None:
        vram = query_vram()
    if vram.cuda_available and vram.free_mb >= VRAM_MIN_MB_FOR_CUDA:
        return STTDevice.CUDA.value
    return STTDevice.CPU.value


def resolve_tts_engine(cfg: TTSConfig, vram: Optional[VRAMInfo] = None) -> str:
    """
    Retourne le moteur TTS effectif.
    Auto : Kokoro si VRAM libre >= 1500 MB, sinon Piper.
    """
    if cfg.engine != TTSEngine.AUTO.value:
        return cfg.engine
    if vram is None:
        vram = query_vram()
    if vram.cuda_available and vram.free_mb >= VRAM_MIN_MB_FOR_CUDA:
        return TTSEngine.KOKORO.value
    return TTSEngine.PIPER.value


# ---------------------------------------------------------------------------
# Audio feedback helper (bips UI)
# ---------------------------------------------------------------------------

@dataclass
class BeepSpec:
    """Specification d'un bip audio genere par numpy + sounddevice."""
    frequency_hz: float
    duration_ms: int
    amplitude: float = 0.3
    sample_rate: int = 44100

    def generate_pcm(self):  # -> numpy.ndarray | None
        """
        Genere un tableau PCM float32 pour ce bip.
        Retourne None si numpy est absent.
        """
        try:
            import numpy as np  # type: ignore
            t = np.linspace(
                0,
                self.duration_ms / 1000.0,
                int(self.sample_rate * self.duration_ms / 1000.0),
                endpoint=False,
                dtype=np.float32,
            )
            # Onde sinusoidale avec enveloppe courte pour eviter le clic
            wave = self.amplitude * np.sin(2 * np.pi * self.frequency_hz * t)
            # Fade-out rapide (10% de la duree)
            fade_len = max(1, int(len(wave) * 0.10))
            fade = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
            wave[-fade_len:] *= fade
            return wave
        except Exception:
            return None

    def to_dict(self) -> dict:
        return {
            "frequency_hz": self.frequency_hz,
            "duration_ms": self.duration_ms,
            "amplitude": self.amplitude,
            "sample_rate": self.sample_rate,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BeepSpec":
        return cls(
            frequency_hz=float(d.get("frequency_hz", 440.0)),
            duration_ms=int(d.get("duration_ms", 80)),
            amplitude=float(d.get("amplitude", 0.3)),
            sample_rate=int(d.get("sample_rate", 44100)),
        )


# Bips standards LCCA Voice
BEEP_START = BeepSpec(frequency_hz=440.0, duration_ms=80, amplitude=0.3)   # activation micro
BEEP_STOP = BeepSpec(frequency_hz=220.0, duration_ms=60, amplitude=0.25)   # desactivation micro
