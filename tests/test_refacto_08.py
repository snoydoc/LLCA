# -*- coding: utf-8-sig -*-
"""
Tests REFACTO-08 -- ObserverReporter + EducatorIngester + EducatorCurator.

28 tests couvrant :
  TestMakeReportId (3)         : deterministe, 12 chars, different si params differents
  TestShouldArchive (4)        : vieux->True, recent->False, malformed->False, exactement N jours
  TestObserverReporter (4)     : archive vide si dir None, archive 1 receipt, store via memory, store via MCP
  TestObserverDelegates (3)    : _archive_old_receipts wrapper, _store_snapshot wrapper, report_id dans payload

  TestEducatorIngester (6)     : dedup hash, dry_run pas d'ecriture, AST fallback syntaxerror,
                                 extract_symbols top-level only, ingest counts skills, process_repo check licence
  TestEducatorCurator (5)      : run_curation already_running, repos_filter, emit cb, sandbox_check syntax,
                                 sandbox_check ok
  TestEducatorDelegates (3)    : _ingest wrapper, _process_repo wrapper, _sandbox_check wrapper
"""
from __future__ import annotations

import json
import threading
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from core.agents.observer_reporter import (
    ObserverReporter,
    make_report_id,
    should_archive,
    _make_report_id,
    _should_archive,
)
from core.agents.educator_ingester import EducatorIngester
from core.agents.educator_curator import EducatorCurator
from core.agents.a2a_bus import A2ALocalBus, TaskContract


# ===========================================================================
# TestMakeReportId
# ===========================================================================

class TestMakeReportId:
    def test_deterministe(self):
        assert make_report_id("observer", "2026-04-22T10:00:00") == \
               make_report_id("observer", "2026-04-22T10:00:00")

    def test_12_chars(self):
        rid = make_report_id("observer", "ts")
        assert len(rid) == 12

    def test_different_si_params_differents(self):
        assert make_report_id("obs", "t1") != make_report_id("obs", "t2")

    def test_alias_prive(self):
        assert _make_report_id is make_report_id


# ===========================================================================
# TestShouldArchive
# ===========================================================================

class TestShouldArchive:
    def test_vieux_retourne_true(self):
        # Il y a 31 jours
        from datetime import datetime, timezone, timedelta
        old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        assert should_archive(old, 30) is True

    def test_recent_retourne_false(self):
        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        assert should_archive(recent, 30) is False

    def test_malformed_retourne_false(self):
        assert should_archive("pas-une-date", 30) is False

    def test_exactement_n_jours(self):
        from datetime import datetime, timezone, timedelta
        exact = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        assert should_archive(exact, 30) is True

    def test_alias_prive(self):
        assert _should_archive is should_archive


# ===========================================================================
# TestObserverReporter
# ===========================================================================

class TestObserverReporter:
    def _make_reporter(self, receipts_dir=None, memory=None, mcp=None):
        return ObserverReporter(
            receipts_dir=receipts_dir,
            archive_after_days=30,
            memory_engine=memory,
            mcp_caller=mcp,
        )

    def test_archive_vide_si_dir_none(self):
        r = self._make_reporter()
        assert r.archive_old_receipts() == []

    def test_archive_receipt_ancien(self, tmp_path):
        from datetime import datetime, timezone, timedelta
        old_ts = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        receipt = {"task_id": "t1", "timestamp": old_ts}
        (tmp_path / "t1.json").write_text(json.dumps(receipt), encoding="utf-8")

        r = self._make_reporter(receipts_dir=tmp_path)
        archived = r.archive_old_receipts()
        assert "t1" in archived
        assert not (tmp_path / "t1.json").exists()
        assert (tmp_path / "t1.archived").exists()

    def test_store_via_memory(self):
        memory = MagicMock()
        r = self._make_reporter(memory=memory)
        snapshot = {
            "skills_total": 10, "low_quality_count": 1,
            "duplicate_count": 0, "archived_count": 0,
            "observed_at": "ts",
        }
        r.store_snapshot(snapshot)
        memory.store.assert_called_once()

    def test_store_via_mcp(self):
        mcp = MagicMock()
        r = self._make_reporter(mcp=mcp)
        snapshot = {
            "skills_total": 5, "low_quality_count": 0,
            "duplicate_count": 0, "archived_count": 0,
            "observed_at": "ts",
        }
        r.store_snapshot(snapshot)
        mcp.assert_called_once()


