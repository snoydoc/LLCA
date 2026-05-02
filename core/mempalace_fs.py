# -*- coding: utf-8-sig -*-
"""
mempalace_fs.py — LCCA V5 Fusion
REFACTO-14 — Extrait de mempalace_client.py

Gestion du filesystem hiérarchique du palace :
  palace_path/wings/<wing>/rooms/<room>/<entry_id>.json

Responsabilité : créer la hiérarchie de dossiers et persister
les souvenirs en JSON. Aucune dépendance sur ChromaDB.

Usage interne :
    from core.mempalace_fs import PalaceFilesystem
    fs = PalaceFilesystem(palace_path)
    fs.write_entry(entry_id, content, meta, wing, room)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("lcca.mempalace.fs")


class PalaceFilesystem:
    """
    Gestion du filesystem hiérarchique du palace.

    Structure :
        palace_path/
          wings/
            <wing>/rooms/<room>/<entry_id>.json
            _untagged/rooms/default/<entry_id>.json
          halls/
          chroma_db/

    Séparé de PalaceLayers pour respecter SRP :
    filesystem ≠ stockage vectoriel.
    """

    def __init__(self, palace_path: Path) -> None:
        self.palace_path = palace_path
        self.chroma_path = palace_path / "chroma_db"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Crée la hiérarchie de dossiers nécessaire."""
        for sub in ["wings", "halls"]:
            (self.palace_path / sub).mkdir(parents=True, exist_ok=True)
        self.chroma_path.mkdir(parents=True, exist_ok=True)

    def write_entry(
        self,
        entry_id: str,
        content: str,
        meta: Dict[str, Any],
        wing: Optional[str],
        room: Optional[str],
    ) -> Path:
        """
        Sauvegarde le souvenir en JSON sur le filesystem.

        Args:
            entry_id : Identifiant MD5 12-chars.
            content  : Texte du souvenir.
            meta     : Métadonnées ChromaDB (wing, room, layer, source…).
            wing     : Wing cible (None → _untagged).
            room     : Room cible (None → default).

        Returns:
            Path du fichier JSON créé.
        """
        if wing:
            room_dir = self.palace_path / "wings" / wing / "rooms" / (room or "default")
        else:
            room_dir = self.palace_path / "wings" / "_untagged" / "rooms" / "default"
        room_dir.mkdir(parents=True, exist_ok=True)

        payload = {"entry_id": entry_id, "content": content, **meta}
        out = room_dir / f"{entry_id}.json"
        out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8-sig",
        )
        log.debug("mempalace_fs: écrit %s", out)
        return out
