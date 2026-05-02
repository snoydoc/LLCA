# -*- coding: utf-8-sig -*-
"""
LCCA V8 -- ObserverReporter : rapport, archivage receipts, persistance snapshot.

Responsabilites :
    - Generer un ID de rapport (_make_report_id)
    - Decider si un receipt doit etre archive (_should_archive)
    - Archiver les receipts anciens sur disque (_archive_old_receipts)
    - Persister le snapshot dans la memoire (_store_snapshot)

Aucune dependance vers BaseAgent / bus / MCP — testable seul.

REFACTO-08 : extrait de observer_agent.py.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers module-level
# ---------------------------------------------------------------------------

def make_report_id(agent: str, ts: str) -> str:
    """Genere un ID court pour le rapport d'observation (MD5 12 chars)."""
    raw = f"{agent}:{ts}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def should_archive(receipt_ts: str, archive_after_days: int) -> bool:
    """
    Retourne True si le receipt est plus vieux que archive_after_days.

    receipt_ts : ISO 8601 UTC (ex: "2026-04-20T10:00:00+00:00")
    """
    try:
        ts = datetime.fromisoformat(receipt_ts)
        now = datetime.now(timezone.utc)
        delta = now - ts
        return delta.days >= archive_after_days
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# ObserverReporter
# ---------------------------------------------------------------------------

class ObserverReporter:
    """
    Couche rapport + persistance pour ObserverAgent.

    Responsabilites :
        - archive_old_receipts() : renomme les .json -> .archived
        - store_snapshot()       : persiste dans memory_engine ou MCP
    """

    def __init__(
        self,
        receipts_dir      : Optional[Path],
        archive_after_days: int,
        memory_engine     = None,
        mcp_caller        = None,
    ) -> None:
        self._receipts_dir       = receipts_dir
        self._archive_after_days = archive_after_days
        self._memory             = memory_engine
        self._mcp_caller         = mcp_caller

    def archive_old_receipts(self, force: bool = False) -> List[str]:
        """
        Identifie et renomme les receipts anciens en .archived.

        Retourne la liste des task_id archives.
        Silencieux si receipts_dir est None ou absent.
        """
        archived: List[str] = []
        if self._receipts_dir is None:
            return archived

        receipts_path = Path(self._receipts_dir)
        if not receipts_path.exists():
            return archived

        for receipt_file in receipts_path.glob("*.json"):
            try:
                data = json.loads(receipt_file.read_text(encoding="utf-8"))
                ts      = data.get("timestamp", "")
                task_id = data.get("task_id", receipt_file.stem)

                if force or should_archive(ts, self._archive_after_days):
                    archived_path = receipt_file.with_suffix(".archived")
                    receipt_file.rename(archived_path)
                    archived.append(task_id)
                    logger.debug("[observer] archive receipt %s", task_id)
            except Exception as exc:
                logger.debug("[observer] archive_old_receipts %s: %s", receipt_file, exc)

        return archived

    def store_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """
        Persiste le snapshot dans lcca_context via memory_engine ou MCP.
        Silencieux en cas d'echec.
        """
        payload = {
            "snippet": (
                f"Observer snapshot: {snapshot['skills_total']} skills, "
                f"{snapshot['low_quality_count']} low-quality, "
                f"{snapshot['duplicate_count']} duplicates, "
                f"{snapshot['archived_count']} archived."
            ),
            "score":    0.7,
            "type":     "observer_snapshot",
            "snapshot": str(snapshot),
        }

        # Voie 1 : memory_engine injecte
        if self._memory is not None:
            try:
                self._memory.store("lcca_context", payload)
                return
            except Exception as exc:
                logger.debug("[observer] store_snapshot memory_engine: %s", exc)

        # Voie 2 : MCP memory_store
        if self._mcp_caller is not None:
            try:
                self._mcp_caller("memory_store", {
                    "collection": "lcca_context",
                    "payload":    payload,
                })
            except PermissionError:
                raise
            except Exception as exc:
                logger.debug("[observer] store_snapshot MCP: %s", exc)


# ---------------------------------------------------------------------------
# Aliases prives (retrocompat)
# ---------------------------------------------------------------------------
_make_report_id  = make_report_id
_should_archive  = should_archive
