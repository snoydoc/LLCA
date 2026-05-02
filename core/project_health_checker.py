# -*- coding: utf-8-sig -*-
"""
project_health_checker.py - LCCA V10 / Mode Projets
Sprint PROJ-10 - Rapport de sante complet d'un projet

Inspecte un projet LCCA V10 et produit un HealthReport detaille :
  - Presence / integrite des fichiers requis
  - Stats history.jsonl (taille, entrees, lignes corrompues, derniere entree)
  - Stats WAL (entrees, succes/echecs, derniere entree)
  - Stats archives history et WAL
  - Recommandations (compaction conseillée, WAL volumineux, etc.)

Invariants :
  - check() ne leve jamais (mode degrade silencieux, issues renseignes)
  - 0 import transaction_manager
  - 0 modification disque (lecture seule)
  - Toutes les tailles en KB arrondies a 2 decimales
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Seuils de recommandation
HISTORY_COMPACTION_THRESHOLD_KB  = 500.0   # > 500 KB -> recommande compaction
WAL_COMPACTION_THRESHOLD_ENTRIES = 300      # > 300 entrees WAL -> recommande compaction WAL
WAL_FAILURE_RATE_WARN            = 0.20     # > 20% echecs -> avertissement


@dataclass
class HealthReport:
    """Rapport de sante d'un projet LCCA V10."""

    # Identite
    project_id:   str = ""
    slug:         str = ""
    name:         str = ""
    status:       str = ""

    # Sante globale
    healthy:      bool = True
    issues:       list[str] = field(default_factory=list)
    warnings:     list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    # Fichiers requis
    files_ok:     bool = True
    missing_files: list[str] = field(default_factory=list)
    missing_dirs:  list[str] = field(default_factory=list)

    # history.jsonl
    history_exists:         bool  = False
    history_entries:        int   = 0
    history_corrupt_lines:  int   = 0
    history_size_kb:        float = 0.0
    history_last_ts:        Optional[str] = None
    history_archive_count:  int   = 0
    history_archive_size_kb: float = 0.0

    # WAL (.llca/project_wal.jsonl)
    wal_exists:        bool  = False
    wal_entries:       int   = 0
    wal_success:       int   = 0
    wal_failures:      int   = 0
    wal_size_kb:       float = 0.0
    wal_last_ts:       Optional[str] = None
    wal_archive_count: int   = 0
    wal_archive_size_kb: float = 0.0

    # Integrité project.json
    project_json_valid: bool = True

    def to_dict(self) -> dict:
        return {
            "project_id":    self.project_id,
            "slug":          self.slug,
            "name":          self.name,
            "status":        self.status,
            "healthy":       self.healthy,
            "issues":        self.issues,
            "issues_count":  len(self.issues),
            "warnings":      self.warnings,
            "recommendations": self.recommendations,
            "files": {
                "ok":           self.files_ok,
                "missing_files": self.missing_files,
                "missing_dirs":  self.missing_dirs,
            },
            "history": {
                "exists":        self.history_exists,
                "entries":       self.history_entries,
                "corrupt_lines": self.history_corrupt_lines,
                "size_kb":       self.history_size_kb,
                "last_ts":       self.history_last_ts,
                "archive_count": self.history_archive_count,
                "archive_size_kb": self.history_archive_size_kb,
            },
            "wal": {
                "exists":        self.wal_exists,
                "entries":       self.wal_entries,
                "success":       self.wal_success,
                "failures":      self.wal_failures,
                "failure_rate":  round(
                    self.wal_failures / self.wal_entries, 3
                ) if self.wal_entries > 0 else 0.0,
                "size_kb":       self.wal_size_kb,
                "last_ts":       self.wal_last_ts,
                "archive_count": self.wal_archive_count,
                "archive_size_kb": self.wal_archive_size_kb,
            },
            "project_json_valid": self.project_json_valid,
        }


