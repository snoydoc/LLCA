# -*- coding: utf-8-sig -*-
"""
project_context_assembler.py - LCCA V10 / Mode Projets
Sprint PROJ-03 - Worker : skills + specs + fenetre history + palace

Assemble le ProjectContext depuis le filesystem projet.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from core.project_manager import ProjectMeta

log = logging.getLogger(__name__)

# Import tardif MemPalaceClient pour eviter crash si chromadb absent
_PALACE_AVAILABLE = False
try:
    from core.mempalace_client import MemPalaceClient
    _PALACE_AVAILABLE = True
except Exception:
    MemPalaceClient = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Dataclass ProjectContext
# ---------------------------------------------------------------------------

try:
    from dataclasses import dataclass, field

    @dataclass
    class ProjectContext:
        """Contexte complet d'un projet charge en memoire."""
        meta: ProjectMeta
        skills: list
        specs: list
        history_window: list
        palace: object                  # MemPalaceClient ou None si chromadb absent
        user_prefix: str = ""           # Placeholder — peuple par PROJ-07
        snapshot: dict = field(default_factory=dict)

except Exception:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# Helper palace
# ---------------------------------------------------------------------------

def get_palace(project_id: str, storage_mode: str, legacy_namespaces: list) -> object:
    """
    Instancie MemPalaceClient selon storage_mode.
    Retourne None si chromadb absent (mode degrade silencieux).

    Args:
        project_id       : slug ou id du projet.
        storage_mode     : "shared" | "isolated".
        legacy_namespaces: ex. ["lcca_*"] pour projet legacy.
    """
    if not _PALACE_AVAILABLE:
        log.warning("get_palace : chromadb absent, palace = None (mode degrade)")
        return None

    try:
        from config import PALACE_DIR
        palace_path = str(PALACE_DIR)
    except ImportError:
        palace_path = "~/.mempalace/palace"

    try:
        return MemPalaceClient(palace_path=palace_path)
    except Exception as exc:
        log.warning("get_palace : impossible d'instancier MemPalaceClient : %s", exc)
        return None


# ---------------------------------------------------------------------------
# ProjectContextAssembler
# ---------------------------------------------------------------------------

class ProjectContextAssembler:
    """
    Worker PROJ-03 : assemble skills + specs + fenetre history + palace.

    Usage:
        assembler = ProjectContextAssembler(projects_dir)
        context = assembler.build(meta)
    """

    DEFAULT_MAX_HISTORY_TOKENS = 8000
    # Approximation 1 token ~ 4 chars
    CHARS_PER_TOKEN = 4

    def __init__(self, projects_dir: Optional[Path] = None) -> None:
        from pathlib import Path as _Path
        if projects_dir is None:
            _core = _Path(__file__).parent
            projects_dir = _core.parent / "projects"
        self._projects_dir = projects_dir

    def build(self, meta: ProjectMeta) -> "ProjectContext":
        """
        Construit un ProjectContext depuis le filesystem.
        """
        project_dir = self._projects_dir / meta.slug

        skills  = self._load_skills(project_dir)
        specs   = self._load_specs(project_dir)
        history = self._load_history(project_dir, meta)
        palace  = get_palace(meta.id, meta.storage_mode, meta.legacy_namespaces)

        return ProjectContext(
            meta=meta,
            skills=skills,
            specs=specs,
            history_window=history,
            palace=palace,
            user_prefix="",
            snapshot={},
        )

    # ------------------------------------------------------------------
    # Helpers prives
    # ------------------------------------------------------------------

    def _load_skills(self, project_dir: Path) -> list:
        """Lit tous les *.md dans projects/{slug}/skills/."""
        skills_dir = project_dir / "skills"
        if not skills_dir.exists():
            return []
        skills = []
        for md_file in sorted(skills_dir.glob("*.md")):
            try:
                skills.append(md_file.read_text(encoding="utf-8"))
            except OSError as exc:
                log.warning("_load_skills : impossible de lire %s : %s", md_file, exc)
        return skills

    def _load_specs(self, project_dir: Path) -> list:
        """Lit tous les *.json dans projects/{slug}/specs/."""
        specs_dir = project_dir / "specs"
        if not specs_dir.exists():
            return []
        specs = []
        for json_file in sorted(specs_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                specs.append(data)
            except Exception as exc:
                log.warning("_load_specs : impossible de lire %s : %s", json_file, exc)
        return specs

    def _load_history(self, project_dir: Path, meta: ProjectMeta) -> list:
        """
        Lit les N derniers messages de history.jsonl.
        Respecte max_history_tokens depuis meta.history.
        """
        history_file = project_dir / "history.jsonl"
        if not history_file.exists():
            return []

        max_tokens = meta.history.get("max_history_tokens", self.DEFAULT_MAX_HISTORY_TOKENS)
        max_chars  = max_tokens * self.CHARS_PER_TOKEN

        try:
            lines = history_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []

        # Lire en ordre inverse, accumuler jusqu'a la limite
        window: list[dict] = []
        total_chars = 0
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            entry_chars = len(json.dumps(entry))
            if total_chars + entry_chars > max_chars:
                break
            window.append(entry)
            total_chars += entry_chars

        window.reverse()
        return window
