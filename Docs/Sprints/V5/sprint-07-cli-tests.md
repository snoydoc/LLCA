# 🖥️ Sprint 07 — CLI, Tests d'intégration & Polish

> **Durée estimée** : 4 jours  
> **Statut** : ⚪ À FAIRE  
> **Priorité** : 🟡 Normale  
> **Dépend de** : Sprint 01 → 06 (tous les composants core)  
> **Objectif** : Finaliser l'interface CLI, écrire les tests d'intégration end-to-end, archiver le WAL, et polir le projet pour une première livraison stable.

---

## 🎯 Objectifs du Sprint

Ce sprint transforme les composants individuels en un **produit utilisable**. L'utilisateur doit pouvoir lancer `python main.py "commande DSL"` et obtenir un résultat cohérent, avec des messages clairs, un WAL propre, et une suite de tests verte.

---

## 📋 Tâches

### TASK-07-01 — `main.py` — CLI complète
**Priorité** : 🔴 Critique  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `main.py`

**Description** :  
Finaliser l'entry point CLI avec argparse, gestion des erreurs utilisateur, et affichage des résultats.

**Interface CLI complète** :
```
python main.py [commande] [options]

Arguments positionnels:
  commande              Commande DSL (ex: "Projet - Cible - Action Details")

Options:
  -w, --workspace DIR   Dossier workspace (défaut: D:/LLMCodeAgent/workspace)
  --no-rollback         Désactive le rollback automatique en cas d'erreur
  --recover             Mode recovery manuel (reprocess le WAL)
  --dry-run             Affiche le plan sans exécuter
  --list-tx             Liste les transactions récentes
  --status              Affiche l'état du système (index, WAL, transactions)
  --clear-wal           Archive et vide le WAL (après confirmation)
  -v, --verbose         Mode verbeux (niveau DEBUG)
  -h, --help            Affiche l'aide
```

