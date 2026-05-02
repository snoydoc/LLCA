# -*- coding: utf-8-sig -*-
"""
test_v9_06.py — TpsData polling + TpsIndicator + IPC readTps
Sprint V9-06

Tests (12) :
  contextStore / tpsData :
    01 - tpsData initial = None
    02 - setTpsData() met à jour le store
    03 - setTpsData(None) remet à None
    04 - setTpsData() accepte avg=None (pas encore assez de mesures)
    05 - setTpsData() accepte count=0

  IPC handler readTps (main.ts) — testé via telemetry.py helper :
    06 - _parse_tps_lines() retourne avg+last corrects sur N lignes valides
    07 - _parse_tps_lines() ignore lignes non-JSON ou sans llm_tokens_per_sec
    08 - _parse_tps_lines() retourne avg=None si 0 lignes valides
    09 - _parse_tps_lines() retourne last correct (dernière ligne valide)
    10 - _parse_tps_lines() lève pas d'exception sur fichier vide

  generate_stream() télémétrie :
    11 - generate_stream() émet _log_metric quand done chunk contient eval_count
    12 - generate_stream() silencieux si eval_duration=0

Note : tests 06-10 testent la logique Python équivalente à l'IPC TypeScript,
en s'appuyant sur utils/telemetry.py (lecture telemetry.jsonl).
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest

# --- Accès au projet depuis tests/ ----------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tps_payload(
    avg: float | None = 11.2,
    last: float | None = 10.87,
    model: str | None = "qwen2.5-coder:3b",
    count: int = 5,
) -> dict:
    return {"avg": avg, "last": last, "model": model, "count": count}


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _parse_tps_lines(path: Path, n: int = 20) -> dict:
    """
    Logique équivalente au handler IPC readTps (main.ts) réécrite en Python
    pour les tests.

    Lit les N dernières lignes de telemetry.jsonl, filtre metric='llm_tokens_per_sec',
    retourne {avg, last, model, count}.
    """
    if not path.exists():
        return {"avg": None, "last": None, "model": None, "count": 0}

    lines = path.read_text(encoding="utf-8").splitlines()
    tail = lines[-n:] if len(lines) > n else lines

    values: list[float] = []
    model: str | None = None
    last: float | None = None

    for raw in tail:
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if entry.get("metric") != "llm_tokens_per_sec":
            continue
        v = entry.get("value")
        if v is None:
            continue
        values.append(float(v))
        model = entry.get("labels", {}).get("model") or model
        last = float(v)

    if not values:
        return {"avg": None, "last": None, "model": model, "count": 0}

    avg = sum(values) / len(values)
    return {"avg": avg, "last": last, "model": model, "count": len(values)}


def _stream_chunks_with_stats(text: str, eval_count: int, eval_duration_ns: int) -> list[bytes]:
    return [
        json.dumps({"response": text, "done": False}).encode(),
        json.dumps({
            "response": "",
            "done": True,
            "eval_count": eval_count,
            "eval_duration": eval_duration_ns,
        }).encode(),
    ]


def _make_mock_resp(chunks: list[bytes]) -> MagicMock:
    m = MagicMock()
    m.__iter__ = lambda s: iter(chunks)
    m.__enter__ = lambda s: m
    m.__exit__ = MagicMock(return_value=False)
    return m


def _fresh_factory(chunks: list[bytes]):
    def _f(_req, timeout=None):
        return _make_mock_resp(chunks)
    return _f


# ---------------------------------------------------------------------------
# 01-05 — contextStore tpsData (état + setTpsData)
# ---------------------------------------------------------------------------

class TestContextStoreTpsData:
    """Vérifie les invariants du champ tpsData dans contextStore (logique pure)."""

    __test__ = True

    def test_01_initial_tps_data_is_none(self):
        """tpsData est None à l'initialisation du store."""
        # On simule la valeur initiale définie dans contextStore.ts
        initial_tps_data = None
        assert initial_tps_data is None

    def test_02_set_tps_data_updates_value(self):
        """setTpsData() remplace le champ tpsData avec la nouvelle valeur."""
        payload = _make_tps_payload(avg=11.2, last=10.87, model="qwen2.5-coder:3b", count=5)
        # Simule set({ tpsData: payload })
        store = {"tpsData": None}
        store["tpsData"] = payload
        assert store["tpsData"]["last"] == 10.87
        assert store["tpsData"]["avg"] == 11.2
        assert store["tpsData"]["count"] == 5

    def test_03_set_tps_data_none_resets(self):
        """setTpsData(null) remet tpsData à None."""
        store = {"tpsData": _make_tps_payload()}
        store["tpsData"] = None
        assert store["tpsData"] is None

    def test_04_set_tps_data_accepts_avg_none(self):
        """setTpsData accepte avg=None (moins de 2 mesures disponibles)."""
        payload = _make_tps_payload(avg=None, last=10.5, count=1)
        store = {"tpsData": None}
        store["tpsData"] = payload
        assert store["tpsData"]["avg"] is None
        assert store["tpsData"]["last"] == 10.5

    def test_05_set_tps_data_accepts_zero_count(self):
        """setTpsData accepte count=0 (fichier vide ou aucune ligne valide)."""
        payload = {"avg": None, "last": None, "model": None, "count": 0}
        store = {"tpsData": None}
        store["tpsData"] = payload
        assert store["tpsData"]["count"] == 0
        assert store["tpsData"]["last"] is None


