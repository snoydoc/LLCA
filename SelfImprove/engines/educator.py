# -*- coding: utf-8 -*-
"""
SelfImprove — EducatorSI V10.5 (SI-05)
Analyse des auto-fix réussis et borgnes pour générer des suggestions de patterns.

Règle fondamentale : EducatorSI ne modifie JAMAIS les fichiers système
(orchestrator_rules.json, auto_fix_whitelist.json). Suggestions uniquement.

Sources supportées :
  - "auto-fix"  : lit actions.log (CSV) → suggestions opérationnelles
  - "borgnes"   : lit borgnes_map.json → suggestions cognitives (angles morts V10)
  - "manual"    : analyse libre d'un fichier fourni

Sortie : fichiers .md dans SelfImprove/patterns/suggested_YYYY-MM-DD-NNN.md
Déduplication : hashlib.sha256(pattern_id + source)[:16]
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from SelfImprove.si_config import load_config, get_paths

log = logging.getLogger(__name__)

# Template Markdown pour les suggestions
_SUGGESTION_TEMPLATE = """\
# Suggestion — {pattern_id}
> Générée le : {date} | Source : {source} | Type : {suggestion_type}

## Pattern détecté
- **Nom** : `{pattern_id}`
- **Source** : {source_detail}
- **Type** : {suggestion_type}

## {section_title}
{section_body}

## Confiance
{confidence} ({count} occurrence(s))

