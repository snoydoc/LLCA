# -*- coding: utf-8-sig -*-
"""
migration_manager.py — LCCA V10 / Mode Projets
Sprint PROJ-00 — MigrationManager + Structure .llca/

Détecte si LLCA est en mode V9 (sans projects/) et crée la structure V10.
Non-destructif : aucune donnée supprimée ou renommée dans ChromaDB.
Rollback = supprimer le dossier projects/ (collections lcca_* restent intactes).

Double namespace legacy :
- project_legacy_*  → futures collections (écritures)
- lcca_*            → collections historiques V9 (lecture en fallback)
"""
from __future__ import annotations

import json
import logging
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Racine projet détectée dynamiquement (2 niveaux au-dessus de core/)
_CORE_DIR = Path(__file__).parent
_LCCA_ROOT = _CORE_DIR.parent


@dataclass
class MigrationResult:
    """Résultat d'une exécution de MigrationManager.run()."""
    success: bool
    already_done: bool = False
    projects_dir: Optional[Path] = None
    legacy_project_id: Optional[str] = None
    skills_copied: int = 0
    errors: list[str] = field(default_factory=list)
    report: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "already_done": self.already_done,
            "projects_dir": str(self.projects_dir) if self.projects_dir else None,
            "legacy_project_id": self.legacy_project_id,
            "skills_copied": self.skills_copied,
            "errors": self.errors,
            "report": self.report,
        }


class MigrationManager:
    """
    Détecte si LLCA est en mode V9 (sans projects/) et crée la structure V10.

    Usage:
        mgr = MigrationManager()
        if mgr.needs_migration():
            result = mgr.run()
    """

    def __init__(self, lcca_root: Optional[Path] = None) -> None:
        self._root = Path(lcca_root) if lcca_root else _LCCA_ROOT
        self._projects_dir = self._root / "projects"

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def needs_migration(self) -> bool:
        """True si projects/ absent ou si index.cache.json absent."""
        if not self._projects_dir.exists():
            return True
        cache = self._projects_dir / ".llca" / "index.cache.json"
        return not cache.exists()

    def run(self) -> MigrationResult:
        """Pipeline complet. Retourne MigrationResult avec statut + rapport."""
        if not self.needs_migration():
            log.info("MigrationManager : déjà migré, rien à faire.")
            return MigrationResult(
                success=True,
                already_done=True,
                projects_dir=self._projects_dir,
                report="Déjà migré (projects/ et index.cache.json présents).",
            )

        log.info("MigrationManager : démarrage migration V9 → V10")
        errors: list[str] = []
        skills_copied = 0

        try:
            # 1. Créer arborescence projects/.llca/
            global_llca = self._projects_dir / ".llca"
            global_llca.mkdir(parents=True, exist_ok=True)

            # 2. Initialiser user_context.json vide
            self._write_json(global_llca / "user_context.json", {
                "version": 1,
                "entries": [],
            })

            # 3. WAL vide
            wal_path = global_llca / "user_context.wal.jsonl"
            if not wal_path.exists():
                wal_path.write_text("", encoding="utf-8")

            # 4. Créer projet legacy
            legacy_dir = self._projects_dir / "legacy"
            legacy_llca = legacy_dir / ".llca"
            legacy_llca.mkdir(parents=True, exist_ok=True)

            now_iso = datetime.now(timezone.utc).isoformat()
            project_id = str(uuid.uuid4())

            project_json = {
                "id": project_id,
                "slug": "legacy",
                "name": "Legacy (LLCA V9)",
                "description": "Projet de migration automatique depuis LLCA V9",
                "created_at": now_iso,
                "last_opened": now_iso,
                "status": "active",
                "tags": ["legacy", "migration"],
                "model_override": None,
                "storage_mode": "shared",
                "legacy_namespaces": ["lcca_*"],
                "history": {
                    "compaction_threshold_mb": 10,
                    "compression_strategy": "sliding_window",
                    "max_history_tokens": 8000,
                },
                "stats": {
                    "total_sessions": 0,
                    "total_tokens_spent": 0,
                    "skills_generated": 0,
                    "specs_validated": 0,
                    "last_healthcheck": None,
                    "issues_count": 0,
                },
                "migrated_from_v9": True,
            }
            self._write_json(legacy_llca / "project.json", project_json)

            # context_snapshot vide
            self._write_json(legacy_llca / "context_snapshot.json", {})

            # dossiers legacy
            (legacy_dir / "history_archive").mkdir(exist_ok=True)
            (legacy_dir / "skills").mkdir(exist_ok=True)
            (legacy_dir / "specs").mkdir(exist_ok=True)

            # history.jsonl vide
            history_path = legacy_dir / "history.jsonl"
            if not history_path.exists():
                history_path.write_text("", encoding="utf-8")

            # 5. Copier skills globaux → projects/legacy/skills/
            global_skills_dir = self._root / "skills"
            if global_skills_dir.exists():
                for skill_file in global_skills_dir.glob("**/*"):
                    if skill_file.is_file():
                        rel = skill_file.relative_to(global_skills_dir)
                        dest = legacy_dir / "skills" / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            content = skill_file.read_text(encoding="utf-8", errors="replace")
                            content = self._rewrite_paths(content)
                            dest.write_text(content, encoding="utf-8")
                            skills_copied += 1
                        except Exception as exc:
                            errors.append(f"skill copy {rel}: {exc}")

            # 6. Créer index.cache.json minimal
            self._write_json(global_llca / "index.cache.json", {
                "version": 1,
                "generated_at": now_iso,
                "projects": [
                    {
                        "id": project_id,
                        "slug": "legacy",
                        "name": "Legacy (LLCA V9)",
                        "status": "active",
                        "last_opened": now_iso,
                    }
                ],
            })

            report = (
                f"Migration V9→V10 terminée. "
                f"Projet legacy créé (id={project_id}). "
                f"Skills copiés : {skills_copied}. "
                f"Erreurs : {len(errors)}."
            )
            log.info("MigrationManager : %s", report)

            return MigrationResult(
                success=True,
                already_done=False,
                projects_dir=self._projects_dir,
                legacy_project_id=project_id,
                skills_copied=skills_copied,
                errors=errors,
                report=report,
            )

        except Exception as exc:
            log.exception("MigrationManager : échec migration")
            return MigrationResult(
                success=False,
                errors=[str(exc)],
                report=f"Échec migration : {exc}",
            )

    # ------------------------------------------------------------------
    # Helpers privés
    # ------------------------------------------------------------------

    def _rewrite_paths(self, content: str) -> str:
        """
        Substitution string simple sur le Markdown des skills.
        3 passes pour couvrir les variantes Windows.
        NE PAS utiliser libcst — les skills sont du Markdown, pas du code Python.
        """
        content = content.replace("D:\\\\LLMCodeAgent\\\\", "{PROJECT_ROOT}/")
        content = content.replace("D:\\LLMCodeAgent\\", "{PROJECT_ROOT}/")
        content = content.replace("D:/LLMCodeAgent/", "{PROJECT_ROOT}/")
        return content

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        """Écriture JSON UTF-8 sans BOM, 2 espaces d'indentation."""
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
