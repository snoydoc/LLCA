# -*- coding: utf-8-sig -*-
"""
educator_whitelist.py -- Loader de la whitelist Educator LCCA

Source de verite unique : core/agents/educator_whitelist.json
Toute modification (ajout, retrait) doit se faire dans ce JSON.

Expose :
    WHITELIST         : list[tuple[str, str]]   -- (owner, repo)
    WHITELIST_PATH    : Path                    -- chemin absolu du JSON
    ACCEPTED_SPDX     : frozenset[str]          -- licences SPDX acceptees
    load_whitelist()  : recharge le JSON depuis le disque (utile apres ecriture)
    load_whitelist_full() : retourne la liste complete de dicts
    load_skip_set()   : retourne set["owner/repo"] ayant skip_license_check=true
    save_whitelist()  : ecrit une liste de dicts [{owner, repo, description}] dans le JSON
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("lcca.educator.whitelist")

WHITELIST_PATH: Path = Path(__file__).resolve().parent / "educator_whitelist.json"

# Licences SPDX acceptees (Option 3 : set elargi)
ACCEPTED_SPDX: frozenset = frozenset({
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "Python-2.0",    # CPython / PSF License
    "PSF-2.0",       # variante utilisee par certains forks
    "ISC",           # equivalent MIT, usage courant
})


def load_whitelist() -> list[tuple[str, str]]:
    """Charge le JSON et retourne une liste de (owner, repo)."""
    try:
        data = json.loads(WHITELIST_PATH.read_text(encoding="utf-8"))
        return [(e["owner"], e["repo"]) for e in data if e.get("owner") and e.get("repo")]
    except Exception as exc:
        log.error("educator_whitelist: impossible de charger %s : %s", WHITELIST_PATH, exc)
        return []


def load_whitelist_full() -> list[dict]:
    """Charge le JSON complet (owner + repo + description)."""
    try:
        return json.loads(WHITELIST_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("educator_whitelist: impossible de charger %s : %s", WHITELIST_PATH, exc)
        return []


def save_whitelist(entries: list[dict]) -> None:
    """Ecrit la liste complete dans educator_whitelist.json."""
    WHITELIST_PATH.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_skip_set() -> set:
    """
    Retourne un set de "owner/repo" pour lesquels skip_license_check=true.
    Utilise par EducatorIngester.process_repo() pour bypasser check_license().
    """
    try:
        data = json.loads(WHITELIST_PATH.read_text(encoding="utf-8"))
        return {
            f"{e['owner']}/{e['repo']}"
            for e in data
            if e.get("skip_license_check") is True
        }
    except Exception as exc:
        log.error("educator_whitelist: impossible de charger skip_set : %s", exc)
        return set()


# Charge une fois au demarrage du module -- valeur partagee par les importeurs
WHITELIST: list[tuple[str, str]] = load_whitelist()
