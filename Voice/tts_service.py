# Voice/tts_service.py
# VOICE-06 -- Serveur WebSocket TTS (port 8766)
# Isolation totale : 0 import depuis core/
# Encodage : utf-8-sig (BOM Windows)

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
from typing import Optional, Set

logger = logging.getLogger("lcca.voice.tts_service")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

DEFAULT_PORT: int = 8766
DEFAULT_HOST: str = "localhost"


# ---------------------------------------------------------------------------
# TTSService
# ---------------------------------------------------------------------------

class TTSService:
    """
    Serveur WebSocket TTS (Text-to-Speech) port 8766.

    Protocole client -> serveur :
        {"cmd": "speak", "text": "..."}   -> synthese + diffusion audio PCM
        {"cmd": "stop"}                   -> arrete la synthese en cours
        {"cmd": "status"}                 -> retourne l'etat courant

    Protocole serveur -> client :
        {"type": "status", "state": "idle"|"speaking"|"error", "msg": ""}
        {"type": "chunk",  "pcm_b64": "<base64>", "sample_rate": 24000, "seq": N}
        {"type": "done",   "duration_ms": N}

    Args:
        host           : Interface d'ecoute (defaut: localhost)
        port           : Port WebSocket (defaut: 8766)
        piper_engine   : PiperTTSEngine injectable (optionnel)
        kokoro_engine  : KokoroTTSEngine injectable (optionnel)
        config         : TTSConfig (si None, utilise les defauts)
        _ws_factory    : Injectable pour les tests -- remplace websockets.serve()
        _engine_factory: Injectable pour les tests -- retourne l'engine a utiliser
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        piper_engine=None,
        kokoro_engine=None,
        config=None,
        _ws_factory=None,
        _engine_factory=None,
    ) -> None:
        self._host = host
        self._port = port
        self._piper = piper_engine
        self._kokoro = kokoro_engine
        self._config = config
        self._ws_factory = _ws_factory
        self._engine_factory = _engine_factory

        # Etat interne
        self._clients: Set = set()
        self._speaking: bool = False
        self._running: bool = False
        self._server = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Proprietes
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # ------------------------------------------------------------------
    # Demarrage / arret
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Demarre le serveur WebSocket TTS."""
        self._running = True
        logger.info("[tts_service] demarrage sur %s:%d", self._host, self._port)

        if self._ws_factory is not None:
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
                logger.error("[tts_service] websockets absent -- serveur non demarre")
                self._running = False
                return

        logger.info("[tts_service] serveur pret sur ws://%s:%d", self._host, self._port)

    async def stop(self) -> None:
        """Arrete le serveur et ferme toutes les connexions."""
        self._running = False
        self._speaking = False
        self._stop_event.set()

        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None

        clients = list(self._clients)
        for ws in clients:
            try:
                await ws.close()
            except Exception:
                pass
        self._clients.clear()
        logger.info("[tts_service] serveur arrete")

    # ------------------------------------------------------------------
    # Gestion des clients WebSocket
    # ------------------------------------------------------------------

    async def _handle_client(self, websocket) -> None:
        """Handler par connexion WebSocket."""
        with self._lock:
            self._clients.add(websocket)
        logger.debug("[tts_service] nouveau client (total=%d)", len(self._clients))

        try:
            await self._send_status(websocket, "idle")
            async for raw_msg in websocket:
                await self._handle_message(websocket, raw_msg)
        except Exception as exc:
            logger.debug("[tts_service] client deconnecte : %s", exc)
        finally:
            with self._lock:
                self._clients.discard(websocket)
            logger.debug("[tts_service] client retire (total=%d)", len(self._clients))

    async def _handle_message(self, websocket, raw_msg: str) -> None:
        """
        Traite un message JSON recu d'un client.

        Commandes :
            speak  -> synthese TTS du texte fourni
            stop   -> arrete la synthese en cours
            status -> retourne l'etat courant
        """
        try:
            msg = json.loads(raw_msg)
        except (json.JSONDecodeError, TypeError):
            logger.debug("[tts_service] message invalide : %r", raw_msg)
            return

        cmd = msg.get("cmd", "")

        if cmd == "speak":
            text = msg.get("text", "").strip()
            if text:
                await self._do_speak(text)
            else:
                logger.debug("[tts_service] speak avec texte vide -- ignore")
        elif cmd == "stop":
            await self._do_stop()
        elif cmd == "status":
            state = "speaking" if self._speaking else "idle"
            await self._send_status(websocket, state)
        else:
            logger.debug("[tts_service] commande inconnue : %s", cmd)

    # ------------------------------------------------------------------
    # Synthese TTS
    # ------------------------------------------------------------------

    async def _do_speak(self, text: str) -> None:
        """
        Synthetise le texte phrase par phrase et diffuse les chunks PCM.

        Pipeline :
        1. Selectionner l'engine (factory ou config)
        2. Decouper en phrases via tts_sentence.split_sentences
        3. Pour chaque phrase : synthese -> chunk PCM -> broadcast
        4. Envoyer {"type": "done"} a la fin
        """
        import base64
        import os as _os
        import sys as _sys

        # Import tts_sentence depuis le meme dossier
        _voice_dir = _os.path.dirname(_os.path.abspath(__file__))
        if _voice_dir not in _sys.path:
            _sys.path.insert(0, _voice_dir)
        from tts_sentence import split_sentences

        if self._speaking:
            logger.debug("[tts_service] synthese deja en cours -- ignore")
            return

        self._speaking = True
        self._stop_event.clear()
        await self._broadcast_status("speaking")

        engine = self._select_engine()
        if engine is None:
            logger.warning("[tts_service] aucun engine TTS disponible")
            await self._broadcast_status("error", "aucun engine TTS")
            self._speaking = False
            return

        sentences = split_sentences(text)
        if not sentences:
            logger.debug("[tts_service] aucune phrase a synthetiser")
            self._speaking = False
            await self._broadcast_status("idle")
            return

        total_duration_ms = 0
        seq = 0

        try:
            for sentence in sentences:
                if self._stop_event.is_set():
                    logger.debug("[tts_service] synthese interrompue")
                    break

                result = engine.synthesize(sentence)

                if not result.success:
                    logger.warning("[tts_service] echec synthese : %s", result.error)
                    continue

                if not result.pcm_bytes:
                    continue

                # Encoder PCM en base64 pour transport JSON
                pcm_b64 = base64.b64encode(result.pcm_bytes).decode("ascii")
                chunk_msg = json.dumps({
                    "type": "chunk",
                    "pcm_b64": pcm_b64,
                    "sample_rate": result.sample_rate,
                    "seq": seq,
                })
                await self._broadcast(chunk_msg)
                total_duration_ms += result.duration_ms
                seq += 1

                # Laisser la boucle asyncio respirer entre les chunks
                await asyncio.sleep(0)

        except Exception as exc:
            logger.error("[tts_service] erreur synthese : %s", exc)
        finally:
            self._speaking = False
            done_msg = json.dumps({"type": "done", "duration_ms": total_duration_ms})
            await self._broadcast(done_msg)
            if not self._stop_event.is_set():
                await self._broadcast_status("idle")

    async def _do_stop(self) -> None:
        """Interrompt la synthese en cours."""
        if not self._speaking:
            return
        self._stop_event.set()
        logger.info("[tts_service] arret synthese demande")

    # ------------------------------------------------------------------
    # Selection de l'engine
    # ------------------------------------------------------------------

    def _select_engine(self):
        """
        Retourne l'engine TTS a utiliser.
        Priorite : _engine_factory > _kokoro > _piper > tentative auto
        """
        if self._engine_factory is not None:
            return self._engine_factory()

        if self._kokoro is not None:
            return self._kokoro

        if self._piper is not None:
            return self._piper

        # Tentative auto : essayer Piper puis Kokoro
        return self._try_auto_engine()

    def _try_auto_engine(self):
        """
        Tente de construire un engine TTS automatiquement depuis la config.
        Retourne None si aucun engine disponible.
        Mode degrade silencieux.
        """
        import os as _os
        import sys as _sys
        _voice_dir = _os.path.dirname(_os.path.abspath(__file__))
        if _voice_dir not in _sys.path:
            _sys.path.insert(0, _voice_dir)

        try:
            from tts_engine_piper import PiperTTSEngine
            engine = PiperTTSEngine()
            if engine.is_available():
                return engine
        except Exception:
            pass

        try:
            from tts_engine_kokoro import KokoroTTSEngine
            engine = KokoroTTSEngine()
            if engine.is_available():
                return engine
        except Exception:
            pass

        return None

    # ------------------------------------------------------------------
    # Diffusion (broadcast)
    # ------------------------------------------------------------------

    async def _broadcast(self, message: str) -> None:
        """Envoie un message a tous les clients connectes."""
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
            logger.debug("[tts_service] send_status erreur : %s", exc)

    # ------------------------------------------------------------------
    # Point d'entree CLI
    # ------------------------------------------------------------------

    @classmethod
    def run_forever(cls, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        """Lance le serveur en mode standalone (entree CLI)."""
        import os as _os
        _voice_dir = _os.path.dirname(_os.path.abspath(__file__))
        if _voice_dir not in sys.path:
            sys.path.insert(0, _voice_dir)

        from voice_types import load_voice_config, resolve_tts_engine
        from tts_engine_piper import PiperTTSEngine
        from tts_engine_kokoro import KokoroTTSEngine

        cfg = load_voice_config()
        engine_name = resolve_tts_engine(cfg.tts)

        piper = None
        kokoro = None

        if engine_name == "piper":
            piper = PiperTTSEngine(
                volume=cfg.tts.volume,
            )
        else:
            kokoro = KokoroTTSEngine(
                lang=cfg.tts.kokoro.lang,
                voice=cfg.tts.kokoro.voice,
                volume=cfg.tts.volume,
            )

        service = cls(
            host=host,
            port=port,
            piper_engine=piper,
            kokoro_engine=kokoro,
            config=cfg.tts,
        )

        async def _main():
            await service.start()
            if service._server is not None:
                async with service._server:
                    await service._server.wait_closed()

        try:
            asyncio.run(_main())
        except KeyboardInterrupt:
            logger.info("[tts_service] arret par KeyboardInterrupt")


# ---------------------------------------------------------------------------
# Entree CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    parser = argparse.ArgumentParser(description="LCCA TTSService WebSocket")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    TTSService.run_forever(host=args.host, port=args.port)
