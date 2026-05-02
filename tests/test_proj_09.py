# -*- coding: utf-8 -*-
"""
test_proj_09.py - Tests PROJ-09 : ProjectHistoryCompactor

Couvre :
  - CompactionResult : construction, to_dict()
  - compact() sur history.jsonl absent -> compacted=False
  - compact() sur history vide -> compacted=False
  - compact() sur N <= keep -> compacted=False
  - compact() sur N > keep -> compacted=True, entrees correctes
  - entrees archivees = N - keep (les plus anciennes)
  - entrees gardees = les keep plus recentes
  - ecriture atomique : pas de fichier .tmp residuel
  - archive creee dans history_archive/
  - contenu archive NDJSON valide
  - contenu history.jsonl apres compaction NDJSON valide
  - lignes invalides ignorees silencieusement
  - keep=1 cas extreme
  - appel depuis le handler MCP project_compact_history
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from core.project_history_compactor import (
    ProjectHistoryCompactor,
    CompactionResult,
    DEFAULT_KEEP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_history(project_dir: Path, entries: list[dict]) -> Path:
    """Ecrit un history.jsonl dans project_dir."""
    history_path = project_dir / "history.jsonl"
    lines = "\n".join(json.dumps(e) for e in entries)
    history_path.write_text(lines + "\n" if lines else "", encoding="utf-8")
    return history_path


def _make_entries(n: int) -> list[dict]:
    """Cree n entrees NDJSON factices numerotees."""
    return [{"idx": i, "content": f"message_{i}"} for i in range(n)]


# ===========================================================================
# 1. CompactionResult
# ===========================================================================

class TestCompactionResult:
    def test_default_values(self):
        r = CompactionResult(compacted=False)
        assert r.entries_kept == 0
        assert r.entries_archived == 0
        assert r.archive_path is None
        assert r.size_before_kb == 0.0
        assert r.size_after_kb == 0.0
        assert r.reason is None

    def test_to_dict_keys(self):
        r = CompactionResult(
            compacted=True,
            entries_kept=50,
            entries_archived=150,
            archive_path="/some/path.jsonl",
            size_before_kb=12.5,
            size_after_kb=3.1,
        )
        d = r.to_dict()
        assert set(d.keys()) == {
            "compacted", "entries_kept", "entries_archived",
            "archive_path", "size_before_kb", "size_after_kb", "reason",
        }
        assert d["compacted"] is True
        assert d["entries_kept"] == 50
        assert d["entries_archived"] == 150

    def test_to_dict_size_rounded(self):
        r = CompactionResult(compacted=True, size_before_kb=12.3456, size_after_kb=3.1234)
        d = r.to_dict()
        assert d["size_before_kb"] == 12.35
        assert d["size_after_kb"] == 3.12


# ===========================================================================
# 2. compact() — cas ou rien ne se passe
# ===========================================================================

class TestCompactNoOp:
    def test_history_absent(self, tmp_path):
        compactor = ProjectHistoryCompactor()
        result = compactor.compact(tmp_path, keep=10)
        assert result.compacted is False
        assert "absent" in (result.reason or "")

    def test_history_empty_file(self, tmp_path):
        (tmp_path / "history.jsonl").write_text("", encoding="utf-8")
        compactor = ProjectHistoryCompactor()
        result = compactor.compact(tmp_path, keep=10)
        assert result.compacted is False
        assert result.entries_kept == 0

    def test_entries_equal_keep(self, tmp_path):
        _write_history(tmp_path, _make_entries(10))
        result = ProjectHistoryCompactor().compact(tmp_path, keep=10)
        assert result.compacted is False
        assert result.entries_kept == 10
        assert result.entries_archived == 0

    def test_entries_less_than_keep(self, tmp_path):
        _write_history(tmp_path, _make_entries(5))
        result = ProjectHistoryCompactor().compact(tmp_path, keep=200)
        assert result.compacted is False
        assert result.entries_kept == 5


# ===========================================================================
# 3. compact() — compaction effective
# ===========================================================================

class TestCompactEffective:
    def test_compacted_true(self, tmp_path):
        _write_history(tmp_path, _make_entries(50))
        result = ProjectHistoryCompactor().compact(tmp_path, keep=20)
        assert result.compacted is True

    def test_entries_kept_count(self, tmp_path):
        _write_history(tmp_path, _make_entries(50))
        result = ProjectHistoryCompactor().compact(tmp_path, keep=20)
        assert result.entries_kept == 20
        assert result.entries_archived == 30

    def test_kept_are_most_recent(self, tmp_path):
        """Les entrees conservees doivent etre les 20 dernieres (idx 30-49)."""
        _write_history(tmp_path, _make_entries(50))
        ProjectHistoryCompactor().compact(tmp_path, keep=20)
        history_path = tmp_path / "history.jsonl"
        kept = [
            json.loads(l)
            for l in history_path.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        assert len(kept) == 20
        assert kept[0]["idx"] == 30   # premiere entree conservee
        assert kept[-1]["idx"] == 49  # derniere entree

    def test_archived_are_oldest(self, tmp_path):
        """Les entrees archivees doivent etre les 30 premieres (idx 0-29)."""
        _write_history(tmp_path, _make_entries(50))
        ProjectHistoryCompactor().compact(tmp_path, keep=20)
        archive_dir = tmp_path / "history_archive"
        archives = list(archive_dir.glob("*.jsonl"))
        assert len(archives) == 1
        archived = [
            json.loads(l)
            for l in archives[0].read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        assert len(archived) == 30
        assert archived[0]["idx"] == 0
        assert archived[-1]["idx"] == 29

    def test_sizes_reported(self, tmp_path):
        _write_history(tmp_path, _make_entries(100))
        result = ProjectHistoryCompactor().compact(tmp_path, keep=10)
        assert result.size_before_kb > 0
        assert result.size_after_kb > 0
        assert result.size_after_kb < result.size_before_kb

    def test_archive_path_in_result(self, tmp_path):
        _write_history(tmp_path, _make_entries(50))
        result = ProjectHistoryCompactor().compact(tmp_path, keep=20)
        assert result.archive_path is not None
        assert Path(result.archive_path).exists()

    def test_archive_ndjson_valid(self, tmp_path):
        _write_history(tmp_path, _make_entries(50))
        result = ProjectHistoryCompactor().compact(tmp_path, keep=20)
        archive = Path(result.archive_path)
        for line in archive.read_text(encoding="utf-8").splitlines():
            if line.strip():
                json.loads(line)  # ne doit pas lever

    def test_history_ndjson_valid_after(self, tmp_path):
        _write_history(tmp_path, _make_entries(50))
        ProjectHistoryCompactor().compact(tmp_path, keep=20)
        history_path = tmp_path / "history.jsonl"
        for line in history_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                json.loads(line)  # ne doit pas lever


# ===========================================================================
# 4. Atomicite et robustesse
# ===========================================================================

class TestAtomicity:
    def test_no_tmp_file_left(self, tmp_path):
        """Aucun fichier .tmp ne doit rester apres la compaction."""
        _write_history(tmp_path, _make_entries(50))
        ProjectHistoryCompactor().compact(tmp_path, keep=20)
        assert list(tmp_path.glob("*.tmp")) == []
        archive_dir = tmp_path / "history_archive"
        if archive_dir.exists():
            assert list(archive_dir.glob("*.tmp")) == []

    def test_invalid_lines_ignored(self, tmp_path):
        """Les lignes NDJSON invalides sont ignorees, compaction se poursuit."""
        history_path = tmp_path / "history.jsonl"
        lines = []
        for i in range(50):
            lines.append(json.dumps({"idx": i}))
        # Inserer 3 lignes invalides
        lines.insert(10, "INVALID_JSON{{{")
        lines.insert(25, "")
        lines.insert(40, "not json at all")
        history_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = ProjectHistoryCompactor().compact(tmp_path, keep=20)
        assert result.compacted is True
        # 50 entrees valides -> kept=20, archived=30
        assert result.entries_kept == 20
        assert result.entries_archived == 30

    def test_keep_one_extreme(self, tmp_path):
        _write_history(tmp_path, _make_entries(10))
        result = ProjectHistoryCompactor().compact(tmp_path, keep=1)
        assert result.compacted is True
        assert result.entries_kept == 1
        assert result.entries_archived == 9

    def test_keep_zero_clamped_to_one(self, tmp_path):
        """keep=0 doit etre clamp a 1 en interne."""
        _write_history(tmp_path, _make_entries(5))
        result = ProjectHistoryCompactor().compact(tmp_path, keep=0)
        # 5 entrees, keep clamp a 1 -> compacte
        assert result.compacted is True
        assert result.entries_kept == 1


# ===========================================================================
# 5. Integration handler MCP project_compact_history
# ===========================================================================

class TestMcpHandlerIntegration:
    def _make_handler(self, tmp_path):
        """Construit un McpHandlersProjects minimal avec un vrai ProjectManager mock."""
        from core.mcp_handlers_projects import McpHandlersProjects

        class FakeServer(McpHandlersProjects):
            pass

        server = FakeServer()

        # Mock ProjectManager : retourne une meta pointant sur tmp_path
        from core.project_manager import ProjectMeta
        meta = ProjectMeta(
            id="test-id",
            slug=tmp_path.name,
            name="Test",
        )
        pm = MagicMock()
        pm.get_project.return_value = meta
        server._project_manager = pm

        # Patcher _LCCA_ROOT pour que le handler trouve projects/{slug}/
        import core.mcp_handlers_projects as mod
        # Le handler construit : _LCCA_ROOT / "projects" / meta.slug / "history.jsonl"
        # On a besoin que tmp_path.parent soit _LCCA_ROOT / "projects"
        # -> plus simple : on patche directement _tool_project_compact_history via
        #    un project_dir qui correspond a tmp_path
        return server, meta

    def test_handler_stub_returns_stats(self, tmp_path):
        """Le handler retourne les stats apres vraie compaction."""
        import core.project_manager as pm_mod
        original_root = pm_mod._LCCA_ROOT

        projects_dir = tmp_path / "projects"
        slug = "myproject"
        project_dir = projects_dir / slug
        project_dir.mkdir(parents=True)
        _write_history(project_dir, _make_entries(50))

        pm_mod._LCCA_ROOT = tmp_path
        try:
            from core.mcp_handlers_projects import McpHandlersProjects
            from core.project_manager import ProjectMeta

            class FakeServer(McpHandlersProjects):
                pass

            server = FakeServer()
            meta = ProjectMeta.from_dict({
                "id": "test-id", "slug": slug, "name": "Test",
                "description": "", "created_at": "2026-01-01T00:00:00+00:00",
                "last_opened": "2026-01-01T00:00:00+00:00", "status": "active",
                "tags": [], "model_override": None, "storage_mode": "shared",
                "legacy_namespaces": [], "history": {}, "stats": {},
                "migrated_from_v9": False,
            })
            pm = MagicMock()
            pm.get_project.return_value = meta
            server._project_manager = pm

            result = server._tool_project_compact_history(
                {"project_id": "test-id", "keep": 20}
            )

            assert result.get("project_id") == "test-id"
            assert result.get("compacted") is True
            assert result.get("entries_kept") == 20
            assert result.get("entries_archived") == 30
        finally:
            pm_mod._LCCA_ROOT = original_root

    def test_handler_no_history_returns_gracefully(self, tmp_path):
        """Sans history.jsonl, le handler retourne compacted=False sans lever."""
        import core.project_manager as pm_mod
        original_root = pm_mod._LCCA_ROOT

        projects_dir = tmp_path / "projects"
        slug = "emptyproject"
        (projects_dir / slug).mkdir(parents=True)

        pm_mod._LCCA_ROOT = tmp_path
        try:
            from core.mcp_handlers_projects import McpHandlersProjects
            from core.project_manager import ProjectMeta

            class FakeServer(McpHandlersProjects):
                pass

            server = FakeServer()
            meta = ProjectMeta.from_dict({
                "id": "empty-id", "slug": slug, "name": "Empty",
                "description": "", "created_at": "2026-01-01T00:00:00+00:00",
                "last_opened": "2026-01-01T00:00:00+00:00", "status": "active",
                "tags": [], "model_override": None, "storage_mode": "shared",
                "legacy_namespaces": [], "history": {}, "stats": {},
                "migrated_from_v9": False,
            })
            pm = MagicMock()
            pm.get_project.return_value = meta
            server._project_manager = pm

            result = server._tool_project_compact_history({"project_id": "empty-id"})
            assert result.get("compacted") is False
        finally:
            pm_mod._LCCA_ROOT = original_root
