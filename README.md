![LCCA — Local Cognitive Coding Agency](assets/brand/lcca-logo.svg)

# LCCA V5 Fusion — Local Cognitive Coding Agency

**Votre agence de développement assistée par IA, directement sur votre poste.**

LCCA V5 Fusion est un environnement de développement intelligent qui associe la puissance d'un agent de codage à une architecture locale et transactionnelle. Le projet dispose de sa propre **interface graphique (GUI) de bureau**, pensée pour offrir une expérience utilisateur moderne dans l'esprit de Claude Desktop ou Codex.

LCCA vous donne également la liberté de **connecter des modèles d'IA externes via leurs API** : choisissez les modèles et les fournisseurs adaptés à vos besoins, et faites évoluer votre environnement sans vous enfermer dans un écosystème unique.

Son moteur Python applique les modifications de code de manière **transactionnelle**, en s'appuyant sur l'AST avec libcst plutôt que sur des remplacements de texte brut. Chaque opération est atomique, avec rollback automatique en cas d'erreur.

### Les atouts de LCCA

- **Une véritable interface graphique de bureau** : pilotez votre environnement de codage depuis une GUI dédiée.
- **Liberté de choix des modèles** : ajoutez et utilisez des modèles d'IA externes au moyen de leurs API.
- **Modifications maîtrisées** : transformations structurelles du code via AST/libcst.
- **Sécurité transactionnelle** : opérations atomiques, journalisation WAL et rollback.
- **Architecture locale** : gardez la maîtrise de votre environnement et de vos projets.

---

## Installation

```powershell
python -m venv venv
venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
```

**Prérequis** : Python 3.11+, Windows (paths `D:\\`)

---

## Utilisation

```powershell
# Commande DSL principale
python main.py "Projet - Cible - Action Details"

# Mode simulation (aucune modification)
python main.py --dry-run "Auth - login - Ajoute validate_token()"

# État du système
python main.py --status

# Lister les dernières transactions
python main.py --list-tx

# Réparer les transactions orphelines
python main.py --recover

# Archiver et vider le WAL
python main.py --clear-wal

# Mode verbeux
python main.py -v "..."
```

### Format DSL

```
"Projet - Cible - Action Details"
"Projet - Cible - SousCible - Action Details"
```

Exemples :
```
"DashboardV1 - Auth - Ajoute validate_email()"
"MediBot - RDV - Modal - Modifie confirm_rdv()"
"Projet - utils - Crée le module helpers"
```

---

## Architecture

```
D:\\LLMCodeAgent
├── core\\                    # Moteur transactionnel
│   ├── transaction_manager  # ACID + WAL JSONL + rollback
│   ├── ast_indexer          # Indexation symboles (ast stdlib)
│   ├── smart_patcher        # Patches AST (libcst)
│   ├── dependency_graph     # Graphe dépendances inter-fichiers
│   ├── planner              # MultiFilePlanner + tri topologique
│   ├── orchestrator         # LCCAV5Fusion — pipeline end-to-end
│   ├── dsl_parser           # Parsing commandes utilisateur
│   ├── file_selector       # Sélection fichiers cibles (3 stratégies)
│   ├── executor             # Validation syntaxe + pytest
│   ├── recovery_service     # Détection/repair transactions orphelines
│   └── error_analyzer       # Suggestions auto-fix
├── workspace\\               # Code cible (seul dossier modifiable)
├── transactions\\            # WAL JSONL + backups .bak
├── tests\\                   # Tests unitaires + intégration
├── main.py                  # CLI
└── config.py                # Paths centralisés
```

### Pipeline d'exécution

```
Commande DSL
    │
    ▼
DSLParser → Intent (projet, cible, action, confiance)
    │
    ▼
FileSelector → Fichiers cibles (max 3, 3 stratégies)
    │
    ▼
MultiFilePlanner → Plan ordonné par priorité
    │
    ▼
TransactionManager.begin() → WAL BEGIN + snapshots MD5
    │
    ▼
SmartPatcher (libcst) → Patches AST
    │
    ▼
Executor.validate() → compile() syntaxe
    │
    ├─ OK  → COMMIT → re-indexation
    └─ KO  → ROLLBACK → restauration .bak
```

---

## Conventions LCCA

| Règle | Détail |
|-------|--------|
| Paths | Toujours `pathlib.Path`, jamais `"D:\\\\"` strings |
| Encodage | `encoding='utf-8-sig'` (BOM) sur tous les `write_text` Windows |
| AST | Libcst pour **modifier**, ast stdlib pour **indexer** |
| Subprocess | Toujours `sys.executable` (jamais `"python"` hardcodé) |
| Classes | `PascalCase` · Fonctions `snake_case` · Privés `_prefix` |
| TX | Max 3 fichiers par transaction (`MAX_FILES_PER_TX`) |

---

## Lancer les tests

```powershell
pytest tests/ -v
# 120+ tests, ~40s
```

---

## Sprints réalisés

| Sprint | Contenu | Statut |
|--------|---------|--------|
| 01 | Fondations, structure, stubs | ✅ |
| 02 | TransactionManager ACID + WAL | ✅ |
| 03 | ASTIndexer + SmartPatcher + DependencyGraph | ✅ |
| 04 | DSLParser + FileSelector + MultiFilePlanner + Orchestrateur | ✅ |
| 05 | MemPalace (ChromaDB) + ContextAssembler | ✅ |
| 06 | RecoveryService + Executor + ErrorAnalyzer | ✅ |
| 07 | CLI main.py + Tests intégration + WAL archivage | ✅ |

---

*LCCA V5 Fusion — 2026*
