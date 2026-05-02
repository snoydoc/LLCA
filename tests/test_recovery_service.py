# -*- coding: utf-8-sig -*-
"""
test_recovery_service.py — LCCA V5 Fusion
Sprint 06 — TASK-06-05

Tests unitaires : RecoveryService (boot_check + auto_recover_pending).
Utilise un WAL temporaire isolé pour chaque test.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_tx_dir(tmp_path: Path) -> Path:
    d = tmp_path / "transactions"
    d.mkdir()
    return d


@pytest.fixture
def tx_manager(tmp_tx_dir: Path):
    """TransactionManager isolé dans tmp_path."""
    from core.transaction_manager import TransactionManager
    wal = tmp_tx_dir / "wal.jsonl"
    return TransactionManager(tx_dir=tmp_tx_dir, wal_path=wal)


@pytest.fixture
def recovery(tx_manager):
    """RecoveryService branché sur le tx_manager de test."""
    from core.recovery_service import RecoveryService
    return RecoveryService(tx_manager)


def _write_wal_lines(wal_path: Path, entries: list) -> None:
    """Écrit des entrées JSON brutes dans le WAL (sans passer par TransactionManager)."""
    with wal_path.open("a", encoding="utf-8-sig") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


# ──────────────────────────────────────────────────────────────────────────────
# Tests boot_check()
# ──────────────────────────────────────────────────────────────────────────────

class TestBootCheck:

    def test_boot_check_empty_wal(self, recovery, tx_manager) -> None:
        """WAL inexistant → liste vide, pas d'erreur."""
        assert not tx_manager.wal_path.exists()
        result = recovery.boot_check()
        assert result == []

    def test_boot_check_committed_tx(self, recovery, tx_manager) -> None:
        """TX avec BEGIN + COMMIT → non détectée comme orpheline."""
        _write_wal_lines(tx_manager.wal_path, [
            {"type": "BEGIN",  "tx_id": "tx_aaa111"},
            {"type": "COMMIT", "tx_id": "tx_aaa111"},
        ])
        result = recovery.boot_check()
        assert "tx_aaa111" not in result

    def test_boot_check_rolled_back_tx(self, recovery, tx_manager) -> None:
        """TX avec BEGIN + ROLLBACK → non détectée comme orpheline."""
        _write_wal_lines(tx_manager.wal_path, [
            {"type": "BEGIN",    "tx_id": "tx_bbb222"},
            {"type": "ROLLBACK", "tx_id": "tx_bbb222"},
        ])
        result = recovery.boot_check()
        assert "tx_bbb222" not in result

    def test_boot_check_orphan_tx(self, recovery, tx_manager) -> None:
        """TX avec BEGIN sans COMMIT → détectée comme orpheline."""
        _write_wal_lines(tx_manager.wal_path, [
            {"type": "BEGIN", "tx_id": "tx_orphan01"},
            {"type": "OP_START", "tx_id": "tx_orphan01", "op_id": "op001"},
        ])
        result = recovery.boot_check()
        assert "tx_orphan01" in result

    def test_boot_check_multiple_mixed(self, recovery, tx_manager) -> None:
        """Plusieurs TX : 1 commitée + 1 orpheline → seule l'orpheline détectée."""
        _write_wal_lines(tx_manager.wal_path, [
            {"type": "BEGIN",  "tx_id": "tx_ok"},
            {"type": "COMMIT", "tx_id": "tx_ok"},
            {"type": "BEGIN",  "tx_id": "tx_nok"},
        ])
        result = recovery.boot_check()
        assert "tx_ok"  not in result
        assert "tx_nok" in result

    def test_boot_check_invalid_json_lines_ignored(self, recovery, tx_manager) -> None:
        """Lignes JSON invalides dans le WAL → ignorées, pas de crash."""
        with tx_manager.wal_path.open("w", encoding="utf-8-sig") as f:
            f.write('{"type": "BEGIN", "tx_id": "tx_good"}\n')
            f.write('NOT_JSON_AT_ALL\n')
            f.write('\n')  # ligne vide
            f.write('{"type": "COMMIT", "tx_id": "tx_good"}\n')
        result = recovery.boot_check()
        assert result == []  # tx_good commitée, ligne invalide ignorée

    def test_boot_check_empty_lines_ignored(self, recovery, tx_manager) -> None:
        """Lignes vides dans le WAL → ignorées sans crash."""
        with tx_manager.wal_path.open("w", encoding="utf-8-sig") as f:
            f.write("\n\n\n")
        result = recovery.boot_check()
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# Tests auto_recover_pending()
# ──────────────────────────────────────────────────────────────────────────────