## Validation humaine requise
- [ ] Ajouter dans `orchestrator_rules.json`
- [ ] Ajouter dans `auto_fix_whitelist.json` (si pertinent)
- [ ] Ajouter dans `prompts/rules.md` (si borgne cognitif)
"""


class EducatorSI:
    """Générateur de suggestions de patterns à partir des données SelfImprove.

    Ne modifie JAMAIS les fichiers de configuration système.
    Toutes les sorties sont des fichiers .md dans patterns/ pour révision humaine.
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self._cfg = cfg or load_config()
        self._paths = get_paths(self._cfg)
        self._patterns_dir = self._paths["patterns_dir"]
        self._patterns_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Point d'entrée public
    # ------------------------------------------------------------------

    def ingest(self, source: str, file_path: str | None = None) -> Path | None:
        """Analyse une source et crée une suggestion si les données sont suffisantes.

        Args:
            source: "auto-fix" | "borgnes" | "manual"
            file_path: chemin fichier source (requis pour source="manual")

        Returns:
            Chemin du fichier suggestion créé, ou None si données insuffisantes.
        """
        if source == "auto-fix":
            return self._ingest_auto_fix()
        if source == "borgnes":
            return self._ingest_borgnes()
        if source == "manual" and file_path:
            return self._ingest_manual(Path(file_path))
        log.info("EducatorSI.ingest : source '%s' invalide ou file_path manquant", source)
        return None

    # ------------------------------------------------------------------
    # Source : actions.log (auto-fix réussis)
    # ------------------------------------------------------------------

    def _ingest_auto_fix(self) -> Path | None:
        """Lit actions.log et génère une suggestion par pattern ayant au moins 1 succès."""
        actions_log = self._paths["actions_log"]
        if not actions_log.exists():
            log.info("EducatorSI : actions.log absent — aucune donnée auto-fix")
            return None

        # Comptage des succès par pattern_id
        counts: dict[str, int] = {}
        try:
            with actions_log.open(encoding="utf-8", newline="") as fh:
                reader = csv.reader(fh)
                for row in reader:
                    # Format : timestamp,rule_id,action,target,status,details
                    if len(row) < 5:
                        continue
                    _ts, rule_id, action, _target, status = row[:5]
                    if action == "auto_fix" and status == "success":
                        counts[rule_id] = counts.get(rule_id, 0) + 1
        except Exception as exc:  # noqa: BLE001
            log.error("EducatorSI : lecture actions.log échouée : %s", exc)
            return None

        if not counts:
            log.info("EducatorSI : aucun auto-fix réussi dans actions.log")
            return None

        # Génère une suggestion pour le pattern le plus fréquent
        top_pattern = max(counts, key=lambda k: counts[k])
        count = counts[top_pattern]

        confidence = self._count_to_confidence(count)
        source_detail = "actions.log (%d auto-fix(s) réussi(s))" % count

        return self._write_suggestion(
            pattern_id=top_pattern,
            source="auto-fix",
            suggestion_type="opérationnel",
            content={
                "section_title": "Correction appliquée",
                "section_body": (
                    "Pattern `%s` appliqué avec succès %d fois.\n"
                    "Candidat pour promotion dans `orchestrator_rules.json` "
                    "avec `auto_trigger: true`." % (top_pattern, count)
                ),
                "source_detail": source_detail,
                "confidence": confidence,
                "count": count,
            },
        )

    # ------------------------------------------------------------------
    # Source : borgnes_map.json (angles morts cognitifs V10)
    # ------------------------------------------------------------------

    def _ingest_borgnes(self) -> Path | None:
        """Lit borgnes_map.json et génère une suggestion cognitive pour les borgnes critiques."""
        borgnes_path = self._paths["borgnes_map"]
        if not borgnes_path.exists():
            log.info("EducatorSI : borgnes_map.json absent")
            return None

        try:
            data = json.loads(borgnes_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.error("EducatorSI : lecture borgnes_map.json échouée : %s", exc)
            return None

        borgnes = data.get("borgnes", [])
        if not borgnes:
            log.info("EducatorSI : borgnes_map vide — aucune suggestion")
            return None

        # Filtre : count >= 3 ET severity == "high"
        candidates = [
            b for b in borgnes
            if b.get("count", 0) >= 3 and b.get("severity", "") == "high"
        ]

        if not candidates:
            log.info("EducatorSI : aucun borgne count>=3 severity=high")
            return None

        # Prend le borgne le plus fréquent
        top = max(candidates, key=lambda b: b.get("count", 0))
        pattern_id = top.get("id", "borgne_inconnu")
        count = top.get("count", 0)
        description = top.get("description", "Angle mort détecté par clustering WAL.")

        confidence = self._count_to_confidence(count)
        source_detail = "borgnes_map.json (cluster WAL, %d occurrences)" % count

        return self._write_suggestion(
            pattern_id=pattern_id,
            source="borgnes",
            suggestion_type="cognitif (borgne V10)",
            content={
                "section_title": "Description du borgne",
                "section_body": (
                    "%s\n\n"
                    "**Fréquence** : %d occurrences\n"
                    "**Sévérité** : high\n\n"
                    "Envisager d'ajouter une règle dans `prompts/rules.md` "
                    "pour guider le modèle sur ce type de situation." % (description, count)
                ),
                "source_detail": source_detail,
                "confidence": confidence,
                "count": count,
            },
        )

    # ------------------------------------------------------------------
    # Source : fichier manuel
    # ------------------------------------------------------------------

    def _ingest_manual(self, source_file: Path) -> Path | None:
        """Analyse un fichier fourni manuellement et génère une suggestion."""
        if not source_file.exists():
            log.warning("EducatorSI : fichier manuel introuvable : %s", source_file)
            return None

        try:
            raw = source_file.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            log.error("EducatorSI : lecture fichier manuel échouée : %s", exc)
            return None

        # Identifiant basé sur le nom du fichier
        pattern_id = "manual_%s" % source_file.stem
        lines = raw.splitlines()
        preview = "\n".join(lines[:20]) if len(lines) > 20 else raw
        source_detail = "Fichier manuel : %s (%d lignes)" % (source_file.name, len(lines))

        return self._write_suggestion(
            pattern_id=pattern_id,
            source="manual",
            suggestion_type="opérationnel",
            content={
                "section_title": "Contenu analysé",
                "section_body": (
                    "**Fichier** : `%s`\n\n"
                    "```\n%s\n```\n\n"
                    "Réviser ce contenu et extraire les patterns applicables." % (
                        source_file.name, preview
                    )
                ),
                "source_detail": source_detail,
                "confidence": "manuelle",
                "count": 1,
            },
        )

    # ------------------------------------------------------------------
    # Écriture de la suggestion (avec déduplication)
    # ------------------------------------------------------------------

    def _write_suggestion(
        self,
        pattern_id: str,
        source: str,
        suggestion_type: str,
        content: dict[str, Any],
    ) -> Path:
        """Écrit un fichier suggestion .md avec déduplication par hash.

        Retourne le chemin du fichier (existant si doublon, nouveau sinon).
        """
        # Clé de déduplication : sha256(pattern_id + source)[:16]
        dedup_key = hashlib.sha256((pattern_id + source).encode("utf-8")).hexdigest()[:16]

        # Recherche doublon existant
        existing = list(self._patterns_dir.glob("suggested_*.md"))
        for f in existing:
            if dedup_key in f.read_text(encoding="utf-8", errors="ignore"):
                log.info("EducatorSI : suggestion déjà présente pour %s/%s — skip",
                         pattern_id, source)
                return f

        # Nouveau fichier
        seq = self._next_seq(self._patterns_dir)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filename = "suggested_%s-%03d.md" % (today, seq)
        out_path = self._patterns_dir / filename

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        body = _SUGGESTION_TEMPLATE.format(
            pattern_id=pattern_id,
            date=date_str,
            source=source,
            suggestion_type=suggestion_type,
            source_detail=content["source_detail"],
            section_title=content["section_title"],
            section_body=content["section_body"],
            confidence=content["confidence"],
            count=content["count"],
        )

        # Ajoute la clé de déduplication en commentaire HTML invisible
        body += "\n<!-- dedup:%s -->\n" % dedup_key

        try:
            out_path.write_text(body, encoding="utf-8")
            log.info("EducatorSI : suggestion créée : %s", out_path.name)
        except Exception as exc:  # noqa: BLE001
            log.error("EducatorSI : écriture suggestion échouée : %s", exc)
            raise

        return out_path

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _next_seq(self, patterns_dir: Path) -> int:
        """Retourne le prochain numéro séquentiel pour aujourd'hui."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        existing = list(patterns_dir.glob("suggested_%s-*.md" % today))
        return len(existing) + 1

    @staticmethod
    def _count_to_confidence(count: int) -> str:
        """Convertit un count en label de confiance."""
        if count >= 10:
            return "haute"
        if count >= 3:
            return "moyenne"
        return "faible"
