# -*- coding: utf-8-sig -*-
"""
educator_runner.py -- Lanceur autonome de l'EducatorAgent LCCA

Usage (appele par lcca_educator.bat) :
    python educator_runner.py --mode all
    python educator_runner.py --mode update
    python educator_runner.py --add-source <owner> <repo> [description]
    python educator_runner.py --list-sources
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# -- Racine du projet
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# -- Chemins Educator
EDUCATOR_DIR = Path(__file__).resolve().parent
LOGS_DIR     = EDUCATOR_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Source de verite unique -- tout est dans educator_whitelist.json
from core.agents.educator_whitelist import (
    load_whitelist_full,
    save_whitelist,
    WHITELIST_PATH,
)


# =============================================================================
# Gestion educator_whitelist.json
# =============================================================================

def cmd_add_source(owner: str, repo: str, description: str, skip_license: bool = False) -> int:
    data = load_whitelist_full()
    for entry in data:
        if entry.get("owner") == owner and entry.get("repo") == repo:
            print(f"  [INFO] {owner}/{repo} est deja dans la whitelist.")
            return 0
    entry: dict = {"owner": owner, "repo": repo, "description": description}
    if skip_license:
        entry["skip_license_check"] = True
    data.append(entry)
    save_whitelist(data)
    flag = "  [skip_license_check=true]" if skip_license else ""
    print(f"  [OK] {owner}/{repo} ajoute a educator_whitelist.json{flag}")
    print(f"  Total repos : {len(data)}")
    return 0


def cmd_toggle_skip(owner: str, repo: str) -> int:
    """Active ou desactive skip_license_check sur un repo existant."""
    data = load_whitelist_full()
    for entry in data:
        if entry.get("owner") == owner and entry.get("repo") == repo:
            current = entry.get("skip_license_check", False)
            if current:
                entry.pop("skip_license_check", None)
                save_whitelist(data)
                print(f"  [OK] {owner}/{repo} -- skip_license_check DESACTIVE")
            else:
                entry["skip_license_check"] = True
                save_whitelist(data)
                print(f"  [OK] {owner}/{repo} -- skip_license_check ACTIVE")
            return 0
    print(f"  [ERREUR] {owner}/{repo} introuvable dans la whitelist.")
    print("  Utilisez [3] Nouvelle source pour l'ajouter d'abord.")
    return 1


def cmd_list_sources() -> int:
    data = load_whitelist_full()
    if not data:
        print("  Whitelist vide.")
    else:
        print(f"  {len(data)} repo(s) dans la whitelist :")
        print()
        for i, e in enumerate(data, 1):
            desc = e.get("description", "")
            line = f"  [{i:02d}]  {e['owner']}/{e['repo']}"
            if desc:
                line += f"  --  {desc}"
            print(line)
    print()
    print(f"  Fichier : {WHITELIST_PATH}")
    return 0


# =============================================================================
# Logging
# =============================================================================

def setup_logging(log_file: Path) -> logging.Logger:
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    logging.basicConfig(
        level    = logging.INFO,
        format   = "%(asctime)s [%(levelname)s] %(name)s -- %(message)s",
        datefmt  = "%H:%M:%S",
        handlers = handlers,
    )
    return logging.getLogger("educator_runner")


# =============================================================================
# Callback progression
# =============================================================================

def make_progress_cb():
    start = time.monotonic()

    def cb(msg: str) -> None:
        elapsed = time.monotonic() - start
        m = int(elapsed // 60)
        s = int(elapsed % 60)
        print(f"  [{m:02d}:{s:02d}] {msg}", flush=True)

    return cb


# =============================================================================
# Rapport
# =============================================================================

def print_report(result, total_repos: int, elapsed: float, log_file: Path) -> None:
    lines = [
        "",
        "=" * 60,
        f"  RAPPORT EDUCATOR -- {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "=" * 60,
        f"  Mode           : {'SIMULATION (dry_run)' if result.dry_run else 'INGESTION REELLE'}",
        f"  Duree          : {int(elapsed // 60)}m {int(elapsed % 60)}s",
        f"  Whitelist      : {total_repos} repo(s)",
        "-" * 60,
        f"  Repos traites  : {result.repos_processed}",
        f"  Fichiers lus   : {result.files_fetched}",
        f"  Fichiers passes: {result.files_filtered}",
        f"  Skills ingeres : {result.skills_ingested}",
        f"  Contexte stocke: {result.context_ingested}",
        f"  Erreurs        : {len(result.errors)}",
    ]
    if result.errors:
        lines.append("-" * 60)
        lines.append("  Erreurs :")
        for err in result.errors[:10]:
            lines.append(f"    . {err}")
        if len(result.errors) > 10:
            lines.append(f"    ... et {len(result.errors) - 10} autres")
    lines += [
        "=" * 60,
        f"  Log : {log_file}",
        "=" * 60,
        "",
    ]
    print("\n".join(lines))


# =============================================================================
# Selection interactive des repos
# =============================================================================

def build_full_list() -> list[tuple[str, str, str]]:
    """
    Charge la whitelist complete depuis educator_whitelist.json.
    Retourne une liste de (owner, repo, description).
    """
    data = load_whitelist_full()
    return [
        (e["owner"], e["repo"], e.get("description", ""))
        for e in data
        if e.get("owner") and e.get("repo")
    ]


def select_repos(all_repos: list[tuple[str, str, str]]) -> list[str] | None:
    """
    Affiche la liste numerotee et demande une selection interactive.

    Saisie acceptee :
        *          -> tous
        1          -> un seul
        1 3 5      -> plusieurs (espaces ou virgules)
        1-5        -> plage inclusive
        q          -> annuler et retourner au menu

    Retourne une liste de 'owner/repo', ou None si annule.
    """
    print()
    print("=" * 64)
    print("  SELECTION DES REPOS A INGERER")
    print("=" * 64)
    print()
    print(f"  {'N':>3}  {'REPO':<32}  URL")
    print(f"  {'-'*3}  {'-'*32}  {'-'*38}")

    for i, (owner, repo, desc) in enumerate(all_repos, 1):
        label = f"{owner}/{repo}"
        url   = f"https://github.com/{owner}/{repo}"
        suffix = f"  -- {desc}" if desc else ""
        print(f"  {i:>3}  {label:<38}  {url}{suffix}")

    print()
    print("  *        -> tous les repos")
    print("  1        -> un seul repo")
    print("  1 3 5    -> plusieurs repos")
    print("  1-5      -> plage de repos")
    print("  q        -> annuler")
    print()

    while True:
        try:
            raw = input("  Votre selection : ").strip()
        except (EOFError, KeyboardInterrupt):
            return None

        if raw.lower() == "q":
            return None

        if raw == "*":
            selected = [f"{o}/{r}" for o, r, _d in all_repos]
        else:
            indices: set[int] = set()
            valid = True
            tokens = raw.replace(",", " ").split()
            for token in tokens:
                if "-" in token:
                    parts = token.split("-", 1)
                    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                        lo, hi = int(parts[0]), int(parts[1])
                        indices.update(range(lo, hi + 1))
                    else:
                        print(f"  [ERREUR] Plage invalide : {token}")
                        valid = False
                        break
                elif token.isdigit():
                    indices.add(int(token))
                else:
                    print(f"  [ERREUR] Token invalide : '{token}'")
                    valid = False
                    break

            if not valid:
                continue

            out_of_range = [i for i in indices if i < 1 or i > len(all_repos)]
            if out_of_range:
                print(f"  [ERREUR] Numero(s) hors plage 1-{len(all_repos)} : {sorted(out_of_range)}")
                continue

            if not indices:
                print("  [ERREUR] Aucune selection valide.")
                continue

            selected = [f"{all_repos[i-1][0]}/{all_repos[i-1][1]}" for i in sorted(indices)]  # (owner, repo, desc)

        # Confirmation
        print()
        print(f"  {len(selected)} repo(s) selectionne(s) :")
        for s in selected:
            print(f"    + {s}")
        print()
        try:
            confirm = input("  Confirmer et lancer l'ingestion ? [O/N] : ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None

        if confirm == "o":
            return selected

        print()
        print("  Annule. Recommencez votre selection.")
        print()


# =============================================================================
# Curation
# =============================================================================

def cmd_curation(dry_run: bool, log: logging.Logger, log_file: Path) -> int:
    try:
        import config as cfg
        cfg.EDUCATOR_ENABLED      = True
        cfg.EDUCATOR_DRY_RUN      = dry_run
        cfg.EDUCATOR_GITHUB_TOKEN = ""
        from core.agents.educator_agent import EducatorAgent, EducatorConfig
    except ImportError as exc:
        log.error("Import LCCA impossible : %s", exc)
        log.error("Verifiez que le venv est active et dans D:\\LLMCodeAgent")
        return 1

    educator_cfg = EducatorConfig(
        dry_run             = dry_run,
        max_files_per_repo  = cfg.EDUCATOR_MAX_FILES_PER_REPO,
        max_skills_per_repo = cfg.EDUCATOR_MAX_SKILLS_PER_REPO,
        min_score           = cfg.EDUCATOR_MIN_SCORE,
        min_filter_score    = cfg.EDUCATOR_MIN_FILTER_SCORE,
        sleep_between_repos = cfg.EDUCATOR_SLEEP_BETWEEN_REPOS,
        fetch_timeout       = cfg.EDUCATOR_FETCH_TIMEOUT,
        github_token        = "",
        stars_threshold     = cfg.EDUCATOR_STARS_THRESHOLD,
        retry_max           = cfg.EDUCATOR_RETRY_MAX,
        hash_persist_path   = str(cfg.EDUCATOR_HASH_PERSIST_PATH),
    )

    # Initialiser MemoryEngine pour que les snippets atterrissent dans ChromaDB
    memory = None
    try:
        from core.memory_engine import MemoryEngine
        memory = MemoryEngine()
        log.info("MemoryEngine initialise -- lcca_context actif")
    except Exception as exc:
        log.warning("MemoryEngine non disponible (ChromaDB absent ?) : %s", exc)
        log.warning("Les skills seront comptes mais pas stockes en memoire vectorielle.")

    agent = EducatorAgent(cfg=educator_cfg, memory=memory)

    # Selection interactive -- whitelist complete depuis le JSON
    all_repos    = build_full_list()
    repos_filter = select_repos(all_repos)
    if repos_filter is None:
        print("  Ingestion annulee.")
        return 0

    mode_label = "SIMULATION (dry-run)" if dry_run else "INGESTION COMPLETE"
    print()
    print("=" * 60)
    print(f"  LCCA Educator -- {mode_label}")
    print(f"  Debut  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Repos  : {len(repos_filter)} / {len(all_repos)}")
    print("=" * 60)
    print()
    print("  Curation en cours... (Ctrl+C pour interrompre)")
    print()

    start = time.monotonic()
    try:
        result = agent.run_curation(
            dry_run      = dry_run,
            repos_filter = repos_filter,
            progress_cb  = make_progress_cb(),
        )
    except KeyboardInterrupt:
        print("\n\n  [ARRET] Interruption clavier.")
        return 0

    elapsed = time.monotonic() - start
    print_report(result, len(all_repos), elapsed, log_file)
    return 0 if not result.errors else 1


# =============================================================================
# Reset hashes
# =============================================================================

def cmd_reset_hashes() -> int:
    """
    Vide le fichier educator_hashes.json pour forcer une re-ingestion complete.
    Utile quand une session precedente a compte des skills sans ecrire en memoire.
    """
    try:
        import config as cfg
        hash_path = Path(str(cfg.EDUCATOR_HASH_PERSIST_PATH))
    except Exception:
        hash_path = PROJECT_ROOT / "transactions" / "educator_hashes.json"

    print()
    if not hash_path.exists():
        print("  Aucun fichier de hashes trouve. Rien a faire.")
        print(f"  (chemin verifie : {hash_path})")
        return 0

    try:
        existing = json.loads(hash_path.read_text(encoding="utf-8"))
        count = len(existing) if isinstance(existing, list) else 0
    except Exception:
        count = 0

    print(f"  Fichier hashes : {hash_path}")
    print(f"  Hashes actuels : {count}")
    print()
    print("  Attention : cela forcera la re-ingestion de tous les fichiers")
    print("  deja vus lors des sessions precedentes.")
    print()

    try:
        confirm = input("  Confirmer la suppression des hashes ? [O/N] : ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return 0

    if confirm != "o":
        print("  Annule.")
        return 0

    hash_path.write_text("[]", encoding="utf-8")
    print(f"  [OK] {count} hash(es) effaces. La prochaine ingestion re-traitera tous les fichiers.")
    return 0


# =============================================================================
# Point d'entree
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="LCCA Educator Runner")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--mode", choices=["all", "update", "dry"],
                       help="all=ingestion reelle | update/dry=simulation")
    group.add_argument("--add-source", nargs="+", metavar=("OWNER", "REPO"),
                       help="Ajouter une source : owner repo [description] [--skip-license]")
    group.add_argument("--toggle-skip", nargs=2, metavar=("OWNER", "REPO"),
                       help="Activer/desactiver skip_license_check sur un repo existant")
    parser.add_argument("--skip-license", action="store_true",
                       help="Avec --add-source : ajouter skip_license_check=true")
    group.add_argument("--list-sources", action="store_true",
                       help="Lister les sources custom")
    group.add_argument("--reset-hashes", action="store_true",
                       help="Vider le fichier de deduplication pour forcer une re-ingestion")
    args = parser.parse_args()

    if args.list_sources:
        return cmd_list_sources()

    if args.reset_hashes:
        return cmd_reset_hashes()

    if args.toggle_skip:
        return cmd_toggle_skip(args.toggle_skip[0], args.toggle_skip[1])

    if args.add_source:
        parts = args.add_source
        if len(parts) < 2:
            print("  [ERREUR] Usage : --add-source owner repo [description]")
            return 1
        owner = parts[0]
        repo  = parts[1]
        desc  = " ".join(parts[2:]) if len(parts) > 2 else ""
        return cmd_add_source(owner, repo, desc, skip_license=getattr(args, "skip_license", False))

    # Curation avec logging complet
    session_ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    log_file   = LOGS_DIR / f"{session_ts}.log"
    log        = setup_logging(log_file)

    dry_run = args.mode in ("update", "dry")
    return cmd_curation(dry_run, log, log_file)


if __name__ == "__main__":
    sys.exit(main())
