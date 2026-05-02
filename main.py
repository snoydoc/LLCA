# -*- coding: utf-8-sig -*-
"""
main.py — LCCA V5 Fusion
Sprint 07 — TASK-07-01

Entry point CLI. Transforme les composants core en produit utilisable.

Exemples :
    python main.py "DashboardV1 - Auth - Ajoute validate_email()"
    python main.py --dry-run "Auth - Modifie login()"
    python main.py --status
    python main.py --list-tx
    python main.py --recover
    python main.py --clear-wal
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _build_lcca(workspace_str: str):
    """Instancie LCCAV5Fusion avec gestion d'erreur claire."""
    from core.orchestrator import LCCAV5Fusion
    try:
        return LCCAV5Fusion(workspace=Path(workspace_str))
    except Exception as exc:
        print(f"❌ Erreur initialisation LCCA: {exc}")
        sys.exit(1)


def _build_recovery(lcca):
    """Instancie RecoveryService à partir d'une instance LCCAV5Fusion."""
    from core.recovery_service import RecoveryService
    return RecoveryService(lcca.tx_manager)


# ──────────────────────────────────────────────────────────────────────────────
# Sous-commandes
# ──────────────────────────────────────────────────────────────────────────────

def cmd_execute(args, lcca) -> int:
    """Exécute une commande DSL (mode normal ou dry-run)."""
    if not args.command:
        print("❌ Commande manquante.")
        print('   Usage: python main.py "Projet - Cible - Action Details"')
        return 1

    if args.dry_run:
        print("🔍 Mode dry-run — aucune modification ne sera effectuée\n")
        result = lcca.dry_run(args.command)
        intent = result["intent"]
        print(f"🎯 Intent parsé:")
        print(f"   Projet    : {intent.project}")
        print(f"   Cible     : {intent.target}")
        print(f"   Sous-cible: {intent.sub_target or 'N/A'}")
        print(f"   Action    : {intent.action}")
        print(f"   Détails   : {intent.details}")
        print(f"   Confiance : {intent.confidence:.0%}")

        print(f"\n📁 Fichiers cibles ({len(result['target_files'])}):")
        for f in result["target_files"]:
            exists = (lcca.workspace / f).exists()
            tag = "📄 existant" if exists else "🆕 à créer"
            print(f"   {tag}: {f}")

        plan = result["plan"]
        print(f"\n📋 Plan ({len(plan)} opération(s)):")
        for i, op in enumerate(plan, 1):
            sym = f" :: {op.target_symbol}" if op.target_symbol else ""
            print(f"   {i}. [{op.action.upper()}] {op.file}{sym}")
            print(f"      ↳ {op.description}")

        if not result["plan_valid"]:
            print(f"\n⚠️  Plan invalide: {result['plan_errors']}")

        print("\n⚠️  Mode dry-run — AUCUNE MODIFICATION EFFECTUÉE")
        return 0

    success = lcca.execute(args.command, auto_rollback=not args.no_rollback)
    if success:
        print("✅ Commande exécutée avec succès.")
        return 0
    else:
        print("❌ Echec d'exécution. Consultez les logs pour les détails.")
        return 1


def cmd_status(lcca) -> int:
    """Affiche l'état global du système."""
    from config import WAL_PATH

    print(f"📁 Workspace   : {lcca.workspace}")
    n_files   = len(lcca.indexer.files)
    n_symbols = len(lcca.indexer.symbols_table)
    print(f"🧠 Index       : {n_files} fichier(s), {n_symbols} symbole(s)")

    if WAL_PATH.exists():
        size_kb = WAL_PATH.stat().st_size // 1024
        n_lines = sum(1 for _ in WAL_PATH.open(encoding="utf-8-sig"))
        print(f"📋 WAL         : {n_lines} entrée(s) ({size_kb} KB) — {WAL_PATH}")
    else:
        print("📋 WAL         : non créé")

    recovery = _build_recovery(lcca)
    orphans = recovery.boot_check()
    if orphans:
        print(f"⚠️  TX orphelines: {orphans}")
    else:
        print("✅ Transactions : aucune orpheline")

    return 0


