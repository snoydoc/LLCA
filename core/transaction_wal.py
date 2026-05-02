# -*- coding: utf-8-sig -*-
"""
transaction_wal.py — Maintenance WAL + cleanup snapshots (REFACTO-20).

Extrait de transaction_manager.py pour séparation des responsabilités.
Contient : TransactionWalMixin

    _read_wal_for_tx()           — lecture WAL filtrée par tx_id
    _get_tx_completion_timestamp() — timestamp COMMIT/ROLLBACK d'une TX
    cleanup_old_snapshots()      — supprime les répertoires de TX périmés
    archive_old_wal_entries()    — déplace les vieilles entrées WAL en archive

Suppose que self.tx_dir (Path) et self.wal_path (Path) sont définis
par TransactionManager.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from utils.logger import get_logger

log = get_logger("transaction_manager")


class TransactionWalMixin:
    """
    Mixin maintenance WAL + snapshots pour TransactionManager.

    Toutes les méthodes supposent :
      self.tx_dir   : Path  — répertoire racine des transactions
      self.wal_path : Path  — chemin du fichier WAL actif
    """

    # ── Lecture WAL ───────────────────────────────────────────

    def _read_wal_for_tx(self, tx_id: str) -> List[dict]:
        """Extrait les entrées WAL pour un tx_id spécifique."""
        entries = []
        if not self.wal_path.exists():
            return entries
        for line in self.wal_path.read_text(encoding="utf-8-sig").splitlines():
            try:
                entry = json.loads(line)
                if entry.get("tx_id") == tx_id:
                    entries.append(entry)
            except Exception:
                continue
        return entries

    def _get_tx_completion_timestamp(self, tx_id: str) -> Optional[float]:
        """
        Retourne le timestamp du dernier COMMIT ou ROLLBACK dans le WAL
        pour ce tx_id. Retourne None si la TX n'est pas finalisée.
        """
        last_ts = None
        for entry in self._read_wal_for_tx(tx_id):
            if entry.get("type") in ("COMMIT", "ROLLBACK"):
                ts_str = entry.get("_ts") or entry.get("timestamp", "")
                if ts_str:
                    try:
                        ts_str_norm = ts_str.replace("Z", "+00:00")
                        dt = datetime.fromisoformat(ts_str_norm)
                        last_ts = dt.timestamp()
                    except (ValueError, TypeError):
                        pass
        return last_ts

    # ── Cleanup snapshots V7 ──────────────────────────────────

    def cleanup_old_snapshots(self, days: int = 7) -> int:
        """
        Supprime les répertoires de transactions finalisées de plus de N jours.
        Returns: Nombre de répertoires supprimés.
        """
        cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
        removed = 0

        for tx_subdir in self.tx_dir.iterdir():
            if not tx_subdir.is_dir() or tx_subdir.name == ".llm_cache":
                continue

            completion_ts = self._get_tx_completion_timestamp(tx_subdir.name)
            if completion_ts is None:
                continue

            if completion_ts < cutoff:
                try:
                    shutil.rmtree(tx_subdir)
                    removed += 1
                except Exception as exc:
                    log.warning(
                        "cleanup_old_snapshots: erreur sur %s — %s",
                        tx_subdir.name, exc,
                    )

        if removed:
            log.info("cleanup_old_snapshots: %d répertoire(s) supprimé(s)", removed)
        return removed

    # ── Archivage WAL Sprint 07 ───────────────────────────────

    def archive_old_wal_entries(self, days_to_keep: int = 7) -> int:
        """
        Déplace les entrées WAL de plus de N jours dans un fichier archive.
        Retourne le nombre d'entrées archivées.
        """
        if not self.wal_path.exists():
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
        kept_lines: list = []
        archived_lines: list = []

        with self.wal_path.open("r", encoding="utf-8-sig") as f:
            for line in f:
                archived = False
                stripped = line.strip()
                if stripped:
                    try:
                        entry = json.loads(stripped)
                        ts_str = entry.get("_ts") or entry.get("timestamp", "")
                        if ts_str:
                            ts_clean = ts_str.replace("Z", "+00:00")
                            try:
                                ts = datetime.fromisoformat(ts_clean).astimezone(timezone.utc)
                            except ValueError:
                                ts = datetime.fromisoformat(ts_clean[:19]).replace(tzinfo=timezone.utc)
                            if ts < cutoff:
                                archived_lines.append(line)
                                archived = True
                    except (json.JSONDecodeError, ValueError):
                        pass
                if not archived:
                    kept_lines.append(line)

        if not archived_lines:
            return 0

        archive_date = cutoff.strftime("%Y%m%d")
        archive_file = self.wal_path.parent / f"wal_archive_{archive_date}.jsonl"
        with archive_file.open("a", encoding="utf-8-sig") as f:
            f.writelines(archived_lines)

        with self.wal_path.open("w", encoding="utf-8-sig") as f:
            f.writelines(kept_lines)

        n = len(archived_lines)
        log.info("WAL: %d entrée(s) archivée(s) dans %s", n, archive_file.name)
        return n
