"""
Tests pour utils/telemetry.py — TASK-12-07.

Suite : test_telemetry.py
Sprint : 12 — Phase 2
Couvre :
  - log_metric() : écriture JSONL, labels, silencieux en cas d'erreur
  - MetricTimer  : durée, labels, status ok/error, elapsed_ms
"""
from __future__ import annotations

import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_handler(tmp_path: Path, monkeypatch):
    """
    Réinitialise le handler rotatif global avant chaque test
    et redirige TELEMETRY_PATH vers tmp_path.
    """
    import utils.telemetry as tmod

    monkeypatch.setattr(tmod, "TELEMETRY_PATH", tmp_path / "telemetry.jsonl")
    monkeypatch.setattr(tmod, "_rotating_handler", None)
    yield
    # Fermeture propre du handler si créé
    if tmod._rotating_handler is not None:
        try:
            tmod._rotating_handler.close()
        except Exception:
            pass
    monkeypatch.setattr(tmod, "_rotating_handler", None)


def _read_lines(tmp_path: Path) -> list[dict]:
    """Lit et parse toutes les lignes JSONL du fichier de télémétrie."""
    p = tmp_path / "telemetry.jsonl"
    if not p.exists():
        return []
    lines = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            lines.append(json.loads(line))
    return lines


# ---------------------------------------------------------------------------
# Tests log_metric()
# ---------------------------------------------------------------------------

class TestLogMetric:

    def test_creates_jsonl_file(self, tmp_path: Path) -> None:
        """log_metric() crée le fichier s'il n'existe pas."""
        from utils.telemetry import log_metric
        log_metric("test.metric", 42.0)
        assert (tmp_path / "telemetry.jsonl").exists()

    def test_entry_format(self, tmp_path: Path) -> None:
        """Chaque entrée contient _ts, metric, value, labels."""
        from utils.telemetry import log_metric
        log_metric("my.metric", 7.5, {"env": "test"})
        lines = _read_lines(tmp_path)
        assert len(lines) == 1
        entry = lines[0]
        assert entry["metric"] == "my.metric"
        assert entry["value"] == 7.5
        assert entry["labels"]["env"] == "test"
        assert "_ts" in entry

    def test_empty_labels_default(self, tmp_path: Path) -> None:
        """Sans labels, le champ labels est un dict vide."""
        from utils.telemetry import log_metric
        log_metric("no.labels", 1.0)
        entry = _read_lines(tmp_path)[0]
        assert entry["labels"] == {}

    def test_multiple_entries_appended(self, tmp_path: Path) -> None:
        """Plusieurs appels → plusieurs lignes dans le fichier."""
        from utils.telemetry import log_metric
        for i in range(5):
            log_metric("counter", float(i))
        lines = _read_lines(tmp_path)
        assert len(lines) == 5
        assert [e["value"] for e in lines] == [0.0, 1.0, 2.0, 3.0, 4.0]

    def test_silent_on_write_error(self, tmp_path: Path) -> None:
        """log_metric() ne lève jamais d'exception, même si l'écriture échoue."""
        import utils.telemetry as tmod
        with patch.object(tmod, "_get_handler", return_value=None), \
             patch("builtins.open", side_effect=OSError("disk full")):
            # Ne doit pas lever
            tmod.log_metric("fail.metric", 99.0)

    def test_value_zero(self, tmp_path: Path) -> None:
        """Valeur 0.0 est écrite correctement."""
        from utils.telemetry import log_metric
        log_metric("zero", 0.0)
        entry = _read_lines(tmp_path)[0]
        assert entry["value"] == 0.0

    def test_value_negative(self, tmp_path: Path) -> None:
        """Valeurs négatives acceptées."""
        from utils.telemetry import log_metric
        log_metric("delta", -5.0)
        entry = _read_lines(tmp_path)[0]
        assert entry["value"] == -5.0

    def test_labels_multiple_keys(self, tmp_path: Path) -> None:
        """Plusieurs clés dans labels."""
        from utils.telemetry import log_metric
        log_metric("mcp.call", 120.0, {"tool": "edit_batch", "status": "ok", "n": 3})
        entry = _read_lines(tmp_path)[0]
        assert entry["labels"]["tool"] == "edit_batch"
        assert entry["labels"]["status"] == "ok"
        assert entry["labels"]["n"] == 3

    def test_json_valid_per_line(self, tmp_path: Path) -> None:
        """Chaque ligne est un JSON valide indépendamment."""
        from utils.telemetry import log_metric
        for i in range(3):
            log_metric(f"m{i}", float(i))
        raw = (tmp_path / "telemetry.jsonl").read_text(encoding="utf-8")
        for line in raw.strip().splitlines():
            json.loads(line)  # Ne doit pas lever


