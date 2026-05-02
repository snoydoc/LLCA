# -*- coding: utf-8-sig -*-
"""
tests/test_ed_02.py -- Sprint ED-02 -- Robustesse P1

Tests de robustesse de l'EducatorAgent :
- Retry reseau avec backoff exponentiel
- Persistance cross-session des hashes
- Edge cases encodages (latin-1, cp1252)
- Fichiers Python malformes (SyntaxError)
- repos_filter vide
- Constantes config ED-02

0 appel reseau reel | 0 SQLite externe | 0 dependance Ollama
"""
from __future__ import annotations

import json
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from core.agents.educator_agent import EducatorAgent, EducatorConfig, CurationResult


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_agent(
    dry_run: bool = True,
    retry_max: int = 3,
    hash_persist_path: str = "",
) -> EducatorAgent:
    cfg = EducatorConfig(
        dry_run             = dry_run,
        max_files_per_repo  = 5,
        max_skills_per_repo = 3,
        min_score           = 70,
        min_filter_score    = 3,
        sleep_between_repos = 0,
        fetch_timeout       = 5,
        stars_threshold     = 0,
        retry_max           = retry_max,
        hash_persist_path   = hash_persist_path,
    )
    return EducatorAgent(cfg=cfg)


# ---------------------------------------------------------------------------
# TestEducatorConfigED02
# ---------------------------------------------------------------------------

class TestEducatorConfigED02:
    """Verifie que les champs ED-02 existent et ont des valeurs par defaut saines."""

    def test_retry_max_default(self):
        cfg = EducatorConfig()
        assert cfg.retry_max == 3

    def test_hash_persist_path_default_empty(self):
        cfg = EducatorConfig()
        assert cfg.hash_persist_path == ""

    def test_retry_max_custom(self):
        cfg = EducatorConfig(retry_max=5)
        assert cfg.retry_max == 5

    def test_from_config_retry_max(self):
        """from_config() lit EDUCATOR_RETRY_MAX depuis config."""
        import config as _cfg
        original = getattr(_cfg, "EDUCATOR_RETRY_MAX", 3)
        try:
            _cfg.EDUCATOR_RETRY_MAX = 7
            cfg = EducatorConfig.from_config()
            assert cfg.retry_max == 7
        finally:
            _cfg.EDUCATOR_RETRY_MAX = original

    def test_from_config_hash_persist_path(self):
        """from_config() convertit EDUCATOR_HASH_PERSIST_PATH en str."""
        import config as _cfg
        original = getattr(_cfg, "EDUCATOR_HASH_PERSIST_PATH", None)
        try:
            _cfg.EDUCATOR_HASH_PERSIST_PATH = Path("/tmp/test_hashes.json")
            cfg = EducatorConfig.from_config()
            assert isinstance(cfg.hash_persist_path, str)
            assert "test_hashes.json" in cfg.hash_persist_path
        finally:
            _cfg.EDUCATOR_HASH_PERSIST_PATH = original


# ---------------------------------------------------------------------------
# TestRetryMechanism
# ---------------------------------------------------------------------------

