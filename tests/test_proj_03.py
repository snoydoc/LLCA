# -*- coding: utf-8 -*-
"""
test_proj_03.py - Tests PROJ-03 : ProjectOrchestrator + 4 Workers

Couvre :
- ProjectOrchestrator : load_project(), save_project() avec mocks
- ProjectLoader       : load() normal, not_found, lock occupe
- ProjectContextAssembler : skills, specs, history, history_window tokens
- ProjectCheckpoint   : restore, save (atomique), fichier absent
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from core.project_manager import ProjectManager, ProjectMeta
from core.project_lock import ProjectLock, ProjectAlreadyOpenError
from core.project_loader import ProjectLoader, ProjectNotFoundError
from core.project_context_assembler import (
    ProjectContextAssembler,
    ProjectContext,
    get_palace,
)
from core.project_checkpoint import ProjectCheckpoint
from core.project_orchestrator import ProjectOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_meta(
    slug: str = "test-proj",
    project_id: str = None,
    storage_mode: str = "shared",
    max_history_tokens: int = 8000,
) -> ProjectMeta:
    """Cree un ProjectMeta minimal pour les tests."""
    return ProjectMeta(
        id=project_id or str(uuid.uuid4()),
        slug=slug,
        name="Test Project",
        description="",
        created_at=datetime.now(timezone.utc).isoformat(),
        last_opened=datetime.now(timezone.utc).isoformat(),
        status="active",
        tags=[],
        model_override=None,
        storage_mode=storage_mode,
        legacy_namespaces=[],
        history={"max_history_tokens": max_history_tokens},
        stats={},
        migrated_from_v9=False,
    )


def _seed_project(tmp_path: Path, slug: str) -> Path:
    """Cree la structure minimale d'un projet dans tmp_path/projects/{slug}/."""
    project_dir = tmp_path / "projects" / slug
    llca_dir = project_dir / ".llca"
    llca_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "history.jsonl").write_text("", encoding="utf-8")
    (project_dir / "skills").mkdir(exist_ok=True)
    (project_dir / "specs").mkdir(exist_ok=True)
    return project_dir


def _make_mock_lock() -> MagicMock:
    """Cree un mock ProjectLock avec _verify_pid neutralise."""
    lock = MagicMock(spec=ProjectLock)
    return lock


# ---------------------------------------------------------------------------
# ProjectOrchestrator
# ---------------------------------------------------------------------------

def test_load_project_calls_loader():
    """load_project() appelle loader.load(project_id)."""
    meta = _make_meta()
    loader = MagicMock()
    loader.load.return_value = meta
    assembler = MagicMock()
    assembler.build.return_value = ProjectContext(
        meta=meta, skills=[], specs=[], history_window=[],
        palace=None, user_prefix="", snapshot={},
    )
    checkpoint = MagicMock()
    orch = ProjectOrchestrator(MagicMock(), MagicMock(), loader, assembler, checkpoint)

    orch.load_project("test-proj")

    loader.load.assert_called_once_with("test-proj")


def test_load_project_calls_assembler():
    """load_project() appelle assembler.build(meta)."""
    meta = _make_meta()
    loader = MagicMock()
    loader.load.return_value = meta
    assembler = MagicMock()
    assembler.build.return_value = ProjectContext(
        meta=meta, skills=[], specs=[], history_window=[],
        palace=None, user_prefix="", snapshot={},
    )
    checkpoint = MagicMock()
    orch = ProjectOrchestrator(MagicMock(), MagicMock(), loader, assembler, checkpoint)

    orch.load_project("test-proj")

    assembler.build.assert_called_once_with(meta)


def test_load_project_calls_checkpoint_restore():
    """load_project() appelle checkpoint.restore(context)."""
    meta = _make_meta()
    context = ProjectContext(
        meta=meta, skills=[], specs=[], history_window=[],
        palace=None, user_prefix="", snapshot={},
    )
    loader = MagicMock()
    loader.load.return_value = meta
    assembler = MagicMock()
    assembler.build.return_value = context
    checkpoint = MagicMock()
    orch = ProjectOrchestrator(MagicMock(), MagicMock(), loader, assembler, checkpoint)

    orch.load_project("test-proj")

    checkpoint.restore.assert_called_once_with(context)


def test_load_project_returns_project_context():
    """load_project() retourne un ProjectContext avec user_prefix=''."""
    meta = _make_meta()
    context = ProjectContext(
        meta=meta, skills=[], specs=[], history_window=[],
        palace=None, user_prefix="ignored", snapshot={},
    )
    loader = MagicMock()
    loader.load.return_value = meta
    assembler = MagicMock()
    assembler.build.return_value = context
    checkpoint = MagicMock()
    orch = ProjectOrchestrator(MagicMock(), MagicMock(), loader, assembler, checkpoint)

    result = orch.load_project("test-proj")

    assert isinstance(result, ProjectContext)
    assert result.user_prefix == ""   # Placeholder force par l'orchestrateur


