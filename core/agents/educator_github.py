# -*- coding: utf-8-sig -*-
"""
educator_github.py -- EducatorAgent V9.1 -- Couche reseau GitHub

Responsabilite unique : acces a l'API GitHub et fetch de fichiers bruts.
Isole du reste de l'agent pour faciliter les mocks en test et la maintenabilite.

Extrait de educator_agent.py (REFACTO-02, 2026-04-21).
"""
from __future__ import annotations

import json
import logging
import time
from time import sleep as _sleep
import urllib.request
from typing import Optional

log = logging.getLogger("lcca.educator.github")


class EducatorGitHub:
    """
    Couche reseau GitHub : API REST + fetch fichiers bruts.

    Gestion :
    - Token d'authentification optionnel (EDUCATOR_GITHUB_TOKEN)
    - Rate limit X-RateLimit-Remaining
    - Retry avec backoff exponentiel (retry_max, fetch_timeout)
    - Encodages multiples (utf-8, latin-1, cp1252)
    """

    def __init__(
        self,
        github_token  : str = "",
        retry_max     : int = 3,
        fetch_timeout : int = 300,
    ) -> None:
        self._github_token  = github_token
        self._retry_max     = retry_max
        self._fetch_timeout = fetch_timeout

    # -------------------------------------------------------------------------
    # Appel API GitHub (JSON)
    # -------------------------------------------------------------------------

    def github_request(self, url: str) -> Optional[dict]:
        """Appel API GitHub avec token optionnel, gestion rate limit et retry backoff."""
        headers = {"Accept": "application/vnd.github+json"}
        if self._github_token:
            headers["Authorization"] = f"Bearer {self._github_token}"
        req = urllib.request.Request(url, headers=headers)
        for attempt in range(max(1, self._retry_max)):
            try:
                with urllib.request.urlopen(req, timeout=self._fetch_timeout) as resp:
                    remaining = resp.headers.get("X-RateLimit-Remaining", "999")
                    if int(remaining) < 10:
                        reset_at = int(resp.headers.get("X-RateLimit-Reset", 0))
                        wait = max(5, reset_at - int(time.time()) + 5)
                        log.warning("Rate limit GitHub proche -- pause %ds", wait)
                        _sleep(wait)
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as exc:
                wait = 2 ** attempt
                log.debug(
                    "GitHub request failed %s (attempt %d/%d): %s -- retry dans %ds",
                    url, attempt + 1, self._retry_max, exc, wait,
                )
                if attempt < self._retry_max - 1:
                    _sleep(wait)
        return None

    # -------------------------------------------------------------------------
    # Fetch fichier brut (raw.githubusercontent.com)
    # -------------------------------------------------------------------------

    def fetch_file(self, owner: str, repo: str, path: str) -> Optional[str]:
        """Fetch brut d'un fichier avec tentatives d'encodage successives."""
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{path}"
        req = urllib.request.Request(url)
        if self._github_token:
            req.add_header("Authorization", f"Bearer {self._github_token}")
        for attempt in range(max(1, self._retry_max)):
            try:
                with urllib.request.urlopen(req, timeout=self._fetch_timeout) as resp:
                    raw_bytes = resp.read()
                    for enc in ("utf-8", "latin-1", "cp1252"):
                        try:
                            return raw_bytes.decode(enc)
                        except UnicodeDecodeError:
                            continue
                    return None
            except Exception as exc:
                wait = 2 ** attempt
                log.debug(
                    "Fetch failed %s/%s/%s (attempt %d/%d): %s -- retry dans %ds",
                    owner, repo, path, attempt + 1, self._retry_max, exc, wait,
                )
                if attempt < self._retry_max - 1:
                    _sleep(wait)
        return None

    def fetch_raw(self, owner: str, repo: str, filename: str) -> Optional[str]:
        """Fetch simplifie pour un fichier racine (LICENSE, README...)."""
        return self.fetch_file(owner, repo, filename)

    # -------------------------------------------------------------------------
    # Verification licence
    # -------------------------------------------------------------------------

    def check_license(self, owner: str, repo: str, skip: bool = False) -> bool:
        """Verifie la licence via API, puis fallback lecture fichier LICENSE.

        Args:
            skip : si True, bypasse le check et retourne True directement.
                   Positionne par EducatorIngester pour les repos avec
                   skip_license_check=true dans educator_whitelist.json.
        """
        if skip:
            log.debug("check_license bypasse (skip=True) pour %s/%s", owner, repo)
            return True

        from core.agents.educator_whitelist import ACCEPTED_SPDX

        data = self.github_request(
            f"https://api.github.com/repos/{owner}/{repo}/license"
        )
        if data and "license" in data:
            spdx = (data["license"] or {}).get("spdx_id", "")
            return spdx in ACCEPTED_SPDX

        for fname in ("LICENSE", "LICENSE.txt", "COPYING"):
            raw = self.fetch_raw(owner, repo, fname)
            if raw:
                upper = raw.upper()
                if "GPL" in upper:
                    return False
                if any(k in upper for k in ("MIT LICENSE", "APACHE LICENSE", "BSD", "PYTHON SOFTWARE FOUNDATION")):
                    return True
        return False

    # -------------------------------------------------------------------------
    # Liste des fichiers .py d'un repo
    # -------------------------------------------------------------------------

    def list_py_files(self, owner: str, repo: str) -> list[str]:
        """Liste recursive des .py via l'API Git trees (shallow)."""
        data = self.github_request(
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"
        )
        if not data or "tree" not in data:
            return []
        return [
            item["path"]
            for item in data["tree"]
            if item.get("type") == "blob" and item["path"].endswith((".py", ".pyi"))
        ]

    # -------------------------------------------------------------------------
    # Stars + commit hash (ED-03)
    # -------------------------------------------------------------------------

    def get_stars(self, owner: str, repo: str) -> Optional[int]:
        """Retourne le nombre d'etoiles du repo, None si erreur reseau."""
        data = self.github_request(
            f"https://api.github.com/repos/{owner}/{repo}"
        )
        if data is None:
            return None
        return data.get("stargazers_count", 0)

    def get_commit_hash(self, owner: str, repo: str) -> str:
        """Retourne le SHA court du dernier commit HEAD."""
        data = self.github_request(
            f"https://api.github.com/repos/{owner}/{repo}/commits/HEAD"
        )
        if data and "sha" in data:
            return data["sha"][:12]
        return ""
