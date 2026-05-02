# -*- coding: utf-8-sig -*-
"""
main_medi.py — LCCA V5 Fusion
Sprint 08 — TASK-08-03

Entry point dédié au projet MediBot.
Deux modes :
    1. Commande directe : python main_medi.py "DashV1 - rdv - Ajoute export_pdf()"
    2. REPL interactif  : python main_medi.py

Commandes REPL spéciales :
    exit / quit / q   → Quitter
    status            → Stats workspace + palace
    history           → 20 dernières commandes
    dry:<commande>    → Simulation sans modification
    help / ?          → Aide rapide
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# ── Utilitaires ──────────────────────────────────────────────────────────────

def _setup_logging(verbose: bool = False) -> None:
    """Configure le logging (INFO par défaut, DEBUG si --verbose)."""
    import logging
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        level=level,
    )


def _print_banner(orchestrator) -> None:
    """Affiche le bandeau de démarrage avec les stats du contexte."""
    stats = orchestrator.status()
    print("\n" + "═" * 60)
    print("  🏥  LCCA V5 Fusion — MediBot Mode")
    print("═" * 60)
    print(f"  📁  Workspace  : {stats['workspace']}")
    print(f"  🗂️   Fichiers   : {stats['n_files']} indexés, {stats['n_symbols']} symboles")
    if stats["palace_available"]:
        print(f"  🧠  MemPalace  : ✅ {stats['palace_path']}")
        print(f"  📄  Specs      : {stats['specs_loaded']} chargée(s)")
        if stats["lcca_collections"]:
            cols = ", ".join(stats["lcca_collections"])
            print(f"  🗄️   Collections : {cols}")
    else:
        print("  🧠  MemPalace  : ⚠️  Non disponible (mode dégradé)")
    print("═" * 60)


# ── REPL ─────────────────────────────────────────────────────────────────────

def run_repl(orchestrator) -> None:
    """REPL interactif avec historique des 20 dernières commandes."""
    history: list[str] = []

    print("\n💡 Commandes spéciales : exit | status | history | dry:<commande> | help")
    print("   Appuyer sur Ctrl+C puis taper 'exit' pour quitter.\n")

    while True:
        try:
            cmd = input("MediBot> ").strip()
        except EOFError:
            print("\nFin d'entrée (EOF) — au revoir 👋")
            break
        except KeyboardInterrupt:
            print("\n  (Ctrl+C — taper 'exit' pour quitter)")
            continue

        if not cmd:
            continue

        lower = cmd.lower()

        # ── Commandes spéciales ───────────────────────────────────────────────
        if lower in ("exit", "quit", "q"):
            print("Au revoir 👋")
            break

        if lower in ("help", "?"):
            print(
                "\n  exit / quit / q     → Quitter\n"
                "  status              → Stats workspace + palace\n"
                "  history             → 20 dernières commandes\n"
                "  dry:<commande>      → Simulation sans modification\n"
                "  <commande DSL>      → Exécution réelle\n"
                "  Format DSL : Projet - Cible - [Sous-cible -] Action\n"
                "  Exemple    : DashV1 - rdv - Ajoute validate_slot()\n"
            )
            continue

        if lower == "status":
            stats = orchestrator.status()
            print(f"\n  📁  {stats['n_files']} fichier(s) indexé(s)")
            print(f"  🧠  {stats['n_symbols']} symbole(s)")
            print(f"  💾  Palace : {'✅' if stats['palace_available'] else '⚠️  Non disponible'}")
            print(f"  📄  {stats['specs_loaded']} spec(s) chargée(s)\n")
            continue

        if lower == "history":
            if not history:
                print("  (historique vide)")
            else:
                for i, h in enumerate(history[-20:], 1):
                    print(f"  {i:2d}. {h}")
            print()
            continue

        if lower.startswith("dry:"):
            dry_cmd = cmd[4:].strip()
            if not dry_cmd:
                print("  Usage: dry:<commande DSL>")
                continue
            result = orchestrator.dry_run(dry_cmd)
            intent = result["intent"]
            print(f"\n  🔍  Dry run : {dry_cmd!r}")
            print(f"  Intent   : target={intent.target!r}, action={intent.action!r}, "
                  f"confidence={intent.confidence:.0%}")
            print(f"  Fichiers : {result['target_files']}")
            print(f"  Plan     : {len(result['plan'])} opération(s)")
            if not result["plan_valid"]:
                print(f"  ⚠️  Erreurs plan : {result['plan_errors']}")
            print()
            continue

        # ── Exécution DSL ─────────────────────────────────────────────────────
        history.append(cmd)
        success = orchestrator.execute(cmd)
        if success:
            print(f"  ✅ Exécuté avec succès\n")
        else:
            print(f"  ❌ Échec (voir logs pour détails)\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="main_medi",
        description="LCCA V5 Fusion — Agent de codage MediBot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples :\n"
            '  python main_medi.py "DashV1 - rdv - Ajoute export_pdf()"\n'
            "  python main_medi.py --dry \"Auth - auth - Ajoute validate_token()\"\n"
            "  python main_medi.py --status\n"
            "  python main_medi.py             (mode REPL interactif)\n"
        ),
    )
    parser.add_argument(
        "command",
        nargs="?",
        help="Commande DSL à exécuter (mode direct). Si omis : mode REPL.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help=r"Chemin du workspace MediBot (défaut: D:\MediBot)",
    )
    parser.add_argument(
        "--dry",
        action="store_true",
        help="Simulation sans modification (dry_run).",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Affiche les stats du workspace et quitte.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Mode verbose (DEBUG logs).",
    )

    args = parser.parse_args()
    _setup_logging(verbose=args.verbose)

    # Import tardif pour ne pas crasher si core manque
    try:
        from core.orchestrator_medi import MediBotOrchestrator
    except ImportError as exc:
        print(f"❌ Import échoué : {exc}", file=sys.stderr)
        return 2

    # Initialisation
    try:
        orchestrator = MediBotOrchestrator(workspace=args.workspace)
    except FileNotFoundError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    _print_banner(orchestrator)

    # ── Mode --status ─────────────────────────────────────────────────────────
    if args.status:
        return 0

    # ── Mode direct avec --dry ────────────────────────────────────────────────
    if args.command and args.dry:
        result = orchestrator.dry_run(args.command)
        intent = result["intent"]
        print(f"\n🔍 Dry run : {args.command!r}")
        print(f"   target={intent.target!r}, action={intent.action!r}, "
              f"confidence={intent.confidence:.0%}")
        print(f"   Fichiers  : {result['target_files']}")
        print(f"   Opérations: {len(result['plan'])}")
        return 0

    # ── Mode direct ───────────────────────────────────────────────────────────
    if args.command:
        success = orchestrator.execute(args.command)
        return 0 if success else 1

    # ── Mode REPL ─────────────────────────────────────────────────────────────
    run_repl(orchestrator)
    return 0


if __name__ == "__main__":
    sys.exit(main())
