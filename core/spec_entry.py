# -*- coding: utf-8-sig -*-
"""spec_entry.py — LCCA V7.2
Sprint 14 — Dataclass autonome initial.
Sprint 19 — memory_layer ajouté (champ officiel, plus de getattr fragile).
Sprint 20 — Migration V7.2 :
            - Ajout : domain, version, complexity_score, generated_by,
                      validated, validation_notes, superseded_by, deprecated.
            - VALID_DOMAINS + VALID_GENERATED_BY (frozensets).
            - SpecEntry.make_spec_id(body_md) disponible comme classmethod V7.2.
            - make_spec_id(title, abstract) conservée comme fonction module-level
              pour rétrocompatibilité (Sprints 14-19, tests existants).
            - is_usable() migré vers logique V7.2 :
                validated AND NOT deprecated AND superseded_by is None AND score >= min_score
            - to_dict() / from_dict() : tous les champs V7.2 + champs legacy.
Sprint 22 — Cleanup legacy :
            - Suppression champ `complexity` (remplacé par complexity_score).
            - Champs legacy conservés : tags, created_at, promoted, score.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional


# ── Constantes de domaine (spec V7.2) ────────────────────────────────────────

VALID_DOMAINS = frozenset({
    "transaction", "ast", "mcp", "sandbox",
    "memory", "spec", "orchestration", "global"
})

VALID_GENERATED_BY = frozenset({
    "deep_reasoning", "spec_formatter", "hybrid", "manual"
})


# ── SpecDiff (V9-09) ────────────────────────────────────────────────────────

@dataclass
class SpecDiff:
    """Résultat de la comparaison entre deux versions de SpecEntry.

    Attributes:
        spec_id_before : spec_id de la version de référence (self).
        spec_id_after  : spec_id de la version comparée (other).
        added          : Violations présentes dans other mais pas dans self.
        removed        : Violations présentes dans self mais pas dans other.
        stable         : Violations communes aux deux versions.
        changed_fields : Champs SpecEntry dont la valeur diffère.
    """
    spec_id_before: str
    spec_id_after:  str
    added:          List[str]
    removed:        List[str]
    stable:         List[str]
    changed_fields: List[str]


# ── Fonction module-level (rétrocompatibilité Sprints 14-19) ─────────────────

def make_spec_id(title: str, abstract: str) -> str:
    """Rétrocompat : MD5 de title::abstract (12 chars).
    Conservée pour les tests et le code existants qui appellent
    make_spec_id(title, abstract). Utiliser SpecEntry.make_spec_id(body_md)
    pour le nouveau code conforme V7.2.
    """
    raw = f"{title.strip()}::{abstract.strip()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class SpecEntry:
    """
    Entrée de specification technique dans la collection lcca_specs.

    Champs identité (V7.2) :
        spec_id          : MD5 12 chars — SpecEntry.make_spec_id(body_md)
        domain           : Domaine architectural (VALID_DOMAINS)
        version          : Version de la spec (ex: "7.2.0")
        complexity_score : Score 0-100 (heuristique sections + règles)

    Champs contenu :
        title, body_md, abstract

    Champs provenance (V7.2) :
        generated_by     : VALID_GENERATED_BY
        validated        : True si spec a passé validation — Règle 11
        validation_notes : Texte formaté des violations

    Champs lifecycle (V7.2) :
        superseded_by    : spec_id successeur — Règle 13
        deprecated       : True si retirée

    Champs partagés V7.2 + legacy :
        usage_count      : Réutilisations TX
        memory_layer     : 2=scoped, 1=compressed, 0=identity (Sprint 19)

    Champs legacy (Sprints 14-19, conservés pour rétrocompat) :
        tags             : Labels libres
        created_at       : ISO-8601 UTC
        promoted         : True si intégrée Layer 0 (identity)
        score            : Score de validation 0.0-1.0 (utilisé dans is_usable)
    """
    # Champs requis (sans valeur par défaut)
    spec_id:          str
    title:            str
    abstract:         str
    body_md:          str

    # Champs V7.2 avec valeurs par défaut
    domain:           str           = "global"
    version:          str           = "7.2.0"
    complexity_score: int           = 0
    generated_by:     str           = "manual"
    validated:        bool          = False
    validation_notes: str           = ""
    superseded_by:    Optional[str] = None
    deprecated:       bool          = False

    # Champs partagés V7.2 + legacy
    usage_count:      int           = 0
    memory_layer:     int           = 2   # 2=scoped (défaut), 1=compressed, 0=identity

    # Champs legacy conservés (rétrocompat Sprints 14-19)
    tags:             list[str]     = field(default_factory=list)
    created_at:       str           = field(default_factory=lambda: datetime.utcnow().isoformat())
    promoted:         bool          = False
    score:            float         = 0.0

    # ── API V7.2 ──────────────────────────────────────────────────────────────

    @classmethod
    def make_spec_id(cls, body_md: str) -> str:
        """V7.2 : spec_id = MD5 du corps complet (12 chars).
        Interface classmethod conforme à la spec V7.2.
        Distinct de la fonction module-level make_spec_id(title, abstract).
        """
        return hashlib.md5(body_md.encode("utf-8")).hexdigest()[:12]

    def is_usable(self, min_score: float = 0.8) -> bool:
        """
        True si la spec peut être utilisée dans un pipeline TX.

        Logique V7.2 (Sprint 20) :
          - validated=True obligatoire (Règle 11 : spec non validée jamais réutilisée)
          - deprecated=False obligatoire
          - superseded_by=None obligatoire (Règle 13 : spec supersedée jamais réutilisée)
          - score >= min_score (garde secondaire sur la qualité)
        """
        return (
            self.validated
            and not self.deprecated
            and self.superseded_by is None
            and self.score >= min_score
        )

    # ── Sérialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            # Champs V7.2
            "spec_id":          self.spec_id,
            "domain":           self.domain,
            "version":          self.version,
            "complexity_score": self.complexity_score,
            "title":            self.title,
            "body_md":          self.body_md,
            "abstract":         self.abstract,
            "generated_by":     self.generated_by,
            "validated":        self.validated,
            "validation_notes": self.validation_notes,
            "superseded_by":    self.superseded_by,
            "deprecated":       self.deprecated,
            "usage_count":      self.usage_count,
            "memory_layer":     self.memory_layer,
            # Champs legacy conservés
            "tags":             self.tags,
            "created_at":       self.created_at,
            "promoted":         self.promoted,
            "score":            self.score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpecEntry":
        return cls(
            spec_id          = data["spec_id"],
            title            = data["title"],
            abstract         = data["abstract"],
            body_md          = data["body_md"],
            # Champs V7.2 (défauts rétrocompat pour anciens JSON sans ces clés)
            domain           = data.get("domain", "global"),
            version          = data.get("version", "7.2.0"),
            complexity_score = int(data.get("complexity_score", 0)),
            generated_by     = data.get("generated_by", "manual"),
            validated        = bool(data.get("validated", False)),
            validation_notes = data.get("validation_notes", ""),
            superseded_by    = data.get("superseded_by"),
            deprecated       = bool(data.get("deprecated", False)),
            usage_count      = int(data.get("usage_count", 0)),
            memory_layer     = int(data.get("memory_layer", 2)),
            # Champs legacy conservés
            tags             = data.get("tags", []),
            created_at       = data.get("created_at", datetime.utcnow().isoformat()),
            promoted         = bool(data.get("promoted", False)),
            score            = float(data.get("score", 0.0)),
        )

    # ── Diff V9-09 ──────────────────────────────────────────────────────────

    def diff(self, other: "SpecEntry") -> "SpecDiff":
        """
        Compare cette spec avec `other` et retourne les violations
        ajoutées, supprimées et stables entre les deux versions.

        Args:
            other : Spec à comparer (version plus récente typiquement).

        Returns:
            SpecDiff avec listes added/removed/stable.
        """
        self_v  = set(self.validation_notes.splitlines()) if self.validation_notes else set()
        other_v = set(other.validation_notes.splitlines()) if other.validation_notes else set()

        # Filtrer les lignes vides
        self_v  = {l for l in self_v  if l.strip()}
        other_v = {l for l in other_v if l.strip()}

        added   = sorted(other_v - self_v)
        removed = sorted(self_v  - other_v)
        stable  = sorted(self_v  & other_v)

        changed_fields: List[str] = []
        for attr in ("title", "domain", "version", "generated_by",
                      "validated", "deprecated", "superseded_by",
                      "complexity_score", "score"):
            if getattr(self, attr) != getattr(other, attr):
                changed_fields.append(attr)

        return SpecDiff(
            spec_id_before = self.spec_id,
            spec_id_after  = other.spec_id,
            added          = added,
            removed        = removed,
            stable         = stable,
            changed_fields = changed_fields,
        )

    def save(self, directory: Path) -> Path:
        """Sauvegarde en JSON utf-8 (sans BOM — standard JSON)."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.spec_id}.json"
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path) -> "SpecEntry":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)
