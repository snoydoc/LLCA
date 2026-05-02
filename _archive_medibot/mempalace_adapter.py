# -*- coding: utf-8-sig -*-
r"""
mempalace_adapter.py — LCCA V5 Fusion
Sprint 05 — TASK-05-06 | Sprint 08 — TASK-08-01 (finalisation)

Adaptateur vers le MemPalace existant (D:\\MediBot\\Mempalace).
Lecture seule des données MediBot — les écrits LCCA vont dans des
collections préfixées ``lcca_*`` pour isolation totale.

Usage :
    adapter = ExistingMemPalaceAdapter()
    ctx = adapter.wake_up_medi()
    print(ctx["identity"])
    print(ctx["specs"])
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("lcca.mempalace_adapter")

# Chemins à sonder dans l'ordre de priorité
POSSIBLE_PATHS: List[Path] = [
    Path(r"D:\MediBot\Mempalace\memory_palace"),
    Path(r"D:\MediBot\Mempalace"),
    Path.home() / ".mempalace" / "palace",
]


class ExistingMemPalaceAdapter:
    r"""
    Connexion au MemPalace existant (MediBot ou local).

    Stratégie de détection :
        1. Cherche chroma.sqlite3 dans POSSIBLE_PATHS
        2. Fallback vers ~/.mempalace/palace si rien trouvé
        3. Ne crée rien si aucun palace n'existe

    Isolation des données :
        Les collections LCCA sont toutes préfixées ``lcca_`` pour ne
        jamais polluer les collections MediBot existantes.

    Attributes:
        palace_path  : Chemin détecté ou None si absent.
        _client      : MemPalaceClient connecté (lazy init).
        _specs       : Liste de dicts {name, content} des fichiers specs/.
        _identity    : Contenu de identity.txt ou chaîne vide.
        _lcca_cols   : Dict des collections ChromaDB isolées LCCA.
    """

    # Collections LCCA créées dans le palace MediBot (préfixe lcca_ = isolation)
    # NOTE : Ces collections sont spécifiques à l'adaptateur MediBot (Sprint 05/08).
    # Elles sont DISTINCTES des 5 collections de MemoryEngine V7 (lcca_solutions,
    # lcca_failures, lcca_context, lcca_patches, lcca_specs). C'est intentionnel :
    # l'adaptateur stocke les données de session MediBot, MemoryEngine gère
    # les solutions/specs LCCA. Deux couches d'isolation indépendantes.
    _LCCA_COLLECTION_NAMES = ("lcca_transactions", "lcca_ast_index", "lcca_sessions")

    def __init__(self) -> None:
        self.palace_path: Optional[Path] = self._detect_palace_path()
        self._client = None
        self._specs: List[Dict[str, str]] = []
        self._identity: str = ""
        self._lcca_cols: Dict[str, Any] = {}

        if self.palace_path:
            log.info("ExistingMemPalaceAdapter: palace trouvé à %s", self.palace_path)
            self._load_identity()
            self._load_specs()
            self._init_lcca_collections()
        else:
            log.warning(
                "ExistingMemPalaceAdapter: aucun palace trouvé. "
                r"Vérifier D:\MediBot\Mempalace ou ~/.mempalace/palace"
            )

    # ── Détection ─────────────────────────────────────────────────────────────

    def _detect_palace_path(self) -> Optional[Path]:
        """
        Détecte le chemin du palace existant.

        Returns:
            Path si trouvé (dossier existe), None sinon.
            Accepte avec ou sans chroma.sqlite3 (le fichier peut ne pas
            encore exister dans les environnements de test).
        """
        for candidate in POSSIBLE_PATHS:
            if not candidate.exists():
                continue
            # Préférence: chroma.sqlite3 présent
            if (candidate / "chroma.sqlite3").exists():
                return candidate
            if (candidate / "chroma_db" / "chroma.sqlite3").exists():
                return candidate
            # Accepte aussi les dossiers avec identity.txt (tests)
            if (candidate / "identity.txt").exists():
                return candidate
        return None

    # ── Chargement données ────────────────────────────────────────────────────

    def _load_identity(self) -> None:
        """Charge identity.txt depuis palace_path si présent."""
        if not self.palace_path:
            return
        identity_file = self.palace_path / "identity.txt"
        if identity_file.exists():
            try:
                self._identity = identity_file.read_text(encoding="utf-8-sig", errors="replace").strip()
                log.debug("Identity chargée (%d chars)", len(self._identity))
            except Exception as exc:
                log.warning("_load_identity: impossible de lire identity.txt — %s", exc)

    def _load_specs(self) -> None:
        """
        Charge les fichiers .md et .txt depuis palace_path/specs/.
        Stocke dans self._specs comme liste de dicts {name, content}.
        """
        if not self.palace_path:
            return

        specs_dir = self.palace_path / "specs"
        if not specs_dir.exists():
            log.debug("_load_specs: dossier specs/ absent dans %s", self.palace_path)
            return

        for f in sorted(specs_dir.iterdir()):
            if f.suffix in (".md", ".txt") and f.is_file():
                try:
                    content = f.read_text(encoding="utf-8-sig", errors="replace")
                    self._specs.append({"name": f.stem, "content": content})
                    log.debug("Spec chargée : %s (%d chars)", f.name, len(content))
                except Exception as exc:
                    log.warning("_load_specs: impossible de lire %s — %s", f.name, exc)

        log.info("_load_specs: %d fichier(s) chargé(s)", len(self._specs))

    def _init_lcca_collections(self) -> None:
        """
        Crée (ou ouvre) les collections ChromaDB dédiées à LCCA.
        Ne touche JAMAIS aux collections MediBot existantes.
        Silencieux si ChromaDB non disponible.
        """
        if not self.palace_path:
            return
        try:
            import chromadb
            chroma_path = str(self.palace_path)
            client = chromadb.PersistentClient(path=chroma_path)
            for col_name in self._LCCA_COLLECTION_NAMES:
                col = client.get_or_create_collection(col_name)
                self._lcca_cols[col_name] = col
                log.debug("Collection LCCA prête : %s", col_name)
            log.info(
                "_init_lcca_collections: %d collection(s) LCCA initialisée(s)",
                len(self._lcca_cols),
            )
        except ImportError:
            log.debug("chromadb non disponible — collections LCCA ignorées")
        except Exception as exc:
            log.warning("_init_lcca_collections: %s", exc)

    # ── Client MemPalace ──────────────────────────────────────────────────────

    def _get_client(self):
        """Lazy init du client MemPalace sur le palace détecté."""
        if self._client is None:
            if not self.palace_path:
                raise FileNotFoundError(
                    r"ExistingMemPalaceAdapter: aucun palace trouvé. "
                    r"Vérifier D:\MediBot\Mempalace"
                )
            from core.mempalace_client import MemPalaceClient
            self._client = MemPalaceClient(palace_path=str(self.palace_path))
        return self._client

    # ── Interface publique ────────────────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        """True si un palace a été trouvé."""
        return self.palace_path is not None

    @property
    def specs(self) -> List[Dict[str, str]]:
        """Retourne les specs chargées (lecture seule — liste de {name, content})."""
        return list(self._specs)

    @property
    def identity(self) -> str:
        """Retourne l'identity du palace."""
        return self._identity

    @property
    def lcca_collections(self) -> Dict[str, Any]:
        """Retourne les collections ChromaDB LCCA (préfixe lcca_*)."""
        return dict(self._lcca_cols)

    def wake_up_medi(
        self,
        wing: Optional[str] = "medibot",
        room: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Contexte de démarrage enrichi MediBot.

        Combines :
        - identity.txt (Layer 0)
        - specs/ chargées (Layer 1)
        - wake_up() du MemPalaceClient si disponible (Layer 2)

        Returns:
            Dict avec identity, compressed_knowledge, recent_activity,
            specs (liste), palace_path (str|None), timestamp.
        """
        from datetime import datetime, timezone

        if not self.is_available:
            return {
                "identity": "MemPalace non disponible.",
                "compressed_knowledge": [],
                "recent_activity": [],
                "specs": [],
                "palace_path": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        ctx: Dict[str, Any] = {
            "identity": self._identity,
            "compressed_knowledge": [],
            "recent_activity": [],
            "specs": self._specs,
            "palace_path": str(self.palace_path),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Enrichissement optionnel via MemPalaceClient (Layer 2)
        try:
            client = self._get_client()
            deep = client.wake_up(wing=wing, room=room)
            ctx["compressed_knowledge"] = deep.get("compressed_knowledge", [])
            ctx["recent_activity"] = deep.get("recent_activity", [])
            if not ctx["identity"] and deep.get("identity"):
                ctx["identity"] = deep["identity"]
        except Exception as exc:
            log.debug("wake_up_medi: client indisponible — %s", exc)

        return ctx

    def search(
        self,
        query: str,
        wing: Optional[str] = None,
        n_results: int = 5,
    ) -> List[Any]:
        """
        Recherche dans le MemPalace existant (délégation au client).

        Returns:
            Liste de MemoryEntry, vide si palace non disponible.
        """
        if not self.is_available:
            return []
        try:
            return self._get_client().search_memories(query, wing=wing, n_results=n_results)
        except Exception as exc:
            log.error("ExistingMemPalaceAdapter.search error: %s", exc)
            return []

    def find_relevant_specs(self, keywords: List[str], max_specs: int = 2) -> str:
        """
        Retourne un extrait des specs pertinentes selon les mots-clés.

        Args:
            keywords:  Mots-clés à chercher (insensible à la casse).
            max_specs: Nombre maximum de specs retournées.

        Returns:
            Chaîne formatée "[nom_spec]: extrait…" ou chaîne vide.
        """
        if not self._specs or not keywords:
            return ""

        lower_kw = [k.lower() for k in keywords if k]
        relevant = []

        for spec in self._specs:
            content_lower = spec["content"].lower()
            if any(kw in content_lower for kw in lower_kw):
                excerpt = spec["content"][:300].replace("\n", " ")
                relevant.append(f"[{spec['name']}]: {excerpt}")

        return "\n".join(relevant[:max_specs])
