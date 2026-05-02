# tests/test_voice_03.py
# VOICE-03 -- Tests VoiceService (serveur WebSocket STT)
# websockets mocke via _ws_factory injectable

from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

_VOICE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Voice")
if _VOICE_DIR not in sys.path:
    sys.path.insert(0, _VOICE_DIR)

from voice_service import VoiceService, DEFAULT_PORT, DEFAULT_HOST


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------

class _FakeWebSocket:
    """WebSocket client fake pour les tests."""

    def __init__(self):
        self.sent: list[str] = []
        self.closed = False
        self._messages: list[str] = []   # messages a "recevoir" (iterable)

    async def send(self, msg: str) -> None:
        self.sent.append(msg)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._messages:
            return self._messages.pop(0)
        raise StopAsyncIteration

    def inject(self, *msgs: str) -> "_FakeWebSocket":
        """Injecte des messages a recevoir lors de l'iteration."""
        self._messages.extend(msgs)
        return self

    def last_msg(self) -> dict:
        return json.loads(self.sent[-1]) if self.sent else {}

    def all_msgs(self) -> list[dict]:
        return [json.loads(m) for m in self.sent]


class _FakeServer:
    """Serveur WebSocket fake."""

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


class _FakeCapture:
    """VoiceCapture fake."""

    def __init__(self, utterance=None):
        self._utterance = utterance
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True
        return self._utterance

    def process_chunk(self, pcm):
        return self._utterance


class _FakeTranscriber:
    """VoiceTranscriber fake."""

    def __init__(self, text="bonjour", success=True, error=""):
        from unittest.mock import MagicMock
        r = MagicMock()
        r.text = text
        r.confidence = 0.9
        r.duration_ms = 500
        r.success = success
        r.error = error
        self._result = r

    def transcribe(self, pcm_bytes):
        return self._result


def _make_service(capture=None, transcriber=None) -> VoiceService:
    """Fabrique un VoiceService avec server fake."""
    server = _FakeServer()

    async def fake_ws_factory(handler, host, port):
        return server

    return VoiceService(
        capture=capture,
        transcriber=transcriber,
        _ws_factory=fake_ws_factory,
    )


def _make_capture_result(text: str = "test", duration_ms: int = 300):
    """Fabrique un CaptureResult fake."""
    from unittest.mock import MagicMock
    r = MagicMock()
    r.pcm_bytes = b"\x00" * 960
    r.duration_ms = duration_ms
    return r


# ---------------------------------------------------------------------------
# Run helper asyncio
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ===========================================================================
# 1. Proprietes initiales
# ===========================================================================

class TestVoiceServiceInit:
    def test_not_running_by_default(self):
        svc = _make_service()
        assert svc.is_running is False

    def test_not_listening_by_default(self):
        svc = _make_service()
        assert svc.is_listening is False

    def test_no_clients_by_default(self):
        svc = _make_service()
        assert svc.client_count == 0

    def test_default_host_port(self):
        svc = VoiceService()
        assert svc._host == DEFAULT_HOST
        assert svc._port == DEFAULT_PORT


# ===========================================================================
# 2. Demarrage et arret
# ===========================================================================

class TestStartStop:
    def test_start_sets_running(self):
        svc = _make_service()
        _run(svc.start())
        assert svc.is_running is True

    def test_stop_clears_running(self):
        svc = _make_service()
        _run(svc.start())
        _run(svc.stop())
        assert svc.is_running is False

    def test_stop_clears_listening(self):
        svc = _make_service()
        _run(svc.start())
        svc._listening = True
        _run(svc.stop())
        assert svc.is_listening is False

    def test_start_without_ws_factory_import_error(self):
        """Sans ws_factory et websockets absent -> running=False, pas d'exception."""
        import sys
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "websockets":
                raise ImportError("websockets absent")
            return real_import(name, *args, **kwargs)

        svc = VoiceService(port=19999)  # pas de _ws_factory
        builtins.__import__ = mock_import
        try:
            _run(svc.start())
        finally:
            builtins.__import__ = real_import

        assert svc.is_running is False


# ===========================================================================
# 3. Gestion des clients
# ===========================================================================

