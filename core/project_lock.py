# -*- coding: utf-8-sig -*-
"""
project_lock.py - LCCA V10 / Mode Projets
Sprint PROJ-02 - ProjectLock + Heartbeat TEMP

Empeche la corruption de history.jsonl sur ouverture simultanee.
Strategie : fichier .lock minimal dans le projet + payload heartbeat dans %TEMP%.
Le heartbeat ne s'ecrit que dans %TEMP% pour eviter les scans Windows Defender.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_CORE_DIR = Path(__file__).parent
_LCCA_ROOT = _CORE_DIR.parent


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ProjectAlreadyOpenError(Exception):
    """Leve quand on tente d'acquerir un lock deja valide."""
    def __init__(self, slug: str, instance_id: str, pid: int) -> None:
        self.slug = slug
        self.instance_id = instance_id
        self.pid = pid
        super().__init__(
            f"Projet '{slug}' deja ouvert par l'instance '{instance_id}' (PID {pid})."
        )


# ---------------------------------------------------------------------------
# ProjectLock
# ---------------------------------------------------------------------------

class ProjectLock:
    """
    Verrou de projet base sur fichier .lock + heartbeat dans %TEMP%.

    Utilisation:
        lock = ProjectLock(projects_dir)
        lock.acquire("mon-projet")
        try:
            ...
        finally:
            lock.release("mon-projet")
    """

    HEARTBEAT_INTERVAL: int = 30    # secondes entre chaque mise a jour heartbeat
    STALE_THRESHOLD: int = 60       # secondes sans heartbeat -> stale
    DAEMON_JOIN_TIMEOUT: float = 1.0  # timeout join() a la fermeture

    def __init__(self, projects_dir: Optional[Path] = None) -> None:
        self._projects_dir = projects_dir or (_LCCA_ROOT / "projects")
        self._temp_dir = Path(tempfile.gettempdir())
        # Suffixe unique par instance pour eviter collision sur meme PID (tests)
        self._instance_suffix = uuid.uuid4().hex[:8]
        # {slug: (thread, stop_event, temp_path)}
        self._active: dict[str, tuple[threading.Thread, threading.Event, Path]] = {}

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def acquire(self, slug: str) -> None:
        """
        Cree .lock dans projects/{slug}/.llca/ et payload dans %TEMP%.
        Lance le thread daemon heartbeat.
        Leve ProjectAlreadyOpenError si lock valide existant.
        """
        lock_path = self._lock_path(slug)

        # Verifier si un lock existe
        if lock_path.exists():
            if not self.is_stale(slug):
                # Lock valide — lire les infos pour l'erreur
                try:
                    lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
                    temp_path = Path(lock_data.get("temp_lock", ""))
                    payload = json.loads(temp_path.read_text(encoding="utf-8"))
                    raise ProjectAlreadyOpenError(
                        slug=slug,
                        instance_id=payload.get("instance_id", "inconnu"),
                        pid=payload.get("pid", 0),
                    )
                except ProjectAlreadyOpenError:
                    raise
                except Exception:
                    raise ProjectAlreadyOpenError(slug=slug, instance_id="inconnu", pid=0)
            else:
                # Lock stale — on le casse silencieusement
                self.break_stale_lock(slug)

        pid = os.getpid()
        temp_filename = f".llca_lock_{slug}_{pid}_{self._instance_suffix}.json"
        temp_path = self._temp_dir / temp_filename

        # Ecrire le payload heartbeat initial
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "pid": pid,
            "started_at": now_iso,
            "last_heartbeat": now_iso,
            "instance_id": self._instance_id(),
        }
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        # Ecrire le .lock (reference vers %TEMP%)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_data = {"temp_lock": str(temp_path)}
        lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

        # Lancer le thread daemon heartbeat
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(temp_path, stop_event),
            daemon=True,
            name=f"lcca-heartbeat-{slug}",
        )
        thread.start()
        self._active[slug] = (thread, stop_event, temp_path)
        log.info("ProjectLock.acquire : lock acquis slug=%s pid=%d", slug, pid)

    def release(self, slug: str) -> None:
        """
        Arrete le thread heartbeat (join timeout=1.0s).
        Supprime fichier %TEMP puis .lock.
        Ordre : heartbeat stop -> %TEMP -> .lock (.lock en dernier).
        No-op si le lock n'est pas actif.
        """
        if slug not in self._active:
            # release sans acquire prealable = no-op silencieux
            return

        thread, stop_event, temp_path = self._active.pop(slug)

        # 1. Arreter le daemon
        stop_event.set()
        thread.join(timeout=self.DAEMON_JOIN_TIMEOUT)

        # 2. Supprimer le fichier %TEMP
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError as exc:
            log.warning("ProjectLock.release : impossible de supprimer %s : %s", temp_path, exc)

        # 3. Supprimer le .lock (en dernier)
        lock_path = self._lock_path(slug)
        try:
            if lock_path.exists():
                lock_path.unlink()
        except OSError as exc:
            log.warning("ProjectLock.release : impossible de supprimer %s : %s", lock_path, exc)

        log.info("ProjectLock.release : lock libere slug=%s", slug)

    def is_stale(self, slug: str) -> bool:
        """
        Stale si : fichier %TEMP absent OU last_heartbeat > STALE_THRESHOLD OU PID invalide.
        """
        lock_path = self._lock_path(slug)
        if not lock_path.exists():
            return True

        try:
            lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
            temp_path = Path(lock_data.get("temp_lock", ""))
        except Exception:
            return True

        # Fichier %TEMP absent -> stale (crash scenario)
        if not temp_path.exists():
            return True

        try:
            payload = json.loads(temp_path.read_text(encoding="utf-8"))
        except Exception:
            return True

        # Heartbeat expire ?
        try:
            last_hb = datetime.fromisoformat(payload["last_heartbeat"])
            # Rendre timezone-aware si naive
            if last_hb.tzinfo is None:
                last_hb = last_hb.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            age = (now - last_hb).total_seconds()
            if age > self.STALE_THRESHOLD:
                return True
        except Exception:
            return True

        # PID valide ?
        pid = payload.get("pid", 0)
        if not self._verify_pid(pid):
            return True

        return False

    def break_stale_lock(self, slug: str) -> None:
        """Supprime .lock et fichier %TEMP si stale."""
        lock_path = self._lock_path(slug)
        if lock_path.exists():
            try:
                lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
                temp_path = Path(lock_data.get("temp_lock", ""))
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
            try:
                lock_path.unlink()
            except OSError as exc:
                log.warning("ProjectLock.break_stale_lock : %s", exc)
        log.info("ProjectLock.break_stale_lock : lock stale casse slug=%s", slug)

    # ------------------------------------------------------------------
    # Helpers prives
    # ------------------------------------------------------------------

    def _verify_pid(self, pid: int) -> bool:
        """
        Verifie si le PID existe.
        psutil si disponible, sinon os.kill(pid, 0), fallback True.
        """
        try:
            import psutil  # type: ignore
            if callable(getattr(psutil, "pid_exists", None)):
                return psutil.pid_exists(pid)
        except ImportError:
            pass

        # Fallback : os.kill(pid, 0)
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Le process existe mais appartient a un autre utilisateur
            return True
        except OSError:
            return False

    def _heartbeat_loop(self, temp_path: Path, stop_event: threading.Event) -> None:
        """Thread daemon - met a jour last_heartbeat toutes les HEARTBEAT_INTERVAL secondes."""
        while not stop_event.wait(timeout=self.HEARTBEAT_INTERVAL):
            try:
                if not temp_path.exists():
                    break
                payload = json.loads(temp_path.read_text(encoding="utf-8"))
                payload["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
                temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            except Exception as exc:
                log.warning("ProjectLock._heartbeat_loop : %s", exc)

    def _lock_path(self, slug: str) -> Path:
        return self._projects_dir / slug / ".llca" / ".lock"

    @staticmethod
    def _instance_id() -> str:
        """Identifiant de l'instance courante (hostname + pid).
        N'utilise pas socket.gethostname() pour eviter tout appel reseau.
        """
        hostname = (
            os.environ.get("COMPUTERNAME")
            or os.environ.get("HOSTNAME")
            or "unknown"
        )
        return f"{hostname}-{os.getpid()}"
