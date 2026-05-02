# -*- coding: utf-8-sig -*-
"""
project_manager.py - LCCA V10 / Mode Projets
Sprint PROJ-01 - ProjectManager + Scan Filesystem

CRUD projets. Source de verite : scan projects/*/.llca/project.json.
index.cache.json = cache performance uniquement (reconstruit au boot, < 50 ms).
Ne jamais lire index.cache.json comme source de verite.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_CORE_DIR = Path(__file__).parent
_LCCA_ROOT = _CORE_DIR.parent


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class ProjectMeta:
    """Metadonnees d'un projet LCCA V10."""
    id: str
    slug: str
    name: str
    description: str
    created_at: str
    last_opened: str
    status: str                      # active | archived | paused
    tags: list[str]
    model_override: Optional[str]
    storage_mode: str                # shared | isolated
    legacy_namespaces: list[str]     # [] normaux, ["lcca_*"] pour legacy
    history: dict
    stats: dict
    migrated_from_v9: bool

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "last_opened": self.last_opened,
            "status": self.status,
            "tags": self.tags,
            "model_override": self.model_override,
            "storage_mode": self.storage_mode,
            "legacy_namespaces": self.legacy_namespaces,
            "history": self.history,
            "stats": self.stats,
            "migrated_from_v9": self.migrated_from_v9,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectMeta":
        return cls(
            id=data["id"],
            slug=data["slug"],
            name=data["name"],
            description=data.get("description", ""),
            created_at=data["created_at"],
            last_opened=data.get("last_opened", data["created_at"]),
            status=data.get("status", "active"),
            tags=data.get("tags", []),
            model_override=data.get("model_override"),
            storage_mode=data.get("storage_mode", "shared"),
            legacy_namespaces=data.get("legacy_namespaces", []),
            history=data.get("history", {}),
            stats=data.get("stats", {}),
            migrated_from_v9=data.get("migrated_from_v9", False),
        )


# ---------------------------------------------------------------------------
# ProjectManager
# ---------------------------------------------------------------------------

