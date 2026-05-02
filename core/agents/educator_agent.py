# -*- coding: utf-8-sig -*-
"""
educator_agent.py -- EducatorAgent V9.1

Agent satellite de curation externe.
Recupere du code exemplaire depuis une whitelist de repos GitHub (MIT/Apache/BSD),
filtre selon les regles LCCA, et ingere dans lcca_context.

REFACTO-02 (2026-04-21) :
- Couche reseau extraite dans educator_github.py (EducatorGitHub)
- Couche filtrage extraite dans educator_filter.py (EducatorFilter)

REFACTO-08 (2026-04-22) :
- Pipeline ingest extrait dans educator_ingester.py (EducatorIngester)
- Logique curation extraite dans educator_curator.py (EducatorCurator)
- educator_agent.py : orchestration + interfaces publiques (retrocompat totale)
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import config
from core.agents.base_agent import BaseAgent, AgentResult
from core.agents.agent_card import AgentCard, RecoveryPolicy
from core.agents.a2a_bus import A2ALocalBus
from core.agents.educator_github import EducatorGitHub
from core.agents.educator_filter import EducatorFilter
from core.agents.educator_ingester import EducatorIngester   # REFACTO-08
from core.agents.educator_curator import EducatorCurator     # REFACTO-08
from core.agents.educator_whitelist import WHITELIST as _WHITELIST  # source de verite
from core.code_evaluator import CodeEvaluator

log = logging.getLogger("lcca.educator")


# ---------------------------------------------------------------------------
# WHITELIST -- importe depuis core/agents/educator_whitelist.py
# Ne pas redefinir ici. Modifier educator_whitelist.py uniquement.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# EducatorConfig
# ---------------------------------------------------------------------------

@dataclass
class EducatorConfig:
    dry_run            : bool  = True
    max_files_per_repo : int   = 30
    max_skills_per_repo: int   = 20
    min_score          : int   = 70
    min_filter_score   : int   = 5
    sleep_between_repos: float = 1.0
    fetch_timeout      : int   = 300
    github_token       : str   = ""
    stars_threshold    : int   = 1000
    retry_max          : int   = 3
    hash_persist_path  : str   = ""
    cache_dir          : str   = "memory/educator_cache"

    @classmethod
    def from_config(cls) -> "EducatorConfig":
        persist = getattr(config, "EDUCATOR_HASH_PERSIST_PATH", None)
        return cls(
            dry_run             = getattr(config, "EDUCATOR_DRY_RUN", True),
            max_files_per_repo  = getattr(config, "EDUCATOR_MAX_FILES_PER_REPO", 30),
            max_skills_per_repo = getattr(config, "EDUCATOR_MAX_SKILLS_PER_REPO", 20),
            min_score           = getattr(config, "EDUCATOR_MIN_SCORE", 70),
            min_filter_score    = getattr(config, "EDUCATOR_MIN_FILTER_SCORE", 5),
            sleep_between_repos = getattr(config, "EDUCATOR_SLEEP_BETWEEN_REPOS", 1.0),
            fetch_timeout       = getattr(config, "EDUCATOR_FETCH_TIMEOUT", 300),
            github_token        = getattr(config, "EDUCATOR_GITHUB_TOKEN", ""),
            stars_threshold     = getattr(config, "EDUCATOR_STARS_THRESHOLD", 1000),
            retry_max           = getattr(config, "EDUCATOR_RETRY_MAX", 3),
            hash_persist_path   = str(persist) if persist else "",
        )


# ---------------------------------------------------------------------------
# CurationResult
# ---------------------------------------------------------------------------

@dataclass
class CurationResult:
    repos_processed : int = 0
    files_fetched   : int = 0
    files_filtered  : int = 0
    skills_ingested : int = 0
    context_ingested: int = 0
    errors          : list[str] = field(default_factory=list)
    dry_run         : bool = True


# ---------------------------------------------------------------------------
# EducatorAgent
# ---------------------------------------------------------------------------

class EducatorAgent(BaseAgent):
    """
    Agent satellite de curation externe V9.1.

    Orchestration uniquement — la logique est dans :
        EducatorGitHub   (reseau)
        EducatorFilter   (filtrage)
        EducatorIngester (ingest AST + memoire)    REFACTO-08
        EducatorCurator  (curation + SFT + diff)   REFACTO-08
    """

    VERSION = "9.1.0"

    def __init__(
        self,
        cfg       : Optional[EducatorConfig] = None,
        memory    = None,
        evaluator : Optional[CodeEvaluator]  = None,
        bus       : Optional[A2ALocalBus]    = None,
    ) -> None:
        card = AgentCard(
            name            = "educator",
            version         = self.VERSION,
            capabilities    = ["external_curation", "skill_ingestion", "github_fetch"],
            mcp_tools       = frozenset(),
            recovery_policy = RecoveryPolicy(max_retries=1, retry_delay_sec=5.0),
            description     = "Agent de curation externe V9.1 — fetch GitHub + ingestion memoire",
        )
        super().__init__(card, bus)
        self._cfg       = cfg or EducatorConfig.from_config()
        self._memory    = memory
        self._evaluator = evaluator or CodeEvaluator()
        self._lock      = threading.Lock()
        self._last_result: Optional[CurationResult] = None

        # Deduplication en memoire (partage avec ingester)
        self._ingested_hashes: set[str] = set()

        # REFACTO-02 : couches reseau et filtrage
        self._gh = EducatorGitHub(
            github_token  = self._cfg.github_token,
            retry_max     = self._cfg.retry_max,
            fetch_timeout = self._cfg.fetch_timeout,
        )
        self._flt = EducatorFilter(
            min_filter_score = self._cfg.min_filter_score,
            min_score        = self._cfg.min_score,
            evaluator        = self._evaluator,
        )

        # REFACTO-08 : pipeline ingest
        self._ingester = EducatorIngester(
            gh                  = self._gh,
            flt                 = self._flt,
            memory              = self._memory,
            lock                = self._lock,
            ingested_hashes     = self._ingested_hashes,
            max_files_per_repo  = self._cfg.max_files_per_repo,
            max_skills_per_repo = self._cfg.max_skills_per_repo,
        )

        # REFACTO-08 : logique curation
        self._curator = EducatorCurator(
            whitelist = _WHITELIST,
            ingester  = self._ingester,
            cfg       = self._cfg,
            lock      = self._lock,
            evaluator = self._evaluator,
        )

        # ED-02 : charger hashes persistes
        self._load_persisted_hashes()

    # -------------------------------------------------------------------------
    # A2A -- run_task
    # -------------------------------------------------------------------------

    def run_task(self, contract) -> AgentResult:
        """Lance run_curation() dans un thread daemon."""
        dry_run      = contract.context.get("dry_run", self._cfg.dry_run)
        repos_filter = contract.context.get("repos", None)

        def _run() -> None:
            result = self.run_curation(dry_run=dry_run, repos_filter=repos_filter)
            with self._lock:
                self._last_result = result

        t = threading.Thread(target=_run, daemon=True, name="educator-curation")
        t.start()

        return AgentResult(
            success=True,
            payload={"status": "started", "dry_run": dry_run, "thread": t.name},
        )

    # -------------------------------------------------------------------------
    # CURATION -- delegation vers EducatorCurator
    # -------------------------------------------------------------------------

    def run_curation(
        self,
        dry_run      : Optional[bool]      = None,
        repos_filter : Optional[list[str]] = None,
        progress_cb  : Optional[Callable[[str], None]] = None,
    ) -> CurationResult:
        """Lance la curation complete. Delegu'e a EducatorCurator."""
        result = self._curator.run_curation(
            result_cls=CurationResult,
            dry_run=dry_run,
            repos_filter=repos_filter,
            progress_cb=progress_cb,
        )
        if not result.dry_run:
            self._persist_hashes()
        return result

    def run_diff(
        self,
        repos_filter : Optional[list[str]] = None,
        progress_cb  : Optional[Callable[[str], None]] = None,
    ) -> dict:
        """Mode diff dry_run. Delegu'e a EducatorCurator."""
        skill_lib = getattr(self, "_skill_lib", None)
        return self._curator.run_diff(
            result_cls=CurationResult,
            repos_filter=repos_filter,
            progress_cb=progress_cb,
            skill_lib=skill_lib,
        )

    def export_sft_pairs(
        self,
        output_dir : Optional[str] = None,
        min_score  : Optional[int] = None,
    ) -> int:
        """Export JSONL SFT. Delegu'e a EducatorCurator."""
        skill_lib = getattr(self, "_skill_lib", None)
        self._curator._evaluator = self._evaluator  # sync si patche apres __init__
        return self._curator.export_sft_pairs(
            skill_lib=skill_lib,
            output_dir=output_dir,
            min_score=min_score,
        )

    def deprecate_stale_skills(self, days: Optional[int] = None) -> int:
        """Politique de rarete. Delegu'e a EducatorCurator."""
        skill_lib = getattr(self, "_skill_lib", None)
        return self._curator.deprecate_stale_skills(
            skill_lib=skill_lib,
            memory=self._memory,
            days=days,
        )

    # -------------------------------------------------------------------------
    # Wrappers retrocompat REFACTO-02 (reseau + filtre)
    # -------------------------------------------------------------------------

    def _github_request(self, url: str):
        return self._gh.github_request(url)

    def _check_license(self, owner: str, repo: str) -> bool:
        return self._gh.check_license(owner, repo)

    def _list_py_files(self, owner: str, repo: str) -> list[str]:
        return self._gh.list_py_files(owner, repo)

    def _fetch_file(self, owner: str, repo: str, path: str):
        return self._gh.fetch_file(owner, repo, path)

    def _fetch_raw(self, owner: str, repo: str, filename: str):
        return self._gh.fetch_raw(owner, repo, filename)

    def _filter(self, src: str) -> bool:
        return self._flt.passes(src)

    def _has_type_hints(self, src: str) -> bool:
        return self._flt.has_type_hints(src)

    def _has_bad_print(self, src: str) -> bool:
        return self._flt.has_bad_print(src)

    def _pathlib_rule(self, src: str) -> bool:
        return self._flt.pathlib_rule(src)

    # Wrappers retrocompat REFACTO-08
    def _process_repo(self, owner, repo, result, dry_run):
        self._ingester._memory = self._memory  # sync au cas ou patche apres __init__
        return self._ingester.process_repo(owner, repo, result, dry_run)

    def _ingest(self, src, owner, repo, path, dry_run):
        self._ingester._memory = self._memory  # sync au cas ou patche apres __init__
        return self._ingester.ingest(src, owner, repo, path, dry_run)

    def _extract_symbols(self, src, tree):
        return self._ingester._extract_symbols(src, tree)

    def _sandbox_check(self, body: str) -> bool:
        return self._curator.sandbox_check(body)

    # -------------------------------------------------------------------------
    # ED-03 -- Cache + stars + commit hash (conserves ici car lies a EducatorGitHub)
    # -------------------------------------------------------------------------

    def _check_stars(self, owner: str, repo: str) -> bool:
        threshold = self._cfg.stars_threshold
        if threshold <= 0:
            return True
        cache_key = f"stars_{owner}_{repo}"
        cached = self._cache_read(cache_key)
        if cached is not None:
            return cached.get("ok", False)
        data  = self._github_request(f"https://api.github.com/repos/{owner}/{repo}")
        if data is None:
            return True
        stars = data.get("stargazers_count", 0)
        ok    = stars >= threshold
        self._cache_write(cache_key, {"ok": ok, "stars": stars})
        return ok

    def _cache_path(self, key: str) -> Path:
        import os
        cache_dir = Path(self._cfg.cache_dir)
        if not cache_dir.is_absolute():
            cache_dir = Path(os.getcwd()) / cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        safe_key = key.replace("/", "_").replace(":", "_")
        return cache_dir / f"{safe_key}.json"

    def _cache_read(self, key: str):
        import time as _time
        p = self._cache_path(key)
        if not p.exists():
            return None
        try:
            data  = json.loads(p.read_text(encoding="utf-8"))
            age_h = (_time.time() - data.get("_cached_at", 0)) / 3600
            if age_h > getattr(config, "EDUCATOR_CACHE_TTL_HOURS", 24):
                return None
            return data
        except Exception:
            return None

    def _cache_write(self, key: str, value: dict) -> None:
        import time as _time
        p = self._cache_path(key)
        try:
            payload = {**value, "_cached_at": _time.time()}
            p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            log.debug("Cache write failed %s: %s", key, exc)

    def _get_commit_hash(self, owner: str, repo: str) -> str:
        data = self._github_request(
            f"https://api.github.com/repos/{owner}/{repo}/commits/HEAD"
        )
        if data and "sha" in data:
            return data["sha"][:12]
        return ""

    # -------------------------------------------------------------------------
    # ED-02 -- Persistance hashes
    # -------------------------------------------------------------------------

    def _load_persisted_hashes(self) -> None:
        path = self._cfg.hash_persist_path
        if not path:
            return
        try:
            p = Path(path)
            if p.exists():
                data   = json.loads(p.read_text(encoding="utf-8"))
                loaded = set(data) if isinstance(data, list) else set()
                with self._lock:
                    self._ingested_hashes.update(loaded)
                log.info("Educator: %d hashes charges depuis %s", len(loaded), path)
        except Exception as exc:
            log.warning("Educator: impossible de charger hashes persistes: %s", exc)

    def _persist_hashes(self) -> None:
        path = self._cfg.hash_persist_path
        if not path:
            return
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                hashes_snapshot = list(self._ingested_hashes)
            p.write_text(json.dumps(hashes_snapshot, indent=2), encoding="utf-8")
            log.info("Educator: %d hashes persistes dans %s", len(hashes_snapshot), path)
        except Exception as exc:
            log.warning("Educator: impossible de persister hashes: %s", exc)

    # -------------------------------------------------------------------------
    # Utilitaires
    # -------------------------------------------------------------------------

    @staticmethod
    def _emit(cb: Optional[Callable[[str], None]], msg: str) -> None:
        if cb:
            try:
                cb(msg)
            except Exception:
                pass

    def last_result(self) -> Optional[CurationResult]:
        with self._lock:
            return self._last_result

    # ------------------------------------------------------------------
    # Propriete retrocompat : agent._running -> curator._running
    # Les anciens tests patchent agent._running directement.
    # ------------------------------------------------------------------

    @property
    def _running(self) -> bool:
        return self._curator._running

    @_running.setter
    def _running(self, value: bool) -> None:
        self._curator._running = value

    @classmethod
    def create(
        cls,
        memory = None,
        cfg    : Optional[EducatorConfig] = None,
        bus    : Optional[A2ALocalBus]    = None,
    ) -> "EducatorAgent":
        return cls(cfg=cfg, memory=memory, bus=bus)