class TestRetryMechanism:
    """Verifie le retry avec backoff sur _fetch_file et _github_request."""

    def test_fetch_file_retries_on_failure(self):
        """_fetch_file doit retenter retry_max fois avant de retourner None."""
        agent = _make_agent(retry_max=3)
        call_count = 0

        def bad_urlopen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise OSError("connection refused")

        with patch("urllib.request.urlopen", side_effect=bad_urlopen), \
             patch("time.sleep"):  # Pas de vraie pause en test
            result = agent._fetch_file("owner", "repo", "file.py")

        assert result is None
        assert call_count == 3  # retry_max = 3

    def test_fetch_file_succeeds_on_second_attempt(self):
        """_fetch_file retourne le contenu si la 2eme tentative reussit."""
        agent = _make_agent(retry_max=3)
        attempt = 0

        class FakeResp:
            def read(self):
                return b"def foo() -> None:\n    pass\n"
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        def flaky_urlopen(*args, **kwargs):
            nonlocal attempt
            attempt += 1
            if attempt < 2:
                raise OSError("flaky network")
            return FakeResp()

        with patch("urllib.request.urlopen", side_effect=flaky_urlopen), \
             patch("time.sleep"):
            result = agent._fetch_file("owner", "repo", "file.py")

        assert result is not None
        assert "def foo" in result
        assert attempt == 2

    def test_github_request_retries_on_failure(self):
        """_github_request doit retenter retry_max fois."""
        agent = _make_agent(retry_max=2)
        call_count = 0

        def bad_urlopen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise OSError("timeout")

        with patch("urllib.request.urlopen", side_effect=bad_urlopen), \
             patch("time.sleep"):
            result = agent._github_request("https://api.github.com/test")

        assert result is None
        assert call_count == 2

    def test_retry_max_one_no_sleep(self):
        """retry_max=1 -> 1 seule tentative, pas de sleep entre essais."""
        agent = _make_agent(retry_max=1)
        sleep_calls = []

        def bad_urlopen(*args, **kwargs):
            raise OSError("fail")

        with patch("urllib.request.urlopen", side_effect=bad_urlopen), \
             patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            result = agent._fetch_file("owner", "repo", "file.py")

        assert result is None
        assert len(sleep_calls) == 0  # retry_max=1 -> pas de sleep inter-essais

    def test_fetch_file_latin1_fallback(self):
        """_fetch_file doit decoder en latin-1 si utf-8 echoue."""
        agent = _make_agent(retry_max=1)
        latin1_bytes = "def foo():\n    # Accentue: \xe9\xe0\xfc\n    pass\n".encode("latin-1")

        class FakeResp:
            def read(self):
                return latin1_bytes
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        with patch("urllib.request.urlopen", return_value=FakeResp()):
            result = agent._fetch_file("owner", "repo", "file.py")

        assert result is not None
        # latin-1 decode doit reussir
        assert "def foo" in result


# ---------------------------------------------------------------------------
# TestHashPersistence
# ---------------------------------------------------------------------------

