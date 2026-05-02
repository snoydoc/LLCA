# -*- coding: utf-8 -*-
"""
LCCA SelfImprove — CLI V10.5
Point d'entrée : python lcca_si.py <commande> [options]

Commandes disponibles :
  observe                    Observer une fois, génère observation JSON
  decide [--dry-run|--auto]  Orchestrator sur observations récentes
  auto-fix enable|disable    Active/désactive l'Auto-Fix Engine
  educator ingest            Génère une suggestion de pattern
  history [--since] [--action] Affiche les dernières actions
  approve <action_id>        Valide une action en attente
  borgnes                    Affiche la borgnes_map.json
  mode <1|2|3>               Change le mode de couplage

Conforme aux conventions LCCA (skill 001) :
  - Path, snake_case, pas de f-strings dans les logs
  - Imports stdlib au niveau module
  - sys.executable pour toute invocation Python
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Ajout SelfImprove au path si lancé depuis la racine du projet
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("lcca_si")

_SI_DIR = _ROOT / "SelfImprove"
_AUTO_FIX_FLAG = _SI_DIR / ".auto_fix_enabled"
_ORCHESTRATOR_LOCK = _SI_DIR / ".orchestrator_lock"


# ---------------------------------------------------------------------------
# Commandes
# ---------------------------------------------------------------------------

def cmd_observe(args: argparse.Namespace) -> int:
    """Lance l'Observer une fois et écrit le fichier d'observation."""
    from SelfImprove.engines.observer_daemon import ObserverDaemon
    daemon = ObserverDaemon()
    obs_path = daemon.run_once()
    if obs_path:
        print("Observation écrite :", obs_path)
        return 0
    print("[ERREUR] L'Observer n'a produit aucune observation.", file=sys.stderr)
    return 1


def cmd_decide(args: argparse.Namespace) -> int:
    """Lance l'Orchestrator sur les observations récentes."""
    dry_run: bool = getattr(args, "dry_run", False)
    auto: bool = getattr(args, "auto", False)

    if auto and _ORCHESTRATOR_LOCK.exists():
        print("[SKIP] Orchestrator déjà en cours (.orchestrator_lock présent).")
        return 0

    from SelfImprove.engines.orchestrator import OrchestratorLight
    orch = OrchestratorLight(dry_run=dry_run)

    if auto:
        _ORCHESTRATOR_LOCK.touch()
        try:
            result = orch.run()
        finally:
            _ORCHESTRATOR_LOCK.unlink(missing_ok=True)
    else:
        result = orch.run()

    if dry_run:
        print("\n=== DRY-RUN — aucune action exécutée ===")
        for item in result.get("matched_rules", []):
            print(" •", item["rule_id"], "→", item["action"], "(", item.get("reason", ""), ")")
        if not result.get("matched_rules"):
            print("  (aucune règle matchée)")
    else:
        triggered = result.get("triggered", 0)
        skipped = result.get("skipped", 0)
        print("Orchestrator terminé — déclenché:", triggered, "| ignoré:", skipped)
    return 0


def cmd_auto_fix(args: argparse.Namespace) -> int:
    """Active ou désactive l'Auto-Fix Engine."""
    subcommand = args.subcommand
    if subcommand == "enable":
        _AUTO_FIX_FLAG.touch()
        print("Auto-Fix Engine ACTIVÉ.")
    elif subcommand == "disable":
        _AUTO_FIX_FLAG.unlink(missing_ok=True)
        print("Auto-Fix Engine DÉSACTIVÉ.")
    else:
        print("[ERREUR] Sous-commande inconnue :", subcommand, file=sys.stderr)
        return 1
    return 0


