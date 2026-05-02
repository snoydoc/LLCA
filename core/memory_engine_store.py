# -*- coding: utf-8-sig -*-
"""
memory_engine_store.py — REFACTO-15
Extrait de memory_engine.py : logique de stockage et d'enrichissement.

Responsabilité unique : écriture dans les collections LCCA.
  - StoreResult dataclass
  - _check_threshold()  : vérification seuils solutions / context
  - _enrich_payload()   : ajout métadonnées standard (_collection, _ts, _version)
  - _store_via_adapter(): délégation ChromaDB ou fallback log
  - _extract_content()  : extraction du contenu textuel principal
  - MemoryStoreService  : façade des opérations store + helpers
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("lcca.memory_engine")

# ── Seuils (source de vérité unique — importés par memory_engine.py) ─────────
_THRESHOLD_SOLUTIONS: float = 0.8
_THRESHOLD_CONTEXT:   float = 0.6

# ── Collections valides ───────────────────────────────────────────────────────
_VALID_COLLECTIONS = frozenset(
    {"lcca_solutions", "lcca_failures", "lcca_context", "lcca_patches", "lcca_specs", "lcca_skills"}
)


@dataclass
class StoreResult:
    """Résultat d'un appel à store()."""
    stored:     bool
    collection: str
    entry_id:   Optional[str] = None
    reason:     Optional[str] = None   # Si stored=False, raison du rejet


# ── Fonctions pures (stateless) ───────────────────────────────────────────────

def check_threshold(collection: str, payload: Dict) -> Optional[str]:
    """
    Vérifie le seuil de stockage.

    Returns:
        Message de rejet si seuil non atteint, None si OK.
    """
    score = payload.get("score", None)

    if collection == "lcca_solutions":
        if score is None or score < _THRESHOLD_SOLUTIONS:
            return (
                f"lcca_solutions requiert score >= {_THRESHOLD_SOLUTIONS} "
                f"(reçu : {score})"
            )

    elif collection == "lcca_context":
        if score is None or score < _THRESHOLD_CONTEXT:
            return (
                f"lcca_context requiert score >= {_THRESHOLD_CONTEXT} "
                f"(reçu : {score})"
            )

    return None


def enrich_payload(collection: str, payload: Dict) -> Dict:
    """Ajoute les métadonnées standard (timestamp, collection, version)."""
    enriched = dict(payload)
    enriched.setdefault("_collection", collection)
    enriched.setdefault("_ts", datetime.now(timezone.utc).isoformat())
    enriched.setdefault("_version", "7.0")
    return enriched


def extract_content(payload: Dict) -> str:
    """Extrait le contenu textuel principal d'un payload."""
    for key in ("code", "snippet", "error", "content", "text"):
        if key in payload and isinstance(payload[key], str):
            return payload[key]
    parts = [
        f"{k}: {v}" for k, v in payload.items()
        if not k.startswith("_") and isinstance(v, str)
    ]
    return "\n".join(parts) or "(empty)"


def store_via_adapter(adapter: Any, collection: str, payload: Dict) -> str:
    """
    Délègue l'écriture à l'adaptateur MemPalace.

    Stratégie :
      1. Utilise les collections ChromaDB si disponibles dans l'adaptateur
      2. Sinon, log seulement (fallback silencieux)

    Returns:
        entry_id généré (MD5 déterministe du payload).
    """
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    entry_id = hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]

    lcca_cols = getattr(adapter, "lcca_collections", {})
    col = lcca_cols.get(collection)

    if col is not None:
        content = extract_content(payload)
        meta = {
            k: str(v) for k, v in payload.items()
            if not k.startswith("_") and isinstance(v, (str, int, float, bool))
        }
        try:
            col.upsert(ids=[entry_id], documents=[content], metadatas=[meta])
            log.debug("store_via_adapter: upsert %s → %s", collection, entry_id)
        except Exception as exc:
            log.warning("ChromaDB upsert error (%s): %s", collection, exc)
    else:
        log.debug(
            "store_via_adapter: pas de collection ChromaDB pour %s "
            "— entry_id=%s (non persisté)", collection, entry_id
        )

    return entry_id


# ── MemoryStoreService ────────────────────────────────────────────────────────

class MemoryStoreService:
    """
    Gère les opérations d'écriture dans les collections LCCA.

    Injecté dans MemoryEngine.
    """

    def __init__(self, adapter: Any, enforce_thresholds: bool = False) -> None:
        self._adapter  = adapter
        self._enforce  = enforce_thresholds

    def store(self, collection: str, payload: Dict[str, Any], available: bool) -> StoreResult:
        """
        Stocke une entrée dans une collection LCCA.

        Args:
            collection : nom de la collection.
            payload    : données à stocker.
            available  : True si MemPalace est connecté.

        Returns:
            StoreResult(stored=True, entry_id=...) ou StoreResult(stored=False, reason=...)
        """
        if collection not in _VALID_COLLECTIONS:
            return StoreResult(
                stored=False,
                collection=collection,
                reason=f"Collection inconnue : {collection}. "
                       f"Valides : {sorted(_VALID_COLLECTIONS)}",
            )

        threshold_msg = check_threshold(collection, payload)
        if threshold_msg is not None:
            log.debug("store: seuil non atteint pour %s — %s", collection, threshold_msg)
            if self._enforce:
                return StoreResult(stored=False, collection=collection, reason=threshold_msg)

        if not available:
            return StoreResult(
                stored=False,
                collection=collection,
                reason="MemPalace non disponible",
            )

        enriched = enrich_payload(collection, payload)

        try:
            entry_id = store_via_adapter(self._adapter, collection, enriched)
            return StoreResult(stored=True, collection=collection, entry_id=entry_id)
        except Exception as exc:  # noqa: BLE001
            log.error("MemoryStoreService.store(%s): %s", collection, exc)
            return StoreResult(stored=False, collection=collection, reason=str(exc))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def store_solution(self, available: bool, code: str, score: float, metadata: Optional[Dict] = None) -> StoreResult:
        return self.store("lcca_solutions", {"code": code, "score": score, **(metadata or {})}, available)

    def store_failure(self, available: bool, error: str, file: str, metadata: Optional[Dict] = None) -> StoreResult:
        return self.store("lcca_failures", {"error": error, "file": file, **(metadata or {})}, available)

    def store_patch(self, available: bool, tx_id: str, files: List[str], metadata: Optional[Dict] = None) -> StoreResult:
        return self.store("lcca_patches", {"tx_id": tx_id, "files": files, **(metadata or {})}, available)

    def store_context(self, available: bool, snippet: str, score: float, metadata: Optional[Dict] = None) -> StoreResult:
        return self.store("lcca_context", {"snippet": snippet, "score": score, **(metadata or {})}, available)
