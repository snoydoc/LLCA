# -*- coding: utf-8 -*-
"""
test_proj_00.py — Tests PROJ-00 : MigrationManager

Couvre :
- needs_migration() : détection
- run() : création arborescence, project.json, user_context.json, index.cache.json
- _rewrite_paths() : 3 variantes slash
- idempotence si déjà migré
- copie skills
- MigrationResult.to_dict()
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from core.migration_manager import MigrationManager, MigrationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mgr(tmp_path: Path) -> MigrationManager:
    """MigrationManager pointant sur un répertoire temporaire."""
    return MigrationManager(lcca_root=tmp_path)


def _run_migration(tmp_path: Path) -> tuple[MigrationManager, MigrationResult]:
    mgr = _make_mgr(tmp_path)
    result = mgr.run()
    return mgr, result


# ---------------------------------------------------------------------------
# needs_migration()
# ---------------------------------------------------------------------------

def test_needs_migration_true_when_projects_absent(tmp_path):
    mgr = _make_mgr(tmp_path)
    assert mgr.needs_migration() is True


def test_needs_migration_false_when_projects_exists(tmp_path):
    mgr = _make_mgr(tmp_path)
    # Créer projects/.llca/index.cache.json
    cache_dir = tmp_path / "projects" / ".llca"
    cache_dir.mkdir(parents=True)
    (cache_dir / "index.cache.json").write_text("{}", encoding="utf-8")
    assert mgr.needs_migration() is False


def test_needs_migration_true_when_cache_absent(tmp_path):
    """projects/ existe mais index.cache.json manquant → migration nécessaire."""
    mgr = _make_mgr(tmp_path)
    (tmp_path / "projects" / ".llca").mkdir(parents=True)
    assert mgr.needs_migration() is True


# ---------------------------------------------------------------------------
# run() — arborescence
# ---------------------------------------------------------------------------

def test_run_creates_projects_llca_directory(tmp_path):
    _run_migration(tmp_path)
    assert (tmp_path / "projects" / ".llca").is_dir()


def test_run_creates_user_context_json(tmp_path):
    _run_migration(tmp_path)
    uc = tmp_path / "projects" / ".llca" / "user_context.json"
    assert uc.exists()
    data = json.loads(uc.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert "entries" in data


def test_run_creates_index_cache_json(tmp_path):
    _run_migration(tmp_path)
    cache = tmp_path / "projects" / ".llca" / "index.cache.json"
    assert cache.exists()
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert len(data["projects"]) == 1
    assert data["projects"][0]["slug"] == "legacy"


def test_run_creates_legacy_project_json(tmp_path):
    _run_migration(tmp_path)
    pj = tmp_path / "projects" / "legacy" / ".llca" / "project.json"
    assert pj.exists()


# ---------------------------------------------------------------------------
# run() — project.json contenu
# ---------------------------------------------------------------------------

def test_legacy_project_has_migrated_from_v9_true(tmp_path):
    _run_migration(tmp_path)
    pj = json.loads(
        (tmp_path / "projects" / "legacy" / ".llca" / "project.json")
        .read_text(encoding="utf-8")
    )
    assert pj["migrated_from_v9"] is True


def test_legacy_project_storage_mode_is_shared(tmp_path):
    _run_migration(tmp_path)
    pj = json.loads(
        (tmp_path / "projects" / "legacy" / ".llca" / "project.json")
        .read_text(encoding="utf-8")
    )
    assert pj["storage_mode"] == "shared"


def test_legacy_namespaces_contains_lcca_wildcard(tmp_path):
    _run_migration(tmp_path)
    pj = json.loads(
        (tmp_path / "projects" / "legacy" / ".llca" / "project.json")
        .read_text(encoding="utf-8")
    )
    assert "lcca_*" in pj["legacy_namespaces"]


def test_legacy_project_slug_is_legacy(tmp_path):
    _run_migration(tmp_path)
    pj = json.loads(
        (tmp_path / "projects" / "legacy" / ".llca" / "project.json")
        .read_text(encoding="utf-8")
    )
    assert pj["slug"] == "legacy"


def test_legacy_project_has_uuid_id(tmp_path):
    _, result = _run_migration(tmp_path)
    import uuid
    # Doit être un UUID valide
    uuid.UUID(result.legacy_project_id)  # lève ValueError si invalide


# ---------------------------------------------------------------------------
# _rewrite_paths()
# ---------------------------------------------------------------------------

def test_rewrite_paths_double_backslash(tmp_path):
    mgr = _make_mgr(tmp_path)
    original = "voir D:\\\\LLMCodeAgent\\\\core\\\\foo.py"
    result = mgr._rewrite_paths(original)
    assert "{PROJECT_ROOT}" in result
    assert "D:\\\\" not in result


def test_rewrite_paths_single_backslash(tmp_path):
    mgr = _make_mgr(tmp_path)
    original = r"voir D:\LLMCodeAgent\core\foo.py"
    result = mgr._rewrite_paths(original)
    assert "{PROJECT_ROOT}" in result


def test_rewrite_paths_forward_slash(tmp_path):
    mgr = _make_mgr(tmp_path)
    original = "voir D:/LLMCodeAgent/core/foo.py"
    result = mgr._rewrite_paths(original)
    assert "{PROJECT_ROOT}" in result


def test_rewrite_paths_preserves_non_llca_content(tmp_path):
    mgr = _make_mgr(tmp_path)
    original = "Contenu sans chemin LLCA, reste intact."
    result = mgr._rewrite_paths(original)
    assert result == original


# ---------------------------------------------------------------------------
# Idempotence + already_done
# ---------------------------------------------------------------------------

def test_run_is_idempotent_if_projects_exists(tmp_path):
    """Deux run() successifs ne lèvent pas d'exception, le second retourne already_done."""
    mgr = _make_mgr(tmp_path)
    r1 = mgr.run()
    r2 = mgr.run()
    assert r1.success is True
    assert r2.success is True
    assert r2.already_done is True


