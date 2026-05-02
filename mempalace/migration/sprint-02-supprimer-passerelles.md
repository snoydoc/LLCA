# MIG-02 — Suppression des fichiers passerelle MediBot
# Statut : À FAIRE

## Objectif
Supprimer les 4 fichiers qui créent une dépendance directe vers MediBot.
Nettoyer les imports résiduels dans les fichiers qui restent.

## Prérequis
- MIG-01 lu et validé ✅

## Fichiers à supprimer

### 1. core/mempalace_adapter.py (11.3 KB)
Passerelle principale vers D:\MediBot\Mempalace\.
Contient : ExistingMemPalaceAdapter, wake_up_medi(), find_relevant_specs()
Collections : lcca_* (données LLCA stockées dans le palace MediBot)

**Action** : Supprimer via `filesystem:move_file` vers un dossier _archive temporaire
(on déplace, on ne supprime pas immédiatement — sécurité)

### 2. core/orchestrator_medi.py (7.6 KB)
MediBotOrchestrator — monte D:\MediBot comme workspace.
Importe : ExistingMemPalaceAdapter, LCCAV5Fusion

**Action** : Supprimer (move vers _archive)

### 3. main_medi.py (à la racine)
Point d'entrée MediBot.
Importe : MediBotOrchestrator depuis core.orchestrator_medi

**Action** : Supprimer (move vers _archive)

### 4. tests/test_medibot_adapter.py
8 tests sur ExistingMemPalaceAdapter.
Classes : TestExistingMemPalaceAdapter (5 tests dans test_mempalace_client.py aussi)

**Action** : Supprimer (move vers _archive)

## Références résiduelles à vérifier après suppression

Après avoir déplacé les 4 fichiers, vérifier dans :
- `core/orchestrator.py` → grep "orchestrator_medi" ou "MediBotOrchestrator"
- `core/mempalace_client.py` → grep "mempalace_adapter" ou "ExistingMemPalaceAdapter"
- `tests/test_mempalace_client.py` → contient TestExistingMemPalaceAdapter (5 tests à supprimer)
- Tout autre fichier .py → grep "MediBot" ou "medi"

## Procédure détaillée

```
ÉTAPE 1 — Créer dossier archive
filesystem:create_directory → D:\LLMCodeAgent\_archive_medibot\

ÉTAPE 2 — Déplacer les 4 fichiers
filesystem:move_file :
  core\mempalace_adapter.py    → _archive_medibot\mempalace_adapter.py
  core\orchestrator_medi.py    → _archive_medibot\orchestrator_medi.py
  main_medi.py                 → _archive_medibot\main_medi.py
  tests\test_medibot_adapter.py → _archive_medibot\test_medibot_adapter.py

ÉTAPE 3 — Lire tests/test_mempalace_client.py
Identifier les tests TestExistingMemPalaceAdapter et les supprimer (filesystem:edit_file)

ÉTAPE 4 — Grep références résiduelles
Lire les fichiers suspects listés ci-dessus
Supprimer les imports / blocs qui référencent les modules archivés

ÉTAPE 5 — Confirmer : aucun import "mempalace_adapter" ou "orchestrator_medi" restant
```

## Décompte tests après MIG-02
- Suppression test_medibot_adapter.py : -8 tests
- Suppression TestExistingMemPalaceAdapter dans test_mempalace_client.py : -5 tests
- **Total attendu : 1211 - 13 = 1198 passed**

## Statut final
Une fois terminé, mettre README.md MIG-02 → ✅ FAIT et lancer MIG-03.