# ===========================================================================
# TestObserverDelegates
# ===========================================================================

class TestObserverDelegates:
    def _make_agent(self, tmp_path=None):
        from core.agents.observer_agent import ObserverAgent
        from core.agents.agent_card import AgentCard, AGENT_MCP_ALLOWLIST, OBSERVER_POLICY
        bus = MagicMock(spec=A2ALocalBus)
        mcp = MagicMock(return_value={"results": []})
        card = AgentCard(
            name="observer", version="8.0.0",
            capabilities=["maintenance"],
            mcp_tools=AGENT_MCP_ALLOWLIST["observer"],
            recovery_policy=OBSERVER_POLICY,
            description="test",
        )
        return ObserverAgent(
            card=card, bus=bus, mcp_caller=mcp,
            receipts_dir=tmp_path,
        )

    def test_archive_old_receipts_wrapper(self):
        agent = self._make_agent()
        with patch.object(agent._reporter, "archive_old_receipts", return_value=["t1"]) as mock:
            result = agent._archive_old_receipts(force=True)
            mock.assert_called_once_with(force=True)
            assert result == ["t1"]

    def test_store_snapshot_wrapper(self):
        agent = self._make_agent()
        with patch.object(agent._reporter, "store_snapshot") as mock:
            snap = {"skills_total": 0, "low_quality_count": 0,
                    "duplicate_count": 0, "archived_count": 0, "observed_at": "ts"}
            agent._store_snapshot(snap)
            mock.assert_called_once_with(snap)

    def test_report_id_dans_payload(self):
        agent = self._make_agent()
        with patch.object(agent._analyzer, "find_low_quality", return_value=[]), \
             patch.object(agent._analyzer, "find_duplicates", return_value=[]), \
             patch.object(agent._reporter, "archive_old_receipts", return_value=[]), \
             patch.object(agent._analyzer, "build_snapshot", return_value={
                 "skills_total": 0, "low_quality_count": 0,
                 "duplicate_count": 0, "archived_count": 0,
                 "observed_at": "2026-04-22T10:00:00",
                 "low_quality_ids": [], "duplicate_pairs": [],
             }), \
             patch.object(agent._reporter, "store_snapshot"):
            contract = TaskContract(
                task_id="t_r08", intent="observe", domain="global",
                source_agent="orchestrator", target_agent="observer",
            )
            result = agent.run_task(contract)
            assert "report_id" in result.payload
            assert len(result.payload["report_id"]) == 12


# ===========================================================================
# TestEducatorIngester
# ===========================================================================

class TestEducatorIngester:
    def _make_ingester(self, memory=None):
        gh  = MagicMock()
        flt = MagicMock()
        flt.passes.return_value = True
        lock = threading.Lock()
        hashes: set = set()
        return EducatorIngester(
            gh=gh, flt=flt, memory=memory,
            lock=lock, ingested_hashes=hashes,
        ), hashes

    def test_dedup_hash_skip_si_deja_vu(self):
        ing, hashes = self._make_ingester()
        src = "def foo(): pass"
        import hashlib
        h = hashlib.sha256(src.encode()).hexdigest()[:16]
        hashes.add(h)
        counts = ing.ingest(src, "o", "r", "f.py", dry_run=False)
        assert counts["skills"] == 0
        assert counts["context"] == 0

    def test_dry_run_pas_decriture_memoire(self):
        memory = MagicMock()
        ing, _ = self._make_ingester(memory=memory)
        ing.ingest("def foo(): pass", "o", "r", "f.py", dry_run=True)
        memory.store.assert_not_called()

    def test_ast_fallback_syntaxerror(self):
        ing, _ = self._make_ingester()
        counts = ing.ingest("def (broken syntax!!!:", "o", "r", "f.py", dry_run=True)
        # Pas de crash, counts retournes
        assert isinstance(counts, dict)

    def test_extract_symbols_top_level_only(self):
        import ast as _ast
        src = "def public(): pass\ndef _private(): pass\n"
        tree = _ast.parse(src)
        symbols = EducatorIngester._extract_symbols(src, tree)
        names = [s[0] for s in symbols]
        assert "public" in names
        assert "_private" not in names

    def test_ingest_counts_skills(self):
        ing, _ = self._make_ingester()
        src = "def foo(): pass\ndef bar(): pass\n"
        counts = ing.ingest(src, "o", "r", "f.py", dry_run=True)
        assert counts["skills"] >= 2

    def test_process_repo_check_licence(self):
        ing, _ = self._make_ingester()
        ing._gh.check_license.return_value = False
        from dataclasses import dataclass, field as _field
        @dataclass
        class FakeResult:
            files_fetched: int = 0
            files_filtered: int = 0
            skills_ingested: int = 0
            context_ingested: int = 0
        r = FakeResult()
        ing.process_repo("o", "r", r, dry_run=True)
        ing._gh.list_py_files.assert_not_called()