# ---------------------------------------------------------------------------
# Copie skills
# ---------------------------------------------------------------------------

def test_run_copies_skills_to_legacy(tmp_path):
    """Si skills/ existe dans la racine projet, les fichiers sont copiés dans legacy/skills/."""
    skills_src = tmp_path / "skills"
    skills_src.mkdir()
    (skills_src / "example.md").write_text("# Skill test\nD:\\LLMCodeAgent\\core\\foo.py", encoding="utf-8")

    _run_migration(tmp_path)

    dest = tmp_path / "projects" / "legacy" / "skills" / "example.md"
    assert dest.exists()
    content = dest.read_text(encoding="utf-8")
    # _rewrite_paths() doit avoir remplacé le chemin
    assert "{PROJECT_ROOT}" in content


def test_run_skills_copied_count_in_result(tmp_path):
    """skills_copied reflète le nombre de fichiers copiés."""
    skills_src = tmp_path / "skills"
    skills_src.mkdir()
    (skills_src / "a.md").write_text("a", encoding="utf-8")
    (skills_src / "b.md").write_text("b", encoding="utf-8")

    _, result = _run_migration(tmp_path)
    assert result.skills_copied == 2


# ---------------------------------------------------------------------------
# MigrationResult
# ---------------------------------------------------------------------------

def test_migration_result_contains_report(tmp_path):
    _, result = _run_migration(tmp_path)
    assert isinstance(result.report, str)
    assert len(result.report) > 0


def test_migration_result_to_dict(tmp_path):
    _, result = _run_migration(tmp_path)
    d = result.to_dict()
    assert "success" in d
    assert "report" in d
    assert "legacy_project_id" in d
    assert d["success"] is True


def test_migration_result_success_true(tmp_path):
    _, result = _run_migration(tmp_path)
    assert result.success is True
    assert result.already_done is False
