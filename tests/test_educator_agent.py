# -*- coding: utf-8-sig -*-
"""
tests/test_educator_agent.py -- Sprint ED-01

Tests unitaires de l'EducatorAgent V9.1.
- 0 dependance Ollama (tout mocke)
- 0 appel reseau reel
- 0 SQLite externe
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from core.agents.educator_agent import EducatorAgent, EducatorConfig, CurationResult


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_agent(dry_run: bool = True) -> EducatorAgent:
    cfg = EducatorConfig(
        dry_run             = dry_run,
        max_files_per_repo  = 5,
        max_skills_per_repo = 3,
        min_score           = 70,
        min_filter_score    = 3,
        sleep_between_repos = 0,
        fetch_timeout       = 5,
        stars_threshold     = 0,
    )
    return EducatorAgent(cfg=cfg)


# ---------------------------------------------------------------------------
# TestEducatorConfig
# ---------------------------------------------------------------------------

class TestEducatorConfig:
    def test_defaults(self):
        cfg = EducatorConfig()
        assert cfg.dry_run is True
        assert cfg.min_filter_score == 5
        assert cfg.stars_threshold == 1000

    def test_from_config(self):
        cfg = EducatorConfig.from_config()
        assert isinstance(cfg.max_files_per_repo, int)
        assert isinstance(cfg.dry_run, bool)

    def test_custom_values(self):
        cfg = EducatorConfig(dry_run=False, min_score=80, fetch_timeout=10)
        assert cfg.dry_run is False
        assert cfg.min_score == 80
        assert cfg.fetch_timeout == 10


# ---------------------------------------------------------------------------
# TestFilterRules
# ---------------------------------------------------------------------------

class TestFilterRules:
    def setup_method(self):
        self.agent = _make_agent()

    # R4 : print hors __main__
    def test_print_in_main_allowed(self):
        src = (
            'def foo() -> None:\n    """doc."""\n    pass\n\n'
            'if __name__ == "__main__":\n    print("ok")\n'
        )
        assert self.agent._has_bad_print(src) is False

    def test_print_outside_main_rejected(self):
        src = 'def foo():\n    print("bad")\n'
        assert self.agent._has_bad_print(src) is True

    def test_no_print_returns_false(self):
        src = "def foo():\n    return 42\n"
        assert self.agent._has_bad_print(src) is False

    # R7 : pathlib assoupli
    def test_pathlib_rule_no_io(self):
        src = "X = 42\n"
        assert self.agent._pathlib_rule(src) is True

    def test_pathlib_rule_open_no_import(self):
        src = "with open('f') as fh:\n    data = fh.read()\n"
        assert self.agent._pathlib_rule(src) is False

    def test_pathlib_rule_open_with_import(self):
        src = "from pathlib import Path\nwith open('f') as fh:\n    pass\n"
        assert self.agent._pathlib_rule(src) is True

    # R1 : type hints
    def test_type_hints_detected(self):
        src = "def foo(x: int) -> str:\n    return str(x)\n"
        assert self.agent._has_type_hints(src) is True

    def test_type_hints_absent(self):
        src = "def foo(x):\n    return x\n"
        assert self.agent._has_type_hints(src) is False

    def test_type_hints_syntax_error_fallback(self):
        # Fallback texte si SyntaxError : cherche "->"
        src = "def foo( ->:\n    pass  # invalide mais contient ->\n"
        result = self.agent._has_type_hints(src)
        assert isinstance(result, bool)  # Pas d'exception


# ---------------------------------------------------------------------------
# TestIngestDedup
# ---------------------------------------------------------------------------

class TestIngestDedup:
    def setup_method(self):
        self.agent = _make_agent(dry_run=True)

    def test_dry_run_no_memory_write(self):
        memory = MagicMock()
        self.agent._memory = memory
        src = "def foo() -> None:\n    '''doc.'''\n    pass\n"
        self.agent._ingest(src, "owner", "repo", "foo.py", dry_run=True)
        memory.store.assert_not_called()

    def test_wet_run_calls_memory_store(self):
        memory = MagicMock()
        memory.store.return_value = MagicMock(stored=True)
        self.agent._memory = memory
        src = "def foo() -> None:\n    '''doc.'''\n    pass\n"
        self.agent._ingest(src, "owner", "repo", "foo.py", dry_run=False)
        memory.store.assert_called_once()

    def test_dedup_second_call_skipped(self):
        memory = MagicMock()
        memory.store.return_value = MagicMock(stored=True)
        self.agent._memory = memory
        src = "def foo() -> None:\n    '''doc.'''\n    pass\n"
        self.agent._ingest(src, "owner", "repo", "foo.py", dry_run=False)
        self.agent._ingest(src, "owner", "repo", "foo.py", dry_run=False)
        # Deuxieme appel doit etre ignore (meme hash)
        assert memory.store.call_count == 1

    def test_context_count_increments(self):
        memory = MagicMock()
        memory.store.return_value = MagicMock(stored=True)
        self.agent._memory = memory
        src = "def foo() -> None:\n    '''doc.'''\n    pass\n"
        counts = self.agent._ingest(src, "owner", "repo", "foo.py", dry_run=False)
        assert counts["context"] == 1


# ---------------------------------------------------------------------------
# TestRunTask
# ---------------------------------------------------------------------------

class TestRunTask:
    def test_run_task_returns_started(self):
        agent = _make_agent()
        contract = MagicMock()
        contract.context = {"dry_run": True}
        result = agent.run_task(contract)
        assert result.success is True
        assert result.payload["status"] == "started"
        assert result.payload["dry_run"] is True

    def test_run_task_thread_launched(self):
        import time as _time
        agent = _make_agent()
        contract = MagicMock()
        contract.context = {"dry_run": True}
        with patch.object(agent, "run_curation", return_value=CurationResult()) as mock:
            agent.run_task(contract)
            _time.sleep(0.15)  # Laisser le thread demarrer
            mock.assert_called_once()

    def test_run_task_dry_run_from_context(self):
        agent = _make_agent(dry_run=False)
        contract = MagicMock()
        contract.context = {"dry_run": True}  # Override
        # Mocker run_curation pour eviter appels reseau reels
        with patch.object(agent, "run_curation", return_value=CurationResult(dry_run=True)):
            result = agent.run_task(contract)
        assert result.payload["dry_run"] is True


# ---------------------------------------------------------------------------
# TestCurationAlreadyRunning
# ---------------------------------------------------------------------------

class TestCurationGuard:
    def test_already_running_returns_error(self):
        agent = _make_agent()
        # Simuler une curation deja en cours
        with agent._lock:
            agent._running = True
        result = agent.run_curation(dry_run=True)
        assert "already_running" in result.errors
        # Cleanup
        with agent._lock:
            agent._running = False


# ---------------------------------------------------------------------------
# TestLastResult
# ---------------------------------------------------------------------------

class TestLastResult:
    def test_last_result_initially_none(self):
        agent = _make_agent()
        assert agent.last_result() is None

    def test_last_result_stored_after_curation(self):
        agent = _make_agent()
        fake_result = CurationResult(repos_processed=3, dry_run=True)
        with agent._lock:
            agent._last_result = fake_result
        assert agent.last_result().repos_processed == 3


# ---------------------------------------------------------------------------
# TestImport
# ---------------------------------------------------------------------------

class TestImport:
    def test_import_educator_agent(self):
        from core.agents.educator_agent import EducatorAgent, EducatorConfig, CurationResult  # noqa
        assert EducatorAgent.VERSION == "9.1.0"

    def test_import_via_agents_package(self):
        from core.agents import EducatorAgent  # noqa
        assert EducatorAgent is not None

    def test_create_factory(self):
        agent = EducatorAgent.create()
        assert isinstance(agent, EducatorAgent)


# ---------------------------------------------------------------------------
# TestStarsFilter (ED-03)
# ---------------------------------------------------------------------------

class TestStarsFilter:
    def setup_method(self):
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        cfg = EducatorConfig(
            dry_run=True, sleep_between_repos=0, fetch_timeout=5,
            stars_threshold=1000, cache_dir=self._tmpdir,
        )
        self.agent = EducatorAgent(cfg=cfg)

    def test_repo_above_threshold_accepted(self):
        with patch.object(self.agent, "_github_request",
                          return_value={"stargazers_count": 5000}):
            assert self.agent._check_stars("owner", "repo") is True

    def test_repo_below_threshold_rejected(self):
        with patch.object(self.agent, "_github_request",
                          return_value={"stargazers_count": 500}):
            assert self.agent._check_stars("owner", "repo") is False

    def test_threshold_zero_always_pass(self):
        self.agent._cfg.stars_threshold = 0
        assert self.agent._check_stars("owner", "repo") is True

    def test_api_failure_accepted_by_default(self):
        with patch.object(self.agent, "_github_request", return_value=None):
            assert self.agent._check_stars("owner", "repo") is True


# ---------------------------------------------------------------------------
# TestCommitHash (ED-03)
# ---------------------------------------------------------------------------

class TestCommitHash:
    def setup_method(self):
        self.agent = _make_agent()

    def test_commit_hash_extracted(self):
        sha = "abc123def456" + "0" * 28
        with patch.object(self.agent, "_github_request", return_value={"sha": sha}):
            result = self.agent._get_commit_hash("owner", "repo")
        assert result == sha[:12]

    def test_commit_hash_empty_on_failure(self):
        with patch.object(self.agent, "_github_request", return_value=None):
            result = self.agent._get_commit_hash("owner", "repo")
        assert result == ""


# ---------------------------------------------------------------------------
# TestSandboxCheck (ED-04)
# ---------------------------------------------------------------------------

class TestSandboxCheck:
    def setup_method(self):
        self.agent = _make_agent()

    def test_valid_syntax_returns_bool(self):
        """_sandbox_check retourne toujours un bool, pas d'exception."""
        src = "def foo(x: int) -> int:\n    return x + 1\n"
        result = self.agent._sandbox_check(src)
        assert isinstance(result, bool)

    def test_syntax_error_rejected(self):
        """SyntaxError detectee dans stderr -> False."""
        src = "def foo(:\n    pass\n"
        with patch("core.sandbox_engine.SandboxEngine") as MockSandbox:
            instance = MockSandbox.return_value
            instance.run.return_value = (False, "", "SyntaxError: invalid syntax", 1)
            result = self.agent._sandbox_check(src)
        assert result is False

    def test_sandbox_unavailable_returns_true(self):
        """Si la sandbox leve une exception, accepter par defaut."""
        with patch("core.sandbox_engine.SandboxEngine", side_effect=ImportError("no sandbox")):
            result = self.agent._sandbox_check("def foo(): pass")
        assert result is True