**Implémentation** :
```python
#!/usr/bin/env python3
"""
LCCA V5 Fusion — Local Cognitive Coding Agency
Entry point CLI.
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime

from core.orchestrator import LCCAV5Fusion
from utils.logger import get_logger

log = get_logger("main")


def cmd_execute(args, lcca: LCCAV5Fusion) -> int:
    """Exécute une commande DSL."""
    if not args.command:
        print("❌ Commande manquante. Usage: python main.py \"Projet - Cible - Action\"")
        return 1
    
    if args.dry_run:
        print("🔍 Mode dry-run — aucune modification ne sera effectuée")
        lcca.dry_run(args.command)
        return 0
    
    success = lcca.execute(args.command, auto_rollback=not args.no_rollback)
    return 0 if success else 1


def cmd_status(lcca: LCCAV5Fusion) -> int:
    """Affiche l'état du système."""
    print(f"📁 Workspace: {lcca.workspace}")
    print(f"🧠 Index: {len(lcca.indexer.files)} fichiers indexés, {len(lcca.indexer.symbols_table)} symboles")
    
    wal_path = Path("D:/LLMCodeAgent/transactions/wal.jsonl")
    if wal_path.exists():
        lines = sum(1 for _ in open(wal_path, encoding='utf-8'))
        print(f"📋 WAL: {lines} entrées ({wal_path.stat().st_size // 1024} KB)")
    else:
        print("📋 WAL: non créé")
    
    orphans = lcca.recovery.boot_check()
    if orphans:
        print(f"⚠️  Transactions orphelines: {orphans}")
    else:
        print("✅ Pas de transactions orphelines")
    return 0


def cmd_list_tx(lcca: LCCAV5Fusion) -> int:
    """Liste les transactions récentes depuis le WAL."""
    print("📜 Transactions récentes :")
    # Lit les 20 dernières lignes COMMIT du WAL
    wal_path = Path("D:/LLMCodeAgent/transactions/wal.jsonl")
    if not wal_path.exists():
        print("  (WAL vide)")
        return 0
    
    import json
    commits = []
    with open(wal_path, encoding='utf-8') as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if entry.get("type") == "COMMIT":
                    commits.append(entry)
            except:
                pass
    
    for c in commits[-10:]:
        print(f"  ✅ {c['tx_id']} | {c.get('timestamp', '?')[:19]} | {c.get('n_ops', '?')} ops")
    return 0


def cmd_clear_wal() -> int:
    """Archive le WAL courant et en crée un nouveau vide."""
    wal_path = Path("D:/LLMCodeAgent/transactions/wal.jsonl")
    if not wal_path.exists():
        print("WAL déjà vide.")
        return 0
    
    confirm = input("⚠️  Archiver et vider le WAL ? (oui/non) : ")
    if confirm.lower() != "oui":
        print("Annulé.")
        return 0
    
    archive = wal_path.parent / f"wal_archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    wal_path.rename(archive)
    print(f"✅ WAL archivé dans {archive}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description='LCCA V5 Fusion — Agent de codage transactionnel',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  python main.py "DashboardV1 - Page RDV - Ajoute validate_email()"
  python main.py "Auth - Modifie login() pour ajouter 2FA" --dry-run
  python main.py --status
  python main.py --recover
        """
    )
    
    parser.add_argument('command', nargs='?', help='Commande DSL')
    parser.add_argument('-w', '--workspace', default='D:/LLMCodeAgent/workspace')
    parser.add_argument('--no-rollback', action='store_true')
    parser.add_argument('--recover', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--list-tx', action='store_true')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--clear-wal', action='store_true')
    parser.add_argument('-v', '--verbose', action='store_true')
    
    args = parser.parse_args()
    
    if args.verbose:
        import logging
        logging.getLogger('lcca').setLevel(logging.DEBUG)
    
    if args.clear_wal:
        return cmd_clear_wal()
    
    # Initialisation (inclut auto-recovery)
    try:
        lcca = LCCAV5Fusion(workspace=args.workspace)
    except Exception as e:
        print(f"❌ Erreur initialisation LCCA: {e}")
        return 1
    
    if args.recover:
        orphans = lcca.recovery.boot_check()
        if not orphans:
            print("✅ Pas de transactions orphelines à récupérer.")
        else:
            results = lcca.recovery.auto_recover_pending(orphans)
            for tx_id, status in results.items():
                icon = "✅" if status == "committed" else "⏮️" if status == "rolled_back" else "❌"
                print(f"  {icon} {tx_id}: {status}")
        return 0
    
    if args.status:
        return cmd_status(lcca)
    
    if args.list_tx:
        return cmd_list_tx(lcca)
    
    return cmd_execute(args, lcca)


if __name__ == "__main__":
    sys.exit(main())
```

**Critères d'acceptation** :
- [ ] `python main.py --help` affiche l'aide sans erreur
- [ ] `python main.py --status` affiche l'état du système
- [ ] `python main.py --dry-run "commande"` ne modifie aucun fichier
- [ ] `python main.py --list-tx` liste les 10 dernières TX commitées
- [ ] Exit code 0 si succès, 1 si erreur

---

### TASK-07-02 — `dry_run()` dans l'Orchestrateur
**Priorité** : 🟠 Haute  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Ajouter la méthode `dry_run()` à `LCCAV5Fusion` qui simule l'exécution sans rien écrire sur disque.

```python
def dry_run(self, command: str) -> None:
    """
    Simule l'exécution complète sans aucune modification disque.
    Affiche le plan détaillé.
    """
    from core.dsl_parser import DSLParser
    
    intent = DSLParser().parse(command)
    print(f"\n🎯 Intent parsé:")
    print(f"   Projet   : {intent.project}")
    print(f"   Cible    : {intent.target}")
    print(f"   Sous-cible: {intent.sub_target or 'N/A'}")
    print(f"   Action   : {intent.action}")
    print(f"   Détails  : {intent.details}")
    print(f"   Confiance: {intent.confidence:.0%}")
    
    target_files = self.selector.select(intent)
    print(f"\n📁 Fichiers cibles ({len(target_files)}):")
    for f in target_files:
        exists = (self.workspace / f).exists()
        status = "📄 existant" if exists else "🆕 à créer"
        print(f"   {status}: {f}")
    
    if target_files:
        plan = self.planner.create_plan(intent.details, target_files)
        print(f"\n📋 Plan ({len(plan)} opération(s)):")
        for i, op in enumerate(plan, 1):
            print(f"   {i}. [{op.action.upper()}] {op.file}" +
                  (f" :: {op.target_symbol}" if op.target_symbol else ""))
            print(f"      ↳ {op.description}")
    
    print("\n⚠️  Mode dry-run — AUCUNE MODIFICATION EFFECTUÉE")
```