def cmd_educator(args: argparse.Namespace) -> int:
    """Lance l'Educator pour générer une suggestion de pattern."""
    source = getattr(args, "source", "auto-fix")
    file_path = getattr(args, "file", None)

    from SelfImprove.engines.educator import EducatorSI
    educator = EducatorSI()
    suggestion_path = educator.ingest(source=source, file_path=file_path)
    if suggestion_path:
        print("Suggestion générée :", suggestion_path)
        return 0
    print("[INFO] Aucune suggestion générée (données insuffisantes).")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    """Affiche les dernières lignes de actions.log."""
    from SelfImprove.si_config import load_config
    cfg = load_config()
    actions_log = Path(cfg["paths"]["actions_log"])

    if not actions_log.exists():
        print("actions.log absent — aucune action enregistrée.")
        return 0

    since: str | None = getattr(args, "since", None)
    action_filter: str | None = getattr(args, "action", None)
    limit: int = getattr(args, "limit", 20)

    rows: list[list[str]] = []
    with actions_log.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # skip header
        for row in reader:
            if len(row) < 5:
                continue
            if action_filter and row[2] != action_filter:
                continue
            if since and _parse_since(since) and row[0] < _parse_since(since):
                continue
            rows.append(row)

    rows = rows[-limit:]
    if not rows:
        print("Aucune action trouvée.")
        return 0

    # Affichage tableau simple
    header = ["timestamp", "rule_id", "action", "target", "status", "details"]
    col_w = [26, 30, 25, 35, 12, 40]
    sep = "  "
    print(sep.join(h.ljust(w) for h, w in zip(header, col_w)))
    print("-" * (sum(col_w) + len(sep) * (len(col_w) - 1)))
    for row in rows:
        padded = [str(row[i] if i < len(row) else "").ljust(col_w[i]) for i in range(len(col_w))]
        print(sep.join(padded))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    """Valide une action en attente (require_human_ack=true)."""
    from SelfImprove.si_utils import approve_pending_action, log_action
    action_id: str = args.action_id
    approved = approve_pending_action(action_id)
    if approved is None:
        print("[ERREUR] Action introuvable ou déjà traitée :", action_id, file=sys.stderr)
        return 1

    log_action(
        rule_id=approved["rule_id"],
        action=approved["action"],
        target=approved["target"],
        status="approved",
        details="human_ack via lcca approve",
    )
    print("Action approuvée :", action_id)
    print("  rule :", approved["rule_id"])
    print("  action :", approved["action"])
    print("  target :", approved["target"])

    # Exécution immédiate après ACK
    from SelfImprove.engines.orchestrator import OrchestratorLight
    orch = OrchestratorLight(dry_run=False)
    orch.execute_action(
        rule_id=approved["rule_id"],
        action=approved["action"],
        target=approved["target"],
        params=approved.get("params", {}),
    )
    return 0


def cmd_borgnes(args: argparse.Namespace) -> int:
    """Affiche la borgnes_map.json (héritage V10)."""
    from SelfImprove.si_config import load_config
    cfg = load_config()
    borgnes_path = Path(cfg["paths"]["borgnes_map"])

    if not borgnes_path.exists():
        print("borgnes_map.json absent — lancez 'lcca observe' pour alimenter les données.")
        return 0

    data = json.loads(borgnes_path.read_text(encoding="utf-8"))
    borgnes = data.get("borgnes", [])
    if not borgnes:
        print("Aucun borgne identifié pour l'instant.")
        print("Total fossils WAL analysés :", data.get("total_wal_fossils", 0))
        return 0

    print("=== Borgnes Map V10 ===")
    print("Générée le :", data.get("generated_at", "N/A"))
    print("Total fossils WAL :", data.get("total_wal_fossils", 0))
    print()
    for b in borgnes:
        sev = b.get("severity", "?")
        marker = "🔴" if sev == "high" else "🟡" if sev == "medium" else "⚪"
        print(marker, b.get("name", "?"), "— occurrences:", b.get("count", 0))
        print("   Intent sample :", b.get("intent_sample", ""))
        print("   Error type    :", b.get("error_type", ""))
        print()
    return 0