def cmd_list_tx() -> int:
    """Affiche les 10 dernières transactions commitées."""
    from config import WAL_PATH

    if not WAL_PATH.exists():
        print("📜 WAL vide — aucune transaction enregistrée.")
        return 0

    commits = []
    with WAL_PATH.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") == "COMMIT":
                commits.append(entry)

    if not commits:
        print("📜 Aucune transaction commitée trouvée.")
        return 0

    print(f"📜 Dernières transactions ({min(10, len(commits))}/{len(commits)}) :")
    for c in commits[-10:]:
        ts = (c.get("_ts") or c.get("timestamp", "?"))[:19]
        n_ops = c.get("n_ops", "?")
        recovery_tag = " [recovery]" if c.get("recovery") else ""
        print(f"  ✅ {c['tx_id']} | {ts} | {n_ops} op(s){recovery_tag}")

    return 0


def cmd_recover(lcca) -> int:
    """Détecte et répare les transactions orphelines."""
    recovery = _build_recovery(lcca)
    orphans = recovery.boot_check()

    if not orphans:
        print("✅ Aucune transaction orpheline à récupérer.")
        return 0

    print(f"🔧 {len(orphans)} transaction(s) orpheline(s) détectée(s).")
    results = recovery.auto_recover_pending(orphans)
    for tx_id, status in results.items():
        icons = {
            "committed":   "✅",
            "rolled_back": "⏮️",
            "failed":      "❌",
            "skipped":     "⏭️",
        }
        icon = icons.get(status, "❓")
        print(f"  {icon} {tx_id}: {status}")

    return 0


def cmd_clear_wal() -> int:
    """Archive le WAL courant et en crée un nouveau vide (après confirmation)."""
    from config import WAL_PATH

    if not WAL_PATH.exists():
        print("WAL déjà vide ou inexistant.")
        return 0

    size_kb = WAL_PATH.stat().st_size // 1024
    n_lines = sum(1 for _ in WAL_PATH.open(encoding="utf-8-sig"))
    print(f"WAL actuel : {n_lines} entrées, {size_kb} KB")

    try:
        confirm = input("⚠️  Archiver et vider le WAL ? (oui/non) : ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nAnnulé.")
        return 0

    if confirm != "oui":
        print("Annulé.")
        return 0

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive = WAL_PATH.parent / f"wal_archive_{ts}.jsonl"
    WAL_PATH.rename(archive)
    print(f"✅ WAL archivé : {archive}")
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Point d'entrée
# ──────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="LCCA V5 Fusion — Agent de codage transactionnel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  python main.py "DashboardV1 - Auth - Ajoute validate_email()"
  python main.py --dry-run "DashV1 - Auth - Ajoute login()"
  python main.py --status
  python main.py --list-tx
  python main.py --recover
  python main.py --clear-wal
        """,
    )
    parser.add_argument(
        "command", nargs="?",
        help="Commande DSL (ex: \"Projet - Cible - Action Details\")",
    )
    parser.add_argument(
        "-w", "--workspace",
        default="D:/LLMCodeAgent/workspace",
        metavar="DIR",
        help="Dossier workspace cible (défaut: D:/LLMCodeAgent/workspace)",
    )
    parser.add_argument(
        "--no-rollback", action="store_true",
        help="Désactive le rollback automatique en cas d'erreur",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Affiche le plan sans exécuter",
    )
    parser.add_argument(
        "--list-tx", action="store_true",
        help="Liste les 10 dernières transactions commitées",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Affiche l'état du système (index, WAL, transactions)",
    )
    parser.add_argument(
        "--recover", action="store_true",
        help="Détecte et répare les transactions orphelines",
    )
    parser.add_argument(
        "--clear-wal", action="store_true",
        help="Archive et vide le WAL (après confirmation)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Mode verbeux (niveau DEBUG)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # ── Logging ───────────────────────────────────────────────────────────────
    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    # ── Commandes sans LCCA ───────────────────────────────────────────────────
    if args.clear_wal:
        return cmd_clear_wal()

    if args.list_tx:
        return cmd_list_tx()

    # ── Commandes avec LCCA ───────────────────────────────────────────────────
    lcca = _build_lcca(args.workspace)

    if args.recover:
        return cmd_recover(lcca)

    if args.status:
        return cmd_status(lcca)

    # ── Exécution DSL (défaut) ────────────────────────────────────────────────
    return cmd_execute(args, lcca)


if __name__ == "__main__":
    sys.exit(main())
