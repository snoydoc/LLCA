# -*- coding: utf-8-sig -*-
"""
nl_repl.py — REPL interactif NL découplé de NLOrchestrator (Sprint REFACTO-01).

Extrait de nl_orchestrator.py pour réduire sa taille de 20.3 KB à < 12 KB.

NLRepl encapsule la boucle REPL interactive et les méthodes d'affichage.
NLOrchestrator.repl() délègue à NLRepl(self).start().
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.nl_types import NLResult, NLSession

if TYPE_CHECKING:
    from core.nl_orchestrator import NLOrchestrator

log = logging.getLogger("lcca.nl_repl")


class NLRepl:
    """
    REPL interactif découplé de NLOrchestrator.

    Usage :
        repl = NLRepl(orchestrator)
        repl.start()

    Commandes spéciales :
        exit / quit / q / bye  → Quitter
        status / état          → Afficher les stats de session
        history / historique   → Afficher l'historique des commandes
        help / aide / ?        → Afficher l'aide
        dry / simulate         → Activer/désactiver le mode dry-run
    """

    _REPL_EXIT    = {"exit", "quit", "q", "bye", ":q"}
    _REPL_STATUS  = {"status", "état", ":s"}
    _REPL_HISTORY = {"history", "historique", ":h"}
    _REPL_HELP    = {"help", "aide", "?", ":?"}
    _REPL_DRY     = {"dry", "dry-run", "simulate", "sim", ":d"}

    def __init__(self, orchestrator: "NLOrchestrator") -> None:
        self._orc = orchestrator

    def start(self) -> None:
        """Lance la boucle REPL interactive."""
        session  = NLSession()
        dry_mode = False

        self._print_banner()

        while True:
            try:
                prefix = "(dry) " if dry_mode else ""
                raw    = input(f"\n{prefix}▶ ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\nInterruption — fin de session.")
                break

            if not raw:
                continue

            cmd_lower = raw.lower()

            if cmd_lower in self._REPL_EXIT:
                print("\nAu revoir ! " + session.summary())
                break

            if cmd_lower in self._REPL_STATUS:
                nl_ok = self._orc.nl_parser.is_available()
                print(f"\n📊 Status")
                print(f"  NLParser (Ollama) : {'✅ disponible' if nl_ok else '⚠️  hors ligne (fallback heuristique)'}")
                print(f"  Projet            : {self._orc.project_dir}")
                print(f"  Fichiers indexés  : {len(self._orc._project_files)}")
                print(f"  {session.summary()}")
                continue

            if cmd_lower in self._REPL_HISTORY:
                if not session.results:
                    print("  (aucune commande exécutée)")
                else:
                    print(f"\n📋 Historique ({len(session.results)} commandes)")
                    for i, r in enumerate(session.results, 1):
                        icon = "✅" if r.success else "❌"
                        dr   = " [dry]" if r.dry_run else ""
                        print(f"  {i:2}. {icon}{dr} {r.command[:60]}")
                continue

            if cmd_lower in self._REPL_HELP:
                self._print_help()
                continue

            if cmd_lower in self._REPL_DRY:
                dry_mode = not dry_mode
                state = "activé" if dry_mode else "désactivé"
                print(f"  Mode dry-run {state}.")
                continue

            print()
            result = self._orc.run(raw, dry_run=dry_mode)
            session.add(result)
            print(result)

    def _print_banner(self) -> None:
        nl_ok = self._orc.nl_parser.is_available()
        model = getattr(self._orc.nl_parser, "_model", "?")
        print("=" * 60)
        print("  LCCA V5 Fusion — Interface Langage Naturel")
        print("=" * 60)
        print(f"  Projet : {self._orc.project_dir}")
        print(f"  Modèle : {model}")
        if nl_ok:
            print("  Ollama : ✅ disponible")
        else:
            print("  Ollama : ⚠️  hors ligne — mode heuristique")
        print()
        print("  Exemples de commandes :")
        print("    Ajoute une fonction validate_email dans core/utils.py")
        print("    Corrige le bug dans handle_timeout")
        print("    Crée un fichier utils/validators.py")
        print()
        print("  Tapez 'help' pour l'aide, 'exit' pour quitter.")
        print("=" * 60)

    def _print_help(self) -> None:
        print("""
📖 Aide LCCA NL Interface
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Commandes naturelles (exemples) :
    "Ajoute une fonction validate_phone dans core/utils.py"
    "Modifie handle_timeout pour gérer le cas session=None"
    "Corrige le bug dans parse_message"
    "Crée un fichier utils/validators.py avec des helpers"
    "Montre le contenu de core/conversation.py"

  Commandes spéciales :
    status   / état       → Infos système et stats session
    history  / historique → Historique des commandes
    dry      / simulate   → Activer/désactiver le mode dry-run
    help     / aide / ?   → Cette aide
    exit     / quit / q   → Quitter

  Confiance :
    Le parser attribue une note de confiance (0% à 100%).
    En dessous de 40%, la commande est refusée.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━""")
