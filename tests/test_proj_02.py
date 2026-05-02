# -*- coding: utf-8 -*-
"""
test_proj_02.py - Tests PROJ-02 : ProjectLock

Couvre :
- acquire() : creation .lock + fichier %TEMP, lancement heartbeat
- release() : suppression .lock + %TEMP, join thread
- is_stale() : %TEMP absent, heartbeat expire, PID mort, lock recent
- break_stale_lock() : suppression des fichiers stale
- heartbeat_loop() : mise a jour last_heartbeat
- ProjectAlreadyOpenError : levee si lock valide existant
- release sans acquire prealable : no-op
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.project_lock import ProjectAlreadyOpenError, ProjectLock


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_lock(tmp_path: Path) -> ProjectLock:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    lock = ProjectLock(projects_dir=projects_dir)
    # Rediriger les fichiers %TEMP vers tmp_path pour l'isolation
    lock._temp_dir = tmp_path / "temp"
    lock._temp_dir.mkdir(exist_ok=True)
    # Eviter tout appel psutil/os.kill dans les tests (bloque sur Windows)
    # Les tests qui veulent tester PID mort patchent explicitement return_value=False
    lock._verify_pid = lambda pid: True  # type: ignore[method-assign]
    return lock


def _seed_project_dir(tmp_path: Path, slug: str) -> Path:
    """Cree la structure minimale projects/{slug}/.llca/ pour les tests."""
    llca = tmp_path / "projects" / slug / ".llca"
    llca.mkdir(parents=True, exist_ok=True)
    return llca


# ---------------------------------------------------------------------------
# acquire()
# ---------------------------------------------------------------------------

def test_acquire_creates_lock_file(tmp_path):
    lock = _make_lock(tmp_path)
    _seed_project_dir(tmp_path, "proj-a")
    lock.acquire("proj-a")
    try:
        assert (tmp_path / "projects" / "proj-a" / ".llca" / ".lock").exists()
    finally:
        lock.release("proj-a")


def test_acquire_creates_temp_payload(tmp_path):
    lock = _make_lock(tmp_path)
    _seed_project_dir(tmp_path, "proj-b")
    lock.acquire("proj-b")
    try:
        # Lire le .lock pour trouver le fichier temp
        lock_data = json.loads(
            (tmp_path / "projects" / "proj-b" / ".llca" / ".lock")
            .read_text(encoding="utf-8")
        )
        temp_path = Path(lock_data["temp_lock"])
        assert temp_path.exists()
        payload = json.loads(temp_path.read_text(encoding="utf-8"))
        assert "pid" in payload
        assert "last_heartbeat" in payload
        assert "instance_id" in payload
    finally:
        lock.release("proj-b")


def test_acquire_raises_if_lock_exists_and_valid(tmp_path):
    """Deux acquire() sur le meme slug levent ProjectAlreadyOpenError."""
    lock1 = _make_lock(tmp_path)
    lock2 = _make_lock(tmp_path)
    lock2._temp_dir = lock1._temp_dir  # Meme dossier temp
    _seed_project_dir(tmp_path, "proj-c")

    lock1.acquire("proj-c")
    try:
        with pytest.raises(ProjectAlreadyOpenError):
            lock2.acquire("proj-c")
    finally:
        lock1.release("proj-c")


def test_acquire_raises_project_already_open_error(tmp_path):
    """ProjectAlreadyOpenError contient le slug."""
    lock1 = _make_lock(tmp_path)
    lock2 = _make_lock(tmp_path)
    lock2._temp_dir = lock1._temp_dir
    _seed_project_dir(tmp_path, "proj-err")

    lock1.acquire("proj-err")
    try:
        with pytest.raises(ProjectAlreadyOpenError) as exc_info:
            lock2.acquire("proj-err")
        assert "proj-err" in str(exc_info.value)
    finally:
        lock1.release("proj-err")


# ---------------------------------------------------------------------------
# release()
# ---------------------------------------------------------------------------

def test_release_removes_lock_file(tmp_path):
    lock = _make_lock(tmp_path)
    _seed_project_dir(tmp_path, "proj-rel")
    lock.acquire("proj-rel")
    lock.release("proj-rel")
    assert not (tmp_path / "projects" / "proj-rel" / ".llca" / ".lock").exists()


def test_release_removes_temp_file(tmp_path):
    lock = _make_lock(tmp_path)
    _seed_project_dir(tmp_path, "proj-rel2")
    lock.acquire("proj-rel2")

    # Sauvegarder le chemin temp avant release
    lock_data = json.loads(
        (tmp_path / "projects" / "proj-rel2" / ".llca" / ".lock")
        .read_text(encoding="utf-8")
    )
    temp_path = Path(lock_data["temp_lock"])

    lock.release("proj-rel2")
    assert not temp_path.exists()


def test_release_joins_heartbeat_thread(tmp_path):
    """release() join le thread daemon sans bloquer indefiniment."""
    lock = _make_lock(tmp_path)
    _seed_project_dir(tmp_path, "proj-join")
    lock.acquire("proj-join")

    thread = lock._active.get("proj-join", (None,))[0]
    assert thread is not None
    assert thread.is_alive()

    lock.release("proj-join")
    # Apres release, le thread doit etre termine (ou en cours de terminaison)
    thread.join(timeout=2.0)
    assert not thread.is_alive()


def test_release_on_unacquired_lock_is_noop(tmp_path):
    """release() sans acquire() prealable ne leve pas d'exception."""
    lock = _make_lock(tmp_path)
    lock.release("inexistant")  # Doit passer sans erreur