class TestClientHandling:
    def test_handle_client_adds_to_set(self):
        svc = _make_service()
        ws = _FakeWebSocket()

        async def _run_handler():
            await svc._handle_client(ws)

        _run(_run_handler())
        # Apres deconnexion, client retire
        assert svc.client_count == 0

    def test_handle_client_sends_initial_status(self):
        svc = _make_service()
        ws = _FakeWebSocket()

        _run(svc._handle_client(ws))

        msgs = ws.all_msgs()
        assert len(msgs) >= 1
        assert msgs[0]["type"] == "status"
        assert msgs[0]["state"] == "idle"

    def test_stop_closes_all_clients(self):
        svc = _make_service()
        ws1 = _FakeWebSocket()
        ws2 = _FakeWebSocket()
        svc._clients.add(ws1)
        svc._clients.add(ws2)

        _run(svc.stop())

        assert ws1.closed is True
        assert ws2.closed is True
        assert svc.client_count == 0


# ===========================================================================
# 4. Traitement des commandes
# ===========================================================================

class TestCommandHandling:
    def test_cmd_status_returns_idle(self):
        svc = _make_service()
        ws = _FakeWebSocket()
        _run(svc._handle_message(ws, json.dumps({"cmd": "status"})))
        msg = ws.last_msg()
        assert msg["type"] == "status"
        assert msg["state"] == "idle"

    def test_cmd_status_returns_listening_when_active(self):
        svc = _make_service()
        svc._listening = True
        ws = _FakeWebSocket()
        _run(svc._handle_message(ws, json.dumps({"cmd": "status"})))
        msg = ws.last_msg()
        assert msg["state"] == "listening"

    def test_cmd_invalid_json_no_crash(self):
        svc = _make_service()
        ws = _FakeWebSocket()
        _run(svc._handle_message(ws, "pas du json {{{"))
        # Aucun message envoye, pas d'exception
        assert ws.sent == []

    def test_cmd_unknown_no_crash(self):
        svc = _make_service()
        ws = _FakeWebSocket()
        _run(svc._handle_message(ws, json.dumps({"cmd": "inexistant"})))
        assert ws.sent == []

    def test_cmd_stop_sends_idle_when_not_listening(self):
        svc = _make_service()
        ws = _FakeWebSocket()
        _run(svc._handle_message(ws, json.dumps({"cmd": "stop"})))
        # Pas d'ecoute active -> rien a envoyer (guard if not self._listening)
        assert ws.sent == []


# ===========================================================================
# 5. Demarrage et arret ecoute
# ===========================================================================

class TestListeningControl:
    def test_start_listening_sets_flag(self):
        svc = _make_service()
        ws = _FakeWebSocket()

        async def _run_test():
            await svc._start_listening(ws)

        _run(_run_test())
        assert svc.is_listening is True

    def test_start_listening_sends_status_listening(self):
        svc = _make_service()
        ws = _FakeWebSocket()

        async def _run_test():
            await svc._start_listening(ws)

        _run(_run_test())
        msgs = ws.all_msgs()
        states = [m["state"] for m in msgs if m.get("type") == "status"]
        assert "listening" in states

    def test_start_listening_idempotent(self):
        """Appeler start_listening deux fois ne double pas le statut."""
        svc = _make_service()
        ws = _FakeWebSocket()
        svc._listening = True  # deja en ecoute

        async def _run_test():
            before = len(ws.sent)
            await svc._start_listening(ws)
            return len(ws.sent) - before

        sent = _run(_run_test())
        assert sent == 0  # guard -> rien envoye

    def test_stop_listening_clears_flag(self):
        svc = _make_service()
        svc._listening = True
        ws = _FakeWebSocket()

        async def _run_test():
            await svc._stop_listening(ws)

        _run(_run_test())
        assert svc.is_listening is False

    def test_stop_listening_sends_idle(self):
        svc = _make_service()
        svc._listening = True
        ws = _FakeWebSocket()

        async def _run_test():
            await svc._stop_listening(ws)

        _run(_run_test())
        msgs = ws.all_msgs()
        states = [m["state"] for m in msgs if m.get("type") == "status"]
        assert "idle" in states


# ===========================================================================
# 6. Transcription et diffusion
# ===========================================================================

