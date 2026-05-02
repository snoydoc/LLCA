# -*- coding: utf-8-sig -*-
"""
test_transaction_manager.py — Sprint 02
Tests unitaires pour TransactionManager (8 tests).

Exécution : pytest tests/test_transaction_manager.py -v
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.transaction_manager import (
    FileSnapshot,
    OpType,
    Transaction,
    TransactionError,
    TransactionManager,
    TxStatus,
)


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_env(tmp_path: Path):
    """
    Environnement isolé par test :
    - tx_dir  : dossier temporaire pour les backups
    - wal     : fichier WAL dédié
    - tm      : TransactionManager pointant sur cet environnement
    - py_file : fichier Python de test dans workspace/
    """
    tx_dir  = tmp_path / "transactions"
    wal     = tx_dir / "wal.jsonl"
    tx_dir.mkdir()

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    py_file = workspace / "module.py"
    py_file.write_text("# initial content\ndef hello(): pass\n", encoding="utf-8")

    tm = TransactionManager(tx_dir=tx_dir, wal_path=wal)
    return {"tm": tm, "py_file": py_file, "wal": wal, "tx_dir": tx_dir}


# ──────────────────────────────────────────────────────────────
# TASK-02-02 : WAL
# ──────────────────────────────────────────────────────────────

def test_begin_creates_wal_entry(tmp_env):
    """Vérifie que BEGIN est bien écrit dans le WAL."""
    tm: TransactionManager = tmp_env["tm"]
    wal: Path = tmp_env["wal"]

    tx_id = tm.begin(dsl_input="test_begin", intent="smoke")

    assert wal.exists(), "Le fichier WAL doit être créé après begin()"
    lines = [l for l in wal.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
    assert len(lines) == 1, "Exactement une entrée WAL attendue"

    record = json.loads(lines[0])
    assert record["type"]  == "BEGIN"
    assert record["tx_id"] == tx_id
    assert "_ts" in record


def test_wal_is_valid_jsonl(tmp_env):
    """Chaque ligne du WAL est du JSON parseable après begin + commit."""
    tm: TransactionManager = tmp_env["tm"]
    wal: Path = tmp_env["wal"]
    py_file: Path = tmp_env["py_file"]

    tm.begin()
    tm.log_operation(
        target_path=py_file,
        op_type=OpType.PATCH_FILE,
        execute_func=lambda: py_file.write_text("# modified\n", encoding="utf-8"),
    )
    tm.commit()

    lines = [l for l in wal.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
    assert len(lines) >= 3, "BEGIN + OP_START + OP_SUCCESS + COMMIT attendus"

    for i, line in enumerate(lines):
        record = json.loads(line)   # Lève JSONDecodeError si invalide
        assert "type"  in record, f"Ligne {i} sans champ 'type'"
        assert "tx_id" in record, f"Ligne {i} sans champ 'tx_id'"


# ──────────────────────────────────────────────────────────────
# TASK-02-03 : Snapshot MD5
# ──────────────────────────────────────────────────────────────

def test_snapshot_captures_hash(tmp_env):
    """Modification d'un fichier → hash différent."""
    tm: TransactionManager = tmp_env["tm"]
    py_file: Path = tmp_env["py_file"]

    snap1 = tm._snapshot(py_file)
    py_file.write_text("# changed content\n", encoding="utf-8")
    snap2 = tm._snapshot(py_file)

    assert snap1.exists is True
    assert snap2.exists is True
    assert snap1.content_hash != snap2.content_hash, "Hash doit changer si contenu modifié"


def test_snapshot_nonexistent_file(tmp_env):
    """Fichier inexistant → exists=False, content_hash/mtime sont None (V7)."""
    tm: TransactionManager = tmp_env["tm"]
    ghost = tmp_env["py_file"].parent / "does_not_exist.py"

    snap = tm._snapshot(ghost)
    assert snap.exists is False
    assert snap.content_hash is None   # V7 : None, pas "" (fichier absent)
    assert snap.mtime is None          # V7 : None, pas 0.0
    assert snap.content is None


# ──────────────────────────────────────────────────────────────
# TASK-02-04 : begin()
# ──────────────────────────────────────────────────────────────

def test_double_begin_raises(tmp_env):
    """Appeler begin() deux fois sans commit → RuntimeError."""
    tm: TransactionManager = tmp_env["tm"]

    tm.begin()
    with pytest.raises(RuntimeError, match="déjà active"):
        tm.begin()

    tm.rollback()   # Nettoyage