class ProjectManager:
    """
    CRUD projets LCCA V10.

    Source de verite : scan filesystem projects/*/.llca/project.json
    index.cache.json = cache performance uniquement.

    Usage:
        pm = ProjectManager()
        projects = pm.list_projects()
        new_proj = pm.create_project("Mon Projet")
    """

    def __init__(self, lcca_root: Optional[Path] = None) -> None:
        self._root = Path(lcca_root) if lcca_root else _LCCA_ROOT
        self._projects_dir = self._root / "projects"

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def list_projects(self, include_archived: bool = False) -> list[ProjectMeta]:
        """
        Scanne projects/*/.llca/project.json (source de verite).
        Reconstruit index.cache.json. Retourne trie par last_opened desc.
        """
        if not self._projects_dir.exists():
            return []

        projects: list[ProjectMeta] = []
        for project_json in self._projects_dir.glob("*/.llca/project.json"):
            meta = self._parse_meta(project_json)
            if meta is None:
                continue
            if not include_archived and meta.status == "archived":
                continue
            projects.append(meta)

        # Trier par last_opened decroissant
        projects.sort(key=lambda p: p.last_opened, reverse=True)

        # Reconstruire le cache
        self._rebuild_cache(projects)

        return projects

    def get_project(self, project_id: str) -> Optional[ProjectMeta]:
        """Lookup par id ou slug depuis le scan filesystem."""
        for meta in self.list_projects(include_archived=True):
            if meta.id == project_id or meta.slug == project_id:
                return meta
        return None

    def create_project(
        self,
        name: str,
        description: str = "",
        storage_mode: str = "shared",
        tags: Optional[list[str]] = None,
        target_dir: Optional[str] = None,
    ) -> ProjectMeta:
        """
        Cree la structure projects/{slug}/.llca/project.json.
        Initialise history.jsonl vide, skills/, specs/, history_archive/.
        Met a jour index.cache.json.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        project_id = str(uuid.uuid4())
        slug = self._generate_slug(name)

        if target_dir:
            project_dir = self._projects_dir / target_dir
        else:
            project_dir = self._projects_dir / slug

        llca_dir = project_dir / ".llca"
        llca_dir.mkdir(parents=True, exist_ok=True)

        meta = ProjectMeta(
            id=project_id,
            slug=slug,
            name=name,
            description=description,
            created_at=now_iso,
            last_opened=now_iso,
            status="active",
            tags=tags or [],
            model_override=None,
            storage_mode=storage_mode,
            legacy_namespaces=[],
            history={
                "compaction_threshold_mb": 10,
                "compression_strategy": "sliding_window",
                "max_history_tokens": 8000,
            },
            stats={
                "total_sessions": 0,
                "total_tokens_spent": 0,
                "skills_generated": 0,
                "specs_validated": 0,
                "last_healthcheck": None,
                "issues_count": 0,
            },
            migrated_from_v9=False,
        )

        self._write_json(llca_dir / "project.json", meta.to_dict())
        self._write_json(llca_dir / "context_snapshot.json", {})

        # Fichiers/dossiers requis
        (project_dir / "history.jsonl").write_text("", encoding="utf-8")
        (project_dir / "history_archive").mkdir(exist_ok=True)
        (project_dir / "skills").mkdir(exist_ok=True)
        (project_dir / "specs").mkdir(exist_ok=True)

        # Mettre a jour le cache
        all_projects = self.list_projects(include_archived=True)
        self._rebuild_cache(all_projects)

        log.info("ProjectManager : projet cree slug=%s id=%s", slug, project_id)
        return meta

    def archive_project(self, project_id: str) -> bool:
        """status: active -> archived. Met a jour project.json et le cache."""
        meta = self.get_project(project_id)
        if meta is None:
            return False

        project_json_path = self._projects_dir / meta.slug / ".llca" / "project.json"
        if not project_json_path.exists():
            return False

        meta.status = "archived"
        self._write_json(project_json_path, meta.to_dict())

        all_projects = self.list_projects(include_archived=True)
        self._rebuild_cache(all_projects)

        log.info("ProjectManager : projet archive slug=%s", meta.slug)
        return True

    def update_last_opened(self, project_id: str) -> None:
        """Met a jour last_opened dans project.json (appele a chaque project_open MCP)."""
        meta = self.get_project(project_id)
        if meta is None:
            log.warning("ProjectManager.update_last_opened : projet introuvable id=%s", project_id)
            return

        project_json_path = self._projects_dir / meta.slug / ".llca" / "project.json"
        if not project_json_path.exists():
            return

        meta.last_opened = datetime.now(timezone.utc).isoformat()
        self._write_json(project_json_path, meta.to_dict())

    # ------------------------------------------------------------------
    # Helpers prives
    # ------------------------------------------------------------------

    def _rebuild_cache(self, projects: list[ProjectMeta]) -> None:
        """Ecrit index.cache.json depuis la liste en memoire."""
        global_llca = self._projects_dir / ".llca"
        global_llca.mkdir(parents=True, exist_ok=True)

        cache_data = {
            "version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "projects": [
                {
                    "id": p.id,
                    "slug": p.slug,
                    "name": p.name,
                    "status": p.status,
                    "last_opened": p.last_opened,
                }
                for p in projects
            ],
        }
        self._write_json(global_llca / "index.cache.json", cache_data)

    def _parse_meta(self, path: Path) -> Optional[ProjectMeta]:
        """Parse un project.json. Retourne None si invalide (log warning)."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ProjectMeta.from_dict(data)
        except Exception as exc:
            log.warning("ProjectManager : project.json invalide %s : %s", path, exc)
            return None

    def _generate_slug(self, name: str) -> str:
        """
        ASCII lowercase, tirets, unique dans projects/.
        Ex: 'Mon Projet 2' -> 'mon-projet-2'
            'Cafe Parisien' -> 'cafe-parisien'
        """
        # Normaliser les accents (NFD -> retire les diacritiques)
        normalized = unicodedata.normalize("NFD", name)
        ascii_name = normalized.encode("ascii", "ignore").decode("ascii")

        # Lowercase, remplace non-alphanum par tiret
        slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")

        if not slug:
            slug = "projet"

        # Unicite dans projects/
        base = slug
        counter = 1
        while (self._projects_dir / slug).exists():
            slug = f"{base}-{counter}"
            counter += 1

        return slug

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        """Ecriture JSON UTF-8 sans BOM, 2 espaces d'indentation."""
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
