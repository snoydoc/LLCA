# -*- coding: utf-8-sig -*-
"""
user_context.py - LCCA V10 / Mode Projets
Sprint PROJ-06 - UserContext : chargement + WAL + compaction + snapshot

Localisation : projects/.llca/
  - user_context.json         : etat compact (jamais ecrit directement en session)
  - user_context.wal.jsonl    : WAL append-only des changements

Invariants :
  - user_context.json JAMAIS ecrit directement en cours de session
  - Champs identity.* et communication.language → confirmation requise avant WAL
  - Max 3 nouvelles entrees auto_detected par session
  - Compaction a 10 entrees WAL OU fin de session
  - Snapshot de securite toutes les 7 jours ou 100 entrees WAL accumulees
  - Budget token injecte : 800 tokens max (gere par UserContextInjector, PROJ-07)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# Sources valides pour les entrees WAL
VALID_SOURCES = frozenset({"user_correction", "auto_detected", "explicit_command"})

# Champs qui exigent confirmation avant ecriture WAL
SENSITIVE_FIELDS = frozenset({
    "identity.name",
    "identity.locale",
    "identity.timezone",
    "communication.language",
})

# Seuils de compaction
WAL_COMPACT_THRESHOLD = 10      # entrees WAL → compaction
WAL_SNAPSHOT_THRESHOLD = 100    # entrees WAL accumulees → snapshot force
SNAPSHOT_DAYS = 7               # jours sans snapshot → snapshot force
MAX_AUTO_DETECTED_PER_SESSION = 3


# ---------------------------------------------------------------------------
# Schema par defaut
# ---------------------------------------------------------------------------

def _default_context() -> dict:
    """Retourne un user_context.json vide avec tous les champs."""
    return {
        "version": 1,
        "identity": {
            "name": "",
            "locale": "fr-MA",
            "timezone": "Africa/Casablanca",
        },
        "communication": {
            "tone": "casual",
            "verbosity": "concise",
            "language": "fr",
            "code_comments_lang": "fr",
            "prefers_emoji": False,
        },
        "workflow": {
            "preferred_model": None,
            "auto_resume_threshold_min": 30,
            "show_archived_projects": False,
            "default_compression": "sliding_window",
        },
        "shortcuts": {
            "favorite_commands": [],
            "aliases": {},
        },
        "learned": {
            "coding_style": [],
            "pain_points": [],
            "preferred_file_size": "< 10KB par module",
            "last_updated": None,
        },
    }


# ---------------------------------------------------------------------------
# Dataclass UserContextState
# ---------------------------------------------------------------------------

@dataclass
class UserContextState:
    """Etat utilisateur reconstitue (apres replay WAL)."""
    data: dict = field(default_factory=_default_context)
    last_snapshot_at: Optional[str] = None   # ISO timestamp du dernier snapshot
    wal_entry_count: int = 0                  # entrees WAL depuis dernier snapshot
    auto_detected_count: int = 0             # entrees auto_detected cette session

    # ---- Acces raccourcis ------------------------------------------------

    @property
    def name(self) -> str:
        return self.data.get("identity", {}).get("name", "")

    @property
    def locale(self) -> str:
        return self.data.get("identity", {}).get("locale", "fr-MA")

    @property
    def tone(self) -> str:
        return self.data.get("communication", {}).get("tone", "casual")

    @property
    def verbosity(self) -> str:
        return self.data.get("communication", {}).get("verbosity", "concise")

    @property
    def language(self) -> str:
        return self.data.get("communication", {}).get("language", "fr")

    @property
    def prefers_emoji(self) -> bool:
        return self.data.get("communication", {}).get("prefers_emoji", False)

    @property
    def aliases(self) -> dict:
        return self.data.get("shortcuts", {}).get("aliases", {})

    @property
    def learned(self) -> dict:
        return self.data.get("learned", {})

    def to_dict(self) -> dict:
        return {
            "data": self.data,
            "last_snapshot_at": self.last_snapshot_at,
            "wal_entry_count": self.wal_entry_count,
            "auto_detected_count": self.auto_detected_count,
        }


# ---------------------------------------------------------------------------
# Helpers ecriture atomique
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, content: str) -> None:
    """Ecriture atomique : tmp → rename (pattern T-14 LCCA)."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _get_nested(data: dict, dotted_key: str) -> Any:
    """Lit une valeur depuis un dict via une cle pointee 'a.b.c'."""
    keys = dotted_key.split(".")
    cur = data
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _set_nested(data: dict, dotted_key: str, value: Any) -> None:
    """Ecrit une valeur dans un dict via une cle pointee 'a.b.c' (mutates data)."""
    keys = dotted_key.split(".")
    cur = data
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


# ---------------------------------------------------------------------------
# UserContextLoader
# ---------------------------------------------------------------------------

