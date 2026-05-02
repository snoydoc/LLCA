# -*- coding: utf-8-sig -*-
"""
test_refacto_20.py — REFACTO-20 : transaction_wal.py extrait de transaction_manager.py

Vérifie :
  1. Imports directs depuis core.transaction_wal (TransactionWalMixin + méthodes)
  2. Rétrocompat : TransactionManager hérite bien TransactionWalMixin
  3. cleanup_old_snapshots() via TransactionWalMixin isolé
  4. archive_old_wal_entries() via TransactionWalMixin isolé
  5. _read_wal_for_tx() filtre correctement par tx_id
  6. _get_tx_completion_timestamp() COMMIT + ROLLBACK + absent
  7. TransactionManager toujours opérationnel via héritage (tests smoke)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

# ── Imports directs sur les sous-modules (test rétrocompat) ──────────────────
from core.transaction_wal import TransactionWalMixin
from core.transaction_manager import (
    TransactionManager,
    TransactionWalMixin as TxWalReexport,  # réexport rétrocompat
    OpType,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def env(tmp_path: Path):
    tx_dir  = tmp_path / "transactions"
    wal     = tx_dir / "wal.jsonl"
    tx_dir.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    py_file = workspace / "module.py"
    py_file.write_text("# initial\n", encoding="utf-8")
    tm = TransactionManager(tx_dir=tx_dir, wal_path=wal)
    return {"tm": tm, "py_file": py_file, "wal": wal, "tx_dir": tx_dir}


def _make_mixin(tmp_path: Path) -> TransactionWalMixin:
    """Instancie un TransactionWalMixin concret minimal pour tester le mixin seul."""

    class _Concrete(TransactionWalMixin):
        def __init__(self, tx_dir: Path, wal_path: Path) -> None:
            self.tx_dir   = tx_dir
            self.wal_path = wal_path

    tx_dir = tmp_path / "tx"
    tx_dir.mkdir(parents=True, exist_ok=True)
    wal = tx_dir / "wal.jsonl"
    return _Concrete(tx_dir, wal)


# ──────────────────────────────────────────────────────────────────────────────
# 1. Imports directs depuis core.transaction_wal
# ──────────────────────────────────────────────────────────────────────────────

class TestImports:

    def test_transaction_wal_mixin_importable(self):
        """TransactionWalMixin s'importe directement depuis core.transaction_wal."""
        assert TransactionWalMixin is not None

    def test_reexport_from_transaction_manager(self):
        """TransactionWalMixin est ré-exporté depuis core.transaction_manager."""
        assert TxWalReexport is TransactionWalMixin

    def test_mixin_has_cleanup_method(self):
        assert callable(getattr(TransactionWalMixin, "cleanup_old_snapshots", None))

    def test_mixin_has_archive_method(self):
        assert callable(getattr(TransactionWalMixin, "archive_old_wal_entries", None))

    def test_mixin_has_read_wal_method(self):
        assert callable(getattr(TransactionWalMixin, "_read_wal_for_tx", None))

    def test_mixin_has_completion_timestamp_method(self):
        assert callable(getattr(TransactionWalMixin, "_get_tx_completion_timestamp", None))


# ──────────────────────────────────────────────────────────────────────────────
# 2. Héritage MRO
# ──────────────────────────────────────────────────────────────────────────────

class TestMro:

    def test_transaction_manager_inherits_wal_mixin(self):
        assert issubclass(TransactionManager, TransactionWalMixin)

    def test_transaction_manager_mro_wal_before_legacy(self):
        """TransactionWalMixin doit précéder TransactionLegacyMixin dans le MRO."""
        from core.transaction_legacy import TransactionLegacyMixin
        mro = TransactionManager.__mro__
        idx_wal    = next(i for i, c in enumerate(mro) if c is TransactionWalMixin)
        idx_legacy = next(i for i, c in enumerate(mro) if c is TransactionLegacyMixin)
        assert idx_wal < idx_legacy

    def test_cleanup_accessible_on_manager(self, env):
        """cleanup_old_snapshots() est accessible directement sur TransactionManager."""
        tm: TransactionManager = env["tm"]
        assert callable(tm.cleanup_old_snapshots)

    def test_archive_accessible_on_manager(self, env):
        """archive_old_wal_entries() est accessible directement sur TransactionManager."""
        tm: TransactionManager = env["tm"]
        assert callable(tm.archive_old_wal_entries)


