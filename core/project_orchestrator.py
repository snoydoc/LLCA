# -*- coding: utf-8-sig -*-
"""
project_orchestrator.py - LCCA V10 / Mode Projets
Sprint PROJ-03 - Hierarchical Manager : coordonne chargement/sauvegarde projet

Coordonne : ProjectLoader -> ProjectContextAssembler -> ProjectCheckpoint.
save_project() release le lock dans un try/finally (meme si checkpoint.save() leve).
"""
from __future__ import annotations

import logging
from typing import Optional

from core.project_manager import ProjectManager
from core.project_lock import ProjectLock
from core.project_loader import ProjectLoader, ProjectNotFoundError
from core.project_context_assembler import ProjectContextAssembler, ProjectContext
from core.project_checkpoint import ProjectCheckpoint
from core.user_context import UserContextLoader
from core.user_context_injector import UserContextInjector
from core.user_context_learner import UserContextLearner

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ProjectOrchestrator
# ---------------------------------------------------------------------------

class ProjectOrchestrator:
    """
    Hierarchical Manager PROJ-03.

    Coordonne le chargement et la sauvegarde d'un projet LCCA V10.

    Usage:
        orch = ProjectOrchestrator(pm, lock, loader, assembler, checkpoint)
        context = orch.load_project("mon-projet")
        try:
            ...
        finally:
            orch.save_project(context)
    """

    def __init__(
        self,
        project_manager: ProjectManager,
        lock: ProjectLock,
        loader: ProjectLoader,
        assembler: ProjectContextAssembler,
        checkpoint: ProjectCheckpoint,
        user_context_loader: Optional[UserContextLoader] = None,
        user_context_injector: Optional[UserContextInjector] = None,
        user_context_learner: Optional[UserContextLearner] = None,
    ) -> None:
        self._project_manager = project_manager
        self._lock = lock
        self._loader = loader
        self._assembler = assembler
        self._checkpoint = checkpoint
        self._uc_loader   = user_context_loader   or UserContextLoader()
        self._uc_injector = user_context_injector or UserContextInjector()
        self._uc_learner  = user_context_learner  or UserContextLearner()

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def load_project(self, project_id: str) -> ProjectContext:
        """
        Pipeline de chargement :
          1. loader.load()       — lit project.json + acquiert lock
          2. assembler.build()   — skills + specs + history + palace
          3. checkpoint.restore()— lit context_snapshot.json
          4. UserContextInjector  — injecte user_prefix dans context

        Raises:
            ProjectNotFoundError     : projet inconnu.
            ProjectAlreadyOpenError  : lock occupe.
        """
        meta    = self._loader.load(project_id)
        context = self._assembler.build(meta)
        # PROJ-07 : charge le contexte utilisateur et injecte le bloc prompt
        try:
            uc_state = self._uc_loader.load()
        except Exception as exc:  # mode degrade silencieux
            log.warning("load_project : UserContext indisponible : %s", exc)
            uc_state = None
        self._uc_injector.inject_into_context(context, uc_state)
        self._checkpoint.restore(context)
        log.info("ProjectOrchestrator.load_project : projet ouvert id=%s", project_id)
        return context

    def save_project(self, context: ProjectContext, session_messages: Optional[list] = None) -> None:
        """
        Pipeline de sauvegarde :
          1. UserContextLearner  — detecte signaux session → WAL
          2. UserContextLoader   — compact si seuil atteint
          3. checkpoint.save()   — ecrit context_snapshot.json
          4. update_last_opened()— met a jour project.json
          5. lock.release()      — libere le lock (dans finally)

        Le lock est toujours release meme si une etape precedente leve.
        """
        # PROJ-08 : apprentissage fin de session
        try:
            if session_messages:
                uc_state = self._uc_loader.load()
                self._uc_learner.learn_from_session(uc_state, self._uc_loader, session_messages)
                if self._uc_loader.should_compact(uc_state):
                    self._uc_loader.compact(uc_state)
        except Exception as exc:
            log.warning("save_project : UserContext learn/compact silencieux : %s", exc)

        try:
            self._checkpoint.save(context)
            self._project_manager.update_last_opened(context.meta.id)
        finally:
            self._lock.release(context.meta.slug)
            log.info("ProjectOrchestrator.save_project : projet ferme slug=%s", context.meta.slug)
