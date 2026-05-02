# Spec 15 — CLIs (main.py + main_medi.py + main_nl.py)
> **Modules** : `main.py`, `main_medi.py` | **Sprints** : 07, 08, 10 | **Statut** : ✅ VALIDÉ

---

## 1. Vue d'ensemble

LCCA expose trois points d'entrée CLI distincts :

| Fichier | Usage | Sprint |
|---------|-------|--------|
| `main.py` | CLI généraliste LCCA, 6 sous-commandes | 07 |
| `main_medi.py` | CLI + REPL spécialisé MediBot | 08 |
| `main_nl.py` | CLI + REPL langage naturel | 10 |

---

## 2. main.py — CLI généraliste

### Sous-commandes

```
python main.py "Projet - Cible - Action Details"     → Exécution DSL
python main.py --dry-run "..."                        → Simulation
python main.py --status                               → Infos système
python main.py --list-tx                              → 10 dernières TX
python main.py --recover                              → Recovery orphelines
python main.py --clear-wal                            → Archive + vide WAL
```

### Options globales

| Option | Description |
|--------|-------------|
| `-w / --workspace DIR` | Dossier workspace (défaut: `D:/LLMCodeAgent/workspace`) |
| `--no-rollback` | Désactive le rollback automatique |
| `--dry-run` | Affiche le plan sans exécuter |
| `-v / --verbose` | Niveau DEBUG |

### `cmd_execute(args, lcca)`

**Mode dry-run** affiche :
- Intent parsé (projet, cible, sous-cible, action, confiance)
- Fichiers cibles (avec tag `📄 existant` ou `🆕 à créer`)
- Plan d'opérations numéroté avec description

**Mode normal** : appelle `lcca.execute(command, auto_rollback=not args.no_rollback)`

### `cmd_status(lcca)`
Affiche : workspace, nombre de fichiers/symboles indexés, taille WAL, TX orphelines.

### `cmd_list_tx()`
Lit le WAL et affiche les 10 derniers `COMMIT` avec timestamp, n_ops, flag recovery.

### `cmd_recover(lcca)`
Appelle `RecoveryService.boot_check()` + `auto_recover_pending()`, affiche les résultats avec icônes.

### `cmd_clear_wal()`
Archive `wal.jsonl` → `wal_archive_{timestamp}.jsonl` après confirmation interactive (`oui/non`).

---

## 3. main_medi.py — CLI MediBot

### Modes

```
python main_medi.py "DashV1 - rdv - Ajoute export_pdf()"   → Mode direct
python main_medi.py --dry "Auth - Ajoute validate_token()"  → Dry-run direct
python main_medi.py --status                                  → Stats + quitte
python main_medi.py                                           → Mode REPL
```

### Options

| Option | Description |
|--------|-------------|
| `--workspace PATH` | Chemin MediBot (défaut: `D:\MediBot`) |
| `--dry` | Dry-run en mode direct |
| `--status` | Affiche stats et quitte |
| `-v / --verbose` | Niveau DEBUG |

### REPL interactif (`run_repl`)

Historique des 20 dernières commandes en mémoire.

**Commandes spéciales :**
| Commande | Action |
|----------|--------|
| `exit / quit / q` | Quitter |
| `status` | Stats workspace + palace |
| `history` | 20 dernières commandes |
| `dry:<commande>` | Simulation de la commande |
| `help / ?` | Aide |

**Bandeau de démarrage** : affiche workspace, fichiers indexés, palace disponible/indisponible, specs chargées, collections LCCA.

---

## 4. main_nl.py — CLI Langage Naturel (Sprint 10)

```
python main_nl.py --project D:\MediBot\
python main_nl.py "Ajoute une fonction validate_phone"
```

Utilise `NLOrchestrator.repl()` ou `NLOrchestrator.run(command)`.

---

## 5. Conventions CLI communes

| Convention | Détail |
|-----------|--------|
| Import tardif | `from core.xxx import Xxx` dans les fonctions, pas au niveau module |
| Gestion erreur claire | `FileNotFoundError` → message lisible + `sys.exit(1)` |
| Codes de retour | `0` = succès, `1` = erreur, `2` = import échoué |
| `sys.executable` | Jamais `"python"` hardcodé en subprocess |
| Encoding | `utf-8-sig` pour tous les fichiers écrits sur Windows |
| `if __name__ == "__main__": sys.exit(main())` | Pattern standard |

---

## 6. Intégration système

```
main.py
    └── LCCAV5Fusion(workspace)
         ├── execute(command) → bool
         ├── dry_run(command) → dict
         └── tx_manager, indexer, recovery...

main_medi.py
    └── MediBotOrchestrator(workspace)
         ├── execute(command) → bool
         ├── dry_run(command) → dict
         └── status() → dict

main_nl.py
    └── NLOrchestrator(project_dir)
         ├── run(command) → NLResult
         ├── dry_run(command) → NLResult
         └── repl() → interactive
```