class UserContextLoader:
    """
    Charge et maintient le contexte utilisateur global.

    Localisation : projects/.llca/
    Usage :
        loader = UserContextLoader(llca_root)
        state  = loader.load()
        loader.append_wal(state, "communication.tone", "formal", "casual", "user_correction")
        loader.compact(state)
    """

    def __init__(self, llca_root: Optional[Path] = None) -> None:
        if llca_root is None:
            llca_root = Path(__file__).resolve().parent.parent
        self._root = llca_root
        self._ctx_dir  = llca_root / "projects" / ".llca"
        self._ctx_file = self._ctx_dir / "user_context.json"
        self._wal_file = self._ctx_dir / "user_context.wal.jsonl"

    # ---- Chargement principal -------------------------------------------

    def load(self) -> UserContextState:
        """
        Charge l'etat courant :
          1. Lit user_context.json (ou defauts si absent)
          2. Replay WAL → applique les changements

        Retourne un UserContextState pret a l'emploi.
        """
        base = self._read_context_file()
        wal_entries = self._read_wal()
        state = UserContextState(data=base)

        # Replay WAL
        for entry in wal_entries:
            self._apply_entry(state.data, entry)
            state.wal_entry_count += 1
            if entry.get("source") == "auto_detected":
                state.auto_detected_count += 1

        # Lire last_snapshot_at depuis le JSON si present
        state.last_snapshot_at = base.get("_last_snapshot_at")

        return state

    # ---- Ajout WAL ------------------------------------------------------

    def append_wal(
        self,
        state: UserContextState,
        field: str,
        old_value: Any,
        new_value: Any,
        source: str,
    ) -> bool:
        """
        Appende une entree WAL.

        Guards :
          - source invalide → False
          - champ sensible (identity.*, communication.language) → False
            (confirmation utilisateur requise, gerer cote appelant)
          - MAX_AUTO_DETECTED_PER_SESSION atteint → False

        Retourne True si l'entree a ete ecrite.
        """
        if source not in VALID_SOURCES:
            log.warning("append_wal : source invalide '%s'", source)
            return False

        if field in SENSITIVE_FIELDS and source != "user_correction":
            log.warning(
                "append_wal : champ sensible '%s' — confirmation requise (source=%s)",
                field, source,
            )
            return False

        if source == "auto_detected":
            if state.auto_detected_count >= MAX_AUTO_DETECTED_PER_SESSION:
                log.info(
                    "append_wal : limite auto_detected atteinte (%d/session)",
                    MAX_AUTO_DETECTED_PER_SESSION,
                )
                return False

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "field": field,
            "old": old_value,
            "new": new_value,
            "source": source,
        }

        self._ctx_dir.mkdir(parents=True, exist_ok=True)
        with self._wal_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Applique immediatement au state courant
        _set_nested(state.data, field, new_value)
        state.wal_entry_count += 1
        if source == "auto_detected":
            state.auto_detected_count += 1

        log.info("WAL UserContext : %s → %s (source=%s)", field, new_value, source)
        return True

    # ---- Compaction -----------------------------------------------------

    def compact(self, state: UserContextState) -> bool:
        """
        Merge WAL dans user_context.json et tronque le WAL.

        Declenche si :
          - wal_entry_count >= WAL_COMPACT_THRESHOLD
          - OU appele explicitement (fin de session)

        Retourne True si la compaction a ete effectuee.
        """
        if state.wal_entry_count == 0:
            return False

        now_iso = datetime.now(timezone.utc).isoformat()
        data_to_save = dict(state.data)
        data_to_save["_last_snapshot_at"] = now_iso

        self._ctx_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(
            self._ctx_file,
            json.dumps(data_to_save, indent=2, ensure_ascii=False),
        )

        # Tronquer le WAL
        _atomic_write(self._wal_file, "")

        state.last_snapshot_at = now_iso
        state.wal_entry_count = 0
        log.info("UserContext : compaction effectuee, WAL tronque")
        return True

    def should_compact(self, state: UserContextState) -> bool:
        """True si le seuil de compaction est atteint."""
        return state.wal_entry_count >= WAL_COMPACT_THRESHOLD

    def should_snapshot(self, state: UserContextState) -> bool:
        """
        True si un snapshot de securite est necessaire :
          - wal_entry_count >= WAL_SNAPSHOT_THRESHOLD
          - OU dernier snapshot > SNAPSHOT_DAYS jours
        """
        if state.wal_entry_count >= WAL_SNAPSHOT_THRESHOLD:
            return True
        if state.last_snapshot_at is None:
            return True
        try:
            last = datetime.fromisoformat(
                state.last_snapshot_at.replace("Z", "+00:00")
            )
            age = datetime.now(timezone.utc) - last
            return age > timedelta(days=SNAPSHOT_DAYS)
        except (ValueError, TypeError):
            return True

    # ---- Acces champ direct (pour update explicite) ---------------------

    def update_field(
        self,
        state: UserContextState,
        field: str,
        new_value: Any,
        source: str = "user_correction",
    ) -> bool:
        """
        Raccourci : lit l'ancienne valeur, ecrit le WAL.
        Retourne True si l'entree WAL a ete ecrite.
        """
        old_value = _get_nested(state.data, field)
        return self.append_wal(state, field, old_value, new_value, source)

    # ---- Helpers prives -------------------------------------------------

    def _read_context_file(self) -> dict:
        """Lit user_context.json. Retourne les defauts si absent ou invalide."""
        if not self._ctx_file.exists():
            return _default_context()
        try:
            raw = self._ctx_file.read_text(encoding="utf-8")
            data = json.loads(raw)
            # Fusionner avec les defauts pour les cles manquantes
            defaults = _default_context()
            return _deep_merge(defaults, data)
        except Exception as exc:
            log.warning("user_context.json illisible : %s — defauts utilises", exc)
            return _default_context()

    def _read_wal(self) -> list[dict]:
        """Lit le WAL JSONL. Lignes invalides ignorees silencieusement."""
        if not self._wal_file.exists():
            return []
        entries = []
        for line in self._wal_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    @staticmethod
    def _apply_entry(data: dict, entry: dict) -> None:
        """Applique une entree WAL sur le dict data (mutates)."""
        field_key = entry.get("field", "")
        new_val   = entry.get("new")
        if field_key:
            _set_nested(data, field_key, new_val)


# ---------------------------------------------------------------------------
# Helper deep merge
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    """
    Fusionne override dans base recursivement.
    Les valeurs de override prennent priorite.
    Retourne un nouveau dict (non-mutant).
    """
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result
