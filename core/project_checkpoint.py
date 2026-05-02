# -*- coding: utf-8-sig -*-
"""
project_checkpoint.py - LCCA V10 / Mode Projets
Sprint PROJ-03 - Worker : sauvegarde et restauration context_snapshot.json

Ecriture atomique via fichier .tmp (regle T-14 : Path.replace() sur Windows).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ProjectCheckpoint
# ---------------------------------------------------------------------------

class ProjectCheckpoint:
    """
    Worker PROJ-03 : sauvegarde et restauration context_snapshot.json.

    Chemin : projects/{slug}/.llca/context_snapshot.json

    Usage:
        ckpt = ProjectCheckpoint(projects_dir)
        ckpt.restore(context)   # lit le snapshot dans context.snapshot
        ckpt.save(context)      # ecrit context.snapshot sur disque (atomique)
    """

    SNAPSHOT_FILENAME = "context_snapshot.json"

    def __init__(self, projects_dir: Optional[Path] = None) -> None:
        if projects_dir is None:
            _core = Path(__file__).parent
            projects_dir = _core.parent / "projects"
        self._projects_dir = projects_dir

    def restore(self, context: object) -> None:
        """
        Lit projects/{slug}/.llca/context_snapshot.json et injecte dans context.snapshot.
        Si le fichier est absent ou invalide : context.snapshot reste {} (mode degrade silencieux).
        """
        snapshot_path = self._snapshot_path(context.meta.slug)  # type: ignore[attr-defined]
        if not snapshot_path.exists():
            log.debug("ProjectCheckpoint.restore : pas de snapshot pour slug=%s", context.meta.slug)  # type: ignore[attr-defined]
            return

        try:
            data = json.loads(snapshot_path.read_text(encoding="utf-8"))
            context.snapshot = data  # type: ignore[attr-defined]
            log.info("ProjectCheckpoint.restore : snapshot restaure slug=%s", context.meta.slug)  # type: ignore[attr-defined]
        except Exception as exc:
            log.warning("ProjectCheckpoint.restore : echec lecture snapshot %s : %s", snapshot_path, exc)
            context.snapshot = {}  # type: ignore[attr-defined]

    def save(self, context: object) -> None:
        """
        Ecrit context.snapshot dans projects/{slug}/.llca/context_snapshot.json.
        Ecriture atomique : .tmp -> Path.replace() (T-14, safe Windows + Linux).
        """
        snapshot_path = self._snapshot_path(context.meta.slug)  # type: ignore[attr-defined]
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)

        data = getattr(context, "snapshot", {})
        tmp_path = snapshot_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(snapshot_path)
            log.info("ProjectCheckpoint.save : snapshot sauvegarde slug=%s", context.meta.slug)  # type: ignore[attr-defined]
        except Exception as exc:
            log.warning("ProjectCheckpoint.save : echec ecriture snapshot %s : %s", snapshot_path, exc)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise

    # ------------------------------------------------------------------
    # Helper prive
    # ------------------------------------------------------------------

    def _snapshot_path(self, slug: str) -> Path:
        return self._projects_dir / slug / ".llca" / self.SNAPSHOT_FILENAME
