# -*- coding: utf-8-sig -*-
"""
project_history_compactor.py - LCCA V10 / Mode Projets
Sprint PROJ-09 - Compaction sliding-window de history.jsonl

Invariants :
  - Ecriture atomique T-14 (Path.replace()) pour history.jsonl compact
  - Archive dans history_archive/YYYYMMDD_HHMMSS.jsonl (ecriture atomique aussi)
  - Mode degrade silencieux : si history.jsonl absent -> CompactionResult(compacted=False)
  - Lignes NDJSON invalides ignorees (skip silencieux)
  - keep >= 1 (clamp interne si valeur nulle passee)
  - 0 import transaction_manager
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Nombre d'entrees a conserver par defaut
DEFAULT_KEEP = 200


@dataclass
class CompactionResult:
    """Resultat d'une operation de compaction."""
    compacted: bool
    entries_kept: int = 0
    entries_archived: int = 0
    archive_path: Optional[str] = None   # chemin absolu de l'archive creee
    size_before_kb: float = 0.0
    size_after_kb: float = 0.0
    reason: Optional[str] = None         # si compacted=False, explication

    def to_dict(self) -> dict:
        return {
            "compacted":        self.compacted,
            "entries_kept":     self.entries_kept,
            "entries_archived": self.entries_archived,
            "archive_path":     self.archive_path,
            "size_before_kb":   round(self.size_before_kb, 2),
            "size_after_kb":    round(self.size_after_kb, 2),
            "reason":           self.reason,
        }


class ProjectHistoryCompactor:
    """
    Compacteur sliding-window pour history.jsonl d'un projet LCCA V10.

    Usage :
        compactor = ProjectHistoryCompactor()
        result = compactor.compact(project_dir, keep=200)
    """

    def compact(self, project_dir: Path, keep: int = DEFAULT_KEEP) -> CompactionResult:
        """
        Compacte history.jsonl en gardant les `keep` dernieres entrees.

        Si le fichier a moins de `keep` entrees -> pas de compaction (compacted=False).
        Les entrees excedentaires sont archivees dans history_archive/.

        Args:
            project_dir : racine du projet (contient history.jsonl)
            keep        : nombre d'entrees a conserver (>= 1)

        Returns:
            CompactionResult avec les stats de l'operation.
        """
        keep = max(1, keep)
        history_path = project_dir / "history.jsonl"

        if not history_path.exists():
            log.debug("ProjectHistoryCompactor : history.jsonl absent dans %s", project_dir)
            return CompactionResult(
                compacted=False,
                reason="history.jsonl absent",
            )

        # Lire toutes les entrees valides
        size_before_kb = history_path.stat().st_size / 1024
        entries = self._read_entries(history_path)

        if len(entries) <= keep:
            log.debug(
                "ProjectHistoryCompactor : %d entrees <= keep=%d, rien a faire",
                len(entries), keep,
            )
            return CompactionResult(
                compacted=False,
                entries_kept=len(entries),
                entries_archived=0,
                size_before_kb=size_before_kb,
                size_after_kb=size_before_kb,
                reason=f"Moins de {keep} entrees, compaction inutile",
            )

        # Separer : a archiver + a garder
        to_archive = entries[:-keep]
        to_keep    = entries[-keep:]

        # Ecrire l'archive
        archive_path = self._write_archive(project_dir, to_archive)

        # Reecrire history.jsonl (atomique T-14)
        self._write_history(history_path, to_keep)

        size_after_kb = history_path.stat().st_size / 1024

        log.info(
            "ProjectHistoryCompactor : compacte slug=%s kept=%d archived=%d "
            "before=%.1fKB after=%.1fKB archive=%s",
            project_dir.name, len(to_keep), len(to_archive),
            size_before_kb, size_after_kb, archive_path.name,
        )

        return CompactionResult(
            compacted=True,
            entries_kept=len(to_keep),
            entries_archived=len(to_archive),
            archive_path=str(archive_path),
            size_before_kb=size_before_kb,
            size_after_kb=size_after_kb,
        )

    # ------------------------------------------------------------------ #
    # Helpers prives                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _read_entries(history_path: Path) -> list[dict]:
        """Lit le NDJSON, ignore les lignes invalides silencieusement."""
        entries = []
        for line in history_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                log.debug("ProjectHistoryCompactor : ligne invalide ignoree")
        return entries

    @staticmethod
    def _archive_dir(project_dir: Path) -> Path:
        """Retourne (et cree si besoin) le dossier history_archive/."""
        archive_dir = project_dir / "history_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        return archive_dir

    def _write_archive(self, project_dir: Path, entries: list[dict]) -> Path:
        """Ecrit les entrees archivees dans history_archive/YYYYMMDD_HHMMSS.jsonl (T-14)."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_dir  = self._archive_dir(project_dir)
        archive_path = archive_dir / f"{ts}.jsonl"
        content      = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n"
        tmp          = archive_path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(archive_path)
        return archive_path

    @staticmethod
    def _write_history(history_path: Path, entries: list[dict]) -> None:
        """Reeecrit history.jsonl avec les entrees a conserver (T-14)."""
        content = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n"
        tmp = history_path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(history_path)