class ProjectHealthChecker:
    """
    Verificateur de sante d'un projet LCCA V10.

    Usage :
        checker = ProjectHealthChecker()
        report  = checker.check(project_dir, meta)
        print(report.to_dict())

    Ne modifie jamais le disque (lecture seule).
    Ne leve jamais d'exception (mode degrade silencieux).
    """

    # Fichiers et dossiers requis dans un projet sain
    REQUIRED_FILES = [".llca/project.json", "history.jsonl"]
    REQUIRED_DIRS  = ["skills", "specs", "history_archive", ".llca"]

    def check(self, project_dir: Path, meta) -> HealthReport:
        """
        Produit un HealthReport complet pour le projet donne.

        Args:
            project_dir : racine du projet (ex: projects/mon-projet/)
            meta        : ProjectMeta (id, slug, name, status)

        Returns:
            HealthReport (jamais None, jamais d'exception)
        """
        report = HealthReport(
            project_id=meta.id,
            slug=meta.slug,
            name=meta.name,
            status=meta.status,
        )

        try:
            self._check_files(project_dir, report)
            self._check_project_json(project_dir, report)
            self._check_history(project_dir, report)
            self._check_wal(project_dir, report)
            self._build_recommendations(report)
        except Exception as exc:
            log.warning(
                "ProjectHealthChecker.check : erreur inattendue slug=%s : %s",
                meta.slug, exc,
            )
            report.issues.append(f"Erreur interne healthcheck : {exc}")
            report.healthy = False

        # healthy = False si au moins un issue
        if report.issues:
            report.healthy = False

        return report

    # ------------------------------------------------------------------ #
    # Checks internes                                                     #
    # ------------------------------------------------------------------ #

    def _check_files(self, project_dir: Path, report: HealthReport) -> None:
        """Verifie la presence des fichiers et dossiers requis."""
        for rel in self.REQUIRED_FILES:
            if not (project_dir / rel).exists():
                report.missing_files.append(rel)
                report.issues.append(f"Fichier manquant : {rel}")

        for rel in self.REQUIRED_DIRS:
            if not (project_dir / rel).is_dir():
                report.missing_dirs.append(rel)
                report.issues.append(f"Dossier manquant : {rel}")

        report.files_ok = not bool(report.missing_files or report.missing_dirs)

    def _check_project_json(self, project_dir: Path, report: HealthReport) -> None:
        """Verifie l'integrite de project.json (parseable + champs minimaux)."""
        path = project_dir / ".llca" / "project.json"
        if not path.exists():
            report.project_json_valid = False
            return  # deja signale dans _check_files

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            required_keys = {"id", "slug", "name", "status"}
            missing = required_keys - set(data.keys())
            if missing:
                report.project_json_valid = False
                report.issues.append(
                    f"project.json : champs manquants {sorted(missing)}"
                )
        except (json.JSONDecodeError, OSError) as exc:
            report.project_json_valid = False
            report.issues.append(f"project.json invalide : {exc}")

    def _check_history(self, project_dir: Path, report: HealthReport) -> None:
        """Inspecte history.jsonl : taille, entrees valides, lignes corrompues."""
        history_path = project_dir / "history.jsonl"
        if not history_path.exists():
            return

        report.history_exists = True
        report.history_size_kb = round(history_path.stat().st_size / 1024, 2)

        try:
            text = history_path.read_text(encoding="utf-8")
            last_ts = None
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    report.history_entries += 1
                    ts = entry.get("_ts") or entry.get("ts")
                    if ts:
                        last_ts = ts
                except json.JSONDecodeError:
                    report.history_corrupt_lines += 1

            report.history_last_ts = last_ts
            if report.history_corrupt_lines > 0:
                report.warnings.append(
                    f"history.jsonl : {report.history_corrupt_lines} ligne(s) corrompue(s)"
                )
        except OSError as exc:
            report.issues.append(f"Impossible de lire history.jsonl : {exc}")

        # Archives history
        archive_dir = project_dir / "history_archive"
        if archive_dir.is_dir():
            archives = list(archive_dir.glob("*.jsonl"))
            report.history_archive_count = len(archives)
            report.history_archive_size_kb = round(
                sum(a.stat().st_size for a in archives) / 1024, 2
            )

    def _check_wal(self, project_dir: Path, report: HealthReport) -> None:
        """Inspecte project_wal.jsonl : entrees, succes/echecs, taille."""
        wal_path = project_dir / ".llca" / "project_wal.jsonl"
        if not wal_path.exists():
            return

        report.wal_exists = True
        report.wal_size_kb = round(wal_path.stat().st_size / 1024, 2)

        try:
            last_ts = None
            for line in wal_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    report.wal_entries += 1
                    if entry.get("success", True):
                        report.wal_success += 1
                    else:
                        report.wal_failures += 1
                    ts = entry.get("_ts")
                    if ts:
                        last_ts = ts
                except json.JSONDecodeError:
                    pass  # WAL : lignes corrompues ignorees silencieusement

            report.wal_last_ts = last_ts
        except OSError as exc:
            report.warnings.append(f"Impossible de lire project_wal.jsonl : {exc}")

        # Taux d'echec WAL
        if report.wal_entries > 0:
            failure_rate = report.wal_failures / report.wal_entries
            if failure_rate > WAL_FAILURE_RATE_WARN:
                report.warnings.append(
                    f"WAL : taux d'echec eleve "
                    f"({report.wal_failures}/{report.wal_entries} = "
                    f"{failure_rate:.0%})"
                )

        # Archives WAL
        wal_archive_dir = project_dir / ".llca" / "wal_archive"
        if wal_archive_dir.is_dir():
            archives = list(wal_archive_dir.glob("*.jsonl"))
            report.wal_archive_count = len(archives)
            report.wal_archive_size_kb = round(
                sum(a.stat().st_size for a in archives) / 1024, 2
            )

    def _build_recommendations(self, report: HealthReport) -> None:
        """Ajoute des recommandations basees sur les seuils."""
        if (
            report.history_exists
            and report.history_size_kb > HISTORY_COMPACTION_THRESHOLD_KB
        ):
            report.recommendations.append(
                f"history.jsonl volumineux ({report.history_size_kb:.1f} KB) "
                f"— envisager project_compact_history"
            )

        if report.wal_entries > WAL_COMPACTION_THRESHOLD_ENTRIES:
            report.recommendations.append(
                f"WAL volumineux ({report.wal_entries} entrees) "
                f"— envisager ProjectWal.compact()"
            )

        if report.history_corrupt_lines > 0:
            report.recommendations.append(
                "Lignes corrompues dans history.jsonl "
                "— verifier les ecritures recentes"
            )
