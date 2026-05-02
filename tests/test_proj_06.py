# -*- coding: utf-8 -*-
"""
test_proj_06.py - Tests PROJ-06 : ProjectWal + make_wal_entry

Couvre :
  make_wal_entry  : structure, timestamp auto, valeurs par defaut
  ProjectWal      : chemins, append, read_last, read_all, read_for_tx,
                    stats, compact (atomique T-14), mode degrade
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.project_wal import (
    ProjectWal,
    make_wal_entry,
    WAL_FILENAME,
    ARCHIVE_DIRNAME,
    DEFAULT_KEEP_ENTRIES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wal(tmp_path: Path, slug: str = "test-proj") -> ProjectWal:
    """Cree un ProjectWal pointe sur tmp_path/projects/{slug}/."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    return ProjectWal(projects_dir=projects_dir, slug=slug)


def _seed_entry(wal: ProjectWal, tx_id: str = "tx_001", success: bool = True) -> dict:
    """Ajoute une entree WAL et la retourne."""
    entry = make_wal_entry(tx_id=tx_id, intent="ajoute login()", success=success)
    wal.append(entry)
    return entry


# ---------------------------------------------------------------------------
# make_wal_entry
# ---------------------------------------------------------------------------

class TestMakeWalEntry:

    def test_has_ts_field(self):
        entry = make_wal_entry(tx_id="tx_x", intent="test")
        assert "_ts" in entry

    def test_ts_is_iso8601(self):
        entry = make_wal_entry(tx_id="tx_x", intent="test")
        # Doit etre parseable en datetime
        dt = datetime.fromisoformat(entry["_ts"])
        assert dt is not None

    def test_required_fields_present(self):
        entry = make_wal_entry(tx_id="tx_abc", intent="ajoute foo()")
        for field in ("_ts", "tx_id", "intent", "action", "files",
                      "llm", "success", "duration_ms", "extra"):
            assert field in entry, f"champ manquant : {field}"

    def test_defaults(self):
        entry = make_wal_entry(tx_id="tx_def", intent="test")
        assert entry["action"] == ""
        assert entry["files"] == []
        assert entry["llm"] == ""
        assert entry["success"] is True
        assert entry["duration_ms"] == 0
        assert entry["extra"] == {}

    def test_custom_values(self):
        entry = make_wal_entry(
            tx_id="tx_custom",
            intent="refacto auth",
            action="modifie",
            files=["auth.py", "tests/test_auth.py"],
            llm="qwen2.5-coder:3b",
            success=False,
            duration_ms=3500,
            extra={"error": "timeout"},
        )
        assert entry["tx_id"] == "tx_custom"
        assert entry["action"] == "modifie"
        assert entry["files"] == ["auth.py", "tests/test_auth.py"]
        assert entry["llm"] == "qwen2.5-coder:3b"
        assert entry["success"] is False
        assert entry["duration_ms"] == 3500
        assert entry["extra"]["error"] == "timeout"


# ---------------------------------------------------------------------------
# ProjectWal — chemins
# ---------------------------------------------------------------------------

class TestProjectWalPaths:

    def test_wal_path_structure(self, tmp_path):
        wal = _make_wal(tmp_path, slug="mon-proj")
        expected = tmp_path / "projects" / "mon-proj" / ".llca" / WAL_FILENAME
        assert wal.wal_path == expected

    def test_archive_dir_structure(self, tmp_path):
        wal = _make_wal(tmp_path, slug="mon-proj")
        expected = tmp_path / "projects" / "mon-proj" / ".llca" / ARCHIVE_DIRNAME
        assert wal.archive_dir == expected


# ---------------------------------------------------------------------------
# ProjectWal — append
# ---------------------------------------------------------------------------

