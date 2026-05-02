# -*- coding: utf-8-sig -*-
"""
recovery_service.py — LCCA V5 Fusion
Sprint 06 — TASK-06-01 + TASK-06-02

Service de recovery au boot : détection des transactions orphelines (BEGIN sans
COMMIT) et récupération automatique via le WAL.

Usage :
    from core.recovery_service import RecoveryService
    svc = RecoveryService(tx_manager)
    orphans = svc.boot_check()
    results = svc.auto_recover_pending(orphans)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("lcca.recovery_service")


class RecoveryService:
    r"""
    Vérifie l'intégrité du WAL au démarrage et répare les transactions
    orphelines.

    Stratégie de récupération :
      - Toutes les OP_START ont un OP_SUCCESS correspondant
        → commit tardif (les fichiers sont déjà en état final)
      - Au moins une OP_START sans OP_SUCCESS
        → rollback depuis les backups .bak

    Attributes:
        tx_manager : Instance TransactionManager (accès WAL + rollback).
        wal_path   : Chemin vers wal.jsonl (résolu depuis tx_manager).
    """

    def __init__(self, tx_manager) -> None:
        self.tx_manager = tx_manager
        self.wal_path: Path = tx_manager.wal_path

    # ── TASK-06-01 : boot_check() ─────────────────────────────────────────────

    def boot_check(self) -> List[str]:
        """
        Lit le WAL et retourne les tx_ids des transactions orphelines.

        Une transaction est orpheline si :
          - Elle a un BEGIN
          - Elle n'a pas de COMMIT ni de ROLLBACK

        Returns:
            Liste de tx_ids orphelins (peut être vide).
        """
        if not self.wal_path.exists():
            return []

        open_tx: Dict[str, Dict] = {}

        with self.wal_path.open("r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("WAL ligne invalide ignorée: %.80s", line)
                    continue

                tx_id = entry.get("tx_id")
                if not tx_id:
                    continue

                event_type = entry.get("type", "")
                if event_type == "BEGIN":
                    open_tx[tx_id] = entry
                elif event_type in ("COMMIT", "ROLLBACK"):
                    open_tx.pop(tx_id, None)

        orphaned = list(open_tx.keys())
        if orphaned:
            log.warning(
                "%d transaction(s) orpheline(s) detectee(s): %s",
                len(orphaned), orphaned,
            )
        else:
            log.debug("boot_check: aucune transaction orpheline.")
        return orphaned

    # ── TASK-06-02 : auto_recover_pending() ──────────────────────────────────

    def auto_recover_pending(
        self, orphaned_ids: List[str]
    ) -> Dict[str, str]:
        """
        Récupère chaque transaction orpheline.

        Logique par TX :
          - Toutes les OP_START ont un OP_SUCCESS → commit tardif
          - Au moins une OP_START sans OP_SUCCESS → rollback

        Args:
            orphaned_ids: Liste de tx_ids issus de boot_check().

        Returns:
            Dict {tx_id: "committed" | "rolled_back" | "skipped" | "failed"}
        """
        results: Dict[str, str] = {}

        for tx_id in orphaned_ids:
            try:
                tx_state = self._reconstruct_tx_state(tx_id)

                if tx_state["n_ops"] == 0:
                    # BEGIN seulement, aucune op enregistrée → commit tardif trivial
                    log.info("Recovery: commit tardif (0 ops) de %s", tx_id)
                    self._write_late_commit(tx_id, n_ops=0)
                    results[tx_id] = "committed"

                elif tx_state["all_ops_succeeded"]:
                    # Toutes les ops sont complètes → just écrire le COMMIT
                    log.info(
                        "Recovery: commit tardif de %s (%d ops completes)",
                        tx_id, tx_state["n_ops"],
                    )
                    self._write_late_commit(tx_id, tx_state["n_ops"])
                    results[tx_id] = "committed"

                else:
                    # Op incomplète → rollback depuis backups
                    incomplete = tx_state["incomplete_ops"]
                    log.warning(
                        "Recovery: rollback de %s (ops incompletes: %s)",
                        tx_id, incomplete,
                    )
                    self._rollback_from_backups(tx_id)
                    self.tx_manager._write_wal({
                        "type":     "ROLLBACK",
                        "tx_id":    tx_id,
                        "reason":   "recovery_incomplete_ops",
                        "n_ops":    tx_state["n_ops"],
                        "recovery": True,
                    })
                    results[tx_id] = "rolled_back"

            except Exception as exc:
                log.error("Recovery echouee pour %s: %s", tx_id, exc, exc_info=True)
                results[tx_id] = "failed"

        return results

    # ── Helpers internes ──────────────────────────────────────────────────────

    def _reconstruct_tx_state(self, tx_id: str) -> Dict:
        """
        Reconstitue l'état d'une TX depuis le WAL :
        quelles ops ont démarré et lesquelles ont réussi.

        Returns:
            {
              "all_ops_succeeded": bool,
              "n_ops":             int,
              "incomplete_ops":    set[str],
              "op_files":          dict[op_id, target_path]
            }
        """
        ops_started: Dict[str, str] = {}   # op_id → target_path
        ops_succeeded: set = set()

        with self.wal_path.open("r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if entry.get("tx_id") != tx_id:
                    continue

                etype = entry.get("type", "")
                op_id = entry.get("op_id")

                if etype == "OP_START" and op_id:
                    ops_started[op_id] = entry.get("target", "")
                elif etype == "OP_SUCCESS" and op_id:
                    ops_succeeded.add(op_id)

        incomplete = set(ops_started.keys()) - ops_succeeded
        all_ok = (len(incomplete) == 0) and (len(ops_started) > 0)

        return {
            "all_ops_succeeded": all_ok,
            "n_ops":             len(ops_started),
            "incomplete_ops":    incomplete,
            "op_files":          ops_started,
        }

    def _write_late_commit(self, tx_id: str, n_ops: int) -> None:
        """Écrit un COMMIT tardif dans le WAL pour une TX déjà complète."""
        self.tx_manager._write_wal({
            "type":     "COMMIT",
            "tx_id":    tx_id,
            "n_ops":    n_ops,
            "recovery": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def _rollback_from_backups(self, tx_id: str) -> None:
        """
        Restaure les fichiers depuis les backups de la TX (dossier transactions/{tx_id}/).
        Ordre LIFO non garanti ici (on rollback tout).
        """
        import shutil

        backup_dir = self.tx_manager.tx_dir / tx_id
        if not backup_dir.exists():
            log.warning(
                "_rollback_from_backups: aucun backup trouve pour %s", tx_id
            )
            return

        # Lit le WAL pour reconstituer la liste des fichiers cibles
        state = self._reconstruct_tx_state(tx_id)
        op_files = state["op_files"]  # op_id → target_path

        for op_id, target_path_str in op_files.items():
            target = Path(target_path_str)
            if not target_path_str:
                continue
            # Cherche un fichier .bak correspondant dans backup_dir
            # sorted() garantit un ordre déterministe si plusieurs backups existent
            bak_candidates = sorted(backup_dir.glob(f"{target.name}_*.bak"))
            if bak_candidates:
                bak = bak_candidates[0]  # Prend le premier (un seul par op)
                shutil.copy2(bak, target)
                log.info(
                    "Restore: %s ← %s", target, bak.name
                )
            else:
                log.warning(
                    "Aucun backup .bak pour %s (op %s)", target.name, op_id
                )