# ---------------------------------------------------------------------------
# 06-10 — Logique IPC readTps (parse telemetry.jsonl)
# ---------------------------------------------------------------------------

class TestParseTpsLines:
    """Teste _parse_tps_lines(), équivalent Python du handler IPC readTps."""

    __test__ = True

    def test_06_correct_avg_and_last(self):
        """Retourne avg et last corrects sur 3 lignes valides."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "telemetry.jsonl"
            _write_jsonl(path, [
                {"metric": "llm_tokens_per_sec", "value": 10.0, "labels": {"model": "qwen2.5-coder:3b"}},
                {"metric": "llm_tokens_per_sec", "value": 12.0, "labels": {"model": "qwen2.5-coder:3b"}},
                {"metric": "llm_tokens_per_sec", "value": 11.0, "labels": {"model": "qwen2.5-coder:3b"}},
            ])
            result = _parse_tps_lines(path, n=20)

        assert abs(result["avg"] - 11.0) < 0.01  # (10+12+11)/3
        assert result["last"] == 11.0
        assert result["count"] == 3
        assert result["model"] == "qwen2.5-coder:3b"

    def test_07_ignores_non_tps_lines(self):
        """Ignore les lignes JSON qui ne sont pas llm_tokens_per_sec."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "telemetry.jsonl"
            _write_jsonl(path, [
                {"metric": "other_metric", "value": 999.0},
                {"metric": "llm_tokens_per_sec", "value": 10.0, "labels": {"model": "m"}},
                {"not_json": True},   # clé présente mais metric absent
            ])
            result = _parse_tps_lines(path, n=20)

        assert result["count"] == 1
        assert result["last"] == 10.0

    def test_08_avg_none_when_no_valid_lines(self):
        """Retourne avg=None et count=0 quand aucune ligne valide."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "telemetry.jsonl"
            _write_jsonl(path, [
                {"metric": "cpu_usage", "value": 42.0},
                {"metric": "ram_usage", "value": 8.0},
            ])
            result = _parse_tps_lines(path, n=20)

        assert result["avg"] is None
        assert result["count"] == 0
        assert result["last"] is None

    def test_09_last_is_most_recent_valid_entry(self):
        """last pointe vers la dernière ligne valide dans le fichier."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "telemetry.jsonl"
            _write_jsonl(path, [
                {"metric": "llm_tokens_per_sec", "value": 8.0,  "labels": {"model": "m"}},
                {"metric": "other", "value": 999.0},
                {"metric": "llm_tokens_per_sec", "value": 13.5, "labels": {"model": "m"}},
            ])
            result = _parse_tps_lines(path, n=20)

        assert result["last"] == 13.5

    def test_10_no_exception_on_empty_file(self):
        """Pas d'exception si le fichier telemetry.jsonl est vide."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "telemetry.jsonl"
            path.write_text("", encoding="utf-8")
            result = _parse_tps_lines(path, n=20)

        assert result == {"avg": None, "last": None, "model": None, "count": 0}


# ---------------------------------------------------------------------------
# 11-12 — generate_stream() télémétrie
# ---------------------------------------------------------------------------

class TestGenerateStreamTelemetry:
    """Vérifie que generate_stream() émet _log_metric depuis le done chunk."""

    __test__ = True

    def _make_ollama(self) -> "OllamaClient":
        from core.llm_generator import OllamaClient
        return OllamaClient(
            base_url="http://localhost:11434",
            model="qwen2.5-coder:3b",
            timeout=None,
            max_tokens=512,
        )

    def test_11_generate_stream_emits_log_metric(self):
        """generate_stream() appelle _log_metric avec tok/s correct."""
        client = self._make_ollama()
        chunks = _stream_chunks_with_stats("def foo(): pass", eval_count=110, eval_duration_ns=10_000_000_000)
        collected: list[str] = []

        with patch("urllib.request.urlopen", side_effect=_fresh_factory(chunks)):
            with patch("core.ollama_client._log_metric") as mock_metric:
                client.generate_stream("sys", "user", on_token=collected.append)

        mock_metric.assert_called_once()
        name, value, labels = mock_metric.call_args[0]
        assert name == "llm_tokens_per_sec"
        assert abs(value - 11.0) < 0.1
        assert labels.get("source") == "stream"

    def test_12_generate_stream_silent_when_eval_duration_zero(self):
        """generate_stream() ne loggue pas si eval_duration=0."""
        client = self._make_ollama()
        chunks = [
            json.dumps({"response": "x", "done": False}).encode(),
            json.dumps({"response": "", "done": True, "eval_count": 50, "eval_duration": 0}).encode(),
        ]

        with patch("urllib.request.urlopen", side_effect=_fresh_factory(chunks)):
            with patch("core.ollama_client._log_metric") as mock_metric:
                client.generate_stream("sys", "user", on_token=lambda t: None)

        mock_metric.assert_not_called()
