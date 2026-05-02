# -*- coding: utf-8-sig -*-
"""
project_loader.py - LCCA V10 / Mode Projets
Sprint PROJ-03 - Worker : chargement project.json + acquisition lock

Charge project.json, acquiert le lock, resout storage_mode.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from core.project_manager import ProjectManager, ProjectMeta
from core.project_lock import ProjectLock, ProjectAlreadyOpenError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ProjectNotFoundError(Exception):
    """Leve quand le projet demande est introuvable."""
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        super().__init__(f"Projet introuvable : '{project_id}'.")


# ---------------------------------------------------------------------------
# ProjectLoader
# ---------------------------------------------------------------------------

class ProjectLoader:
    """
    Worker PROJ-03 : charge project.json et acquiert le lock.

    Usage:
        loader = ProjectLoader(project_manager, lock)
        meta = loader.load("mon-projet")   # Leve ProjectNotFoundError ou ProjectAlreadyOpenError
    """

    def __init__(self, project_manager: ProjectManager, lock: ProjectLock) -> None:
        self._project_manager = project_manager
        self._lock = lock

    def load(self, project_id: str) -> ProjectMeta:
        """
        Charge project.json depuis le filesystem, acquiert le lock.

        Raises:
            ProjectNotFoundError       : projet absent du scan filesystem.
            ProjectAlreadyOpenError    : lock valide existant (autre instance).
        """
        meta = self._project_manager.get_project(project_id)
        if meta is None:
            raise ProjectNotFoundError(project_id)

        # Acquiert le lock — leve ProjectAlreadyOpenError si deja occupe
        self._lock.acquire(meta.slug)

        log.info("ProjectLoader.load : projet charge slug=%s id=%s", meta.slug, meta.id)
        return meta
