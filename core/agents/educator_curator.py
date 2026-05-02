# -*- coding: utf-8-sig -*-
"""
LCCA V9.1 -- EducatorCurator : logique de curation, SFT export, diff, sandbox.

Responsabilites :
    - run_curation()         : boucle principale fetch -> filter -> ingest
    - run_diff()             : simulation dry_run avec rapport delta
    - _sandbox_check()       : validation executable en sandbox
    - export_sft_pairs()     : export JSONL pour fine-tuning
    - deprecate_stale_skills(): politique de rarete ED-03
    - _emit()                : callback progression

Aucune dependance vers BaseAgent / bus / A2ALocalBus — testable seul.

REFACTO-08 : extrait de educator_agent.py.
"""
from __future__ import annotations

import logging
import time
import threading
from typing import Any, Callable, List, Optional

import config

log = logging.getLogger("lcca.educator.curator")


class EducatorCurator:
    """
    Logique de curation pour EducatorAgent.

    Injecte :
        whitelist   : list[tuple[str, str]]  -- repos (owner, repo)
        ingester    : EducatorIngester
        cfg         : EducatorConfig
        lock        : threading.Lock partage
    """

    def __init__(
        self,
        whitelist : List,
        ingester  : Any,   # EducatorIngester (evite import circulaire)
        cfg       : Any,   # EducatorConfig
        lock      : threading.Lock,
        evaluator : Any = None,
    ) -> None:
        self._whitelist = whitelist
        self._ingester  = ingester
        self._cfg       = cfg
        self._lock      = lock
        self._evaluator = evaluator
        self._running   = False

    # ------------------------------------------------------------------
    # Curation principale
    # ------------------------------------------------------------------

    def run_curation(
        self,
        result_cls   : Any,
        dry_run      : Optional[bool]      = None,
        repos_filter : Optional[List[str]] = None,
        progress_cb  : Optional[Callable[[str], None]] = None,
    ) -> Any:
        """
        Lance la curation complete : fetch -> filter -> ingest.

        Args:
            result_cls   : classe CurationResult a instancier
            dry_run      : True = validation seule, pas d'ecriture memoire
            repos_filter : Liste "owner/repo" a traiter. None = whitelist complete
            progress_cb  : Callback(message) appele a chaque etape

        Returns:
            CurationResult
        """
        if dry_run is None:
            dry_run = self._cfg.dry_run

        with self._lock:
            if self._running:
                log.warning("Curation deja en cours -- ignoree.")
                return result_cls(errors=["already_running"], dry_run=dry_run)
            self._running = True

        result    = result_cls(dry_run=dry_run)
        whitelist = self._whitelist

        if repos_filter is not None:
            allowed   = {f"{o}/{r}" for o, r in whitelist}
            whitelist = [
                (o, r) for o, r in self._whitelist
                if f"{o}/{r}" in repos_filter and f"{o}/{r}" in allowed
            ]

        try:
            for owner, repo in whitelist:
                self._emit(progress_cb, f"Curation {owner}/{repo}...")
                try:
                    self._ingester.process_repo(owner, repo, result, dry_run)
                    result.repos_processed += 1
                except Exception as exc:
                    msg = f"{owner}/{repo}: {exc}"
                    log.error("Erreur repo %s/%s: %s", owner, repo, exc)
                    result.errors.append(msg)
                finally:
                    time.sleep(self._cfg.sleep_between_repos)
        finally:
            with self._lock:
                self._running = False

        log.info(
            "Curation terminee -- repos=%d files=%d skills=%d errors=%d dry=%s",
            result.repos_processed, result.files_fetched,
            result.skills_ingested, len(result.errors), dry_run,
        )
        return result

    # ------------------------------------------------------------------
    # Diff
    # ------------------------------------------------------------------

    def run_diff(
        self,
        result_cls   : Any,
        repos_filter : Optional[List[str]] = None,
        progress_cb  : Optional[Callable[[str], None]] = None,
        skill_lib    : Any = None,
    ) -> dict:
        """
        Mode diff : simule une curation dry_run=True et rapporte le delta.

        Returns:
            dict avec new_skills, stale_skills, repos_checked, files_would_fetch, errors
        """
        result = self.run_curation(
            result_cls=result_cls,
            dry_run=True,
            repos_filter=repos_filter,
            progress_cb=progress_cb,
        )

        new_skills: List[str] = []
        stale_skills: List[str] = []

        if skill_lib:
            try:
                for entry in skill_lib.list_all():
                    if getattr(entry, "source_type", "internal") == "external" \
                            and getattr(entry, "usage_count", 0) == 0:
                        stale_skills.append(entry.skill_id)
            except Exception:
                pass

        return {
            "new_skills"       : new_skills,
            "stale_skills"     : stale_skills,
            "repos_checked"    : result.repos_processed,
            "files_would_fetch": result.files_fetched,
            "errors"           : result.errors,
        }

    # ------------------------------------------------------------------
    # Sandbox check
    # ------------------------------------------------------------------

    @staticmethod
    def sandbox_check(body: str) -> bool:
        """
        Verifie qu'un snippet est executable en sandbox (ED-04).
        Silencieux si la sandbox n'est pas disponible (retourne True).

        Returns:
            True si executable ou sandbox indisponible.
            False si SyntaxError detectee.
        """
        try:
            from core.sandbox_engine import SandboxEngine
            sandbox    = SandboxEngine(mode="soft")
            run_result = sandbox.run(body, timeout=5)
            if isinstance(run_result, tuple) and len(run_result) >= 3:
                error_str = str(run_result[2]) if run_result[2] else ""
            else:
                error_str = str(getattr(run_result, "error", "") or "")
            return "SyntaxError" not in error_str
        except Exception:
            return True

    # ------------------------------------------------------------------
    # Export SFT
    # ------------------------------------------------------------------

    def export_sft_pairs(
        self,
        skill_lib  : Any,
        output_dir : Optional[str] = None,
        min_score  : Optional[int] = None,
    ) -> int:
        """
        Exporte les skills externes comme paires instruction/reponse pour SFT.

        Format JSONL :
            {"instruction": "...", "response": "<code>", "source": "external", ...}

        Returns:
            Nombre de paires exportees.
        """
        import json as _json
        from pathlib import Path as _Path

        if skill_lib is None:
            log.warning("export_sft_pairs: SkillLibrary non configuree -- aucune paire exportee.")
            return 0

        if output_dir is None:
            base       = getattr(config, "TRAINING_OUTPUT_DIR", "training_data")
            output_dir = str(_Path(base) / "educator")
        if min_score is None:
            min_score = getattr(config, "EDUCATOR_MIN_SCORE", 70)

        out_dir  = _Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "sft_pairs.jsonl"
        count    = 0

        try:
            with out_path.open("w", encoding="utf-8") as f:
                for entry in skill_lib.list_all():
                    if getattr(entry, "source_type", "internal") != "external":
                        continue
                    try:
                        ev = self._evaluator.evaluate(entry.body)
                        if ev.score < min_score:
                            continue
                    except Exception:
                        pass

                    instruction = (
                        f"Ecris une fonction Python nommee `{entry.name}` "
                        f"provenant du projet `{entry.source}`, "
                        f"bien documentee, avec type hints."
                    )
                    pair = {
                        "instruction": instruction,
                        "response"   : entry.body,
                        "source"     : "external",
                        "skill_id"   : entry.skill_id,
                        "repo"       : entry.source,
                    }
                    f.write(_json.dumps(pair, ensure_ascii=False) + "\n")
                    count += 1
            log.info("export_sft_pairs: %d paires exportees -> %s", count, out_path)
        except Exception as exc:
            log.error("export_sft_pairs: echec export: %s", exc)

        return count

    # ------------------------------------------------------------------
    # Deprecation rarete
    # ------------------------------------------------------------------

    def deprecate_stale_skills(
        self,
        skill_lib : Any,
        memory    : Any,
        days      : Optional[int] = None,
    ) -> int:
        """
        Marque comme deprecated les skills externes non utilises depuis N jours.

        Returns:
            Nombre de skills marques deprecated.
        """
        if memory is None or skill_lib is None:
            return 0
        if days is None:
            days = getattr(config, "EDUCATOR_SKILL_DEPRECATION_DAYS", 30)

        import time as _time
        cutoff = _time.time() - days * 86400
        count  = 0
        try:
            for entry in skill_lib.list_all():
                if getattr(entry, "source_type", "internal") != "external":
                    continue
                if getattr(entry, "usage_count", 0) > 0:
                    continue
                last_used = getattr(entry, "last_used_at", 0) or 0
                if last_used < cutoff:
                    skill_lib.deprecate(entry.skill_id)
                    count += 1
        except Exception as exc:
            log.debug("deprecate_stale_skills: %s", exc)

        log.info("deprecate_stale_skills: %d skills marques deprecated", count)
        return count

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------

    @staticmethod
    def _emit(cb: Optional[Callable[[str], None]], msg: str) -> None:
        if cb:
            try:
                cb(msg)
            except Exception:
                pass