# ──────────────────────────────────────────────────────────────
# TASK-02-05 : log_operation()
# ──────────────────────────────────────────────────────────────

def test_rollback_on_exception(tmp_env):
    """Si execute_func() lève une exception → fichier restauré automatiquement."""
    tm: TransactionManager = tmp_env["tm"]
    py_file: Path = tmp_env["py_file"]

    original_content = py_file.read_text(encoding="utf-8")

    def bad_func():
        py_file.write_text("# corrupted\n", encoding="utf-8")
        raise ValueError("Erreur simulée en milieu d'opération")

    tm.begin()
    with pytest.raises(TransactionError):
        tm.log_operation(
            target_path=py_file,
            op_type=OpType.PATCH_FILE,
            execute_func=bad_func,
        )
    tm.rollback()

    restored_content = py_file.read_text(encoding="utf-8")
    assert restored_content == original_content, (
        "Le contenu doit être identique à l'original après rollback sur exception"
    )


def test_nested_backup_created(tmp_env):
    """Le .bak est créé dans transactions/{tx_id}/ avant chaque write."""
    tm: TransactionManager = tmp_env["tm"]
    py_file: Path = tmp_env["py_file"]
    tx_dir: Path = tmp_env["tx_dir"]

    tx_id = tm.begin()
    tm.log_operation(
        target_path=py_file,
        op_type=OpType.PATCH_FILE,
        execute_func=lambda: py_file.write_text("# v2\n", encoding="utf-8"),
    )
    tm.commit()

    backup_dir = tx_dir / tx_id
    assert backup_dir.exists(), "Le dossier de backup doit exister"
    bak_files = list(backup_dir.glob("*.bak"))
    assert len(bak_files) >= 1, "Au moins un fichier .bak attendu"


# ──────────────────────────────────────────────────────────────
# TASK-02-06 : commit() / rollback()
# ──────────────────────────────────────────────────────────────

def test_commit_changes_status(tmp_env):
    """Après commit, la transaction est COMMITTED et current_tx == None."""
    tm: TransactionManager = tmp_env["tm"]

    tm.begin()
    tx_ref = tm.current_tx
    tm.commit()

    assert tm.current_tx is None
    assert tx_ref.status == TxStatus.COMMITTED


def test_rollback_restores_file(tmp_env):
    """Après rollback, le contenu du fichier est identique bit à bit à l'état initial."""
    tm: TransactionManager = tmp_env["tm"]
    py_file: Path = tmp_env["py_file"]

    original = py_file.read_text(encoding="utf-8")

    tm.begin()
    tm.log_operation(
        target_path=py_file,
        op_type=OpType.PATCH_FILE,
        execute_func=lambda: py_file.write_text("# totally different\n", encoding="utf-8"),
    )

    # On vérifie que le fichier a bien été modifié
    assert py_file.read_text(encoding="utf-8") != original

    # Rollback
    tm.rollback(reason="test_rollback_restores_file")

    restored = py_file.read_text(encoding="utf-8")
    assert restored == original, "Le rollback doit restaurer le contenu original exactement"
    assert tm.current_tx is None


# ──────────────────────────────────────────────────────────────
# TASK-12-T1 : Cas V7 — CREATE_FILE, cleanup, archive WAL
# ──────────────────────────────────────────────────────────────

def test_create_file_rollback_unlinks(tmp_env):
    """
    V7 — CREATE_FILE : si rollback, le fichier créé dans la TX doit être
    supprimé (unlink). Règle : op.type == CREATE_FILE OR rollback_data is None.
    """
    tm: TransactionManager = tmp_env["tm"]
    workspace: Path = tmp_env["py_file"].parent

    new_file = workspace / "brand_new_module.py"
    assert not new_file.exists(), "Précondition : le fichier ne doit pas exister"

    tm.begin(intent="create_new_module")
    tm.log_operation(
        target_path=new_file,
        op_type=OpType.CREATE_FILE,
        execute_func=lambda: new_file.write_text("# nouveau module\n", encoding="utf-8"),
    )

    assert new_file.exists(), "Le fichier doit exister après execute_func()"

    tm.rollback(reason="test_create_file_rollback")

    assert not new_file.exists(), (
        "V7 : rollback CREATE_FILE doit supprimer le fichier (unlink), "
        "pas tenter une restauration .bak inexistante."
    )


