# Voice/voice_service.py
# VOICE-03 -- Serveur WebSocket STT (port 8765)
# Isolation totale : 0 import depuis core/
# Encodage : utf-8-sig (BOM Windows)

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
from typing import Callable, Optional, Set

logger = logging.getLogger("lcca.voice.service")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

DEFAULT_PORT: int = 8765
DEFAULT_HOST: str = "localhost"


# ---------------------------------------------------------------------------
# VoiceService
# ---------------------------------------------------------------------------

class VoiceService:
    """
    Serveur WebSocket STT.

    Gere le cycle de vie complet :
        - accepte les connexions WebSocket des clients (Electron)
        - recoit les commandes de controle (start/stop ecoute)
        - delegue la capture a VoiceCapture + la transcription a VoiceTranscriber
        - diffuse les messages PartialTranscript / FinalTranscript / StatusMessage

    Args:
        host          : Interface d'ecoute (defaut: localhost)
        port          : Port WebSocket (defaut: 8765)
        capture       : VoiceCapture injecte (injectable pour les tests)
        transcriber   : VoiceTranscriber injecte (injectable pour les tests)
        config        : STTConfig (si None, utilise les defauts)
        _ws_factory   : Injectable pour les tests -- remplace websockets.serve()
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        capture=None,
        transcriber=None,
        config=None,
        _ws_factory=None,
    ) -> None:
        self._host = host
        self._port = port
        self._capture = capture
        self._transcriber = transcriber
        self._config = config
        self._ws_factory = _ws_factory

        # Etat interne
        self._clients: Set = set()
        self._listening: bool = False
        self._running: bool = False
        self._server = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Proprietes
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_listening(self) -> bool:
        return self._listening

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # ------------------------------------------------------------------
    # Demarrage / arret serveur
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Demarre le serveur WebSocket.
        Envoie un StatusMessage(state='idle') aux nouveaux clients.
        """
        self._running = True
        logger.info("[voice_service] demarrage sur %s:%d", self._host, self._port)

        if self._ws_factory is not None:
            # Mode test : ws_factory gere le serveur
            self._server = await self._ws_factory(
                self._handle_client, self._host, self._port
            )
        else:
            try:
                import websockets  # type: ignore
                self._server = await websockets.serve(
                    self._handle_client, self._host, self._port
                )
            except ImportError:
                logger.error("[voice_service] websockets absent -- serveur non demarre")
                self._running = False
                return

        logger.info("[voice_service] serveur pret sur ws://%s:%d", self._host, self._port)

    async def stop(self) -> None:
        """Arrete le serveur et ferme toutes les connexions."""
        self._running = False
        self._listening = False

        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None

        # Fermer tous les clients
        clients = list(self._clients)
        for ws in clients:
            try:
                await ws.close()
            except Exception:
                pass
        self._clients.clear()
        logger.info("[voice_service] serveur arrete")

    # ------------------------------------------------------------------
    # Gestion des clients WebSocket
    # ------------------------------------------------------------------

    async def _handle_client(self, websocket) -> None:
        """
        Handler par connexion WebSocket.
        Envoie le statut initial, puis ecoute les commandes.
        """
        with self._lock:
            self._clients.add(websocket)
        logger.debug("[voice_service] nouveau client connecte (total=%d)", len(self._clients))

        try:
            # Statut initial
            await self._send_status(websocket, "idle")

            async for raw_msg in websocket:
                await self._handle_message(websocket, raw_msg)

        except Exception as exc:
            logger.debug("[voice_service] client deconnecte : %s", exc)
        finally:
            with self._lock:
                self._clients.discard(websocket)
            logger.debug("[voice_service] client retire (total=%d)", len(self._clients))

    async def _handle_message(self, websocket, raw_msg: str) -> None:
        """
        Traite un message JSON recu d'un client.

        Commandes supportees :
            {"cmd": "start"}   -> demarre l'ecoute STT
            {"cmd": "stop"}    -> arrete l'ecoute STT
            {"cmd": "status"}  -> retourne l'etat courant
        """
        try:
            msg = json.loads(raw_msg)
        except (json.JSONDecodeError, TypeError):
            logger.debug("[voice_service] message invalide : %r", raw_msg)
            return

        cmd = msg.get("cmd", "")

        if cmd == "start":
            await self._start_listening(websocket)
        elif cmd == "stop":
            await self._stop_listening(websocket)
        elif cmd == "status":
            state = "listening" if self._listening else "idle"
            await self._send_status(websocket, state)
        else:
            logger.debug("[voice_service] commande inconnue : %s", cmd)

    # ------------------------------------------------------------------
    # Controle STT
    # ------------------------------------------------------------------

    async def _start_listening(self, websocket) -> None:
        """Active l'ecoute VAD + capture."""
        if self._listening:
            return

        self._listening = True
        await self._send_status(websocket, "listening")
        logger.info("[voice_service] ecoute demarree")

        # Demarrer la capture dans un thread separe
        if self._capture is not None:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._run_capture, loop)

    async def _stop_listening(self, websocket) -> None:
        """Arrete l'ecoute et flush l'utterance en cours."""
        if not self._listening:
            return

        self._listening = False

        if self._capture is not None:
            result = self._capture.stop()
            if result is not None and self._transcriber is not None:
                await self._transcribe_and_broadcast(result)

        await self._send_status(websocket, "idle")
        logger.info("[voice_service] ecoute arretee")

    def _run_capture(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        Boucle de capture audio (execute dans un thread executor).
        Transcrit chaque utterance complete et la diffuse via WebSocket.
        """
        if self._capture is None:
            return

        self._capture.start()
        try:
            import sounddevice as sd  # type: ignore
            cfg = self._config
            sample_rate = 16_000
            chunk_ms = 30
            chunk_samples = sample_rate * chunk_ms // 1000  # 480

            def audio_callback(indata, frames, time_info, status):
                if not self._listening:
                    return
                pcm = indata[:, 0].tobytes() if hasattr(indata, 'tobytes') else bytes(indata)
                result = self._capture.process_chunk(pcm)
                if result is not None and self._transcriber is not None:
                    # Soumettre la transcription dans la boucle asyncio
                    fut = asyncio.run_coroutine_threadsafe(
                        self._transcribe_and_broadcast(result), loop
                    )

            with sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                blocksize=chunk_samples,
                callback=audio_callback,
            ):
                while self._listening:
                    import time
                    time.sleep(0.05)

        except ImportError:
            logger.warning("[voice_service] sounddevice absent -- capture simulee")
            # Mode degrade : pas de capture reelle, juste attendre
            import time
            while self._listening:
                time.sleep(0.1)
        except Exception as exc:
            logger.error("[voice_service] erreur capture : %s", exc)
        finally:
            self._capture.stop()

    # ------------------------------------------------------------------
    # Transcription et diffusion
    # ------------------------------------------------------------------

    async def _transcribe_and_broadcast(self, capture_result) -> None:
        """
        Transcrit un CaptureResult et diffuse le resultat a tous les clients.

        Envoie d'abord un StatusMessage(state='processing'),
        puis un FinalTranscript si la transcription est non vide,
        puis un StatusMessage(state='listening') pour reprendre.
        """
        await self._broadcast_status("processing")

        try:
            tr = self._transcriber.transcribe(capture_result.pcm_bytes)

            if tr.success and tr.text:
                msg = {
                    "type": "final",
                    "text": tr.text,
                    "confidence": round(tr.confidence, 4),
                    "duration_ms": tr.duration_ms,
                }
                await self._broadcast(json.dumps(msg))
                logger.debug("[voice_service] transcription diffusee : %r", tr.text[:50])
            elif not tr.success:
                logger.warning("[voice_service] transcription echouee : %s", tr.error)

        except Exception as exc:
            logger.error("[voice_service] erreur transcription : %s", exc)
        finally:
            if self._listening:
                await self._broadcast_status("listening")
            else:
                await self._broadcast_status("idle")

    async def broadcast_partial(self, text: str, confidence: float = 0.0) -> None:
        """
        Diffuse une transcription partielle (live feedback).
        Peut etre appele depuis l'exterieur pour les tests ou le streaming.
        """
        msg = {
            "type": "partial",
            "text": text,
            "confidence": round(confidence, 4),
        }
        await self._broadcast(json.dumps(msg))

    # ------------------------------------------------------------------
    # Helpers diffusion
    # ------------------------------------------------------------------

    async def _broadcast(self, message: str) -> None:
        """Envoie un message JSON a tous les clients connectes."""
        if not self._clients:
            return
        clients = list(self._clients)
        dead: list = []
        for ws in clients:
            try:
                await ws.send(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            with self._lock:
                self._clients.discard(ws)

    async def _broadcast_status(self, state: str, msg: str = "") -> None:
        """Raccourci pour diffuser un StatusMessage."""
        payload = json.dumps({"type": "status", "state": state, "msg": msg})
        await self._broadcast(payload)

    async def _send_status(self, websocket, state: str, msg: str = "") -> None:
        """Envoie un StatusMessage a un client specifique."""
        try:
            await websocket.send(json.dumps({"type": "status", "state": state, "msg": msg}))
        except Exception as exc:
            logger.debug("[voice_service] send_status erreur : %s", exc)

    # ------------------------------------------------------------------
    # Point d'entree CLI
    # ------------------------------------------------------------------

    @classmethod
    def run_forever(cls, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        """
        Lance le serveur en mode standalone (entree CLI).
        Construit VoiceCapture + VoiceTranscriber depuis voice_config.toml.
        """
        import os
        _VOICE_DIR = os.path.dirname(os.path.abspath(__file__))
        if _VOICE_DIR not in sys.path:
            sys.path.insert(0, _VOICE_DIR)

        from voice_types import load_voice_config, resolve_stt_device
        from voice_capture import VoiceCapture
        from voice_transcriber import VoiceTranscriber

        cfg = load_voice_config()
        device = resolve_stt_device(cfg.stt)

        capture = VoiceCapture(
            aggressiveness=cfg.stt.vad_aggressiveness,
        )
        transcriber = VoiceTranscriber(
            model=cfg.stt.model,
            language=cfg.stt.language,
            device=device,
            compute_type=cfg.stt.compute_type,
        )

        service = cls(
            host=host,
            port=port,
            capture=capture,
            transcriber=transcriber,
            config=cfg.stt,
        )

        async def _main():
            await service.start()
            if service._server is not None:
                async with service._server:
                    await service._server.wait_closed()

        try:
            asyncio.run(_main())
        except KeyboardInterrupt:
            logger.info("[voice_service] arret par KeyboardInterrupt")


# ---------------------------------------------------------------------------
# Entree CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    parser = argparse.ArgumentParser(description="LCCA VoiceService STT WebSocket")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    VoiceService.run_forever(host=args.host, port=args.port)
