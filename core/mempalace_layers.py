# -*- coding: utf-8-sig -*-
"""
mempalace_layers.py — LCCA V5 Fusion
REFACTO-14 — Extrait de mempalace_client.py

Gestion des 4 layers ChromaDB du palace :
  Layer 0 : Identity    (~170 tokens)
  Layer 1 : Compressed  (~500 tokens)
  Layer 2 : Scoped      (~2000 tokens)
  Layer 3 : Deep        (illimité)

Responsabilité : mine (add), get_by_id, search_memories, wake_up.
Aucune dépendance sur le filesystem — voir mempalace_fs.py.

Usage interne :
    from core.mempalace_layers import PalaceLayers
    layers = PalaceLayers(chroma_client)
    entry_id = layers.add(content, meta, layer=3)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("lcca.mempalace.layers")

_DEFAULT_IDENTITY = (
    "Tu es LCCA V5 Fusion, un agent de codage local transactionnel. "
    "Tu appliques des patches AST atomiques via libcst. "
    "Chaque modification = snapshot + WAL + rollback possible. "
    "Max 3 fichiers par transaction."
)


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class MemoryEntry:
    """Unité de mémoire stockée dans le palace."""
    content:      str
    wing:         Optional[str]       = None
    room:         Optional[str]       = None
    hall:         Optional[str]       = None
    source:       str                 = "system"
    metadata:     Dict[str, Any]      = field(default_factory=dict)
    layer:        int                 = 3
    embedding_id: Optional[str]       = None


# ── PalaceLayers ──────────────────────────────────────────────────────────────

class PalaceLayers:
    """
    Interface ChromaDB pour les 4 layers mémoire du palace.

    Responsabilités :
      - Initialiser les 4 collections ChromaDB.
      - Initialiser l'identité Layer 0.
      - Ajouter des entrées (add).
      - Récupérer par ID (get_by_id).
      - Rechercher sémantiquement (search).
      - Charger le contexte de démarrage (wake_up).

    Pas de logique filesystem ici — voir PalaceFilesystem.
    """

    def __init__(self, chroma_client: Any) -> None:
        self._chroma = chroma_client
        self.collections: Dict[int, Any] = {
            0: chroma_client.get_or_create_collection("layer_0_identity"),
            1: chroma_client.get_or_create_collection("layer_1_compressed"),
            2: chroma_client.get_or_create_collection("layer_2_scoped"),
            3: chroma_client.get_or_create_collection("layer_3_deep"),
        }
        self._init_identity()

    def _init_identity(self) -> None:
        """Insère l'identity par défaut dans Layer 0 si vide."""
        col = self.collections[0]
        try:
            if col.count() == 0:
                col.add(
                    documents=[_DEFAULT_IDENTITY],
                    ids=["identity_lcca_v5"],
                    metadatas=[{"source": "system", "wing": "lcca"}],
                )
                log.debug("Identity Layer 0 initialisée.")
        except Exception as exc:  # pragma: no cover
            log.warning("_init_identity failed: %s", exc)

    # ── Écriture ──────────────────────────────────────────────────────────────

    def add(self, entry_id: str, content: str, meta: Dict[str, Any], layer: int) -> None:
        """Ajoute un document dans la collection du layer spécifié."""
        try:
            self.collections[layer].add(
                documents=[content],
                ids=[entry_id],
                metadatas=[meta],
            )
        except Exception as exc:
            log.error("ChromaDB add failed (layer=%d): %s", layer, exc)
            raise

    # ── Lecture par ID ────────────────────────────────────────────────────────

    def get_by_id(self, entry_id: str) -> Optional[MemoryEntry]:
        """Cherche un souvenir par entry_id dans les 4 layers."""
        for layer, col in self.collections.items():
            try:
                result = col.get(ids=[entry_id], include=["documents", "metadatas"])
                if result and result["documents"]:
                    doc  = result["documents"][0]
                    meta = result["metadatas"][0] if result["metadatas"] else {}
                    return MemoryEntry(
                        content=doc,
                        wing=meta.get("wing"),
                        room=meta.get("room"),
                        hall=meta.get("hall"),
                        source=meta.get("source", "system"),
                        metadata=meta,
                        layer=layer,
                        embedding_id=entry_id,
                    )
            except Exception:
                continue
        return None

    # ── Recherche sémantique ──────────────────────────────────────────────────

    def search(
        self,
        query: str,
        where: Optional[Dict] = None,
        layer: Optional[int] = None,
        n_results: int = 5,
    ) -> List[MemoryEntry]:
        """Recherche sémantique dans les collections ChromaDB."""
        if not query or not query.strip():
            return []

        collections_to_search = (
            [self.collections[layer]] if layer is not None
            else list(self.collections.values())
        )

        entries: List[MemoryEntry] = []
        seen_ids: set = set()

        for col in collections_to_search:
            try:
                if col.count() == 0:
                    continue
                kwargs: Dict[str, Any] = {
                    "query_texts": [query],
                    "n_results": min(n_results, col.count()),
                    "include": ["documents", "metadatas", "distances"],
                }
                if where:
                    kwargs["where"] = where
                result = col.query(**kwargs)

                docs  = result.get("documents", [[]])[0]
                metas = result.get("metadatas", [[]])[0]
                ids   = result.get("ids", [[]])[0]

                for doc, meta, eid in zip(docs, metas, ids):
                    if eid not in seen_ids:
                        seen_ids.add(eid)
                        entries.append(MemoryEntry(
                            content=doc,
                            wing=meta.get("wing"),
                            room=meta.get("room"),
                            hall=meta.get("hall"),
                            source=meta.get("source", "system"),
                            metadata=meta,
                            layer=meta.get("layer", 3),
                            embedding_id=eid,
                        ))
            except Exception as exc:
                log.debug("search layer error: %s", exc)
                continue

        return entries[:n_results]

    # ── Wake up ───────────────────────────────────────────────────────────────

    def wake_up(
        self,
        wing: Optional[str] = None,
        room: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Charge le contexte de démarrage (identity + compressed + recent)."""
        import time
        t0 = time.time()
        ctx: Dict[str, Any] = {
            "identity": _DEFAULT_IDENTITY,
            "compressed_knowledge": [],
            "recent_activity": [],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        # Layer 0 — toujours
        try:
            result = self.collections[0].get(include=["documents"])
            if result and result["documents"]:
                ctx["identity"] = " ".join(result["documents"])
        except Exception as exc:
            log.debug("wake_up Layer 0 error: %s", exc)

        # Layer 1 — si wing précisé
        if wing:
            try:
                col = self.collections[1]
                if col.count() > 0:
                    where1 = {"wing": {"$eq": wing}}
                    kw: Dict[str, Any] = {
                        "query_texts": [wing],
                        "n_results": min(5, col.count()),
                        "include": ["documents"],
                        "where": where1,
                    }
                    r1 = col.query(**kw)
                    ctx["compressed_knowledge"] = r1.get("documents", [[]])[0]
            except Exception as exc:
                log.debug("wake_up Layer 1 error: %s", exc)

        # Layer 2 — si wing + room
        if wing and room:
            try:
                col = self.collections[2]
                if col.count() > 0:
                    where2: Dict[str, Any] = {"$and": [
                        {"wing": {"$eq": wing}},
                        {"room": {"$eq": room}},
                    ]}
                    kw2: Dict[str, Any] = {
                        "query_texts": [f"{wing} {room}"],
                        "n_results": min(10, col.count()),
                        "include": ["documents"],
                        "where": where2,
                    }
                    r2 = col.query(**kw2)
                    ctx["recent_activity"] = r2.get("documents", [[]])[0]
            except Exception as exc:
                log.debug("wake_up Layer 2 error: %s", exc)

        elapsed_ms = (time.time() - t0) * 1000
        if elapsed_ms > 500:  # pragma: no cover
            log.warning("wake_up lent : %.0f ms", elapsed_ms)

        return ctx

    # ── Helper filtre where ───────────────────────────────────────────────────

    @staticmethod
    def build_where(
        wing: Optional[str],
        room: Optional[str],
        hall: Optional[str],
    ) -> Optional[Dict]:
        """Construit le filtre ChromaDB `where` depuis les filtres hiérarchiques."""
        clauses = []
        if wing: clauses.append({"wing": {"$eq": wing}})
        if room: clauses.append({"room": {"$eq": room}})
        if hall: clauses.append({"hall": {"$eq": hall}})
        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}
