# MIG-03 — Nettoyage .claude-skills/ des références MediBot
# Statut : À FAIRE

## Objectif
Nettoyer les 3 fichiers skills LLCA de toutes mentions MediBot.
Mettre à jour le décompte de tests après MIG-02.

## Prérequis
- MIG-02 terminé ✅ (fichiers supprimés, tests à jour)

## Fichiers à éditer

### 001-master.md — AUCUNE MODIFICATION
Pas de référence MediBot directe. ✅ Laisser tel quel.

### 003-antipatterns.md — AUCUNE MODIFICATION
Pas de référence MediBot directe. ✅ Laisser tel quel.

### 002-context.md — MODIFICATIONS REQUISES

#### Section "core/agents/ — 25 fichiers"
Supprimer la ligne :
```
orchestrator_medi.py       Sprint 08 — MediBotOrchestrator : sous-classe LCCAV5Fusion sur D:\MediBot (7.6 KB)
```

#### Section "core/ — modules principaux"
Supprimer la ligne :
```
mempalace_adapter.py       Sprint 05/08 — ExistingMemPalaceAdapter : lecture palace MediBot, collections lcca_* isolées (11.3 KB) ⚠️ WARN >10KB
```

#### Section "SPRINTS TERMINÉS"
Modifier la ligne Sprint 08 :
```
AVANT : Sprint 08 (MediBotOrchestrator + ExistingMemPalaceAdapter)
APRÈS : Sprint 08 (supprimé — passerelle MediBot retirée en MIG-02)
```
Ou simplement supprimer la référence Sprint 08 si elle ne contient que du MediBot.

#### Section "Audit coverage Option B — B2"
Supprimer ou modifier :
```
- orchestrator_medi.py : couvert par test_medibot_adapter.py (mocking filesystem)
- test_medibot_adapter.py : 8 tests (identity, specs, fallback, wake_up_medi, collections)
- NOTE : test_mempalace_client.py contient également TestExistingMemPalaceAdapter (5 tests)
```
Remplacer par :
```
- orchestrator_medi.py : RETIRÉ (MIG-02) — passerelle MediBot supprimée
```

#### Section "ÉTAT DES TESTS"
Mettre à jour le compteur :
```
AVANT : 1211 passed attendus
APRÈS : 1198 passed attendus (1211 - 13 tests MediBot supprimés en MIG-02)
```

#### Section "Fichiers > 10 KB surveillés"
Supprimer la ligne :
```
| mempalace_adapter.py | 11.3 KB | ⚠️ Candidat REFACTO (handlers 13 tools) |
```
(ou la marquer RETIRÉ)

#### Toute autre mention de "MediBot", "medi", "D:\MediBot" dans 002-context.md
Faire un grep mental sur tout le fichier et supprimer les refs résiduelles.

## Procédure

```
ÉTAPE 1 — Lire 002-context.md complet (filesystem:read_text_file)
ÉTAPE 2 — Identifier TOUTES les lignes à modifier (liste exhaustive)
ÉTAPE 3 — Appliquer les edits en une passe (filesystem:edit_file × N)
ÉTAPE 4 — Relire les sections modifiées pour vérifier
```

## Après MIG-03
Le projet LLCA est propre côté code et documentation.
Étape suivante : installer le mempalace local (MIG-04).
