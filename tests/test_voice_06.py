# tests/test_voice_06.py
# VOICE-06 -- Tests SentenceSplitter + TTSService

from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

_VOICE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Voice")
if _VOICE_DIR not in sys.path:
    sys.path.insert(0, _VOICE_DIR)

from tts_sentence import (
    split_sentences,
    iter_sentences,
    flush_partial,
    MIN_SENTENCE_LEN,
    MAX_SEGMENT_LEN,
)
from tts_service import TTSService, DEFAULT_PORT, DEFAULT_HOST


# ---------------------------------------------------------------------------
# Helpers communs
# ---------------------------------------------------------------------------

class _FakeWebSocket:
    def __init__(self):
        self.sent: list[str] = []
        self.closed = False
        self._messages: list[str] = []

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
        self._messages.extend(msgs)
        return self

    def last_msg(self) -> dict:
        return json.loads(self.sent[-1]) if self.sent else {}

    def all_msgs(self) -> list[dict]:
        return [json.loads(m) for m in self.sent]


class _FakeServer:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


class _FakeEngine:
    """Engine TTS fake retournant du PCM int16 silence."""

    def __init__(self, pcm: bytes = b"\x00\x00" * 100, success: bool = True, fail: bool = False):
        self._pcm = pcm
        self._success = success
        self._fail = fail
        self.calls: list[str] = []

    def synthesize(self, text: str):
        self.calls.append(text)
        if self._fail:
            raise RuntimeError("engine crash")
        from tts_engine_piper import SynthesisResult
        if not self._success:
            return SynthesisResult.failure("echec fake")
        return SynthesisResult(
            pcm_bytes=self._pcm,
            sample_rate=24000,
            duration_ms=len(self._pcm) // 2 * 1000 // 24000,
            success=True,
        )

    def is_available(self) -> bool:
        return True


