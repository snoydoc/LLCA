# -*- coding: utf-8-sig -*-
"""
LCCA V9.1 -- EducatorIngester : pipeline fetch -> filter -> ingest.

Responsabilites :
    - _process_repo()    : orchestre fetch -> filter -> ingest pour un repo
    - _ingest()          : deduplication SHA-256 + AST + stockage memoire
    - _extract_symbols() : extrait fonctions/classes top-level publiques

Aucune dependance vers BaseAgent / bus / A2ALocalBus — testable seul.

REFACTO-08 : extrait de educator_agent.py.
"""
from __future__ import annotations

import ast
import hashlib
import logging
import sys
import threading
from typing import Any, Dict, List, Optional

log = logging.getLogger("lcca.educator.ingester")


class EducatorIngester:
    """
    Pipeline fetch → filter → ingest pour un repo GitHub.

    Parametres injectes depuis EducatorAgent :
        gh          : EducatorGitHub  (couche reseau)
        flt         : EducatorFilter  (7 regles LCCA)
        memory      : MemoryEngine ou None
        lock        : threading.Lock partage (deduplication thread-safe)
        ingested_hashes : set[str] partage
        max_files_per_repo  : int
        max_skills_per_repo : int
    """

    def __init__(
        self,
        gh,
        flt,
        memory,
        lock             : threading.Lock,
        ingested_hashes  : set,
        max_files_per_repo  : int = 30,
        max_skills_per_repo : int = 20,
    ) -> None:
        self._gh                  = gh
        self._flt                 = flt
        self._memory              = memory
        self._lock                = lock
        self._ingested_hashes     = ingested_hashes
        self._max_files_per_repo  = max_files_per_repo
        self._max_skills_per_repo = max_skills_per_repo

        # Charge le skip set depuis educator_whitelist.json
        try:
            from core.agents.educator_whitelist import load_skip_set
            self._skip_license_set: set = load_skip_set()
        except Exception:
            self._skip_license_set = set()

    # ------------------------------------------------------------------
    # Interface principale
    # ------------------------------------------------------------------

    def process_repo(
        self,
        owner   : str,
        repo    : str,
        result  : Any,   # CurationResult (evite import circulaire)
        dry_run : bool,
    ) -> None:
        """
        Traite un repo : verifie licence, liste et filtre les .py, ingere.

        Modifie result en place (files_fetched, files_filtered, skills_ingested,
        context_ingested).
        """
        if not self._gh.check_license(owner, repo, skip=f"{owner}/{repo}" in self._skip_license_set):
            log.info("Licence non conforme -- repo ignore: %s/%s", owner, repo)
            return

        files = self._gh.list_py_files(owner, repo)
        skills_this_repo = 0

        for path in files[: self._max_files_per_repo]:
            src = self._gh.fetch_file(owner, repo, path)
            if src is None:
                continue
            result.files_fetched += 1

            if not self._flt.passes(src):
                continue
            result.files_filtered += 1

            if skills_this_repo < self._max_skills_per_repo:
                added = self.ingest(src, owner, repo, path, dry_run)
                result.skills_ingested  += added["skills"]
                result.context_ingested += added["context"]
                skills_this_repo += added["skills"]

    def ingest(
        self,
        src     : str,
        owner   : str,
        repo    : str,
        path    : str,
        dry_run : bool,
    ) -> Dict[str, int]:
        """
        Ingere le fichier filtre dans MemoryEngine (lcca_context).

        Deduplication : hash SHA-256 du corps, skip si deja present.
        AST fallback  : si ast.parse() echoue, ingere comme contexte brut.

        Returns:
            {"skills": int, "context": int}
        """
        body_hash    = hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]
        source_label = f"{owner}/{repo}/{path}"
        counts       = {"skills": 0, "context": 0}

        with self._lock:
            if body_hash in self._ingested_hashes:
                return counts
            if not dry_run:
                self._ingested_hashes.add(body_hash)

        # Extraction AST avec fallback
        symbols: List = []
        try:
            tree    = ast.parse(src, feature_version=sys.version_info[:2])
            symbols = self._extract_symbols(src, tree)
        except (SyntaxError, ValueError) as exc:
            log.debug(
                "AST parse failed %s: %s -- contexte brut seulement", source_label, exc
            )

        if symbols:
            counts["skills"] = len(symbols)

        # Ingestion contexte brut
        if self._memory:
            ctx_id  = f"ext_ctx_{body_hash}"
            ctx_doc = {
                "id"         : ctx_id,
                "content"    : src[:2000],
                "source"     : source_label,
                "source_type": "external",
                "repo"       : f"{owner}/{repo}",
            }
            if not dry_run:
                try:
                    self._memory.store("lcca_context", ctx_doc)
                except Exception as exc:
                    log.debug("Memory store failed %s: %s", ctx_id, exc)
            counts["context"] += 1

        return counts

    @staticmethod
    def _extract_symbols(src: str, tree: ast.Module) -> List:
        """
        Extrait les fonctions et classes publiques de premier niveau.

        Retourne une liste de (nom, code_source).
        Exclut les symboles prives (prefixe _).
        """
        symbols = []
        lines   = src.splitlines()
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            if getattr(node, "col_offset", 1) != 0:
                continue
            if node.name.startswith("_"):
                continue
            start = node.lineno - 1
            end   = getattr(node, "end_lineno", start + 10)
            body  = "\n".join(lines[start:end])
            symbols.append((node.name, body))
        return symbols