# ---------------------------------------------------------------------------
# Tests MetricTimer
# ---------------------------------------------------------------------------

class TestMetricTimer:

    def test_records_duration(self, tmp_path: Path) -> None:
        """MetricTimer enregistre une durée > 0 ms."""
        from utils.telemetry import MetricTimer
        with MetricTimer("test.timer"):
            time.sleep(0.01)  # 10 ms minimum
        lines = _read_lines(tmp_path)
        assert len(lines) == 1
        assert lines[0]["value"] >= 5  # au moins 5 ms (CI peut être lent)

    def test_elapsed_ms_attribute(self, tmp_path: Path) -> None:
        """elapsed_ms est accessible après le bloc."""
        from utils.telemetry import MetricTimer
        t = MetricTimer("attr.timer")
        with t:
            time.sleep(0.005)
        assert t.elapsed_ms >= 0
        assert isinstance(t.elapsed_ms, int)

    def test_labels_propagated(self, tmp_path: Path) -> None:
        """Les labels passés au constructeur apparaissent dans l'entrée."""
        from utils.telemetry import MetricTimer
        with MetricTimer("labeled", {"method": "tools/call"}):
            pass
        entry = _read_lines(tmp_path)[0]
        assert entry["labels"]["method"] == "tools/call"

    def test_unit_label_added(self, tmp_path: Path) -> None:
        """Le label 'unit': 'ms' est toujours ajouté."""
        from utils.telemetry import MetricTimer
        with MetricTimer("unit.check"):
            pass
        entry = _read_lines(tmp_path)[0]
        assert entry["labels"]["unit"] == "ms"

    def test_status_ok_on_success(self, tmp_path: Path) -> None:
        """status='ok' quand le bloc se termine normalement."""
        from utils.telemetry import MetricTimer
        with MetricTimer("status.ok"):
            pass
        entry = _read_lines(tmp_path)[0]
        assert entry["labels"]["status"] == "ok"

    def test_status_error_on_exception(self, tmp_path: Path) -> None:
        """status='error' quand le bloc lève une exception."""
        from utils.telemetry import MetricTimer
        with pytest.raises(ValueError):
            with MetricTimer("status.error"):
                raise ValueError("boom")
        entry = _read_lines(tmp_path)[0]
        assert entry["labels"]["status"] == "error"

    def test_exception_propagated(self, tmp_path: Path) -> None:
        """L'exception levée dans le bloc est bien propagée."""
        from utils.telemetry import MetricTimer
        with pytest.raises(RuntimeError, match="oops"):
            with MetricTimer("propagate"):
                raise RuntimeError("oops")

    def test_metric_name_in_entry(self, tmp_path: Path) -> None:
        """Le nom de la métrique est bien dans l'entrée JSONL."""
        from utils.telemetry import MetricTimer
        with MetricTimer("my.timer.name"):
            pass
        entry = _read_lines(tmp_path)[0]
        assert entry["metric"] == "my.timer.name"

    def test_no_labels_default(self, tmp_path: Path) -> None:
        """Sans labels, seuls 'unit' et 'status' sont présents."""
        from utils.telemetry import MetricTimer
        with MetricTimer("bare"):
            pass
        labels = _read_lines(tmp_path)[0]["labels"]
        assert set(labels.keys()) == {"unit", "status"}

    def test_nested_timers(self, tmp_path: Path) -> None:
        """Deux timers imbriqués enregistrent deux entrées distinctes."""
        from utils.telemetry import MetricTimer
        with MetricTimer("outer"):
            with MetricTimer("inner"):
                pass
        lines = _read_lines(tmp_path)
        assert len(lines) == 2
        names = {e["metric"] for e in lines}
        assert names == {"outer", "inner"}