def _make_service(engine=None, fail_engine: bool = False) -> TTSService:
    """Fabrique un TTSService avec server + engine fake."""
    server = _FakeServer()

    async def fake_ws_factory(handler, host, port):
        return server

    if engine is None and not fail_engine:
        engine = _FakeEngine()

    def engine_factory():
        if fail_engine:
            return None
        return engine

    return TTSService(
        _ws_factory=fake_ws_factory,
        _engine_factory=engine_factory,
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ===========================================================================
# 1. split_sentences — cas nominaux
# ===========================================================================

class TestSplitSentencesNominal:
    def test_empty_returns_empty(self):
        assert split_sentences("") == []

    def test_whitespace_only_returns_empty(self):
        assert split_sentences("   ") == []

    def test_single_sentence_no_punct(self):
        result = split_sentences("Bonjour le monde")
        assert result == ["Bonjour le monde"]

    def test_two_sentences(self):
        result = split_sentences("Bonjour. Au revoir.")
        assert len(result) == 2
        assert result[0] == "Bonjour."
        assert result[1] == "Au revoir."

    def test_exclamation_split(self):
        result = split_sentences("Super! Bravo!")
        assert len(result) == 2

    def test_question_split(self):
        result = split_sentences("Comment allez-vous? Bien merci.")
        assert len(result) == 2

    def test_strips_whitespace(self):
        result = split_sentences("  Bonjour.  ")
        assert result[0] == "Bonjour."

    def test_multiple_spaces_between_sentences(self):
        result = split_sentences("Un.   Deux.")
        assert len(result) == 2

    def test_fragment_too_short_ignored(self):
        # "Ok" est >= MIN_SENTENCE_LEN (3), "Je" est < 3
        result = split_sentences("Je. Ok.")
        # "Je." = 3 chars >= MIN_SENTENCE_LEN -> conserve
        # resultat depend de MIN_SENTENCE_LEN
        for s in result:
            assert len(s) >= MIN_SENTENCE_LEN

    def test_returns_list(self):
        assert isinstance(split_sentences("Test."), list)


# ===========================================================================
# 2. split_sentences — segments longs
# ===========================================================================

class TestSplitSentencesLong:
    def test_long_sentence_force_split(self):
        # Phrase sans ponctuation de plus de MAX_SEGMENT_LEN chars
        long_text = "a " * (MAX_SEGMENT_LEN // 2 + 10)
        result = split_sentences(long_text)
        assert len(result) >= 1
        for s in result:
            assert len(s) <= MAX_SEGMENT_LEN + 5  # tolerance trim

    def test_long_sentence_comma_split(self):
        # Phrase avec virgule qui depasse MAX_SEGMENT_LEN
        part1 = "Voici une longue phrase qui depasse la limite, "
        part2 = "et voici la suite qui est egalement tres longue et depasse aussi"
        # Construire un segment > MAX_SEGMENT_LEN avec une virgule
        long_text = (part1 * 3 + part2)[: MAX_SEGMENT_LEN + 50]
        # S'assurer qu'il y a une virgule
        if "," not in long_text:
            long_text = long_text[:100] + ", " + long_text[100:]
        result = split_sentences(long_text)
        assert len(result) >= 1

    def test_normal_length_unchanged(self):
        text = "Bonjour tout le monde. Comment allez-vous?"
        result = split_sentences(text)
        # Aucun split force : les phrases sont courtes
        assert all(len(s) <= MAX_SEGMENT_LEN for s in result)


# ===========================================================================
# 3. iter_sentences
# ===========================================================================

class TestIterSentences:
    def test_yields_same_as_split(self):
        text = "Un. Deux. Trois."
        assert list(iter_sentences(text)) == split_sentences(text)

    def test_empty_yields_nothing(self):
        assert list(iter_sentences("")) == []

    def test_is_iterator(self):
        import types
        result = iter_sentences("Test.")
        assert isinstance(result, types.GeneratorType)


# ===========================================================================
# 4. flush_partial
# ===========================================================================

class TestFlushPartial:
    def test_empty_buffer(self):
        phrases, remainder = flush_partial("")
        assert phrases == []
        assert remainder == ""

    def test_no_sentence_end(self):
        phrases, remainder = flush_partial("Bonjour le monde")
        assert phrases == []
        assert remainder == "Bonjour le monde"

    def test_one_complete_sentence(self):
        phrases, remainder = flush_partial("Bonjour. Au revoir")
        assert len(phrases) >= 1
        assert "Bonjour." in phrases
        assert "Au revoir" in remainder

    def test_two_complete_sentences(self):
        phrases, remainder = flush_partial("Un. Deux. Trois")
        assert len(phrases) == 2
        assert remainder == "Trois"

    def test_all_complete(self):
        phrases, remainder = flush_partial("Fini.")
        assert len(phrases) >= 1
        assert remainder == ""

    def test_exclamation(self):
        phrases, remainder = flush_partial("Super! Et")
        assert len(phrases) >= 1
        assert "Et" in remainder

    def test_remainder_stripped(self):
        _, remainder = flush_partial("Un. deux")
        assert remainder == remainder.strip()


# ===========================================================================
# 5. TTSService — init + proprietes
# ===========================================================================

class TestTTSServiceInit:
    def test_not_running_by_default(self):
        svc = _make_service()
        assert svc.is_running is False

    def test_not_speaking_by_default(self):
        svc = _make_service()
        assert svc.is_speaking is False

    def test_no_clients_by_default(self):
        svc = _make_service()
        assert svc.client_count == 0

    def test_default_host_port(self):
        svc = TTSService()
        assert svc._host == DEFAULT_HOST
        assert svc._port == DEFAULT_PORT


# ===========================================================================
# 6. TTSService — demarrage / arret
# ===========================================================================

class TestTTSServiceStartStop:
    def test_start_sets_running(self):
        svc = _make_service()
        _run(svc.start())
        assert svc.is_running is True

    def test_stop_clears_running(self):
        svc = _make_service()
        _run(svc.start())
        _run(svc.stop())
        assert svc.is_running is False

    def test_stop_clears_speaking(self):
        svc = _make_service()
        _run(svc.start())
        svc._speaking = True
        _run(svc.stop())
        assert svc.is_speaking is False

    def test_start_without_ws_factory_import_error(self):
        """Sans ws_factory et websockets absent -> running=False."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "websockets":
                raise ImportError("websockets absent")
            return real_import(name, *args, **kwargs)

        svc = TTSService(port=19998)
        builtins.__import__ = mock_import
        try:
            _run(svc.start())
        finally:
            builtins.__import__ = real_import

        assert svc.is_running is False

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
# 7. TTSService — handle_client
# ===========================================================================

class TestTTSServiceClientHandling:
    def test_handle_client_sends_initial_status(self):
        svc = _make_service()
        ws = _FakeWebSocket()
        _run(svc._handle_client(ws))
        msgs = ws.all_msgs()
        assert len(msgs) >= 1
        assert msgs[0]["type"] == "status"
        assert msgs[0]["state"] == "idle"

    def test_handle_client_removed_after_disconnect(self):
        svc = _make_service()
        ws = _FakeWebSocket()
        _run(svc._handle_client(ws))
        assert svc.client_count == 0

    def test_cmd_status_idle(self):
        svc = _make_service()
        ws = _FakeWebSocket()
        _run(svc._handle_message(ws, json.dumps({"cmd": "status"})))
        msg = ws.last_msg()
        assert msg["state"] == "idle"

    def test_cmd_status_speaking(self):
        svc = _make_service()
        svc._speaking = True
        ws = _FakeWebSocket()
        _run(svc._handle_message(ws, json.dumps({"cmd": "status"})))
        msg = ws.last_msg()
        assert msg["state"] == "speaking"

    def test_cmd_invalid_json_no_crash(self):
        svc = _make_service()
        ws = _FakeWebSocket()
        _run(svc._handle_message(ws, "pas du json"))
        assert ws.sent == []

    def test_cmd_unknown_no_crash(self):
        svc = _make_service()
        ws = _FakeWebSocket()
        _run(svc._handle_message(ws, json.dumps({"cmd": "inexistant"})))
        assert ws.sent == []

    def test_cmd_speak_empty_text_ignored(self):
        svc = _make_service()
        ws = _FakeWebSocket()
        _run(svc._handle_message(ws, json.dumps({"cmd": "speak", "text": ""})))
        assert svc.is_speaking is False


# ===========================================================================
# 8. TTSService — synthese
# ===========================================================================

class TestTTSSynthesis:
    def test_speak_broadcasts_chunk(self):
        engine = _FakeEngine(pcm=b"\x00\x00" * 2400)
        svc = _make_service(engine=engine)
        ws = _FakeWebSocket()
        svc._clients.add(ws)

        _run(svc._do_speak("Bonjour."))

        msgs = ws.all_msgs()
        chunks = [m for m in msgs if m.get("type") == "chunk"]
        assert len(chunks) >= 1

    def test_speak_broadcasts_done(self):
        engine = _FakeEngine()
        svc = _make_service(engine=engine)
        ws = _FakeWebSocket()
        svc._clients.add(ws)

        _run(svc._do_speak("Test."))

        msgs = ws.all_msgs()
        dones = [m for m in msgs if m.get("type") == "done"]
        assert len(dones) == 1

    def test_speak_status_speaking_then_idle(self):
        engine = _FakeEngine()
        svc = _make_service(engine=engine)
        ws = _FakeWebSocket()
        svc._clients.add(ws)

        _run(svc._do_speak("Test."))

        msgs = ws.all_msgs()
        states = [m.get("state") for m in msgs if m.get("type") == "status"]
        assert "speaking" in states
        assert states[-1] == "idle"

    def test_speak_not_speaking_after_completion(self):
        engine = _FakeEngine()
        svc = _make_service(engine=engine)
        _run(svc._do_speak("Test."))
        assert svc.is_speaking is False

    def test_speak_engine_failure_swallowed(self):
        engine = _FakeEngine(success=False)
        svc = _make_service(engine=engine)
        ws = _FakeWebSocket()
        svc._clients.add(ws)
        try:
            _run(svc._do_speak("Test."))
        except Exception:
            pytest.fail("_do_speak ne doit pas propager les exceptions")

    def test_speak_no_engine_broadcasts_error(self):
        svc = _make_service(fail_engine=True)
        ws = _FakeWebSocket()
        svc._clients.add(ws)

        _run(svc._do_speak("Test."))

        msgs = ws.all_msgs()
        errors = [m for m in msgs if m.get("type") == "status" and m.get("state") == "error"]
        assert len(errors) >= 1

    def test_speak_idempotent_while_speaking(self):
        """Appeler _do_speak pendant une synthese ne la double pas."""
        engine = _FakeEngine()
        svc = _make_service(engine=engine)
        svc._speaking = True  # simuler synthese en cours

        ws = _FakeWebSocket()
        svc._clients.add(ws)
        _run(svc._do_speak("Test."))
        # Aucun chunk envoye car guard
        msgs = ws.all_msgs()
        chunks = [m for m in msgs if m.get("type") == "chunk"]
        assert len(chunks) == 0

    def test_chunk_has_pcm_b64_and_sample_rate(self):
        engine = _FakeEngine(pcm=b"\x00\x00" * 100)
        svc = _make_service(engine=engine)
        ws = _FakeWebSocket()
        svc._clients.add(ws)

        _run(svc._do_speak("Bonjour."))

        msgs = ws.all_msgs()
        chunks = [m for m in msgs if m.get("type") == "chunk"]
        assert len(chunks) >= 1
        chunk = chunks[0]
        assert "pcm_b64" in chunk
        assert "sample_rate" in chunk
        assert "seq" in chunk
        assert chunk["seq"] == 0

    def test_multi_sentence_increments_seq(self):
        engine = _FakeEngine(pcm=b"\x00\x00" * 100)
        svc = _make_service(engine=engine)
        ws = _FakeWebSocket()
        svc._clients.add(ws)

        _run(svc._do_speak("Phrase un. Phrase deux. Phrase trois."))

        msgs = ws.all_msgs()
        chunks = [m for m in msgs if m.get("type") == "chunk"]
        seqs = [c["seq"] for c in chunks]
        assert seqs == list(range(len(chunks)))


# ===========================================================================
# 9. TTSService — stop
# ===========================================================================

class TestTTSStop:
    def test_stop_sets_event(self):
        svc = _make_service()
        svc._speaking = True
        _run(svc._do_stop())
        assert svc._stop_event.is_set()

    def test_stop_when_not_speaking_no_error(self):
        svc = _make_service()
        try:
            _run(svc._do_stop())
        except Exception:
            pytest.fail("_do_stop ne doit pas lever si non en cours")

    def test_stop_clears_speaking_flag_after_speak(self):
        engine = _FakeEngine()
        svc = _make_service(engine=engine)

        async def _run_test():
            speak_task = asyncio.ensure_future(svc._do_speak("Test long."))
            await asyncio.sleep(0)
            await svc._do_stop()
            await speak_task

        _run(_run_test())
        assert svc.is_speaking is False


# ===========================================================================
# 10. TTSService — _select_engine
# ===========================================================================

class TestSelectEngine:
    def test_engine_factory_takes_priority(self):
        fake = _FakeEngine()
        svc = TTSService(_engine_factory=lambda: fake)
        assert svc._select_engine() is fake

    def test_kokoro_used_if_no_factory(self):
        kokoro = _FakeEngine()
        svc = TTSService(kokoro_engine=kokoro)
        assert svc._select_engine() is kokoro

    def test_piper_used_if_no_factory_no_kokoro(self):
        piper = _FakeEngine()
        svc = TTSService(piper_engine=piper)
        assert svc._select_engine() is piper

    def test_kokoro_preferred_over_piper(self):
        piper = _FakeEngine()
        kokoro = _FakeEngine()
        svc = TTSService(piper_engine=piper, kokoro_engine=kokoro)
        assert svc._select_engine() is kokoro

    def test_none_if_nothing_available(self):
        svc = TTSService()
        # Sans factory ni engines ni binaires reels -> None ou engine auto
        result = svc._select_engine()
        # On accepte None ou un engine valide (selon ce qui est installe)
        assert result is None or hasattr(result, "synthesize")