**Critères d'acceptation** :
- [ ] Aucun fichier modifié après `dry_run()`
- [ ] Aucune entrée créée dans le WAL
- [ ] Affichage clair du plan prévu

---

### TASK-07-03 — Tests d'intégration end-to-end
**Priorité** : 🔴 Critique  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `tests/test_integration.py`

**Description** :  
Tests d'intégration qui exercent le système complet de bout en bout sur un workspace de test temporaire.

**Fixture workspace de test** :
```python
import pytest
import tempfile
from pathlib import Path

@pytest.fixture
def test_workspace(tmp_path):
    """Crée un workspace de test avec quelques fichiers Python."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    
    # Fichier de base
    (ws / "auth.py").write_text('''
"""Module d'authentification."""

def login(username: str, password: str) -> bool:
    """Authentifie un utilisateur."""
    return username == "admin" and password == "secret"
''', encoding='utf-8')
    
    # Fichier secondaire
    (ws / "utils.py").write_text('''
"""Utilitaires."""

def format_email(email: str) -> str:
    """Normalise une adresse email."""
    return email.strip().lower()
''', encoding='utf-8')
    
    return ws
```

**Scénarios de test** :
```python
def test_add_function_to_existing_file(test_workspace):
    """
    Scénario: Ajouter une fonction validate_email() à auth.py
    Résultat attendu: auth.py contient la nouvelle fonction, syntaxe valide
    """

def test_rollback_on_invalid_code(test_workspace):
    """
    Scénario: Patch qui génère du code invalide
    Résultat attendu: auth.py inchangé (MD5 identique à avant)
    """

def test_create_new_file(test_workspace):
    """
    Scénario: Créer un nouveau fichier validation.py
    Résultat attendu: fichier créé, indexé
    """

def test_dry_run_no_modification(test_workspace):
    """
    Scénario: dry_run sur workspace
    Résultat attendu: aucun fichier modifié
    """

def test_full_pipeline_commit(test_workspace):
    """
    Scénario complet: parse → select → plan → tx → patch → validate → commit
    Résultat attendu: TX commitée, fichier modifié, index mis à jour
    """

def test_wal_contains_full_trace(test_workspace):
    """
    Après une TX commitée, le WAL contient BEGIN + OP_START + OP_SUCCESS + COMMIT.
    """
```

**Critères d'acceptation** :
- [ ] `pytest tests/test_integration.py` → 6/6 tests passent
- [ ] Tests s'exécutent en < 30 secondes total
- [ ] Pas d'effets de bord entre les tests (fixtures isolées)

---

### TASK-07-04 — Archivage WAL périodique
**Priorité** : 🟡 Normale  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `core/transaction_manager.py` + `main.py`

**Description** :  
Le WAL grossit indéfiniment. Implémenter un archivage automatique des entrées de plus de 7 jours.

