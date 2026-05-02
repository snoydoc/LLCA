# MIG-04 — Installer le mempalace local LLCA
# Statut : À FAIRE

## Objectif
Créer un mempalace local autonome dans D:\LLMCodeAgent\mempalace\
qui n'a aucune dépendance vers MediBot ni vers le MCP mempalace partagé.

## Prérequis
- MIG-03 terminé ✅ (code propre, skills à jour)

## Architecture cible

```
D:\LLMCodeAgent\mempalace\
├── migration\          ← ce dossier (sprints)
├── palace\             ← données ChromaDB (créé par MIG-04)
│   ├── wings\          ← structure hiérarchique wings/rooms
│   ├── lcca_solutions\ ← collection solutions
│   ├── lcca_context\   ← collection contexte
│   ├── lcca_failures\  ← collection échecs
│   ├── lcca_patches\   ← collection patches
│   ├── lcca_specs\     ← collection specs
│   └── lcca_skills\    ← collection skills
├── config.json         ← config palace LLCA
└── README.md           ← ce fichier (existant)
```

## Analyse des composants existants

Le projet LLCA a déjà `core/mempalace_client.py` (REFACTO-14) avec :
- `MemPalaceClient` → orchestration
- `PalaceLayers` (mempalace_layers.py) → 4 collections ChromaDB
- `PalaceFilesystem` (mempalace_fs.py) → wings/rooms hiérarchie JSON

Ces composants s'initialisent avec un chemin configurable.
**Pas de nouveau code à écrire** — il faut configurer le chemin.

## Procédure

### ÉTAPE 1 — Vérifier la signature de MemPalaceClient
```
filesystem:read_text_file → core/mempalace_client.py
→ identifier le paramètre de chemin palace (palace_path ou similaire)
→ identifier comment changer le chemin par défaut
```

### ÉTAPE 2 — Vérifier config.py
```
filesystem:read_text_file → config.py
→ chercher PALACE_PATH, MEMPALACE_PATH, ou similaire
→ si présent : modifier pour pointer vers D:\LLMCodeAgent\mempalace\palace\
→ si absent : ajouter la constante
```

### ÉTAPE 3 — Créer les dossiers de base
```
filesystem:create_directory → D:\LLMCodeAgent\mempalace\palace\
filesystem:create_directory → D:\LLMCodeAgent\mempalace\palace\wings\
```
(ChromaDB créera ses propres sous-dossiers au premier démarrage)

### ÉTAPE 4 — Créer config.json palace LLCA
```json
{
  "palace_name": "LLCA",
  "palace_path": "D:\\LLMCodeAgent\\mempalace\\palace",
  "version": "1.0",
  "created": "2026-04-23",
  "collections": ["lcca_solutions", "lcca_context", "lcca_failures", "lcca_patches", "lcca_specs", "lcca_skills"],
  "source": "migration MIG-04 (séparé de MediBot)"
}
```

### ÉTAPE 5 — Vérifier que MemPalaceClient pointe sur le bon chemin
Lire core/mempalace_client.py et core/mempalace_layers.py
Confirmer que le chemin configuré est utilisé (pas hardcodé vers MediBot)

### ÉTAPE 6 — Test smoke
Vérifier dans les tests existants (test_mempalace_client.py / test_refacto_14.py)
que le palace s'initialise sans erreur avec le nouveau chemin.

## Résultat attendu
- D:\LLMCodeAgent\mempalace\palace\ créé
- config.py (ou équivalent) pointe sur ce chemin
- MemPalaceClient utilisable de manière autonome, 0 dépendance MediBot
- Tests mempalace toujours verts (1198 passed)

## Note sur le MCP mempalace partagé
Le MCP mempalace (wings/rooms existants) contient des données MediBot.
On ne le modifie PAS dans ce sprint — c'est l'objet de MIG-05.
MIG-04 crée juste l'infrastructure locale vide.
