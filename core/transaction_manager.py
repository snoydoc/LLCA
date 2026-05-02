# -*- coding: utf-8-sig -*-
"""
transaction_manager.py — LCCA V5 Fusion — façade ACID (REFACTO-20).

Gestion ACID + WAL (Write-Ahead Log) + Rollback automatique.

Sprint 02      — Implémentation complète
Sprint 07      — archive_old_wal_entries()
Sprint V7      — OpType.CREATE_FILE, snapshot exists=False,
                 rollback unlink explicite, cleanup_old_snapshots()
Sprint REFACTO-01 — Types → transaction_types.py | helpers legacy → transaction_legacy.py
Sprint REFACTO-20 — Maintenance WAL/cleanup → transaction_wal.py

Rétrocompat : tous les types restent importables depuis ce module.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from utils.logger import get_logger

# ── Types partagés (ré-exportés pour rétrocompat) ─────────────────────────
from core.transaction_types import (  # noqa: F401
    TxStatus, OpType, FileSnapshot, Operation, Transaction, TransactionError,
)
# ── Helpers legacy (ré-exportés pour rétrocompat) ─────────────────────────
from core.transaction_legacy import TransactionLegacyMixin  # noqa: F401
# ── Maintenance WAL + cleanup (ré-exporté pour rétrocompat) ───────────────
from core.transaction_wal import TransactionWalMixin  # noqa: F401

log = get_logger("transaction_manager")


# ──────────────────────────────────────────────────────────────
# Paths projet
# ──────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TX_DIR       = _PROJECT_ROOT / "transactions"
_WAL_FILE     = _TX_DIR / "wal.jsonl"


# ──────────────────────────────────────────────────────────────
# TransactionManager
# ──────────────────────────────────────────────────────────────

class TransactionManager(TransactionWalMixin, TransactionLegacyMixin):
    """
    Gestionnaire de transactions atomiques sur fichiers Python.

    Garantit ACID :
      - Atomicité  : rollback complet si une opération échoue
      - Cohérence  : snapshot MD5 avant/après chaque fichier
      - Isolation  : une seule transaction active à la fois
      - Durabilité : WAL JSONL avec fsync avant toute exécution

    V7        : gestion CREATE_FILE (rollback = unlink), cleanup automatique.
    REFACTO-01 : hérite TransactionLegacyMixin pour les helpers Sprint 01-06.
    REFACTO-20 : hérite TransactionWalMixin pour maintenance WAL + snapshots.
    """

    def __init__(
        self,
        tx_dir: Optional[Path] = None,
        wal_path: Optional[Path] = None,
        auto_cleanup_days: int = 7,
    ) -> None:
        self.tx_dir   = tx_dir   or _TX_DIR
        self.wal_path = wal_path or (self.tx_dir / "wal.jsonl")
        self.auto_cleanup_days = auto_cleanup_days
        self.tx_dir.mkdir(parents=True, exist_ok=True)
        self.current_tx: Optional[Transaction] = None

        # Nettoyage non-bloquant au boot
        try:
            self.cleanup_old_snapshots(days=self.auto_cleanup_days)
            self.archive_old_wal_entries(days=self.auto_cleanup_days * 2)
        except Exception:
            pass

    # ── WAL ──────────────────────────────────────────────────

    def _write_wal(self, entry: Dict[str, Any]) -> None:
        entry["_ts"] = datetime.now(timezone.utc).isoformat()
        with self.wal_path.open("a", encoding="utf-8-sig") as f:
            f.write(json.dumps(entry, default=str, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    # ── Snapshot MD5 ─────────────────────────────────────────

    def _snapshot(self, path: Path) -> FileSnapshot:
        """
        Capture l'état complet d'un fichier (ou note son absence).
        V7 : content_hash et mtime sont None si le fichier n'existe pas.
        """
        if not path.exists():
            return FileSnapshot(
                path=str(path),
                content_hash=None,
                content=None,
                exists=False,
                mtime=None,
            )

        mtime = path.stat().st_mtime
        try:
            content = path.read_text(encoding="utf-8")
            content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
        except (UnicodeDecodeError, PermissionError):
            content = None
            content_hash = hashlib.md5(str(mtime).encode()).hexdigest()

        return FileSnapshot(
            path=str(path),
            content_hash=content_hash,
            content=content,
            exists=True,
            mtime=mtime,
        )

    # ── Backup physique ───────────────────────────────────────

    def _backup(self, tx_id: str, path: Path) -> Optional[Path]:
        """
        Copie le fichier dans transactions/{tx_id}/ avant modification.
        Retourne le chemin du .bak, ou None si le fichier n'existait pas.
        """
        if not path.exists():
            return None
        backup_dir = self.tx_dir / tx_id
        backup_dir.mkdir(parents=True, exist_ok=True)
        safe_name = path.name + f"_{uuid.uuid4().hex[:6]}.bak"
        backup_path = backup_dir / safe_name
        shutil.copy2(path, backup_path)
        return backup_path

    # ── begin() ──────────────────────────────────────────────

    def begin(
        self,
        dsl_input: str = "",
        project: str = "lcca",
        intent: str = "",
    ) -> str:
        if self.current_tx is not None:
            raise RuntimeError(
                f"Transaction déjà active : {self.current_tx.tx_id}. "
                "Appelez commit() ou rollback() avant d'en ouvrir une nouvelle."
            )

        tx_id = f"tx_{uuid.uuid4().hex[:12]}"
        now   = datetime.now(timezone.utc).isoformat()

        tx = Transaction(
            tx_id=tx_id,
            dsl_input=dsl_input,
            project=project,
            intent=intent,
            status=TxStatus.PENDING,
            created_at=now,
            completed_at=None,
        )
        self.current_tx = tx

        self._write_wal({
            "type":   "BEGIN",
            "tx_id":  tx_id,
            "input":  dsl_input,
            "intent": intent,
        })

        tx.status = TxStatus.RUNNING
        return tx_id

    # ── log_operation() ───────────────────────────────────────

    def log_operation(
        self,
        target_path: Path,
        op_type: OpType,
        execute_func: Callable[[], None],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Operation:
        """
        Exécute execute_func() de manière atomique avec snapshot avant/après.

        Séquence :
          1. snapshot before
          2. backup physique (.bak)  — None si fichier inexistant
          3. WAL OP_START
          4. execute_func()
          5. snapshot after
          6. WAL OP_SUCCESS
          En cas d'erreur → restore depuis .bak + WAL OP_FAIL
        """
        if self.current_tx is None:
            raise TransactionError("Aucune transaction active. Appelez begin() d'abord.")

        tx = self.current_tx
        op_id = uuid.uuid4().hex[:8]
        now   = datetime.now(timezone.utc).isoformat()

        snap_before = self._snapshot(target_path)
        bak_path    = self._backup(tx.tx_id, target_path)

        self._write_wal({
            "type":        "OP_START",
            "tx_id":       tx.tx_id,
            "op_id":       op_id,
            "op_type":     op_type.value,
            "target":      str(target_path),
            "hash_before": snap_before.content_hash,
        })

        op = Operation(
            op_id=op_id,
            type=op_type,
            target_path=str(target_path),
            before=snap_before,
            after=None,
            timestamp=now,
            metadata=metadata or {},
            rollback_data=str(bak_path) if bak_path else None,
        )

        try:
            execute_func()

            snap_after = self._snapshot(target_path)
            op.after = snap_after

            self._write_wal({
                "type":       "OP_SUCCESS",
                "tx_id":      tx.tx_id,
                "op_id":      op_id,
                "hash_after": snap_after.content_hash,
            })

            log.info("TX op %s: %s %s", op_id, op_type.value, target_path.name)

        except Exception as exc:
            if bak_path and bak_path.exists():
                shutil.copy2(bak_path, target_path)
                if snap_before.mtime is not None:
                    os.utime(target_path, (snap_before.mtime, snap_before.mtime))

            self._write_wal({
                "type":   "OP_FAIL",
                "tx_id":  tx.tx_id,
                "op_id":  op_id,
                "reason": str(exc),
            })

            raise TransactionError(
                f"Opération {op_id} échouée sur {target_path}: {exc}"
            ) from exc

        tx.operations.append(op)
        return op

    # ── commit() ─────────────────────────────────────────────

    def commit(self) -> str:
        if self.current_tx is None:
            raise RuntimeError("Aucune transaction active à committer.")

        tx = self.current_tx
        tx.status = TxStatus.COMMITTED
        tx.completed_at = datetime.now(timezone.utc).isoformat()

        self._write_wal({
            "type":  "COMMIT",
            "tx_id": tx.tx_id,
            "n_ops": len(tx.operations),
        })

        tx_id = tx.tx_id
        self.current_tx = None
        return tx_id

    # ── rollback() ───────────────────────────────────────────

    def rollback(self, reason: str = "") -> str:
        """
        Annule toutes les opérations de la transaction en cours (ordre LIFO).

        V7 — Règle de décision :
          - Si op.type == CREATE_FILE  OU  op.rollback_data is None
            → le fichier n'existait pas avant la TX → on le supprime.
          - Sinon → restaurer depuis le .bak.
        """
        if self.current_tx is None:
            raise RuntimeError("Aucune transaction active à rollbacker.")

        tx = self.current_tx

        for op in reversed(tx.operations):
            dst = Path(op.target_path)

            if op.type == OpType.CREATE_FILE or op.rollback_data is None:
                if dst.exists():
                    dst.unlink()
            else:
                src = Path(op.rollback_data)
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    if op.before.mtime is not None:
                        os.utime(dst, (op.before.mtime, op.before.mtime))

            self._write_wal({
                "type":   "OP_ROLLBACK",
                "tx_id":  tx.tx_id,
                "op_id":  op.op_id,
                "target": op.target_path,
                "reason": reason,
            })

        tx.status = TxStatus.ROLLED_BACK
        tx.completed_at = datetime.now(timezone.utc).isoformat()

        self._write_wal({
            "type":   "ROLLBACK",
            "tx_id":  tx.tx_id,
            "reason": reason,
            "n_ops":  len(tx.operations),
        })

        tx_id = tx.tx_id
        self.current_tx = None
        return tx_id
