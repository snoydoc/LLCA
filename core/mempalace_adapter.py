# -*- coding: utf-8-sig -*-
"""
mempalace_adapter.py — LCCA MIG-04/MIG-05
Adaptateur entre MemoryEngine (collections lcca_*) et MemPalaceClient.

Créé lors de la correction du bug MCP-CRASH-01 (2026-04-23) :
  ModuleNotFoundError: No module named 'core.mempalace_adapter'

Rôle :
  MemoryEngine attend un adaptateur exposant :
    - adapter.is_available  (bool)       : True si ChromaDB est accessible
    - adapter.palace_path   (str)        : chemin du palace sur disque
    - adapter.lcca_collections (dict)    : {nom_collection: objet_ChromaDB}
      utilisé par store_via_adapter() dans memory_engine_store.py

  Ce fichier fait le pont entre :
    - MemPalaceClient / PalaceLayers (4 layers génériques)
    - Les 6 collections lcca_* spécifiques à LCCA

Architecture :
  ExistingMemPalaceAdapter
    └── MemPalaceClient(palace_path=PALACE_DIR)
          └── PalaceLayers(chroma_client)
                └── 4 layers génériques ChromaDB
    + 6 collections lcca_* créées séparément pour MemoryEngine

Collections lcca_* (MemoryEngine V7) :
  lcca_solutions  score >= 0.8 (Layer 1 compressed)
  lcca_failures   toujours stocker (Layer 2 scoped)
  lcca_context    score >= 0.6 (Layer 2 scoped)
  lcca_patches    toujours stocker (Layer 3 deep)
  lcca_specs      toujours stocker (Spec Layer)
  lcca_skills     toujours stocker (V8 SkillLibrary)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

log = logging.getLogger("lcca.mempalace_adapter")

_LCCA_COLLECTIONS = (
    "lcca_solutions",
    "lcca_failures",
    "lcca_context",
    "lcca_patches",
    "lcca_specs",
    "lcca_skills",
)


class ExistingMemPalaceAdapter:
    """
    Adaptateur MemoryEngine → MemPalaceClient (palace local LLCA).

    Initialise ChromaDB sur D:\\LLMCodeAgent\\mempalace\\palace\\ (PALACE_DIR).
    Si ChromaDB est absent ou le palace inaccessible, passe en mode dégradé
    silencieux (is_available=False) — le MCP Server démarre quand même.

    Attributes:
        is_available (bool): True si ChromaDB est connecté et fonctionnel.
        palace_path  (str) : Chemin du palace sur disque.
        lcca_collections (dict): Mapping nom → collection ChromaDB.
    """

    def __init__(self, palace_path: str | None = None) -> None:
        # ── Chemin palace ──────────────────────────────────────────────────
        if palace_path is None:
            try:
                from config import PALACE_DIR
                palace_path = str(PALACE_DIR)
            except ImportError:
                palace_path = str(Path.home() / ".mempalace" / "palace")

        self.palace_path: str = palace_path
        self.lcca_collections: Dict[str, Any] = {}
        self.is_available: bool = False

        # ── Initialisation ChromaDB ────────────────────────────────────────
        try:
            import chromadb  # Import tardif — optionnel
            chroma_client = chromadb.PersistentClient(path=self.palace_path)
            for col_name in _LCCA_COLLECTIONS:
                self.lcca_collections[col_name] = chroma_client.get_or_create_collection(col_name)
            self.is_available = True
            log.info(
                "ExistingMemPalaceAdapter: 6 collections lcca_* OK → %s",
                self.palace_path,
            )
        except ImportError:
            log.warning(
                "ExistingMemPalaceAdapter: chromadb non installé — "
                "MemoryEngine en mode dégradé (pas de persistance vectorielle)."
            )
        except Exception as exc:
            log.warning(
                "ExistingMemPalaceAdapter: ChromaDB inaccessible (%s) — "
                "MemoryEngine en mode dégradé.",
                exc,
            )
