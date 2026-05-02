# -*- coding: utf-8-sig -*-
"""
migrate_palace.py -- MIG-05
Script de migration : peuple le palace local LLCA depuis les skills .claude-skills/
et les donnees historiques exportees du MCP.

Usage :
    python mempalace/migration/migrate_palace.py [--dry-run]

Le script :
1. Lit les 3 skills LLCA (.claude-skills/001/002/003)
2. Decoupe chaque skill en drawers atomiques par section
3. Importe dans le palace local via MemPalaceClient
4. Importe les drawers historiques MCP (sp03 + v7-env-validation)
5. Produit migration_report.json

Aucune dependance vers D:\\MediBot ni le MCP palace partage.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# -- Setup path pour imports LLCA -----------------------------------------
BASE_DIR = Path(__file__).resolve().parents[2]  # D:\LLMCodeAgent
sys.path.insert(0, str(BASE_DIR))

logging.basicConfig(
    format="%(asctime)s [%(levelname)-8s] %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("migrate_palace")

SKILLS_DIR  = BASE_DIR / ".claude-skills"
EXPORT_DIR  = BASE_DIR / "mempalace" / "migration" / "export"
REPORT_PATH = BASE_DIR / "mempalace" / "migration" / "migration_report.json"

# Mapping section keyword -> (wing, room)
SECTION_MAP: list[tuple[str, str, str]] = [
    # (keyword_in_header, wing, room)
    ("ARBORESCENCE CORE",     "architecture", "arbo"),
    ("core/agents",           "architecture", "agents"),
    ("ÉTAT DES TESTS",        "tests",        "etat_tests"),
    ("SPRINTS TERMINÉS",      "architecture", "sprint_history"),
    ("WHITELIST EDUCATOR",    "educator",     "whitelist"),
    ("EDUCATOR RUNNER",       "educator",     "runner"),
    ("FIX-NETWORK",           "tests",        "fix_network"),
    ("DETTE TECHNIQUE",       "architecture", "dette_technique"),
    ("CONVENTIONS PROJET",    "architecture", "conventions"),
    ("PALACE LOCAL LLCA",     "mempalace",    "config"),
    ("POLITIQUE TIMEOUT",     "llm",          "timeout_policy"),
    ("MODÈLE ACTIF",          "llm",          "model_config"),
    ("ENVIRONNEMENT",         "architecture", "env"),
    ("STACK DÉPENDANCES",     "architecture", "dependencies"),
    ("ANTI-PATTERNS",         "tests",        "antipatterns"),
    ("RÈGLE FONDAMENTALE",    "tests",        "regle_fondamentale"),
    ("ERREURS OUTILS",        "tests",        "erreurs_outils"),
    ("ERREURS PYTEST",        "tests",        "erreurs_pytest"),
    ("CHECKLIST",             "tests",        "checklists"),
    ("RÔLE",                  "architecture", "role"),
    ("WORKFLOW",              "architecture", "workflow"),
    ("RÈGLES INVARIANTES",    "architecture", "regles_invariantes"),
    ("AGENTS",                "architecture", "agents_rules"),
    ("DIAGNOSTIC",            "architecture", "diagnostic"),
    ("MISE À JOUR",           "architecture", "session_update"),
    ("SESSION 2026",          "architecture", "session_logs"),
    ("ui/",                   "ui",           "arbo"),
    ("web_search",            "web_search",   "arbo"),
]


def _split_into_sections(text: str, skill_name: str) -> list[tuple[str, str, str]]:
    """
    Decoupe un fichier skill en sections atomiques.
    Retourne : liste de (wing, room, content).
    """
    sections: list[tuple[str, str, str]] = []
    lines = text.splitlines()
    current_lines: list[str] = []
    current_wing = "architecture"
    current_room = skill_name.replace(".md", "").replace("-", "_")

    for line in lines:
        # Detecte un header de section (## ou ###)
        if line.startswith("## ") or line.startswith("### "):
            # Sauvegarde la section precedente si non vide
            content = "\n".join(current_lines).strip()
            if content and len(content) > 20:
                sections.append((current_wing, current_room, content))
            current_lines = [line]
            # Cherche le mapping
            matched = False
            for kw, wing, room in SECTION_MAP:
                if kw.lower() in line.lower():
                    current_wing = wing
                    current_room = room
                    matched = True
                    break
            if not matched:
                current_wing = "architecture"
                current_room = skill_name.replace(".md", "")
        else:
            current_lines.append(line)

    # Derniere section
    content = "\n".join(current_lines).strip()
    if content and len(content) > 20:
        sections.append((current_wing, current_room, content))

    return sections


def run(dry_run: bool = False) -> dict:
    """Execute la migration. Retourne le rapport."""

    try:
        from config import PALACE_DIR
        from core.mempalace_client import MemPalaceClient
    except ImportError as exc:
        log.error("Import echoue : %s -- lancer depuis D:\\LLMCodeAgent", exc)
        sys.exit(1)

    palace_path = str(PALACE_DIR)
    log.info("Palace cible : %s", palace_path)
    log.info("Mode : %s", "DRY-RUN" if dry_run else "REEL")

    report = {
        "date": datetime.now().isoformat(),
        "palace_path": palace_path,
        "dry_run": dry_run,
        "skills_processed": [],
        "drawers_total": 0,
        "drawers_imported": 0,
        "drawers_skipped": 0,
        "errors": [],
    }

    # -- Init client (skip si dry-run car ChromaDB non necessaire) -----------
    client = None
    if not dry_run:
        try:
            client = MemPalaceClient(palace_path=palace_path)
            log.info("MemPalaceClient initialise OK")
        except Exception as exc:
            log.error("MemPalaceClient init echoue : %s", exc)
            report["errors"].append(f"init: {exc}")
            # Continue en dry-run si ChromaDB absent
            dry_run = True
            log.warning("Basculement en dry-run (ChromaDB absent ?)")

    # -- ETAPE 1 : importer les skills LLCA ----------------------------------
    skill_files = sorted(SKILLS_DIR.glob("*.md"))
    log.info("Skills trouves : %d", len(skill_files))

    for skill_file in skill_files:
        log.info("Traitement : %s", skill_file.name)
        try:
            text = skill_file.read_text(encoding="utf-8-sig")
        except Exception as exc:
            report["errors"].append(f"{skill_file.name}: read error {exc}")
            continue

        sections = _split_into_sections(text, skill_file.name)
        imported = 0
        for wing, room, content in sections:
            report["drawers_total"] += 1
            if dry_run:
                log.debug("  [DRY] wing=%s room=%s len=%d", wing, room, len(content))
                report["drawers_skipped"] += 1
                continue
            try:
                client.mine_content(
                    content,
                    wing=wing,
                    room=room,
                    source="mig05_skills",
                    metadata={
                        "skill_file": skill_file.name,
                        "migration": "MIG-05",
                        "date": "2026-04-23",
                    },
                )
                imported += 1
                report["drawers_imported"] += 1
            except Exception as exc:
                log.warning("  Erreur import section wing=%s room=%s : %s", wing, room, exc)
                report["errors"].append(f"{skill_file.name}/{wing}/{room}: {exc}")
                report["drawers_skipped"] += 1

        report["skills_processed"].append({
            "file": skill_file.name,
            "sections": len(sections),
            "imported": imported,
        })
        log.info("  -> %d sections, %d importees", len(sections), imported)

    # -- ETAPE 2 : importer les drawers historiques MCP ----------------------
    mcp_drawers = [
        {
            "file": EXPORT_DIR / "drawers_llca" / "lccacodeagent_diary_sp03.json",
            "label": "sp03",
            "metadata": {"origin": "mcp_wing_lccacodeagent_diary", "date": "2026-04-16"},
        },
        {
            "file": EXPORT_DIR / "drawers_llca" / "claude_diary_lcca_v7_2026-04-18.json",
            "label": "v7-env-validation",
            "metadata": {"origin": "mcp_wing_claude_diary", "date": "2026-04-18"},
        },
    ]

    for drawer in mcp_drawers:
        drawer_path = drawer["file"]
        label       = drawer["label"]
        if not drawer_path.exists():
            log.warning("Drawer %s introuvable : %s", label, drawer_path)
            continue
        try:
            data    = json.loads(drawer_path.read_text(encoding="utf-8"))
            content = data["original_content"]
            wing    = data["wing_local"]
            room    = data["room_local"]
            report["drawers_total"] += 1

            if dry_run:
                log.info("[DRY] Drawer MCP %s : wing=%s room=%s", label, wing, room)
                report["drawers_skipped"] += 1
            else:
                client.mine_content(
                    content,
                    wing=wing,
                    room=room,
                    source="mig05_mcp_history",
                    metadata=drawer["metadata"],
                )
                report["drawers_imported"] += 1
                log.info("Drawer MCP %s importe OK (wing=%s room=%s)", label, wing, room)
        except Exception as exc:
            log.warning("Drawer %s : %s", label, exc)
            report["errors"].append(f"{label}: {exc}")

    # -- Rapport final -------------------------------------------------------
    log.info("=" * 50)
    log.info("RAPPORT MIGRATION")
    log.info("  Total drawers : %d", report["drawers_total"])
    log.info("  Importes      : %d", report["drawers_imported"])
    log.info("  Skipped       : %d", report["drawers_skipped"])
    log.info("  Erreurs       : %d", len(report["errors"]))
    log.info("=" * 50)

    REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Rapport ecrit : %s", REPORT_PATH)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="MIG-05 -- Migration palace local LLCA")
    parser.add_argument("--dry-run", action="store_true", help="Simulation sans ecriture")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