def test_patch_file_rollback_restores_via_bak(tmp_env):
    """
    V7 — PATCH_FILE : rollback doit restaurer le contenu original via le .bak
    (Scénario B — fichier existait avant la TX).
    """
    tm: TransactionManager = tmp_env["tm"]
    py_file: Path = tmp_env["py_file"]

    original = py_file.read_text(encoding="utf-8")

    tm.begin(intent="patch_existing")
    tm.log_operation(
        target_path=py_file,
        op_type=OpType.PATCH_FILE,
        execute_func=lambda: py_file.write_text("# version modifiée\n", encoding="utf-8"),
    )

    assert py_file.read_text(encoding="utf-8") != original

    tm.rollback(reason="test_patch_file_rollback")

    restored = py_file.read_text(encoding="utf-8")
    assert restored == original, (
        "V7 : rollback PATCH_FILE doit restaurer le contenu original depuis le .bak"
    )
    assert py_file.exists(), "Le fichier doit toujours exister après rollback PATCH_FILE"


def test_cleanup_old_snapshots_removes_old_dirs(tmp_env):
    """
    V7 — cleanup_old_snapshots() : supprime les répertoires de TX finalisées
    de plus de N jours en se basant sur le timestamp COMMIT du WAL.
    """
    tm: TransactionManager = tmp_env["tm"]
    py_file: Path = tmp_env["py_file"]
    tx_dir: Path = tmp_env["tx_dir"]
    wal: Path = tmp_env["wal"]

    # Créer et committer une TX pour avoir un répertoire de backup
    tx_id = tm.begin(intent="old_tx_to_cleanup")
    tm.log_operation(
        target_path=py_file,
        op_type=OpType.PATCH_FILE,
        execute_func=lambda: py_file.write_text("# version temporaire\n", encoding="utf-8"),
    )
    tm.commit()

    backup_dir = tx_dir / tx_id
    assert backup_dir.exists(), "Le répertoire de backup doit exister après commit"

    # Réécrire l'entrée COMMIT avec un timestamp périmé (> 8 jours)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    lines = wal.read_text(encoding="utf-8-sig").splitlines()
    new_lines = []
    for line in lines:
        try:
            entry = json.loads(line)
            if entry.get("type") == "COMMIT" and entry.get("tx_id") == tx_id:
                entry["_ts"] = old_ts
                new_lines.append(json.dumps(entry))
            else:
                new_lines.append(line)
        except json.JSONDecodeError:
            new_lines.append(line)
    wal.write_text("\n".join(new_lines) + "\n", encoding="utf-8-sig")

    # cleanup avec seuil = 7 jours → doit supprimer
    removed = tm.cleanup_old_snapshots(days=7)

    assert removed >= 1, (
        "cleanup_old_snapshots() doit supprimer les répertoires plus vieux que N jours"
    )
    assert not backup_dir.exists(), (
        "Le répertoire de backup doit être supprimé après cleanup"
    )


def test_archive_old_wal_entries_moves_stale_lines(tmp_env):
    """
    V7 — archive_old_wal_entries() : les entrées > N jours sont déplacées
    dans wal_archive_*.jsonl ; le WAL actif est tronqué.
    """
    tm: TransactionManager = tmp_env["tm"]
    wal: Path = tmp_env["wal"]
    tx_dir: Path = tmp_env["tx_dir"]

    # Injecter une entrée périmée et une récente dans le WAL
    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    stale_entry = json.dumps({
        "type": "COMMIT",
        "tx_id": "tx_stale_entry_001",
        "_ts": old_ts,
        "n_ops": 0,
    })
    recent_entry = json.dumps({
        "type": "BEGIN",
        "tx_id": "tx_recent_entry_002",
        "_ts": datetime.now(timezone.utc).isoformat(),
    })
    wal.write_text(
        stale_entry + "\n" + recent_entry + "\n",
        encoding="utf-8-sig",
    )

    archived_count = tm.archive_old_wal_entries(days_to_keep=7)

    assert archived_count >= 1, (
        "archive_old_wal_entries() doit archiver au moins l'entrée périmée"
    )

    remaining = wal.read_text(encoding="utf-8-sig")
    assert "tx_stale_entry_001" not in remaining, (
        "L'entrée périmée doit avoir été retirée du WAL actif"
    )
    assert "tx_recent_entry_002" in remaining, (
        "L'entrée récente doit rester dans le WAL actif"
    )

    archive_files = list(tx_dir.glob("wal_archive_*.jsonl"))
    assert archive_files, "Un fichier d'archive WAL doit avoir été créé"
    archive_content = archive_files[0].read_text(encoding="utf-8-sig")
    assert "tx_stale_entry_001" in archive_content, (
        "L'entrée périmée doit être présente dans le fichier d'archive"
    )