class TestTranscribeAndBroadcast:
    def test_broadcast_final_on_success(self):
        transcriber = _FakeTranscriber(text="bonjour le monde", success=True)
        svc = _make_service(transcriber=transcriber)
        ws = _FakeWebSocket()
        svc._clients.add(ws)
        svc._listening = True
        capture_result = _make_capture_result()

        _run(svc._transcribe_and_broadcast(capture_result))

        msgs = ws.all_msgs()
        finals = [m for m in msgs if m.get("type") == "final"]
        assert len(finals) == 1
        assert finals[0]["text"] == "bonjour le monde"

    def test_no_final_on_empty_text(self):
        transcriber = _FakeTranscriber(text="", success=True)
        svc = _make_service(transcriber=transcriber)
        ws = _FakeWebSocket()
        svc._clients.add(ws)
        svc._listening = True
        capture_result = _make_capture_result()

        _run(svc._transcribe_and_broadcast(capture_result))

        msgs = ws.all_msgs()
        finals = [m for m in msgs if m.get("type") == "final"]
        assert len(finals) == 0

    def test_no_final_on_failure(self):
        transcriber = _FakeTranscriber(text="x", success=False, error="echec")
        svc = _make_service(transcriber=transcriber)
        ws = _FakeWebSocket()
        svc._clients.add(ws)
        svc._listening = True
        capture_result = _make_capture_result()

        _run(svc._transcribe_and_broadcast(capture_result))

        msgs = ws.all_msgs()
        finals = [m for m in msgs if m.get("type") == "final"]
        assert len(finals) == 0

    def test_processing_status_sent_before_final(self):
        transcriber = _FakeTranscriber(text="test")
        svc = _make_service(transcriber=transcriber)
        ws = _FakeWebSocket()
        svc._clients.add(ws)
        svc._listening = True

        _run(svc._transcribe_and_broadcast(_make_capture_result()))

        msgs = ws.all_msgs()
        types = [m.get("type") for m in msgs]
        # processing doit preceder final
        assert "status" in types
        proc_idx = next(i for i, m in enumerate(msgs) if m.get("state") == "processing")
        final_indices = [i for i, m in enumerate(msgs) if m.get("type") == "final"]
        if final_indices:
            assert proc_idx < final_indices[0]

    def test_transcribe_exception_no_propagation(self):
        """Exception dans transcriber -> swallow, pas de crash."""
        from unittest.mock import MagicMock
        transcriber = MagicMock()
        transcriber.transcribe.side_effect = RuntimeError("crash transcriber")
        svc = _make_service(transcriber=transcriber)
        ws = _FakeWebSocket()
        svc._clients.add(ws)
        svc._listening = True

        try:
            _run(svc._transcribe_and_broadcast(_make_capture_result()))
        except Exception:
            pytest.fail("_transcribe_and_broadcast ne doit pas propager les exceptions")


# ===========================================================================
# 7. Diffusion (broadcast)
# ===========================================================================

class TestBroadcast:
    def test_broadcast_to_all_clients(self):
        svc = _make_service()
        ws1 = _FakeWebSocket()
        ws2 = _FakeWebSocket()
        svc._clients.add(ws1)
        svc._clients.add(ws2)

        _run(svc._broadcast('{"type":"test"}'))

        assert len(ws1.sent) == 1
        assert len(ws2.sent) == 1

    def test_broadcast_partial(self):
        svc = _make_service()
        ws = _FakeWebSocket()
        svc._clients.add(ws)

        _run(svc.broadcast_partial("bonjour", confidence=0.75))

        msgs = ws.all_msgs()
        assert len(msgs) == 1
        assert msgs[0]["type"] == "partial"
        assert msgs[0]["text"] == "bonjour"
        assert abs(msgs[0]["confidence"] - 0.75) < 1e-4

    def test_broadcast_no_clients_no_crash(self):
        svc = _make_service()
        _run(svc._broadcast('{"type":"test"}'))  # Pas d'exception

    def test_dead_client_removed_on_broadcast(self):
        svc = _make_service()

        class _DeadWS:
            async def send(self, msg):
                raise ConnectionError("dead")
            async def close(self):
                pass

        dead = _DeadWS()
        svc._clients.add(dead)
        _run(svc._broadcast('{"type":"test"}'))
        assert dead not in svc._clients

    def test_broadcast_status(self):
        svc = _make_service()
        ws = _FakeWebSocket()
        svc._clients.add(ws)

        _run(svc._broadcast_status("processing", "en cours"))

        msg = ws.last_msg()
        assert msg["type"] == "status"
        assert msg["state"] == "processing"
        assert msg["msg"] == "en cours"
