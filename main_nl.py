# -*- coding: utf-8-sig -*-
"""
main_nl.py — LCCA V5 Fusion
Sprint 10 — TASK-10-05

Entry point pour l'interface langage naturel de LCCA.
Permet de piloter n'importe quel projet Python en langage naturel,
en passant par NLParser (Qwen2.5-Coder) → NLOrchestrator → LCCAV5Fusion.

Modes :
    1. REPL interactif  : python main_nl.py
    2. Commande directe : python main_nl.py "Ajoute validate_email dans core/utils.py"
    3. Dry-run          : python main_nl.py --dry "Corrige handle_timeout"
    4. Status           : python main_nl.py --status

Options :
    --project PATH      Dossier racine du projet cible (défaut: config.WORKSPACE_DIR)
    --model  MODEL      Modèle Ollama à utiliser pour le NL (défaut: config.NL_MODEL)
    --min-confidence N  Seuil de confiance 0.0-1.0 (défaut: 0.4)
    --auto-confirm      Exécute même si confiance < seuil (mode non-interactif)
    --dry               Mode dry-run (simule sans écrire)
    --status            Affiche les infos système et quitte
    --verbose / -v      Logs DEBUG

Exemples :
    python main_nl.py
    python main_nl.py "Ajoute validate_email dans core/utils.py"
    python main_nl.py --project D:\\MediBot --dry "Corrige le bug dans handle_timeout"
    python main_nl.py --project D:\\MediBot --status
    python main_nl.py --auto-confirm "Crée un fichier utils/validators.py"
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


# ── Logging ───────────────────────────────────────────────────────────────────

def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        level=level,
    )


# ── Status ────────────────────────────────────────────────────────────────────

def _print_status(orc) -> None:
    """Affiche les infos système de l'orchestrateur NL."""
    nl_ok    = orc.nl_parser.is_available()
    model    = getattr(orc.nl_parser, "_model", "?")
    n_files  = len(orc._project_files)
    min_conf = orc.min_confidence

    print("\n" + "=" * 60)
    print("  LCCA V5 Fusion - NL Interface - Status")
    print("=" * 60)
    print(f"  Projet          : {orc.project_dir}")
    print(f"  Fichiers .py    : {n_files} indexes")
    print(f"  Modele NL       : {model}")
    if nl_ok:
        print("  Ollama          : disponible")
    else:
        print("  Ollama          : hors ligne (mode heuristique)")
    print(f"  Seuil confiance : {min_conf:.0%}")
    print("=" * 60 + "\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="main_nl",
        description="LCCA V5 Fusion - Interface Langage Naturel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples :\n"
            "  python main_nl.py\n"
            '  python main_nl.py "Ajoute validate_email dans core/utils.py"\n'
            '  python main_nl.py --project D:\\MediBot --dry "Corrige handle_timeout"\n'
            "  python main_nl.py --status\n"
        ),
    )

    parser.add_argument(
        "command",
        nargs="?",
        default=None,
        help="Commande NL a executer (mode direct). Si omis : REPL interactif.",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        metavar="PATH",
        help="Dossier racine du projet cible (defaut: config.WORKSPACE_DIR).",
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help="Modele Ollama (ex: qwen2.5-coder:14b). Ecrase config.NL_MODEL.",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.4,
        dest="min_confidence",
        metavar="N",
        help="Seuil de confiance minimum pour executer (0.0-1.0, defaut: 0.4).",
    )
    parser.add_argument(
        "--auto-confirm",
        action="store_true",
        dest="auto_confirm",
        help="Execute meme si confiance < seuil (utile pour scripts).",
    )
    parser.add_argument(
        "--dry",
        action="store_true",
        help="Simule l'execution sans modifier les fichiers.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Affiche les infos systeme et quitte.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Active les logs DEBUG.",
    )

    args = parser.parse_args()
    _setup_logging(verbose=args.verbose)

    # ── Imports tardifs ────────────────────────────────────────────────────────
    try:
        from core.nl_orchestrator import NLOrchestrator
        from core.nl_parser import NLParser
    except ImportError as exc:
        print(f"Import echoue : {exc}", file=sys.stderr)
        return 2

    # ── Resolution du projet cible ─────────────────────────────────────────────
    project_dir: Path | None = args.project
    if project_dir is None:
        try:
            from config import WORKSPACE_DIR
            project_dir = WORKSPACE_DIR
        except ImportError:
            project_dir = Path("workspace")

    # ── Construction NLParser (avec override modele si --model) ───────────────
    nl_parser = NLParser(model=args.model) if args.model else None

    # ── Construction NLOrchestrator ────────────────────────────────────────────
    try:
        orc = NLOrchestrator(
            project_dir    = project_dir,
            nl_parser      = nl_parser,   # None = cree par defaut dans __init__
            min_confidence = args.min_confidence,
            auto_confirm   = args.auto_confirm,
        )
    except Exception as exc:
        print(f"Initialisation echouee : {exc}", file=sys.stderr)
        return 1

    # ── Mode --status ──────────────────────────────────────────────────────────
    if args.status:
        _print_status(orc)
        return 0

    # ── Mode direct + --dry ────────────────────────────────────────────────────
    if args.command and args.dry:
        result = orc.dry_run(args.command)
        print(result)
        return 0 if result.success else 1

    # ── Mode direct ────────────────────────────────────────────────────────────
    if args.command:
        result = orc.run(args.command)
        print(result)
        return 0 if result.success else 1

    # ── Mode REPL interactif ───────────────────────────────────────────────────
    orc.repl()
    return 0


if __name__ == "__main__":
    sys.exit(main())
