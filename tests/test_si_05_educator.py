# -*- coding: utf-8-sig -*-
"""
Tests SI-05 — EducatorSI
Sprint SI-05 : 7 tests couvrant auto-fix, borgnes, manual, déduplication, invariant system files.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers de fixture
# ---------------------------------------------------------------------------

def _make_cfg(tmp_path: Path) -> dict:
    """Crée une configuration minimale pointant sur tmp_path."""
    patterns_dir = tmp_path / "patterns"
    patterns_dir.mkdir()
    return {
        "general": {"coupling_mode": 2},
        "auto_fix": {"min_coverage": 0.60, "failure_cooldown_sec": 3600, "auto_push": False},
        "paths": {
            "self_improve_dir": str(tmp_path),
            "observations_dir": str(tmp_path / "observations"),
            "auto_fixes_dir": str(tmp_path / "auto_fixes"),
            "actions_log": str(tmp_path / "actions.log"),
            "pending_actions": str(tmp_path / "pending_actions.json"),
            "borgnes_map": str(tmp_path / "borgnes_map.json"),
            "patterns_dir": str(patterns_dir),
        },
        "orchestrator": {
            "observation_window": 3,
            "observation_max_age_sec": 600,
            "rules_file": str(tmp_path / "orchestrator_rules.json"),
        },
    }


def _write_actions_log(tmp_path: Path, rows: list[list[str]]) -> None:
    """Écrit actions.log avec les lignes fournies (après l'en-tête CSV)."""
    log_path = tmp_path / "actions.log"
    with log_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["timestamp", "rule_id", "action", "target", "status", "details"])
        for row in rows:
            writer.writerow(row)


def _write_borgnes_map(tmp_path: Path, borgnes: list[dict]) -> None:
    """Écrit borgnes_map.json."""
    data = {
        "version": "1.0",
        "borgnes": borgnes,
        "generated_at": "2026-04-23T00:00:00Z",
        "total_wal_fossils": len(borgnes),
    }
    (tmp_path / "borgnes_map.json").write_text(json.dumps(data), encoding="utf-8")


def _make_educator(tmp_path: Path) -> "EducatorSI":
    from SelfImprove.engines.educator import EducatorSI
    cfg = _make_cfg(tmp_path)
    return EducatorSI(cfg=cfg)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEducatorSI:

    # ------------------------------------------------------------------
    # Auto-fix : log vide → None
    # ------------------------------------------------------------------

    def test_ingest_auto_fix_empty_log_returns_none(self, tmp_path):
        educator = _make_educator(tmp_path)
        # actions.log avec seulement l'en-tête (aucun succès)
        _write_actions_log(tmp_path, [])

        result = educator.ingest("auto-fix")
        assert result is None

    # ------------------------------------------------------------------
    # Auto-fix : 1 succès → fichier suggestion créé
    # ------------------------------------------------------------------

    def test_ingest_auto_fix_creates_suggestion(self, tmp_path):
        educator = _make_educator(tmp_path)
        _write_actions_log(tmp_path, [
            ["2026-04-23T10:00:00Z", "missing_import", "auto_fix",
             "core/foo.py", "success", "patch applied 1 lines"],
        ])

        result = educator.ingest("auto-fix")
        assert result is not None
        assert result.exists()
        content = result.read_text(encoding="utf-8")
        assert "missing_import" in content
        assert "opérationnel" in content

    # ------------------------------------------------------------------
    # Borgnes : map vide → None
    # ------------------------------------------------------------------

    def test_ingest_borgnes_empty_returns_none(self, tmp_path):
        educator = _make_educator(tmp_path)
        _write_borgnes_map(tmp_path, [])

        result = educator.ingest("borgnes")
        assert result is None

    # ------------------------------------------------------------------
    # Borgnes : borgne count>=3 severity=high → suggestion cognitive
    # ------------------------------------------------------------------

    def test_ingest_borgnes_creates_suggestion(self, tmp_path):
        educator = _make_educator(tmp_path)
        _write_borgnes_map(tmp_path, [
            {
                "id": "unhandled_timeout",
                "count": 5,
                "severity": "high",
                "description": "Timeout non géré dans les workers async.",
            }
        ])

        result = educator.ingest("borgnes")
        assert result is not None
        assert result.exists()
        content = result.read_text(encoding="utf-8")
        assert "unhandled_timeout" in content
        assert "cognitif" in content
        assert "borgne" in content.lower()

    # ------------------------------------------------------------------
    # Déduplication : 2 appels identiques → 1 seul fichier
    # ------------------------------------------------------------------

    def test_deduplication_prevents_duplicate(self, tmp_path):
        educator = _make_educator(tmp_path)
        _write_actions_log(tmp_path, [
            ["2026-04-23T10:00:00Z", "missing_import", "auto_fix",
             "core/foo.py", "success", "patch applied 1 lines"],
        ])

        result1 = educator.ingest("auto-fix")
        result2 = educator.ingest("auto-fix")

        assert result1 is not None
        assert result2 is not None
        # Les deux appels retournent le même fichier (doublon détecté)
        assert result1 == result2

        patterns_dir = tmp_path / "patterns"
        suggestions = list(patterns_dir.glob("suggested_*.md"))
        assert len(suggestions) == 1

    # ------------------------------------------------------------------
    # Manual : fichier source → suggestion créée
    # ------------------------------------------------------------------

    def test_ingest_manual_creates_suggestion(self, tmp_path):
        educator = _make_educator(tmp_path)

        source_file = tmp_path / "my_pattern.txt"
        source_file.write_text(
            "Pattern exemple\nCorrection : ajouter un try/except\n",
            encoding="utf-8",
        )

        result = educator.ingest("manual", file_path=str(source_file))
        assert result is not None
        assert result.exists()
        content = result.read_text(encoding="utf-8")
        assert "my_pattern" in content
        assert "manual" in content

    # ------------------------------------------------------------------
    # Invariant : aucun fichier système modifié
    # ------------------------------------------------------------------

    def test_no_system_files_modified(self, tmp_path):
        """EducatorSI ne doit jamais toucher orchestrator_rules.json ni auto_fix_whitelist.json."""
        educator = _make_educator(tmp_path)

        # Crée les fichiers système avec contenu de référence
        rules_file = tmp_path / "orchestrator_rules.json"
        whitelist_file = tmp_path / "auto_fix_whitelist.json"
        rules_content = json.dumps({"rules": []})
        whitelist_content = json.dumps({"patterns": []})
        rules_file.write_text(rules_content, encoding="utf-8")
        whitelist_file.write_text(whitelist_content, encoding="utf-8")

        # Ingestion auto-fix avec données
        _write_actions_log(tmp_path, [
            ["2026-04-23T10:00:00Z", "coroutine_never_awaited", "auto_fix",
             "core/agent.py", "success", "patch applied 1 lines"],
        ])
        educator.ingest("auto-fix")

        # Vérification : fichiers système intacts
        assert rules_file.read_text(encoding="utf-8") == rules_content, \
            "orchestrator_rules.json a été modifié — invariant violé"
        assert whitelist_file.read_text(encoding="utf-8") == whitelist_content, \
            "auto_fix_whitelist.json a été modifié — invariant violé"

    # ------------------------------------------------------------------
    # Source invalide → None
    # ------------------------------------------------------------------

    def test_invalid_source_returns_none(self, tmp_path):
        educator = _make_educator(tmp_path)
        result = educator.ingest("inexistant_source_xyz")
        assert result is None