def cmd_mode(args: argparse.Namespace) -> int:
    """Change le mode de couplage dans config.toml."""
    mode = int(args.mode)
    if mode not in (1, 2, 3):
        print("[ERREUR] Mode invalide. Valeurs acceptées : 1, 2, 3", file=sys.stderr)
        return 1

    config_path = _SI_DIR / "config.toml"
    if not config_path.exists():
        print("[ERREUR] config.toml introuvable.", file=sys.stderr)
        return 1

    content = config_path.read_text(encoding="utf-8")
    import re
    new_content = re.sub(
        r"^coupling_mode\s*=\s*\d",
        "coupling_mode = %d" % mode,
        content,
        flags=re.MULTILINE,
    )
    config_path.write_text(new_content, encoding="utf-8")
    print("Mode de couplage mis à jour :", mode)
    names = {1: "Lecture seule", 2: "Semi-couplé (défaut)", 3: "Couplé pipeline"}
    print(" →", names[mode])
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_since(since: str) -> str | None:
    """Convertit 'yesterday', 'today' ou une date ISO en préfixe ISO UTC."""
    now = datetime.now(timezone.utc)
    if since == "today":
        return now.strftime("%Y-%m-%d")
    if since == "yesterday":
        from datetime import timedelta
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    # Tenter une date directe
    try:
        datetime.fromisoformat(since)
        return since[:10]
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Parser CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lcca_si",
        description="LCCA SelfImprove V10.5 — CLI",
    )
    sub = parser.add_subparsers(dest="command")

    # observe
    sub.add_parser("observe", help="Observer une fois")

    # decide
    p_decide = sub.add_parser("decide", help="Orchestrator sur observations récentes")
    p_decide.add_argument("--dry-run", action="store_true", help="Affiche les actions sans les exécuter")
    p_decide.add_argument("--auto", action="store_true", help="Mode automatique avec verrou")

    # auto-fix
    p_af = sub.add_parser("auto-fix", help="Active/désactive l'Auto-Fix Engine")
    p_af.add_argument("subcommand", choices=["enable", "disable"])

    # educator
    p_edu = sub.add_parser("educator", help="Génère une suggestion de pattern")
    p_edu_sub = p_edu.add_subparsers(dest="edu_command")
    p_ingest = p_edu_sub.add_parser("ingest")
    p_ingest.add_argument("--source", choices=["auto-fix", "borgnes", "manual"], default="auto-fix")
    p_ingest.add_argument("--file", default=None, help="Fichier source (mode manual)")

    # history
    p_hist = sub.add_parser("history", help="Dernières actions")
    p_hist.add_argument("--since", default=None, help="Filtrer par date (today, yesterday, YYYY-MM-DD)")
    p_hist.add_argument("--action", default=None, help="Filtrer par type d'action")
    p_hist.add_argument("--limit", type=int, default=20, help="Nombre de lignes (défaut 20)")

    # approve
    p_app = sub.add_parser("approve", help="Valider une action en attente")
    p_app.add_argument("action_id", help="UUID de l'action à approuver")

    # borgnes
    sub.add_parser("borgnes", help="Afficher la borgnes_map.json")

    # mode
    p_mode = sub.add_parser("mode", help="Changer le mode de couplage (1, 2 ou 3)")
    p_mode.add_argument("mode", type=int, choices=[1, 2, 3])

    return parser


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "observe": cmd_observe,
        "decide": cmd_decide,
        "auto-fix": cmd_auto_fix,
        "educator": cmd_educator,
        "history": cmd_history,
        "approve": cmd_approve,
        "borgnes": cmd_borgnes,
        "mode": cmd_mode,
    }

    if args.command is None:
        parser.print_help()
        return 0

    handler = dispatch.get(args.command)
    if handler is None:
        print("[ERREUR] Commande inconnue :", args.command, file=sys.stderr)
        return 1

    try:
        return handler(args)
    except KeyboardInterrupt:
        print("\nInterrompu.")
        return 130
    except Exception as exc:  # noqa: BLE001
        log.error("Erreur non gérée dans '%s' : %s", args.command, exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