# ──────────────────────────────────────────────────────────────────────────────
# 3. _read_wal_for_tx()
# ──────────────────────────────────────────────────────────────────────────────

class TestReadWalForTx:

    def test_returns_empty_if_wal_absent(self, tmp_path):
        m = _make_mixin(tmp_path)
        assert m._read_wal_for_tx("tx_abc") == []

    def test_filters_by_tx_id(self, tmp_path):
        m = _make_mixin(tmp_path)
        entries = [
            {"tx_id": "tx_aaa", "type": "BEGIN"},
            {"tx_id": "tx_bbb", "type": "BEGIN"},
            {"tx_id": "tx_aaa", "type": "COMMIT"},
        ]
        m.wal_path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n",
            encoding="utf-8-sig",
        )
        result = m._read_wal_for_tx("tx_aaa")
        assert len(result) == 2
        assert all(e["tx_id"] == "tx_aaa" for e in result)

    def test_ignores_malformed_lines(self, tmp_path):
        m = _make_mixin(tmp_path)
        m.wal_path.write_text(
            '{"tx_id": "tx_ok", "type": "BEGIN"}\nNOT_JSON\n',
            encoding="utf-8-sig",
        )
        result = m._read_wal_for_tx("tx_ok")
        assert len(result) == 1


# ──────────────────────────────────────────────────────────────────────────────
# 4. _get_tx_completion_timestamp()
# ──────────────────────────────────────────────────────────────────────────────

class TestGetTxCompletionTimestamp:

    def _write_wal(self, mixin: TransactionWalMixin, entries: list) -> None:
        mixin.wal_path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n",
            encoding="utf-8-sig",
        )

    def test_returns_none_if_no_commit(self, tmp_path):
        m = _make_mixin(tmp_path)
        self._write_wal(m, [{"tx_id": "tx_x", "type": "BEGIN", "_ts": "2026-01-01T00:00:00+00:00"}])
        assert m._get_tx_completion_timestamp("tx_x") is None

    def test_returns_float_on_commit(self, tmp_path):
        m = _make_mixin(tmp_path)
        ts = "2026-01-10T12:00:00+00:00"
        self._write_wal(m, [{"tx_id": "tx_y", "type": "COMMIT", "_ts": ts}])
        result = m._get_tx_completion_timestamp("tx_y")
        assert isinstance(result, float)

    def test_returns_float_on_rollback(self, tmp_path):
        m = _make_mixin(tmp_path)
        ts = "2026-01-10T12:00:00+00:00"
        self._write_wal(m, [{"tx_id": "tx_z", "type": "ROLLBACK", "_ts": ts}])
        result = m._get_tx_completion_timestamp("tx_z")
        assert isinstance(result, float)

    def test_returns_none_for_unknown_tx(self, tmp_path):
        m = _make_mixin(tmp_path)
        self._write_wal(m, [{"tx_id": "tx_other", "type": "COMMIT", "_ts": "2026-01-10T12:00:00+00:00"}])
        assert m._get_tx_completion_timestamp("tx_unknown") is None


# ──────────────────────────────────────────────────────────────────────────────
# 5. cleanup_old_snapshots() via mixin isolé
# ──────────────────────────────────────────────────────────────────────────────