# ---------------------------------------------------------------------------
# is_stale()
# ---------------------------------------------------------------------------

def test_is_stale_true_when_temp_file_absent(tmp_path):
    """Stale si le fichier .lock existe mais %TEMP est absent (simulation crash)."""
    lock = _make_lock(tmp_path)
    _seed_project_dir(tmp_path, "proj-stale1")
    lock.acquire("proj-stale1")

    # Supprimer le fichier %TEMP (simulation crash)
    _, _, temp_path = lock._active["proj-stale1"]
    temp_path.unlink()

    assert lock.is_stale("proj-stale1") is True

    # Cleanup manuel (temp deja supprime)
    lock._active.pop("proj-stale1")[0]  # retirer sans release


def test_is_stale_true_when_heartbeat_expired(tmp_path):
    """Stale si last_heartbeat depasse STALE_THRESHOLD."""
    lock = _make_lock(tmp_path)
    _seed_project_dir(tmp_path, "proj-stale2")
    lock.acquire("proj-stale2")

    # Patcher le last_heartbeat dans le fichier temp pour le rendre expire
    _, _, temp_path = lock._active["proj-stale2"]
    payload = json.loads(temp_path.read_text(encoding="utf-8"))
    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    payload["last_heartbeat"] = old_ts
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    assert lock.is_stale("proj-stale2") is True
    lock.release("proj-stale2")


def test_is_stale_false_when_heartbeat_recent(tmp_path):
    """Non stale si heartbeat recent et PID actif (verify_pid mocke via _make_lock)."""
    lock = _make_lock(tmp_path)
    _seed_project_dir(tmp_path, "proj-fresh")
    lock.acquire("proj-fresh")
    try:
        # _verify_pid est mocke True dans _make_lock — pas d'appel psutil/os.kill
        assert lock.is_stale("proj-fresh") is False
    finally:
        lock.release("proj-fresh")


def test_is_stale_true_when_pid_dead(tmp_path):
    """Stale si le PID dans le payload est mort (override du mock _make_lock)."""
    lock = _make_lock(tmp_path)
    _seed_project_dir(tmp_path, "proj-deadpid")
    lock.acquire("proj-deadpid")

    # Override : simuler PID mort
    lock._verify_pid = lambda pid: False  # type: ignore[method-assign]
    assert lock.is_stale("proj-deadpid") is True

    lock.release("proj-deadpid")


# ---------------------------------------------------------------------------
# break_stale_lock()
# ---------------------------------------------------------------------------

def test_break_stale_lock_removes_files(tmp_path):
    """break_stale_lock() supprime .lock et fichier %TEMP."""
    lock = _make_lock(tmp_path)
    _seed_project_dir(tmp_path, "proj-break")
    lock.acquire("proj-break")

    # Recuperer les chemins avant break
    lock_path = tmp_path / "projects" / "proj-break" / ".llca" / ".lock"
    lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
    temp_path = Path(lock_data["temp_lock"])

    # Stopper le heartbeat proprement mais laisser les fichiers en place
    _, stop_event, _ = lock._active.pop("proj-break")
    stop_event.set()

    lock.break_stale_lock("proj-break")

    assert not lock_path.exists()
    assert not temp_path.exists()


# ---------------------------------------------------------------------------
# heartbeat_loop()
# ---------------------------------------------------------------------------

def test_heartbeat_updates_last_heartbeat(tmp_path):
    """Le heartbeat met a jour last_heartbeat dans le fichier %TEMP."""
    lock = _make_lock(tmp_path)
    # Reduire l'intervalle pour le test
    lock.HEARTBEAT_INTERVAL = 0.05

    _seed_project_dir(tmp_path, "proj-hb")
    lock.acquire("proj-hb")

    _, _, temp_path = lock._active["proj-hb"]
    payload_before = json.loads(temp_path.read_text(encoding="utf-8"))
    ts_before = payload_before["last_heartbeat"]

    # Attendre que le heartbeat se declenche
    time.sleep(0.2)

    payload_after = json.loads(temp_path.read_text(encoding="utf-8"))
    ts_after = payload_after["last_heartbeat"]

    lock.release("proj-hb")
    assert ts_after != ts_before