class TestHashPersistence:
    """Verifie la persistance cross-session des hashes."""

    def test_persist_hashes_writes_json(self):
        """_persist_hashes() ecrit un JSON lisible."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "hashes.json")
            agent = _make_agent(dry_run=False, hash_persist_path=path)
            agent._ingested_hashes = {"abc123", "def456"}
            agent._persist_hashes()

            data = json.loads(Path(path).read_text(encoding="utf-8"))
            assert set(data) == {"abc123", "def456"}

    def test_load_persisted_hashes_restores_set(self):
        """_load_persisted_hashes() charge les hashes depuis le fichier."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "hashes.json")
            Path(path).write_text(
                json.dumps(["aaa111", "bbb222"]), encoding="utf-8"
            )
            agent = _make_agent(hash_persist_path=path)
            # Les hashes doivent etre charges dans __init__
            assert "aaa111" in agent._ingested_hashes
            assert "bbb222" in agent._ingested_hashes

    def test_load_missing_file_silent(self):
        """_load_persisted_hashes() est silencieux si le fichier n'existe pas."""
        agent = _make_agent(hash_persist_path="/tmp/nonexistent_lcca_test_99.json")
        # Aucune exception, set vide
        assert len(agent._ingested_hashes) == 0

    def test_persist_disabled_if_path_empty(self):
        """Si hash_persist_path est vide, _persist_hashes() ne cree aucun fichier."""
        agent = _make_agent(hash_persist_path="")
        agent._ingested_hashes = {"xyz"}
        # Ne doit pas lever d'exception
        agent._persist_hashes()
        # Aucun fichier cree dans le repertoire courant
        assert not Path("educator_hashes.json").exists()

    def test_dedup_cross_session(self):
        """Un hash persiste doit empecher la re-ingestion dans une nouvelle instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "hashes.json")

            # Session 1 : ingest + persist
            agent1 = _make_agent(dry_run=False, hash_persist_path=path)
            memory1 = MagicMock()
            memory1.store.return_value = MagicMock(stored=True)
            agent1._memory = memory1
            src = "def bar() -> int:\n    '''doc.'''\n    return 42\n"
            agent1._ingest(src, "o", "r", "bar.py", dry_run=False)
            agent1._persist_hashes()
            assert memory1.store.call_count == 1

            # Session 2 : meme src, hash present -> skip
            agent2 = _make_agent(dry_run=False, hash_persist_path=path)
            memory2 = MagicMock()
            memory2.store.return_value = MagicMock(stored=True)
            agent2._memory = memory2
            agent2._ingest(src, "o", "r", "bar.py", dry_run=False)
            assert memory2.store.call_count == 0  # Skip car hash deja present

    def test_persist_called_after_wet_curation(self):
        """_persist_hashes() doit etre appele apres une curation dry_run=False."""
        agent = _make_agent(dry_run=False, hash_persist_path="/tmp/test_lcca.json")
        with patch.object(agent, "_persist_hashes") as mock_persist, \
             patch.object(agent._ingester, "process_repo"):  # mock au bon niveau
            agent.run_curation(dry_run=False, repos_filter=["psf/requests"])
        mock_persist.assert_called_once()

    def test_persist_not_called_in_dry_run(self):
        """_persist_hashes() ne doit PAS etre appele en dry_run."""
        agent = _make_agent(dry_run=True, hash_persist_path="/tmp/test_lcca.json")
        with patch.object(agent, "_persist_hashes") as mock_persist, \
             patch.object(agent._ingester, "process_repo"):  # mock au bon niveau
            agent.run_curation(dry_run=True, repos_filter=["psf/requests"])
        mock_persist.assert_not_called()


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases : SyntaxError, repos_filter vide, fichier binaire."""

    def test_syntax_error_ingested_as_context(self):
        """Un fichier Python invalide doit etre ingere comme contexte brut (pas de skills)."""
        agent = _make_agent()
        memory = MagicMock()
        memory.store.return_value = MagicMock(stored=True)
        agent._memory = memory
        broken_src = "def foo(:\n    pass\n"  # SyntaxError intentionnel
        counts = agent._ingest(broken_src, "o", "r", "broken.py", dry_run=False)
        # Contexte ingere (count=1), mais aucun skill extrait (AST echoue)
        assert counts["context"] == 1
        assert counts["skills"] == 0

    def test_repos_filter_empty_processes_nothing(self):
        """repos_filter=[] doit produire une curation avec 0 repo traite."""
        agent = _make_agent()
        result = agent.run_curation(dry_run=True, repos_filter=[])
        assert result.repos_processed == 0
        assert result.files_fetched == 0

    def test_repos_filter_unknown_repo_ignored(self):
        """Un repo hors whitelist dans repos_filter est ignore silencieusement."""
        agent = _make_agent()
        # "notreal/notreal" n'est pas dans la whitelist
        result = agent.run_curation(
            dry_run=True, repos_filter=["notreal/notreal"]
        )
        assert result.repos_processed == 0

    def test_ingest_binary_like_content_no_crash(self):
        """_ingest avec du contenu non-parseable ne leve pas d'exception."""
        agent = _make_agent()
        binary_like = "\x00\x01\x02\x03" * 50
        counts = agent._ingest(binary_like, "o", "r", "bin.py", dry_run=True)
        # Pas d'exception, contexte tente
        assert isinstance(counts, dict)

    def test_config_educator_retry_max_present(self):
        """EDUCATOR_RETRY_MAX doit etre present dans config.py."""
        import config as _cfg
        assert hasattr(_cfg, "EDUCATOR_RETRY_MAX")
        assert isinstance(_cfg.EDUCATOR_RETRY_MAX, int)
        assert _cfg.EDUCATOR_RETRY_MAX >= 1

    def test_config_educator_hash_persist_path_present(self):
        """EDUCATOR_HASH_PERSIST_PATH doit etre present dans config.py."""
        import config as _cfg
        assert hasattr(_cfg, "EDUCATOR_HASH_PERSIST_PATH")
        # Doit etre un Path ou une string non vide
        assert str(_cfg.EDUCATOR_HASH_PERSIST_PATH)