class TestAutoRecover:

    def test_auto_recover_empty_list(self, recovery) -> None:
        """Liste vide → dict vide, pas d'erreur."""
        result = recovery.auto_recover_pending([])
        assert result == {}

    def test_auto_recover_late_commit_no_ops(self, recovery, tx_manager) -> None:
        """TX orpheline sans OP_START → commit tardif trivial."""
        _write_wal_lines(tx_manager.wal_path, [
            {"type": "BEGIN", "tx_id": "tx_noops"},
        ])
        result = recovery.auto_recover_pending(["tx_noops"])
        assert result["tx_noops"] == "committed"

        # Vérifie que le COMMIT tardif est dans le WAL
        lines = [json.loads(l) for l in tx_manager.wal_path.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
        commits = [l for l in lines if l.get("type") == "COMMIT" and l.get("tx_id") == "tx_noops"]
        assert len(commits) >= 1
        assert commits[-1].get("recovery") is True

    def test_auto_recover_late_commit_all_ops_ok(self, recovery, tx_manager) -> None:
        """TX avec toutes ops OP_SUCCESS → commit tardif."""
        _write_wal_lines(tx_manager.wal_path, [
            {"type": "BEGIN",      "tx_id": "tx_allok"},
            {"type": "OP_START",   "tx_id": "tx_allok", "op_id": "op1", "target": ""},
            {"type": "OP_SUCCESS", "tx_id": "tx_allok", "op_id": "op1"},
        ])
        result = recovery.auto_recover_pending(["tx_allok"])
        assert result["tx_allok"] == "committed"

    def test_auto_recover_rollback_incomplete_op(
        self, recovery, tx_manager, tmp_path: Path
    ) -> None:
        """TX avec OP_START sans OP_SUCCESS → rolled_back."""
        # Crée un fichier cible + un backup dans transactions/tx_partial/
        target_file = tmp_path / "module.py"
        target_file.write_text("# original", encoding="utf-8-sig")

        backup_dir = tx_manager.tx_dir / "tx_partial"
        backup_dir.mkdir(parents=True, exist_ok=True)
        bak = backup_dir / "module.py_ab1234.bak"
        bak.write_text("# backup", encoding="utf-8-sig")

        _write_wal_lines(tx_manager.wal_path, [
            {"type": "BEGIN",    "tx_id": "tx_partial"},
            {
                "type": "OP_START", "tx_id": "tx_partial",
                "op_id": "op_inc", "target": str(target_file),
            },
            # Pas de OP_SUCCESS → op incomplète
        ])

        result = recovery.auto_recover_pending(["tx_partial"])
        assert result["tx_partial"] == "rolled_back"

        # Vérifie ROLLBACK dans le WAL
        lines = [
            json.loads(l)
            for l in tx_manager.wal_path.read_text(encoding="utf-8-sig").splitlines()
            if l.strip()
        ]
        rollbacks = [
            l for l in lines
            if l.get("type") == "ROLLBACK" and l.get("tx_id") == "tx_partial"
        ]
        assert len(rollbacks) >= 1

    def test_auto_recover_after_recovery_boot_check_clean(
        self, recovery, tx_manager
    ) -> None:
        """Après recovery, boot_check() ne détecte plus les TX traitées."""
        _write_wal_lines(tx_manager.wal_path, [
            {"type": "BEGIN", "tx_id": "tx_toclean"},
        ])
        # Vérifie qu'elle est orpheline
        assert "tx_toclean" in recovery.boot_check()
        # Recovery
        recovery.auto_recover_pending(["tx_toclean"])
        # Après recovery → plus orpheline (COMMIT ou ROLLBACK ajouté)
        remaining = recovery.boot_check()
        assert "tx_toclean" not in remaining