# ---------------------------------------------------------------------------
# TestExportSftPairs (ED-04)
# ---------------------------------------------------------------------------

class TestExportSftPairs:
    def setup_method(self):
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self.agent = _make_agent()

    def test_no_skill_lib_returns_zero(self):
        self.agent._skill_lib = None
        assert self.agent.export_sft_pairs(output_dir=self._tmpdir) == 0

    def test_exports_external_only(self):
        from core.skill_library import SkillEntry
        from unittest.mock import MagicMock
        internal = MagicMock()
        internal.source_type = "internal"
        external = MagicMock()
        external.source_type = "external"
        external.name = "foo"
        external.source = "owner/repo"
        external.body = "def foo() -> None:\n    '''doc.'''\n    pass\n"
        external.skill_id = "ext_abc_foo000"

        lib = MagicMock()
        lib.list_all.return_value = [internal, external]
        self.agent._skill_lib = lib

        ev_mock = MagicMock()
        ev_mock.score = 80
        self.agent._evaluator.evaluate = MagicMock(return_value=ev_mock)

        count = self.agent.export_sft_pairs(output_dir=self._tmpdir)
        assert count == 1

        import json
        from pathlib import Path
        pairs_file = Path(self._tmpdir) / "sft_pairs.jsonl"
        assert pairs_file.exists()
        pair = json.loads(pairs_file.read_text(encoding="utf-8"))
        assert pair["source"] == "external"
        assert "foo" in pair["instruction"]

    def test_low_score_skipped(self):
        """Skills avec score < min_score ne doivent pas etre exportes."""
        from unittest.mock import MagicMock
        external = MagicMock()
        external.source_type = "external"
        external.name = "bar"
        external.source = "owner/repo2"
        external.body = "def bar(): pass"
        external.skill_id = "ext_bar_000001"

        lib = MagicMock()
        lib.list_all.return_value = [external]
        self.agent._skill_lib = lib

        ev_mock = MagicMock()
        ev_mock.score = 30  # Sous le seuil defaut (70)
        self.agent._evaluator.evaluate = MagicMock(return_value=ev_mock)

        count = self.agent.export_sft_pairs(output_dir=self._tmpdir, min_score=70)
        assert count == 0


# ---------------------------------------------------------------------------
# TestRunDiff (ED-04)
# ---------------------------------------------------------------------------

class TestRunDiff:
    def setup_method(self):
        self.agent = _make_agent()

    def test_run_diff_returns_expected_keys(self):
        """run_diff() retourne un dict avec les 5 cles attendues."""
        with patch.object(self.agent, "run_curation", return_value=CurationResult(
            repos_processed=2, files_fetched=10, errors=[]
        )):
            diff = self.agent.run_diff(repos_filter=["psf/requests"])
        assert "new_skills" in diff
        assert "stale_skills" in diff
        assert "repos_checked" in diff
        assert "files_would_fetch" in diff
        assert "errors" in diff

    def test_run_diff_no_skill_lib(self):
        """Sans _skill_lib, les listes new/stale sont vides."""
        self.agent._skill_lib = None
        with patch.object(self.agent, "run_curation", return_value=CurationResult()):
            diff = self.agent.run_diff()
        assert diff["new_skills"] == []
        assert diff["stale_skills"] == []