def test_save_project_calls_checkpoint_save():
    """save_project() appelle checkpoint.save(context)."""
    meta = _make_meta()
    context = ProjectContext(
        meta=meta, skills=[], specs=[], history_window=[],
        palace=None, user_prefix="", snapshot={},
    )
    pm = MagicMock()
    lock = _make_mock_lock()
    checkpoint = MagicMock()
    orch = ProjectOrchestrator(pm, lock, MagicMock(), MagicMock(), checkpoint)

    orch.save_project(context)

    checkpoint.save.assert_called_once_with(context)


def test_save_project_releases_lock():
    """save_project() release le lock dans le finally."""
    meta = _make_meta(slug="proj-save")
    context = ProjectContext(
        meta=meta, skills=[], specs=[], history_window=[],
        palace=None, user_prefix="", snapshot={},
    )
    pm = MagicMock()
    lock = _make_mock_lock()
    checkpoint = MagicMock()
    orch = ProjectOrchestrator(pm, lock, MagicMock(), MagicMock(), checkpoint)

    orch.save_project(context)

    lock.release.assert_called_once_with("proj-save")


def test_save_project_releases_lock_even_if_checkpoint_raises():
    """save_project() release le lock meme si checkpoint.save() leve."""
    meta = _make_meta(slug="proj-crash")
    context = ProjectContext(
        meta=meta, skills=[], specs=[], history_window=[],
        palace=None, user_prefix="", snapshot={},
    )
    lock = _make_mock_lock()
    checkpoint = MagicMock()
    checkpoint.save.side_effect = RuntimeError("disk full")
    orch = ProjectOrchestrator(MagicMock(), lock, MagicMock(), MagicMock(), checkpoint)

    with pytest.raises(RuntimeError):
        orch.save_project(context)

    lock.release.assert_called_once_with("proj-crash")


# ---------------------------------------------------------------------------
# ProjectLoader
# ---------------------------------------------------------------------------

def test_loader_raises_if_project_not_found(tmp_path):
    """load() leve ProjectNotFoundError si le projet est inconnu."""
    pm = ProjectManager(lcca_root=tmp_path)
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    lock = _make_mock_lock()
    loader = ProjectLoader(pm, lock)

    with pytest.raises(ProjectNotFoundError):
        loader.load("inexistant")


def test_loader_acquires_lock(tmp_path):
    """load() appelle lock.acquire(slug) apres avoir trouve le meta."""
    _seed_project(tmp_path, "mon-projet")
    pm = ProjectManager(lcca_root=tmp_path)
    meta = _make_meta(slug="mon-projet")
    # Ecrire project.json pour que get_project() le trouve
    pj = tmp_path / "projects" / "mon-projet" / ".llca" / "project.json"
    pj.write_text(json.dumps(meta.to_dict()), encoding="utf-8")

    lock = _make_mock_lock()
    loader = ProjectLoader(pm, lock)

    result = loader.load("mon-projet")

    lock.acquire.assert_called_once_with("mon-projet")
    assert result.slug == "mon-projet"


def test_loader_raises_if_lock_occupied(tmp_path):
    """load() propage ProjectAlreadyOpenError si lock.acquire() leve."""
    _seed_project(tmp_path, "proj-locked")
    pm = ProjectManager(lcca_root=tmp_path)
    meta = _make_meta(slug="proj-locked")
    pj = tmp_path / "projects" / "proj-locked" / ".llca" / "project.json"
    pj.write_text(json.dumps(meta.to_dict()), encoding="utf-8")

    lock = _make_mock_lock()
    lock.acquire.side_effect = ProjectAlreadyOpenError("proj-locked", "other", 9999)
    loader = ProjectLoader(pm, lock)

    with pytest.raises(ProjectAlreadyOpenError):
        loader.load("proj-locked")


# ---------------------------------------------------------------------------
# ProjectContextAssembler
# ---------------------------------------------------------------------------

def test_assembler_loads_skills_from_skills_dir(tmp_path):
    """build() charge les fichiers *.md du dossier skills/."""
    project_dir = _seed_project(tmp_path, "proj-skills")
    (project_dir / "skills" / "skill_a.md").write_text("# Skill A", encoding="utf-8")
    (project_dir / "skills" / "skill_b.md").write_text("# Skill B", encoding="utf-8")

    meta = _make_meta(slug="proj-skills")
    assembler = ProjectContextAssembler(projects_dir=tmp_path / "projects")

    with patch("core.project_context_assembler.get_palace", return_value=None):
        ctx = assembler.build(meta)

    assert len(ctx.skills) == 2
    assert "# Skill A" in ctx.skills


def test_assembler_empty_skills_dir_returns_empty_list(tmp_path):
    """build() retourne [] si skills/ est vide."""
    _seed_project(tmp_path, "proj-noskill")
    meta = _make_meta(slug="proj-noskill")
    assembler = ProjectContextAssembler(projects_dir=tmp_path / "projects")

    with patch("core.project_context_assembler.get_palace", return_value=None):
        ctx = assembler.build(meta)

    assert ctx.skills == []