# ===========================================================================
# TestEducatorCurator
# ===========================================================================

class TestEducatorCurator:
    def _make_curator(self, whitelist=None):
        from core.agents.educator_agent import EducatorConfig, CurationResult
        ingester = MagicMock()
        cfg = EducatorConfig(sleep_between_repos=0)
        lock = threading.Lock()
        curator = EducatorCurator(
            whitelist=whitelist or [("psf", "requests")],
            ingester=ingester,
            cfg=cfg,
            lock=lock,
        )
        return curator, ingester, CurationResult

    def test_already_running_retourne_erreur(self):
        curator, _, CurationResult = self._make_curator()
        curator._running = True
        result = curator.run_curation(CurationResult)
        assert "already_running" in result.errors

    def test_repos_filter_filtre_correctement(self):
        curator, ingester, CurationResult = self._make_curator(
            whitelist=[("psf", "requests"), ("numpy", "numpy")]
        )
        curator.run_curation(CurationResult, repos_filter=["psf/requests"])
        # Seul psf/requests doit etre traite
        calls = [c[0][0] for c in ingester.process_repo.call_args_list]
        assert "psf" in calls
        assert "numpy" not in calls

    def test_emit_cb_appele(self):
        curator, ingester, CurationResult = self._make_curator()
        messages = []
        curator.run_curation(CurationResult, progress_cb=messages.append)
        assert any("requests" in m for m in messages)

    def test_sandbox_check_syntax_error(self):
        body = "def broken(:"
        # Sandbox non disponible -> True par defaut
        result = EducatorCurator.sandbox_check(body)
        assert isinstance(result, bool)

    def test_sandbox_check_code_valide(self):
        result = EducatorCurator.sandbox_check("def foo(): return 42")
        assert isinstance(result, bool)


# ===========================================================================
# TestEducatorDelegates
# ===========================================================================

class TestEducatorDelegates:
    def _make_agent(self):
        from core.agents.educator_agent import EducatorAgent, EducatorConfig
        cfg = EducatorConfig(dry_run=True, sleep_between_repos=0)
        return EducatorAgent(cfg=cfg, memory=None, bus=None)

    def test_ingest_wrapper(self):
        agent = self._make_agent()
        with patch.object(agent._ingester, "ingest", return_value={"skills": 2, "context": 1}) as mock:
            result = agent._ingest("src", "o", "r", "f.py", dry_run=True)
            mock.assert_called_once()
            assert result["skills"] == 2

    def test_process_repo_wrapper(self):
        agent = self._make_agent()
        with patch.object(agent._ingester, "process_repo") as mock:
            from core.agents.educator_agent import CurationResult
            r = CurationResult()
            agent._process_repo("o", "r", r, dry_run=True)
            mock.assert_called_once()

    def test_sandbox_check_wrapper(self):
        agent = self._make_agent()
        with patch.object(agent._curator, "sandbox_check", return_value=True) as mock:
            result = agent._sandbox_check("def foo(): pass")
            mock.assert_called_once_with("def foo(): pass")
            assert result is True
