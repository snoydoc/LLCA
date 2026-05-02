# -*- coding: utf-8-sig -*-
"""
project_wal.py - LCCA V10 / Mode Projets
Sprint PROJ-06 - Write-Ahead Log par projet

Enregistre chaque transaction agent dans :
  projects/{slug}/.llca/project_wal.jsonl

Chaque entree = 1 ligne JSON (format NDJSON).
Ecriture atomique : append-only sur fichier ouvert en mode 'a'.
Compaction : deplace les vieilles entrees dans .llca/wal_archive/.

Invariants :
  - append() ne leve jamais (mode degrade silencieux, log warning)
  - Chaque entree a un champ "_ts" ISO8601 UTC
  - compact() preserves les N dernieres entrees, archive le reste
  - Path.replace() pour l'ecriture atomique de la compaction (regle T-14)
  - ProjectWal n'importe JAMAIS core.transaction_manager
    (dependance circulaire interdite)

Structure d'une entree WAL :
  {
    "_ts":       "2026-04-30T12:00:00+00:00",   # timestamp UTC ISO8601
    "tx_id":     "tx_abc123",                    # identifiant TX
    "intent":    "ajoute validate_token()",      # commande NL originale
    "action":    "ajoute",                       # type d'action detecte
    "files":     ["auth.py"],                    # fichiers modifies
    "llm":       "qwen2.5-coder:3b",             # modele utilise
    "success":   true,                           # TX commit ou rollback
    "duration_ms": 4200,                         # duree en ms
    "extra":     {}                              # metadonnees libres
  }
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Nom du fichier WAL dans le repertoire .llca/ du projet
WAL_FILENAME = "project_wal.jsonl"
# Nom du sous-dossier d'archive (cree a la demande)
ARCHIVE_DIRNAME = "wal_archive"
# Nombre d'entrees conservees apres compaction par defaut
DEFAULT_KEEP_ENTRIES = 500


# ---------------------------------------------------------------------------
# WalEntry — dataclass legere (dict enrichi)
# ---------------------------------------------------------------------------

def make_wal_entry(
    tx_id: str,
    intent: str,
    action: str = "",
    files: Optional[list] = None,
    llm: str = "",
    success: bool = True,
    duration_ms: int = 0,
    extra: Optional[dict] = None,
) -> dict:
    """
    Fabrique un dict WAL pre-rempli avec le timestamp courant.

    Usage :
        entry = make_wal_entry(tx_id="tx_abc", intent="ajoute login()")
        wal.append(entry)
    """
    return {
        "_ts":         datetime.now(timezone.utc).isoformat(),
        "tx_id":       tx_id,
        "intent":      intent,
        "action":      action,
        "files":       files or [],
        "llm":         llm,
        "success":     success,
        "duration_ms": duration_ms,
        "extra":       extra or {},
    }


# ---------------------------------------------------------------------------
# ProjectWal
# ---------------------------------------------------------------------------

class ProjectWal:
    """
    Write-Ahead Log par projet.

    Usage :
        wal = ProjectWal(projects_dir, slug="mon-projet")
        wal.append(make_wal_entry(tx_id="tx_xyz", intent="..."))
        entries = wal.read_last(20)
        wal.compact()
    """

    def __init__(
        self,
        projects_dir: Optional[Path] = None,
        slug: str = "",
        wal_filename: str = WAL_FILENAME,
    ) -> None:
        if projects_dir is None:
            _core = Path(__file__).parent
            projects_dir = _core.parent / "projects"
        self._projects_dir = Path(projects_dir)
        self._slug = slug
        self._wal_filename = wal_filename

    # ── Chemin ──────────────────────────────────────────────────────────────

    @property
    def wal_path(self) -> Path:
        """Chemin complet du fichier WAL actif."""
        return self._projects_dir / self._slug / ".llca" / self._wal_filename

    @property
    def archive_dir(self) -> Path:
        """Repertoire d'archive WAL (.llca/wal_archive/)."""
        return self._projects_dir / self._slug / ".llca" / ARCHIVE_DIRNAME

    # ── Ecriture ────────────────────────────────────────────────────────────

    def append(self, entry: dict) -> None:
        """
        Ajoute une entree au WAL (append-only, mode degrade silencieux).

        Garantit que l'entree a un champ "_ts".
        Ne leve jamais — log warning en cas d'erreur disque.
        """
        # Garantir le timestamp
        if "_ts" not in entry:
            entry = dict(entry)
            entry["_ts"] = datetime.now(timezone.utc).isoformat()

        try:
            self.wal_path.parent.mkdir(parents=True, exist_ok=True)
            with self.wal_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            log.warning(
                "ProjectWal.append : echec ecriture WAL slug=%s : %s",
                self._slug, exc,
            )

    # ── Lecture ─────────────────────────────────────────────────────────────

    def read_last(self, n: int = 50) -> list[dict]:
        """
        Retourne les N dernieres entrees WAL (ordre chronologique).

        Retourne [] si le fichier est absent ou vide.
        Les lignes JSON invalides sont ignorees silencieusement.
        """
        if not self.wal_path.exists():
            return []

        entries: list[dict] = []
        try:
            for line in self.wal_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # ligne corrompue, ignorer
        except Exception as exc:
            log.warning(
                "ProjectWal.read_last : echec lecture WAL slug=%s : %s",
                self._slug, exc,
            )
            return []

        return entries[-n:] if n > 0 else entries

    def read_all(self) -> list[dict]:
        """Retourne toutes les entrees WAL (identique a read_last sans limite)."""
        return self.read_last(n=0)

    def read_for_tx(self, tx_id: str) -> list[dict]:
        """Retourne toutes les entrees WAL pour un tx_id specifique."""
        return [e for e in self.read_all() if e.get("tx_id") == tx_id]

    # ── Stats ────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """
        Retourne les statistiques du WAL.

        Retourne :
            {
                "entry_count":  int,   # nombre d'entrees valides
                "size_bytes":   int,   # taille du fichier en octets
                "last_ts":      str | None,  # timestamp de la derniere entree
                "first_ts":     str | None,  # timestamp de la premiere entree
                "success_count": int,
                "failure_count": int,
            }
        """
        if not self.wal_path.exists():
            return {
                "entry_count": 0, "size_bytes": 0,
                "last_ts": None, "first_ts": None,
                "success_count": 0, "failure_count": 0,
            }

        entries = self.read_all()
        size_bytes = self.wal_path.stat().st_size
        first_ts = entries[0].get("_ts")  if entries else None
        last_ts  = entries[-1].get("_ts") if entries else None
        success_count  = sum(1 for e in entries if e.get("success", True))
        failure_count  = sum(1 for e in entries if not e.get("success", True))

        return {
            "entry_count":   len(entries),
            "size_bytes":    size_bytes,
            "first_ts":      first_ts,
            "last_ts":       last_ts,
            "success_count": success_count,
            "failure_count": failure_count,
        }

    # ── Compaction ──────────────────────────────────────────────────────────

    def compact(self, keep_entries: int = DEFAULT_KEEP_ENTRIES) -> int:
        """
        Archive les entrees les plus anciennes, conserve les `keep_entries` dernieres.

        Ecriture atomique : .tmp -> Path.replace() (regle T-14).
        Le fichier archive est nomme : wal_archive/project_wal_YYYYMMDD.jsonl

        Retourne le nombre d'entrees archivees.
        """
        if not self.wal_path.exists():
            return 0

        entries = self.read_all()
        if len(entries) <= keep_entries:
            return 0

        to_archive = entries[:-keep_entries]
        to_keep    = entries[-keep_entries:]

        # Creer le dossier archive
        try:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.warning(
                "ProjectWal.compact : impossible de creer wal_archive/ slug=%s : %s",
                self._slug, exc,
            )
            return 0

        # Nom du fichier archive : date du jour
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        archive_path = self.archive_dir / f"project_wal_{date_str}.jsonl"

        try:
            # Ajouter au fichier archive (append — plusieurs compactions/jour)
            with archive_path.open("a", encoding="utf-8") as fh:
                for entry in to_archive:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

            # Reecrire le WAL actif avec les entrees conservees (atomique T-14)
            tmp_path = self.wal_path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as fh:
                for entry in to_keep:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            tmp_path.replace(self.wal_path)

            n = len(to_archive)
            log.info(
                "ProjectWal.compact : %d entree(s) archivee(s) slug=%s -> %s",
                n, self._slug, archive_path.name,
            )
            return n

        except Exception as exc:
            log.warning(
                "ProjectWal.compact : echec compaction WAL slug=%s : %s",
                self._slug, exc,
            )
            # Nettoyage du .tmp si present
            tmp_path = self.wal_path.with_suffix(".tmp")
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            return 0