def test_assembler_loads_specs_from_specs_dir(tmp_path):
    """build() charge les fichiers *.json du dossier specs/."""
    project_dir = _seed_project(tmp_path, "proj-specs")
    spec_data = {"id": "spec-001", "title": "Test Spec"}
    (project_dir / "specs" / "spec_001.json").write_text(
        json.dumps(spec_data), encoding="utf-8"
    )

    meta = _make_meta(slug="proj-specs")
    assembler = ProjectContextAssembler(projects_dir=tmp_path / "projects")

    with patch("core.project_context_assembler.get_palace", return_value=None):
        ctx = assembler.build(meta)

    assert len(ctx.specs) == 1
    assert ctx.specs[0]["id"] == "spec-001"


def test_assembler_loads_history_window(tmp_path):
    """build() charge les entrees de history.jsonl."""
    project_dir = _seed_project(tmp_path, "proj-hist")
    entries = [
        {"role": "user", "content": "Bonjour"},
        {"role": "assistant", "content": "Salut"},
    ]
    lines = "\n".join(json.dumps(e) for e in entries)
    (project_dir / "history.jsonl").write_text(lines, encoding="utf-8")

    meta = _make_meta(slug="proj-hist")
    assembler = ProjectContextAssembler(projects_dir=tmp_path / "projects")

    with patch("core.project_context_assembler.get_palace", return_value=None):
        ctx = assembler.build(meta)

    assert len(ctx.history_window) == 2
    assert ctx.history_window[0]["role"] == "user"


def test_assembler_history_window_respects_max_tokens(tmp_path):
    """build() tronque history.jsonl pour respecter max_history_tokens."""
    project_dir = _seed_project(tmp_path, "proj-trunc")
    # Creer 20 entrees avec du contenu suffisamment grand
    entries = [{"role": "user", "content": "x" * 200} for _ in range(20)]
    lines = "\n".join(json.dumps(e) for e in entries)
    (project_dir / "history.jsonl").write_text(lines, encoding="utf-8")

    # max_history_tokens tres bas (500 tokens = 2000 chars)
    meta = _make_meta(slug="proj-trunc", max_history_tokens=500)
    assembler = ProjectContextAssembler(projects_dir=tmp_path / "projects")

    with patch("core.project_context_assembler.get_palace", return_value=None):
        ctx = assembler.build(meta)

    # Moins de 20 entrees (tronque)
    assert len(ctx.history_window) < 20


def test_assembler_calls_get_palace_with_correct_args(tmp_path):
    """build() appelle get_palace avec id, storage_mode, legacy_namespaces."""
    _seed_project(tmp_path, "proj-palace")
    meta = _make_meta(slug="proj-palace", storage_mode="isolated")
    meta.legacy_namespaces = ["lcca_*"]
    assembler = ProjectContextAssembler(projects_dir=tmp_path / "projects")

    with patch("core.project_context_assembler.get_palace", return_value=None) as mock_gp:
        assembler.build(meta)

    mock_gp.assert_called_once_with(meta.id, "isolated", ["lcca_*"])


# ---------------------------------------------------------------------------
# ProjectCheckpoint
# ---------------------------------------------------------------------------

def test_checkpoint_restore_reads_snapshot(tmp_path):
    """restore() injecte le contenu de context_snapshot.json dans context.snapshot."""
    project_dir = _seed_project(tmp_path, "proj-ckpt")
    snapshot_data = {"last_intent": "refacto planner"}
    snap_path = project_dir / ".llca" / "context_snapshot.json"
    snap_path.write_text(json.dumps(snapshot_data), encoding="utf-8")

    meta = _make_meta(slug="proj-ckpt")
    ctx = ProjectContext(
        meta=meta, skills=[], specs=[], history_window=[],
        palace=None, user_prefix="", snapshot={},
    )
    ckpt = ProjectCheckpoint(projects_dir=tmp_path / "projects")
    ckpt.restore(ctx)

    assert ctx.snapshot == snapshot_data


def test_checkpoint_restore_no_file_returns_empty_dict(tmp_path):
    """restore() laisse context.snapshot = {} si le fichier est absent."""
    _seed_project(tmp_path, "proj-nosnap")
    meta = _make_meta(slug="proj-nosnap")
    ctx = ProjectContext(
        meta=meta, skills=[], specs=[], history_window=[],
        palace=None, user_prefix="", snapshot={},
    )
    ckpt = ProjectCheckpoint(projects_dir=tmp_path / "projects")
    ckpt.restore(ctx)

    assert ctx.snapshot == {}


def test_checkpoint_save_writes_snapshot(tmp_path):
    """save() ecrit context.snapshot dans context_snapshot.json."""
    _seed_project(tmp_path, "proj-save-ckpt")
    meta = _make_meta(slug="proj-save-ckpt")
    snap = {"key": "value", "count": 42}
    ctx = ProjectContext(
        meta=meta, skills=[], specs=[], history_window=[],
        palace=None, user_prefix="", snapshot=snap,
    )
    ckpt = ProjectCheckpoint(projects_dir=tmp_path / "projects")
    ckpt.save(ctx)

    snap_path = tmp_path / "projects" / "proj-save-ckpt" / ".llca" / "context_snapshot.json"
    assert snap_path.exists()
    loaded = json.loads(snap_path.read_text(encoding="utf-8"))
    assert loaded == snap
