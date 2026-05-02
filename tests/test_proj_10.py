# -*- coding: utf-8-sig -*-
"""
test_proj_10.py - PROJ-10
Tests ProjectHealthChecker + handler MCP _tool_project_healthcheck.

5 classes :
  TestHealthReport          — to_dict(), failure_rate, valeurs par defaut
  TestCheckerFiles          — _check_files (fichiers + dossiers manquants)
  TestCheckerHistory        — _check_history (stats NDJSON, archives, corruption)
  TestCheckerWal            — _check_wal (entrees, succes/echecs, archives, taux echec)
  TestMcpHealthcheckHandler — delegation ProjectHealthChecker depuis le handler MCP
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.project_health_checker import (
    ProjectHealthChecker,
    HealthReport,
    HISTORY_COMPACTION_THRESHOLD_KB,
    WAL_COMPACTION_THRESHOLD_ENTRIES,
    WAL_FAILURE_RATE_WARN,
)


# ===================================================================
# Helpers
# ===================================================================

def _make_meta(slug="test-proj", pid="pid-001", name="Test Projet", status="active"):
    m = MagicMock()
    m.id     = pid
    m.slug   = slug
    m.name   = name
    m.status = status
    return m


def _seed_project(tmp_path: Path) -> Path:
    """Cree un projet minimal sain."""
    proj = tmp_path / "projects" / "test-proj"
    llca = proj / ".llca"
    llca.mkdir(parents=True)
    (proj / "history.jsonl").write_text("", encoding="utf-8")
    (proj / "skills").mkdir()
    (proj / "specs").mkdir()
    (proj / "history_archive").mkdir()
    meta_data = {"id": "pid-001", "slug": "test-proj", "name": "Test Projet", "status": "active"}
    (llca / "project.json").write_text(json.dumps(meta_data), encoding="utf-8")
    return proj


# ===================================================================
# TestHealthReport
# ===================================================================

class TestHealthReport:
    def test_defaults_healthy(self):
        r = HealthReport()
        assert r.healthy is True
        assert r.issues == []
        assert r.warnings == []

    def test_to_dict_keys(self):
        r = HealthReport(project_id="p1", slug="s1", name="N", status="active")
        d = r.to_dict()
        for key in ("project_id", "slug", "name", "status", "healthy",
                    "issues", "issues_count", "warnings", "recommendations",
                    "files", "history", "wal", "project_json_valid"):
            assert key in d, f"Cle manquante : {key}"

    def test_to_dict_failure_rate_zero_entries(self):
        r = HealthReport()
        d = r.to_dict()
        assert d["wal"]["failure_rate"] == 0.0

    def test_to_dict_failure_rate_computed(self):
        r = HealthReport(wal_entries=10, wal_failures=3)
        d = r.to_dict()
        assert d["wal"]["failure_rate"] == pytest.approx(0.3)

    def test_to_dict_issues_count(self):
        r = HealthReport(issues=["a", "b"])
        d = r.to_dict()
        assert d["issues_count"] == 2


# ===================================================================
# TestCheckerFiles
# ===================================================================

class TestCheckerFiles:
    def test_healthy_project_no_issues(self, tmp_path):
        proj  = _seed_project(tmp_path)
        meta  = _make_meta()
        r     = ProjectHealthChecker().check(proj, meta)
        assert r.files_ok is True
        assert r.missing_files == []
        assert r.missing_dirs  == []

    def test_missing_history_jsonl(self, tmp_path):
        proj = _seed_project(tmp_path)
        (proj / "history.jsonl").unlink()
        meta = _make_meta()
        r    = ProjectHealthChecker().check(proj, meta)
        assert r.files_ok is False
        assert "history.jsonl" in r.missing_files
        assert r.healthy is False

    def test_missing_skills_dir(self, tmp_path):
        proj = _seed_project(tmp_path)
        (proj / "skills").rmdir()
        meta = _make_meta()
        r    = ProjectHealthChecker().check(proj, meta)
        assert "skills" in r.missing_dirs
        assert r.healthy is False

    def test_missing_llca_project_json(self, tmp_path):
        proj = _seed_project(tmp_path)
        (proj / ".llca" / "project.json").unlink()
        meta = _make_meta()
        r    = ProjectHealthChecker().check(proj, meta)
        assert ".llca/project.json" in r.missing_files


# ===================================================================
# TestCheckerHistory
# ===================================================================

class TestCheckerHistory:
    def test_empty_history(self, tmp_path):
        proj = _seed_project(tmp_path)
        meta = _make_meta()
        r    = ProjectHealthChecker().check(proj, meta)
        assert r.history_exists is True
        assert r.history_entries == 0
        assert r.history_size_kb == 0.0

    def test_valid_entries_counted(self, tmp_path):
        proj = _seed_project(tmp_path)
        lines = [
            json.dumps({"_ts": "2026-01-01T00:00:00Z", "text": "entry1"}),
            json.dumps({"_ts": "2026-01-02T00:00:00Z", "text": "entry2"}),
        ]
        (proj / "history.jsonl").write_text("\n".join(lines), encoding="utf-8")
        meta = _make_meta()
        r    = ProjectHealthChecker().check(proj, meta)
        assert r.history_entries == 2
        assert r.history_last_ts == "2026-01-02T00:00:00Z"

    def test_corrupt_lines_counted(self, tmp_path):
        proj = _seed_project(tmp_path)
        (proj / "history.jsonl").write_text(
            '{"_ts":"2026-01-01Z","ok":1}\nNOT_JSON\n{"_ts":"2026-01-03Z","ok":2}\n',
            encoding="utf-8",
        )
        meta = _make_meta()
        r    = ProjectHealthChecker().check(proj, meta)
        assert r.history_entries == 2
        assert r.history_corrupt_lines == 1
        assert any("corrompue" in w for w in r.warnings)

    def test_archive_count_and_size(self, tmp_path):
        proj    = _seed_project(tmp_path)
        archive = proj / "history_archive"
        (archive / "20260101_000000.jsonl").write_text('{"a":1}\n', encoding="utf-8")
        (archive / "20260102_000000.jsonl").write_text('{"b":2}\n', encoding="utf-8")
        meta = _make_meta()
        r    = ProjectHealthChecker().check(proj, meta)
        assert r.history_archive_count == 2
        assert r.history_archive_size_kb > 0.0

    def test_recommendation_large_history(self, tmp_path):
        proj = _seed_project(tmp_path)
        big  = '{"text": "' + "x" * 512 + '"}\n'
        # depasser le seuil HISTORY_COMPACTION_THRESHOLD_KB (500 KB)
        content = big * 1025   # ~512 KB par repetition * 1025 > 500 KB
        (proj / "history.jsonl").write_text(content, encoding="utf-8")
        meta = _make_meta()
        r    = ProjectHealthChecker().check(proj, meta)
        assert any("compact" in rec for rec in r.recommendations)


# ===================================================================
# TestCheckerWal
# ===================================================================

class TestCheckerWal:
    def _wal_path(self, proj: Path) -> Path:
        return proj / ".llca" / "project_wal.jsonl"

    def test_no_wal(self, tmp_path):
        proj = _seed_project(tmp_path)
        meta = _make_meta()
        r    = ProjectHealthChecker().check(proj, meta)
        assert r.wal_exists is False
        assert r.wal_entries == 0

    def test_wal_success_failures(self, tmp_path):
        proj = _seed_project(tmp_path)
        lines = [
            json.dumps({"_ts": "2026-01-01Z", "success": True}),
            json.dumps({"_ts": "2026-01-02Z", "success": True}),
            json.dumps({"_ts": "2026-01-03Z", "success": False}),
        ]
        self._wal_path(proj).write_text("\n".join(lines), encoding="utf-8")
        meta = _make_meta()
        r    = ProjectHealthChecker().check(proj, meta)
        assert r.wal_exists is True
        assert r.wal_entries == 3
        assert r.wal_success  == 2
        assert r.wal_failures == 1
        assert r.wal_last_ts  == "2026-01-03Z"

    def test_wal_high_failure_rate_warning(self, tmp_path):
        proj  = _seed_project(tmp_path)
        lines = [json.dumps({"_ts": "2026-01-01Z", "success": False})] * 5 + \
                [json.dumps({"_ts": "2026-01-02Z", "success": True})]
        self._wal_path(proj).write_text("\n".join(lines), encoding="utf-8")
        meta = _make_meta()
        r    = ProjectHealthChecker().check(proj, meta)
        assert any("echec" in w for w in r.warnings)

    def test_wal_archive_count(self, tmp_path):
        proj       = _seed_project(tmp_path)
        wal_archive = proj / ".llca" / "wal_archive"
        wal_archive.mkdir()
        (wal_archive / "20260101.jsonl").write_text('{"success":true}\n', encoding="utf-8")
        self._wal_path(proj).write_text('{"_ts":"2026-01-01Z","success":true}\n', encoding="utf-8")
        meta = _make_meta()
        r    = ProjectHealthChecker().check(proj, meta)
        assert r.wal_archive_count == 1

    def test_recommendation_large_wal(self, tmp_path):
        proj  = _seed_project(tmp_path)
        lines = [json.dumps({"_ts": f"2026-01-{i:02d}Z", "success": True})
                 for i in range(1, WAL_COMPACTION_THRESHOLD_ENTRIES + 2)]
        self._wal_path(proj).write_text("\n".join(lines), encoding="utf-8")
        meta = _make_meta()
        r    = ProjectHealthChecker().check(proj, meta)
        assert any("WAL" in rec for rec in r.recommendations)


# ===================================================================
# TestMcpHealthcheckHandler
# ===================================================================

class TestMcpHealthcheckHandler:
    """Tests du handler _tool_project_healthcheck dans McpHandlersProjects."""

    def _make_handler(self):
        from core.mcp_handlers_projects import McpHandlersProjects

        class _H(McpHandlersProjects):
            _project_manager = None
            _project_lock    = None
            _project_orch    = None

        return _H()

    def test_no_project_id_no_active(self):
        h = self._make_handler()
        result = h._tool_project_healthcheck({})
        assert result["healthy"] is False
        assert "Aucun projet" in result.get("reason", "")

    def test_project_not_found(self):
        h  = self._make_handler()
        pm = MagicMock()
        pm.get_project.return_value = None
        h._project_manager = pm

        result = h._tool_project_healthcheck({"project_id": "ghost-id"})
        assert result["healthy"] is False
        assert result["issues_count"] == 1

    def test_delegates_to_health_checker(self, tmp_path):
        """Le handler doit retourner le to_dict() du HealthReport (pas un mini-check maison)."""
        h   = self._make_handler()
        meta = _make_meta()

        pm = MagicMock()
        pm.get_project.return_value = meta
        h._project_manager = pm

        fake_report = HealthReport(
            project_id="pid-001",
            slug="test-proj",
            name="Test Projet",
            status="active",
            healthy=True,
        )

        with patch("core.project_manager._LCCA_ROOT", tmp_path), \
             patch("core.project_health_checker.ProjectHealthChecker") as MockChecker:
            mock_instance = MagicMock()
            mock_instance.check.return_value = fake_report
            MockChecker.return_value = mock_instance

            result = h._tool_project_healthcheck({"project_id": "pid-001"})

        # Verifier que le checker a ete instancie et appele
        MockChecker.assert_called_once()
        mock_instance.check.assert_called_once()

        # Le resultat est le to_dict() du rapport
        assert result["healthy"] is True
        assert result["project_id"] == "pid-001"
        assert "issues" in result
        assert "wal" in result
        assert "history" in result

    def test_active_ctx_used_when_no_project_id(self, tmp_path):
        """Sans project_id, le handler utilise le projet actif."""
        h   = self._make_handler()
        meta = _make_meta()

        ctx_mock = MagicMock()
        ctx_mock.meta.id = "pid-001"
        h._set_active_ctx(ctx_mock)

        pm = MagicMock()
        pm.get_project.return_value = meta
        h._project_manager = pm

        fake_report = HealthReport(project_id="pid-001", slug="test-proj",
                                   name="Test Projet", status="active", healthy=True)

        with patch("core.project_manager._LCCA_ROOT", tmp_path), \
             patch("core.project_health_checker.ProjectHealthChecker") as MockChecker:
            mock_instance = MagicMock()
            mock_instance.check.return_value = fake_report
            MockChecker.return_value = mock_instance
            result = h._tool_project_healthcheck({})

        assert result["healthy"] is True
        # Cleanup
        h._set_active_ctx(None)

    def test_full_report_structure(self, tmp_path):
        """Le resultat contient toutes les cles du HealthReport.to_dict()."""
        h    = self._make_handler()
        meta = _make_meta()
        proj = _seed_project(tmp_path)

        pm = MagicMock()
        pm.get_project.return_value = meta
        h._project_manager = pm

        # Utilise le checker reel sur un projet sain
        with patch("core.project_manager._LCCA_ROOT", tmp_path / "projects" / ".."):
            # Patcher _LCCA_ROOT pour pointer vers tmp_path
            import core.project_manager as pm_mod
            orig = pm_mod._LCCA_ROOT
            pm_mod._LCCA_ROOT = tmp_path
            try:
                result = h._tool_project_healthcheck({"project_id": "pid-001"})
            finally:
                pm_mod._LCCA_ROOT = orig

        required_keys = {
            "project_id", "slug", "name", "status", "healthy",
            "issues", "issues_count", "warnings", "recommendations",
            "files", "history", "wal", "project_json_valid",
        }
        for key in required_keys:
            assert key in result, f"Cle manquante dans le rapport MCP : {key}"
