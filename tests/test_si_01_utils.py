# -*- coding: utf-8-sig -*-
"""
Tests SI-01 — si_utils.py
9 tests couvrant : atomic_write_json, log_action, add_pending_action,
approve_pending_action, check_and_update_cooldown, force_cooldown.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from SelfImprove.si_utils import (
    atomic_write_json,
    log_action,
    add_pending_action,
    approve_pending_action,
    check_and_update_cooldown,
    force_cooldown,
    _cooldowns,
    _trigger_counts,
    _trigger_date,
)


def _make_cfg(tmp_path: Path) -> dict:
    return {
        "general": {"coupling_mode": 2},
        "auto_fix": {"min_coverage": 0.60, "failure_cooldown_sec": 3600, "auto_push": False},
        "paths": {
            "self_improve_dir": str(tmp_path),
            "observations_dir": str(tmp_path / "observations"),
            "auto_fixes_dir":   str(tmp_path / "auto_fixes"),
            "patterns_dir":     str(tmp_path / "patterns"),
            "actions_log":      str(tmp_path / "actions.log"),
            "pending_actions":  str(tmp_path / "pending_actions.json"),
            "borgnes_map":      str(tmp_path / "borgnes_map.json"),
        },
        "orchestrator": {
            "observation_window": 3,
            "observation_max_age_sec": 600,
            "rules_file": str(tmp_path / "orchestrator_rules.json"),
        },
    }


class TestAtomicWriteJson:

    def test_writes_valid_json(self, tmp_path):
        path = tmp_path / "out.json"
        atomic_write_json(path, {"key": "value", "n": 42})
        data = json.loads(path.read_text("utf-8"))
        assert data == {"key": "value", "n": 42}

    def test_no_tmp_file_left_after_success(self, tmp_path):
        path = tmp_path / "out.json"
        atomic_write_json(path, {"ok": True})
        tmp = path.with_suffix(".tmp")
        assert not tmp.exists()

    def test_overwrites_existing_file(self, tmp_path):
        path = tmp_path / "out.json"
        atomic_write_json(path, {"v": 1})
        atomic_write_json(path, {"v": 2})
        assert json.loads(path.read_text("utf-8"))["v"] == 2


class TestLogAction:

    def test_creates_actions_log(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        log_action("rule-01", "log_only", "core/foo.py", "success", cfg=cfg)
        log_path = Path(cfg["paths"]["actions_log"])
        assert log_path.exists()

    def test_csv_row_has_6_fields(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        log_action("rule-02", "notify_human", "core/bar.py", "started",
                   "details text", cfg=cfg)
        import csv
        rows = list(csv.reader(
            Path(cfg["paths"]["actions_log"]).read_text("utf-8").splitlines()
        ))
        assert len(rows) == 1
        assert len(rows[0]) == 6

    def test_appends_multiple_rows(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        log_action("r1", "log_only", "f1", "success", cfg=cfg)
        log_action("r2", "log_only", "f2", "failed",  cfg=cfg)
        import csv
        rows = list(csv.reader(
            Path(cfg["paths"]["actions_log"]).read_text("utf-8").splitlines()
        ))
        assert len(rows) == 2


class TestPendingActions:

    def test_add_pending_returns_uuid(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        action_id = add_pending_action("rule-x", "notify_human", "core/f.py", {}, cfg=cfg)
        assert isinstance(action_id, str)
        assert len(action_id) == 36  # UUID4

    def test_approve_pending_changes_status(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        action_id = add_pending_action("rule-y", "notify_human", "core/g.py", {}, cfg=cfg)
        result = approve_pending_action(action_id, cfg=cfg)
        assert result is not None
        assert result["status"] == "approved"

    def test_approve_unknown_id_returns_none(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        result = approve_pending_action("non-existent-id-0000", cfg=cfg)
        assert result is None


class TestCooldown:

    def setup_method(self):
        # Isolation des dicts module-level entre tests
        _cooldowns.clear()
        _trigger_counts.clear()
        _trigger_date.clear()

    def test_first_call_returns_true(self):
        ok = check_and_update_cooldown("rule-cd1", cooldown_sec=60, max_per_day=5)
        assert ok is True

    def test_second_call_blocked_by_cooldown(self):
        check_and_update_cooldown("rule-cd2", cooldown_sec=3600, max_per_day=5)
        ok = check_and_update_cooldown("rule-cd2", cooldown_sec=3600, max_per_day=5)
        assert ok is False

    def test_force_cooldown_blocks_next_call(self):
        force_cooldown("rule-cd3", cooldown_sec=3600)
        ok = check_and_update_cooldown("rule-cd3", cooldown_sec=3600, max_per_day=5)
        assert ok is False
