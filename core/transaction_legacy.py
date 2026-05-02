# -*- coding: utf-8-sig -*-
"""
transaction_legacy.py — Helpers legacy du TransactionManager (Sprint REFACTO-01).

Extrait de transaction_manager.py pour réduire sa taille de 21 KB à < 12 KB.

TransactionLegacyMixin fournit les helpers Sprint 01-06 conservés pour rétrocompat :
    begin_legacy / commit_legacy / rollback_legacy
    snapshot / restore
    new_tx_id / md5
    recover_incomplete

Suppose que self.tx_dir, self.wal_path, self._write_wal() sont définis par TransactionManager.
"""
from __future__ import annotations

import hashlib
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List


class TransactionLegacyMixin:
    """
    Mixin helpers legacy pour TransactionManager.

    Méthodes stateless ou ne nécessitant que tx_dir + _write_wal().
    """

    # ── Helpers statiques ─────────────────────────────────────────────────────

    @staticmethod
    def new_tx_id() -> str:
        return f"tx_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def md5(path: Path) -> str:
        return hashlib.md5(path.read_bytes()).hexdigest()

    # ── Snapshot / Restore legacy ─────────────────────────────────────────────

    def snapshot(self, tx_id: str, path: Path) -> Path:
        backup_dir = self.tx_dir / tx_id
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / path.name
        shutil.copy2(path, backup_path)
        return backup_path

    def restore(self, tx_id: str, path: Path) -> bool:
        backup_path = self.tx_dir / tx_id / path.name
        if backup_path.exists():
            shutil.copy2(backup_path, path)
            return True
        return False

    # ── WAL legacy ────────────────────────────────────────────────────────────

    def begin_legacy(self, tx_id: str, file_path: Path, hash_before: str) -> None:
        self._write_wal({
            "type": "BEGIN",
            "tx_id": tx_id,
            "file": str(file_path),
            "hash_before": hash_before,
        })

    def commit_legacy(self, tx_id: str, file_path: Path, hash_after: str) -> None:
        self._write_wal({
            "type": "COMMIT",
            "tx_id": tx_id,
            "file": str(file_path),
            "hash_after": hash_after,
        })

    def rollback_legacy(self, tx_id: str, file_path: Path, reason: str) -> None:
        self._write_wal({
            "type": "ROLLBACK",
            "tx_id": tx_id,
            "file": str(file_path),
            "reason": reason,
        })

    # ── Recovery au boot ─────────────────────────────────────────────────────

    def recover_incomplete(self) -> List[str]:
        """
        Lit le WAL et rollback toute transaction BEGIN sans COMMIT.
        Retourne la liste des tx_id rollbackés.
        """
        if not self.wal_path.exists():
            return []

        import json

        records: dict = {}
        with self.wal_path.open("r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tx_id = rec.get("tx_id", "")
                if not tx_id:
                    continue
                if rec["type"] == "BEGIN":
                    records[tx_id] = rec
                elif rec["type"] in ("COMMIT", "ROLLBACK"):
                    records.pop(tx_id, None)

        rolled_back = []
        for tx_id, rec in records.items():
            file_path = Path(rec.get("file", rec.get("target", "")))
            if file_path and self.restore(tx_id, file_path):
                self.rollback_legacy(tx_id, file_path, reason="recovery_at_boot")
                rolled_back.append(tx_id)

        return rolled_back