```python
def archive_old_wal_entries(self, days_to_keep: int = 7) -> int:
    """
    Déplace les entrées WAL de plus de N jours dans un fichier archive.
    Retourne le nombre d'entrées archivées.
    """
    if not self.wal_path.exists():
        return 0
    
    cutoff = datetime.now() - timedelta(days=days_to_keep)
    kept_lines = []
    archived_lines = []
    
    with open(self.wal_path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                ts_str = entry.get("_ts") or entry.get("timestamp", "")
                if ts_str:
                    ts = datetime.fromisoformat(ts_str[:19])
                    if ts < cutoff:
                        archived_lines.append(line)
                        continue
            except:
                pass
            kept_lines.append(line)
    
    if archived_lines:
        archive_file = self.wal_path.parent / f"wal_archive_{cutoff.strftime('%Y%m%d')}.jsonl"
        with open(archive_file, 'a', encoding='utf-8') as f:
            f.writelines(archived_lines)
        
        with open(self.wal_path, 'w', encoding='utf-8') as f:
            f.writelines(kept_lines)
        
        log.info(f"WAL: {len(archived_lines)} entrées archivées dans {archive_file.name}")
    
    return len(archived_lines)
```

**Critères d'acceptation** :
- [ ] Entrées de plus de 7 jours déplacées dans `wal_archive_YYYYMMDD.jsonl`
- [ ] WAL courant ne contient plus les anciennes entrées
- [ ] Archivage exécuté au démarrage si WAL > 1MB (dans `__init__` du TX Manager)

---

### TASK-07-05 — Documentation `README.md` projet
**Priorité** : 🟡 Normale  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `D:\LLMCodeAgent\README.md`

**Contenu attendu** :
```markdown
# LCCA V5 Fusion — Local Cognitive Coding Agency

Agent de codage local transactionnel pour Python.
Modifie le code via AST (libcst), jamais par texte brut.
Toute modification est atomique (rollback automatique en cas d'erreur).

## Installation
pip install -r requirements.txt

## Utilisation
python main.py "Projet - Cible - Action Details"

# Exemples
python main.py "DashboardV1 - Page RDV - Ajoute validate_email()"
python main.py --status
python main.py --dry-run "Auth - Modifie login()"

## Architecture
[diagramme simplifié]

## Conventions
- PascalCase classes, snake_case fonctions
- Paths via pathlib.Path (jamais strings avec \)
- encoding='utf-8-sig' sur tous les writes Windows
```

**Critères d'acceptation** :
- [ ] `README.md` à la racine du projet
- [ ] Section Installation, Utilisation, Exemples, Architecture
- [ ] Mention des conventions LCCA (pathlib, encoding, AST only)

---

## 📊 Récapitulatif Sprint 07

| Task | Description | Effort | Statut |
|------|------------|--------|--------|
| TASK-07-01 | CLI complète `main.py` | 1j | ⚪ |
| TASK-07-02 | `dry_run()` Orchestrateur | 0.5j | ⚪ |
| TASK-07-03 | Tests intégration e2e | 1j | ⚪ |
| TASK-07-04 | Archivage WAL | 0.5j | ⚪ |
| TASK-07-05 | README.md | 0.5j | ⚪ |
| **TOTAL** | | **3.5j** | |

---

## ✅ Définition of Done (Sprint 07)

- [ ] `pytest tests/` → **0 erreur, tous les tests passent**
- [ ] `python main.py --help` → aide complète affichée
- [ ] `python main.py --status` → état système affiché
- [ ] `python main.py "DashV1 - Auth - Ajoute login()"` → exécution end-to-end sans crash
- [ ] WAL archivage déclenché si WAL > 1MB
- [ ] `README.md` présent et à jour
- [ ] `004-sprint-context.md` mis à jour (toutes tasks cochées)

---

## ⚠️ Contraintes & Risques

| Risque | Probabilité | Mitigation |
|--------|------------|------------|
| Tests d'intégration lents (ChromaDB) | Moyenne | Mock MemPalace dans les tests e2e |
| `tmp_path` pytest ne supporte pas Windows long paths | Faible | Utiliser `D:/LLMCodeAgent/tests/tmp/` si tmp_path échoue |
| README obsolète dès le Sprint 08 | Certaine | Documenter uniquement la V1 (sans MediBot) |

---

## 🔗 Navigation

⬅️ [Sprint 06 — Recovery & Validation](sprint-06-recovery-validation.md)  
➡️ [Sprint 08 — MediBot Adapter (Bonus)](sprint-08-medibot-adapter.md)