class TestCleanupOldSnapshots:

    def test_removes_old_committed_dir(self, tmp_path):
        m = _make_mixin(tmp_path)
        tx_id = "tx_oldone12345"
        old_dir = m.tx_dir / tx_id
        old_dir.mkdir()

        old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        m.wal_path.write_text(
            json.dumps({"tx_id": tx_id, "type": "COMMIT", "_ts": old_ts}) + "\n",
            encoding="utf-8-sig",
        )

        removed = m.cleanup_old_snapshots(days=7)
        assert removed == 1
        assert not old_dir.exists()

    def test_keeps_recent_dir(self, tmp_path):
        m = _make_mixin(tmp_path)
        tx_id = "tx_recent12345"
        recent_dir = m.tx_dir / tx_id
        recent_dir.mkdir()

        recent_ts = datetime.now(timezone.utc).isoformat()
        m.wal_path.write_text(
            json.dumps({"tx_id": tx_id, "type": "COMMIT", "_ts": recent_ts}) + "\n",
            encoding="utf-8-sig",
        )

        removed = m.cleanup_old_snapshots(days=7)
        assert removed == 0
        assert recent_dir.exists()

    def test_skips_llm_cache_dir(self, tmp_path):
        m = _make_mixin(tmp_path)
        cache_dir = m.tx_dir / ".llm_cache"
        cache_dir.mkdir()
        removed = m.cleanup_old_snapshots(days=0)
        assert cache_dir.exists()


# ──────────────────────────────────────────────────────────────────────────────
# 6. archive_old_wal_entries() via mixin isolé
# ──────────────────────────────────────────────────────────────────────────────

class TestArchiveOldWalEntries:

    def test_archives_stale_entry(self, tmp_path):
        m = _make_mixin(tmp_path)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        m.wal_path.write_text(
            json.dumps({"tx_id": "tx_stale", "type": "COMMIT", "_ts": old_ts}) + "\n",
            encoding="utf-8-sig",
        )
        n = m.archive_old_wal_entries(days_to_keep=7)
        assert n == 1
        assert "tx_stale" not in m.wal_path.read_text(encoding="utf-8-sig")

    def test_keeps_recent_entry(self, tmp_path):
        m = _make_mixin(tmp_path)
        recent_ts = datetime.now(timezone.utc).isoformat()
        m.wal_path.write_text(
            json.dumps({"tx_id": "tx_fresh", "type": "BEGIN", "_ts": recent_ts}) + "\n",
            encoding="utf-8-sig",
        )
        n = m.archive_old_wal_entries(days_to_keep=7)
        assert n == 0
        assert "tx_fresh" in m.wal_path.read_text(encoding="utf-8-sig")

    def test_returns_zero_if_no_wal(self, tmp_path):
        m = _make_mixin(tmp_path)
        assert m.archive_old_wal_entries() == 0


# ──────────────────────────────────────────────────────────────────────────────
# 7. TransactionManager smoke (héritage complet)
# ──────────────────────────────────────────────────────────────────────────────

class TestTransactionManagerSmoke:

    def test_begin_commit_cycle(self, env):
        tm: TransactionManager = env["tm"]
        tx_id = tm.begin(intent="smoke_refacto_20")
        assert tx_id.startswith("tx_")
        committed = tm.commit()
        assert committed == tx_id
        assert tm.current_tx is None

    def test_log_operation_and_rollback(self, env):
        tm: TransactionManager = env["tm"]
        py_file: Path = env["py_file"]
        original = py_file.read_text(encoding="utf-8")
        tm.begin()
        tm.log_operation(
            target_path=py_file,
            op_type=OpType.PATCH_FILE,
            execute_func=lambda: py_file.write_text("# modifié\n", encoding="utf-8"),
        )
        tm.rollback()
        assert py_file.read_text(encoding="utf-8") == original

    def test_cleanup_callable_on_tm(self, env):
        tm: TransactionManager = env["tm"]
        result = tm.cleanup_old_snapshots(days=365)
        assert isinstance(result, int)

    def test_archive_callable_on_tm(self, env):
        tm: TransactionManager = env["tm"]
        result = tm.archive_old_wal_entries(days_to_keep=365)
        assert isinstance(result, int)
