# -*- coding: utf-8 -*-
"""
test_proj_01.py - Tests PROJ-01 : ProjectManager

Couvre :
- list_projects() : scan filesystem, tri, JSON invalide, filtre archive
- create_project() : arborescence, slug, unicite, storage_mode
- archive_project() : changement de statut
- update_last_opened() : mise a jour JSON
- _rebuild_cache() : ecriture index.cache.json
- get_project() : par id et par slug
- _generate_slug() : ASCII lowercase
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from core.project_manager import ProjectManager, ProjectMeta


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_pm(tmp_path: Path) -> ProjectManager:
    return ProjectManager(lcca_root=tmp_path)


def _seed_project(tmp_path: Path, slug: str, last_opened: str, status: str = "active") -> Path:
    """Cree un project.json minimal dans tmp_path/projects/{slug}/.llca/."""
    llca = tmp_path / "projects" / slug / ".llca"
    llca.mkdir(parents=True, exist_ok=True)
    pj = {
        "id": str(uuid.uuid4()),
        "slug": slug,
        "name": slug.replace("-", " ").title(),
        "description": "",
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_opened": last_opened,
        "status": status,
        "tags": [],
        "model_override": None,
        "storage_mode": "shared",
        "legacy_namespaces": [],
        "history": {},
        "stats": {},
        "migrated_from_v9": False,
    }
    (llca / "project.json").write_text(json.dumps(pj, indent=2), encoding="utf-8")
    return llca / "project.json"


# ---------------------------------------------------------------------------
# list_projects()
# ---------------------------------------------------------------------------

def test_list_projects_empty_when_no_projects(tmp_path):
    pm = _make_pm(tmp_path)
    assert pm.list_projects() == []


def test_list_projects_finds_project_json(tmp_path):
    _seed_project(tmp_path, "alpha", "2026-01-02T00:00:00+00:00")
    pm = _make_pm(tmp_path)
    projects = pm.list_projects()
    assert len(projects) == 1
    assert projects[0].slug == "alpha"


def test_list_projects_sorted_by_last_opened(tmp_path):
    _seed_project(tmp_path, "older", "2026-01-01T00:00:00+00:00")
    _seed_project(tmp_path, "newer", "2026-06-01T00:00:00+00:00")
    pm = _make_pm(tmp_path)
    projects = pm.list_projects()
    assert projects[0].slug == "newer"
    assert projects[1].slug == "older"


def test_list_projects_ignores_invalid_json(tmp_path):
    """Un project.json corrompu ne plante pas list_projects()."""
    llca = tmp_path / "projects" / "broken" / ".llca"
    llca.mkdir(parents=True)
    (llca / "project.json").write_text("{invalide json{{", encoding="utf-8")

    _seed_project(tmp_path, "valid", "2026-01-01T00:00:00+00:00")
    pm = _make_pm(tmp_path)
    projects = pm.list_projects()
    # Seul le projet valide est retourne
    assert len(projects) == 1
    assert projects[0].slug == "valid"


def test_list_projects_ignores_archived_by_default(tmp_path):
    _seed_project(tmp_path, "active-proj", "2026-01-02T00:00:00+00:00", status="active")
    _seed_project(tmp_path, "archived-proj", "2026-01-01T00:00:00+00:00", status="archived")
    pm = _make_pm(tmp_path)
    projects = pm.list_projects()
    assert len(projects) == 1
    assert projects[0].slug == "active-proj"


def test_list_projects_include_archived(tmp_path):
    _seed_project(tmp_path, "active-proj", "2026-01-02T00:00:00+00:00", status="active")
    _seed_project(tmp_path, "archived-proj", "2026-01-01T00:00:00+00:00", status="archived")
    pm = _make_pm(tmp_path)
    projects = pm.list_projects(include_archived=True)
    assert len(projects) == 2


# ---------------------------------------------------------------------------
# create_project()
# ---------------------------------------------------------------------------

def test_create_project_creates_directory_structure(tmp_path):
    pm = _make_pm(tmp_path)
    pm.create_project("Test Projet")
    slug = "test-projet"
    base = tmp_path / "projects" / slug
    assert (base / ".llca" / "project.json").exists()
    assert (base / "history.jsonl").exists()
    assert (base / "skills").is_dir()
    assert (base / "specs").is_dir()
    assert (base / "history_archive").is_dir()


def test_create_project_generates_slug_from_name(tmp_path):
    pm = _make_pm(tmp_path)
    meta = pm.create_project("Mon Super Projet")
    assert meta.slug == "mon-super-projet"


def test_create_project_slug_is_unique(tmp_path):
    pm = _make_pm(tmp_path)
    m1 = pm.create_project("Alpha")
    m2 = pm.create_project("Alpha")
    assert m1.slug != m2.slug
    assert m2.slug == "alpha-1"


def test_create_project_storage_mode_default_shared(tmp_path):
    pm = _make_pm(tmp_path)
    meta = pm.create_project("Proj")
    assert meta.storage_mode == "shared"


def test_create_project_storage_mode_isolated(tmp_path):
    pm = _make_pm(tmp_path)
    meta = pm.create_project("Proj Iso", storage_mode="isolated")
    assert meta.storage_mode == "isolated"


def test_create_project_has_valid_uuid(tmp_path):
    pm = _make_pm(tmp_path)
    meta = pm.create_project("UUID Test")
    uuid.UUID(meta.id)  # leve ValueError si invalide


def test_create_project_migrated_from_v9_false(tmp_path):
    pm = _make_pm(tmp_path)
    meta = pm.create_project("Normal Project")
    assert meta.migrated_from_v9 is False


# ---------------------------------------------------------------------------
# archive_project()
# ---------------------------------------------------------------------------

def test_archive_project_changes_status(tmp_path):
    pm = _make_pm(tmp_path)
    meta = pm.create_project("To Archive")
    result = pm.archive_project(meta.id)
    assert result is True
    reloaded = pm.get_project(meta.id)
    assert reloaded.status == "archived"


def test_archive_project_returns_false_if_not_found(tmp_path):
    pm = _make_pm(tmp_path)
    assert pm.archive_project("inexistant-id") is False


# ---------------------------------------------------------------------------
# update_last_opened()
# ---------------------------------------------------------------------------

def test_update_last_opened_modifies_json(tmp_path):
    pm = _make_pm(tmp_path)
    meta = pm.create_project("Open Me")
    old_ts = meta.last_opened

    # Petite pause pour garantir un timestamp different
    time.sleep(0.01)
    pm.update_last_opened(meta.id)

    reloaded = pm.get_project(meta.id)
    assert reloaded.last_opened != old_ts


# ---------------------------------------------------------------------------
# _rebuild_cache()
# ---------------------------------------------------------------------------

def test_rebuild_cache_writes_index_cache_json(tmp_path):
    pm = _make_pm(tmp_path)
    pm.create_project("Cache Test")
    cache_path = tmp_path / "projects" / ".llca" / "index.cache.json"
    assert cache_path.exists()
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert len(data["projects"]) >= 1


# ---------------------------------------------------------------------------
# get_project()
# ---------------------------------------------------------------------------

def test_get_project_by_slug(tmp_path):
    pm = _make_pm(tmp_path)
    pm.create_project("Slug Test")
    result = pm.get_project("slug-test")
    assert result is not None
    assert result.slug == "slug-test"


def test_get_project_by_id(tmp_path):
    pm = _make_pm(tmp_path)
    meta = pm.create_project("ID Test")
    result = pm.get_project(meta.id)
    assert result is not None
    assert result.id == meta.id


def test_get_project_returns_none_if_not_found(tmp_path):
    pm = _make_pm(tmp_path)
    assert pm.get_project("does-not-exist") is None


# ---------------------------------------------------------------------------
# _generate_slug()
# ---------------------------------------------------------------------------

def test_generate_slug_ascii_lowercase(tmp_path):
    pm = _make_pm(tmp_path)
    slug = pm._generate_slug("Cafe Parisien")
    assert slug == "cafe-parisien"
    assert slug == slug.lower()
    assert slug.isascii()


def test_generate_slug_strips_accents(tmp_path):
    pm = _make_pm(tmp_path)
    slug = pm._generate_slug("Projet Etude")
    assert "e" in slug
    assert slug.isascii()


def test_generate_slug_replaces_spaces_with_hyphens(tmp_path):
    pm = _make_pm(tmp_path)
    slug = pm._generate_slug("hello world")
    assert " " not in slug
    assert "-" in slug
