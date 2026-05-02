# -*- coding: utf-8-sig -*-
"""
mempalace_client.py — LCCA V5 Fusion
Sprint 05 — TASK-05-01 à 05-04
REFACTO-14 — Orchestration légère (~5 KB).
  - Layers ChromaDB extraits dans mempalace_layers.py (PalaceLayers)
  - Filesystem extrait dans mempalace_fs.py (PalaceFilesystem)
  - API publique identique, aliases rétrocompat maintenus

Architecture 4 layers de mémoire :
  Layer 0 : Identity    (~170 tokens, jamais tronqué)
  Layer 1 : Compressed  (~500 tokens, résumé projet AAAK)
  Layer 2 : Scoped      (~2000 tokens, contexte session active)
  Layer 3 : Deep        (illimité, historique complet)

Usage :
    palace = MemPalaceClient()
    entry_id = palace.mine_content("def foo(): ...", wing="lcca", room="sprint_05")
    results  = palace.search_memories("foo function", wing="lcca")
    ctx      = palace.wake_up(wing="lcca", room="sprint_05")
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.mempalace_layers import MemoryEntry, PalaceLayers
from core.mempalace_fs import PalaceFilesystem

log = logging.getLogger("lcca.mempalace")

# Chemin par defaut : palace local LLCA (MIG-04)
try:
    from config import PALACE_DIR as _PALACE_DIR_DEFAULT
    _DEFAULT_PALACE_PATH = str(_PALACE_DIR_DEFAULT)
except ImportError:
    _DEFAULT_PALACE_PATH = "~/.mempalace/palace"


class MemPalaceClient:
    """
    Client MemPalace : stockage vectoriel (ChromaDB) + filesystem hiérarchique.

    Délègue :
      - Layers ChromaDB → PalaceLayers (mempalace_layers.py)
      - Filesystem       → PalaceFilesystem (mempalace_fs.py)

    Attributes:
        palace_path : Racine du palace sur le filesystem.
        chroma_path : Sous-dossier ChromaDB.
        collections : Proxy vers PalaceLayers.collections.
    """

    def __init__(self, palace_path: str = _DEFAULT_PALACE_PATH) -> None:
        self.palace_path = Path(palace_path).expanduser()

        self._fs = PalaceFilesystem(self.palace_path)
        self.chroma_path = self._fs.chroma_path

        import chromadb  # Import tardif pour ne pas crasher si absent
        chroma_client = chromadb.PersistentClient(path=str(self.chroma_path))

        self._layers = PalaceLayers(chroma_client)

        # Proxy rétrocompat : code existant accède à palace.collections[n]
        self.collections = self._layers.collections

        log.info("MemPalaceClient initialisé : %s", self.palace_path)

    # ── TASK-05-02 : mine_content() ───────────────────────────────────────────

    def mine_content(
        self,
        content: str,
        wing: Optional[str] = None,
        room: Optional[str] = None,
        hall: Optional[str] = None,
        source: str = "lcca",
        metadata: Optional[Dict[str, Any]] = None,
        layer: int = 3,
    ) -> str:
        """
        Stocker un souvenir : vectoriellement (ChromaDB) + filesystem.

        Returns:
            entry_id (str) : identifiant MD5 12-chars unique.

        Raises:
            ValueError : si content est vide ou layer invalide.
        """
        if not content or not content.strip():
            raise ValueError("mine_content: content ne peut pas être vide.")
        if layer not in (0, 1, 2, 3):
            raise ValueError(f"mine_content: layer doit être 0-3, reçu {layer}.")

        raw = f"{content}{time.time_ns()}"
        entry_id = hashlib.md5(raw.encode()).hexdigest()[:12]

        meta: Dict[str, Any] = {"source": source, "layer": layer}
        if wing:     meta["wing"] = wing
        if room:     meta["room"] = room
        if hall:     meta["hall"] = hall
        if metadata: meta.update(metadata)

        self._layers.add(entry_id, content, meta, layer)
        self._fs.write_entry(entry_id, content, meta, wing, room)

        log.debug("mine_content: %s (layer=%d, wing=%s)", entry_id, layer, wing)
        return entry_id

    # ── get_by_id() ───────────────────────────────────────────────────────────

    def get_by_id(self, entry_id: str) -> Optional[MemoryEntry]:
        """Récupère un souvenir par son entry_id (cherche dans les 4 layers)."""
        return self._layers.get_by_id(entry_id)

    # ── TASK-05-03 : search_memories() ───────────────────────────────────────

    def search_memories(
        self,
        query: str,
        wing: Optional[str] = None,
        room: Optional[str] = None,
        hall: Optional[str] = None,
        layer: Optional[int] = None,
        n_results: int = 5,
    ) -> List[MemoryEntry]:
        """Recherche sémantique dans les collections ChromaDB."""
        where = PalaceLayers.build_where(wing, room, hall)
        return self._layers.search(query, where=where, layer=layer, n_results=n_results)

    # ── TASK-05-04 : wake_up() ────────────────────────────────────────────────

    def wake_up(
        self,
        wing: Optional[str] = None,
        room: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Charge le contexte de démarrage optimisé (identity + compressed + recent)."""
        return self._layers.wake_up(wing=wing, room=room)

    # ── Helpers privés (rétrocompat) ──────────────────────────────────────────

    def _build_where(
        self,
        wing: Optional[str],
        room: Optional[str],
        hall: Optional[str],
    ) -> Optional[Dict]:
        """Rétrocompat — délègue à PalaceLayers.build_where."""
        return PalaceLayers.build_where(wing, room, hall)

    def _write_to_filesystem(
        self,
        entry_id: str,
        content: str,
        meta: Dict[str, Any],
        wing: Optional[str],
        room: Optional[str],
    ) -> None:
        """Rétrocompat — délègue à PalaceFilesystem.write_entry."""
        self._fs.write_entry(entry_id, content, meta, wing, room)

    def _ensure_dirs(self) -> None:
        """Rétrocompat — no-op (géré par PalaceFilesystem.__init__)."""

    def _init_identity(self) -> None:
        """Rétrocompat — no-op (géré par PalaceLayers.__init__)."""