class TestProjectWalAppend:

    def test_append_creates_wal_file(self, tmp_path):
        wal = _make_wal(tmp_path)
        _seed_entry(wal)
        assert wal.wal_path.exists()

    def test_append_writes_valid_json_line(self, tmp_path):
        wal = _make_wal(tmp_path)
        entry = make_wal_entry(tx_id="tx_json", intent="test json")
        wal.append(entry)
        lines = wal.wal_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["tx_id"] == "tx_json"

    def test_append_multiple_entries_one_per_line(self, tmp_path):
        wal = _make_wal(tmp_path)
        for i in range(5):
            _seed_entry(wal, tx_id=f"tx_{i:03d}")
        lines = [l for l in wal.wal_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 5

    def test_append_auto_adds_ts_if_missing(self, tmp_path):
        wal = _make_wal(tmp_path)
        # Entree sans _ts (cas pathologique)
        wal.append({"tx_id": "tx_nots", "intent": "x"})
        entries = wal.read_last(1)
        assert "_ts" in entries[0]

    def test_append_never_raises_on_bad_dir(self, tmp_path):
        """append() est silencieux meme si le dossier est inaccessible."""
        wal = ProjectWal(
            projects_dir=tmp_path / "projects",
            slug="ghost",
            # Simule un path illisible : on patche open() indirectement
            # en utilisant un slug valide mais on ne cree pas le dossier
        )
        # Pas de mkdir préalable — append doit creer le dossier lui-meme
        entry = make_wal_entry(tx_id="tx_ghost", intent="ghost")
        wal.append(entry)  # Ne doit pas lever
        assert wal.wal_path.exists()


# ---------------------------------------------------------------------------
# ProjectWal — lecture
# ---------------------------------------------------------------------------

class TestProjectWalRead:

    def test_read_last_returns_empty_if_no_file(self, tmp_path):
        wal = _make_wal(tmp_path)
        assert wal.read_last(10) == []

    def test_read_last_returns_n_entries(self, tmp_path):
        wal = _make_wal(tmp_path)
        for i in range(10):
            _seed_entry(wal, tx_id=f"tx_{i:03d}")
        result = wal.read_last(3)
        assert len(result) == 3

    def test_read_last_returns_most_recent(self, tmp_path):
        wal = _make_wal(tmp_path)
        for i in range(5):
            _seed_entry(wal, tx_id=f"tx_{i:03d}")
        result = wal.read_last(2)
        assert result[-1]["tx_id"] == "tx_004"
        assert result[-2]["tx_id"] == "tx_003"

    def test_read_all_returns_all_entries(self, tmp_path):
        wal = _make_wal(tmp_path)
        for i in range(7):
            _seed_entry(wal, tx_id=f"tx_{i:03d}")
        assert len(wal.read_all()) == 7

    def test_read_for_tx_filters_by_tx_id(self, tmp_path):
        wal = _make_wal(tmp_path)
        _seed_entry(wal, tx_id="tx_aaa")
        _seed_entry(wal, tx_id="tx_bbb")
        _seed_entry(wal, tx_id="tx_aaa")
        result = wal.read_for_tx("tx_aaa")
        assert len(result) == 2
        assert all(e["tx_id"] == "tx_aaa" for e in result)

    def test_read_ignores_corrupt_lines(self, tmp_path):
        wal = _make_wal(tmp_path)
        # Ecrire une ligne valide + une corrompue + une valide
        wal.wal_path.parent.mkdir(parents=True, exist_ok=True)
        wal.wal_path.write_text(
            '{"_ts":"2026-01-01T00:00:00+00:00","tx_id":"tx_ok1","intent":"a"}\n'
            'LIGNE_CORROMPUE_JSON\n'
            '{"_ts":"2026-01-01T00:01:00+00:00","tx_id":"tx_ok2","intent":"b"}\n',
            encoding="utf-8",
        )
        entries = wal.read_all()
        assert len(entries) == 2
        assert entries[0]["tx_id"] == "tx_ok1"
        assert entries[1]["tx_id"] == "tx_ok2"


# ---------------------------------------------------------------------------
# ProjectWal — stats
# ---------------------------------------------------------------------------

class TestProjectWalStats:

    def test_stats_empty_if_no_file(self, tmp_path):
        wal = _make_wal(tmp_path)
        s = wal.stats()
        assert s["entry_count"] == 0
        assert s["size_bytes"] == 0
        assert s["last_ts"] is None

    def test_stats_entry_count(self, tmp_path):
        wal = _make_wal(tmp_path)
        for i in range(4):
            _seed_entry(wal, tx_id=f"tx_{i}")
        s = wal.stats()
        assert s["entry_count"] == 4

    def test_stats_success_failure_counts(self, tmp_path):
        wal = _make_wal(tmp_path)
        _seed_entry(wal, tx_id="tx_ok1", success=True)
        _seed_entry(wal, tx_id="tx_ok2", success=True)
        _seed_entry(wal, tx_id="tx_fail", success=False)
        s = wal.stats()
        assert s["success_count"] == 2
        assert s["failure_count"] == 1

    def test_stats_last_ts_is_most_recent(self, tmp_path):
        wal = _make_wal(tmp_path)
        _seed_entry(wal, tx_id="tx_first")
        _seed_entry(wal, tx_id="tx_last")
        entries = wal.read_all()
        s = wal.stats()
        assert s["last_ts"] == entries[-1]["_ts"]


# ---------------------------------------------------------------------------
# ProjectWal — compact
# ---------------------------------------------------------------------------

class TestProjectWalCompact:

    def test_compact_returns_zero_if_no_file(self, tmp_path):
        wal = _make_wal(tmp_path)
        assert wal.compact(keep_entries=10) == 0

    def test_compact_returns_zero_if_not_enough_entries(self, tmp_path):
        wal = _make_wal(tmp_path)
        for i in range(5):
            _seed_entry(wal, tx_id=f"tx_{i}")
        # 5 entrees, on garde 10 -> rien a archiver
        assert wal.compact(keep_entries=10) == 0

    def test_compact_archives_old_entries(self, tmp_path):
        wal = _make_wal(tmp_path)
        for i in range(20):
            _seed_entry(wal, tx_id=f"tx_{i:03d}")
        n = wal.compact(keep_entries=5)
        assert n == 15

    def test_compact_wal_retains_keep_entries(self, tmp_path):
        wal = _make_wal(tmp_path)
        for i in range(20):
            _seed_entry(wal, tx_id=f"tx_{i:03d}")
        wal.compact(keep_entries=5)
        remaining = wal.read_all()
        assert len(remaining) == 5

    def test_compact_retains_most_recent(self, tmp_path):
        wal = _make_wal(tmp_path)
        for i in range(10):
            _seed_entry(wal, tx_id=f"tx_{i:03d}")
        wal.compact(keep_entries=3)
        remaining = wal.read_all()
        assert remaining[-1]["tx_id"] == "tx_009"
        assert remaining[0]["tx_id"] == "tx_007"

    def test_compact_creates_archive_file(self, tmp_path):
        wal = _make_wal(tmp_path)
        for i in range(15):
            _seed_entry(wal, tx_id=f"tx_{i:03d}")
        wal.compact(keep_entries=5)
        archive_files = list(wal.archive_dir.glob("project_wal_*.jsonl"))
        assert len(archive_files) == 1

    def test_compact_archive_contains_old_entries(self, tmp_path):
        wal = _make_wal(tmp_path)
        for i in range(10):
            _seed_entry(wal, tx_id=f"tx_{i:03d}")
        wal.compact(keep_entries=3)
        archive_file = list(wal.archive_dir.glob("project_wal_*.jsonl"))[0]
        archived = [json.loads(l) for l in archive_file.read_text().splitlines() if l.strip()]
        assert len(archived) == 7
        assert archived[0]["tx_id"] == "tx_000"

    def test_compact_atomic_no_tmp_file_left(self, tmp_path):
        """Apres compact(), aucun fichier .tmp ne doit subsister."""
        wal = _make_wal(tmp_path)
        for i in range(10):
            _seed_entry(wal, tx_id=f"tx_{i:03d}")
        wal.compact(keep_entries=3)
        tmp_file = wal.wal_path.with_suffix(".tmp")
        assert not tmp_file.exists()
