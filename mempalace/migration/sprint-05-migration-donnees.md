# MIG-05 — Migration données MediBot → LLCA palace (avec réorganisation)
# Statut : À FAIRE

## Objectif
Copier les données pertinentes du mempalace MediBot vers le palace LLCA local,
en les réorganisant selon la structure LLCA (wings/rooms propres à LLCA).

## Prérequis
- MIG-04 terminé ✅ (palace LLCA local créé et opérationnel)
- D:\LLMCodeAgent\mempalace\palace\ initialisé

## Contexte
Le projet LLCA utilisait le palace MediBot pour deux raisons :
1. **Comprendre le projet MediBot** (contexte métier — utile à LLCA comme domaine d'application)
2. **Stocker ses propres données** dans des collections `lcca_*` isolées

Ces données `lcca_*` doivent migrer dans le palace LLCA local.
Les données purement MediBot (médical, patients, RDV) ne nous intéressent pas.

## Inventaire des données à migrer

### ÉTAPE 1 — Inventaire du MCP mempalace actuel
```
mempalace:mempalace_list_wings → lister tous les wings
mempalace:mempalace_list_rooms → lister toutes les rooms
mempalace:mempalace_get_taxonomy → vue complète
```
Identifier :
- Wings/rooms qui concernent LLCA (agents, specs, transactions, code, tests...)
- Wings/rooms qui concernent MediBot uniquement (médical, RDV, patients...)
- Wings/rooms mixtes (à trier)

### ÉTAPE 2 — Export des données LLCA du MCP
Pour chaque room LLCA identifiée :
```
mempalace:mempalace_search → requête large pour extraire le contenu
```
Format d'export : JSON dans D:\LLMCodeAgent\mempalace\migration\export\

Structure export :
```
migration/
  export/
    wings_inventory.json     ← résultat list_wings
    rooms_inventory.json     ← résultat list_rooms
    kg_llca.json             ← knowledge graph (faits LLCA)
    drawers_llca/            ← un fichier par drawer LLCA
      wing_room_drawer.json
```

### ÉTAPE 3 — Réorganisation : mapping MCP → palace local LLCA

**Wings LLCA à créer dans le palace local :**

| Wing local LLCA | Contenu | Source MCP |
|-----------------|---------|------------|
| `architecture`  | Agents, orchestrateur, pipeline | rooms agents/* du MCP |
| `specs`         | SpecEntry, validation, promoter | rooms specs/* du MCP |
| `transactions`  | TX manager, WAL, rollback | rooms tx/* du MCP |
| `tests`         | Patterns de tests, anti-patterns | rooms tests/* du MCP |
| `refacto`       | Historique REFACTOs, patterns | rooms refacto/* du MCP |
| `ui`            | Electron, React, IPC | rooms ui/* du MCP |
| `llm`           | Ollama, prompts, timeout | rooms llm/* du MCP |
| `mempalace`     | Structure palace, layers | rooms memory/* du MCP |
| `educator`      | Whitelist, github, curator | rooms educator/* du MCP |
| `web_search`    | Moteurs, cache, scoring | rooms web/* du MCP |
| `medibot_ref`   | Contexte MediBot (lecture seule, référence) | rooms medibot/* du MCP |

**Note sur `medibot_ref`** :
On crée un wing `medibot_ref` en lecture seule dans le palace LLCA.
Ce wing contient le contexte MediBot utile à LLCA (domaine médical, APIs connues)
mais est clairement marqué comme référence externe, pas comme données LLCA.

### ÉTAPE 4 — Import dans le palace local
Pour chaque drawer exporté en ÉTAPE 2 :
```python
# Pseudo-code — à adapter selon l'API MemPalaceClient
client = MemPalaceClient(palace_path="D:/LLMCodeAgent/mempalace/palace")
client.add_entry(
    wing="architecture",
    room="agents",
    content=drawer_content,
    metadata={"source": "mcp_migration", "date": "2026-04-23"}
)
```

### ÉTAPE 5 — Vérification intégrité
Compter les drawers exportés vs importés.
Vérifier que le palace local répond aux requêtes de recherche.

### ÉTAPE 6 — Mise à jour skills post-migration
Mettre à jour 002-context.md :
- Section "mempalace" : pointer vers le palace local
- Supprimer toute référence au MCP palace partagé comme source de données LLCA

## Règles de réorganisation

1. **Un drawer = une information atomique** (pas de blobs géants)
2. **Métadonnées obligatoires** : source, date, sprint_origin, wing, room
3. **medibot_ref wing** : tout ce qui vient de MediBot porte le tag `source=medibot_ref`
4. **Pas de duplication** : si une info est dans lcca_specs ET dans le MCP, une seule copie dans le palace local
5. **Knowledge Graph** : migrer les faits KG qui concernent LLCA (pas les faits patients/RDV)

## Script de migration (à créer en MIG-05)

Créer un script Python autonome :
```
D:\LLMCodeAgent\mempalace\migration\migrate_palace.py
```

Le script :
1. Lit le MCP via mempalace:mempalace_search (via subprocess ou API directe)
2. Filtre les données LLCA vs MediBot
3. Écrit dans le palace local via MemPalaceClient
4. Produit un rapport : migration_report.json

## Résultat attendu
- Palace LLCA local peuplé avec données réorganisées
- Wing medibot_ref présent (référence, pas données opérationnelles)
- 0 dépendance runtime vers D:\MediBot ou le MCP palace partagé
- LLCA fonctionne entièrement en autonome
- 002-context.md mis à jour

## Note finale
Après MIG-05, le mempalace MCP partagé n'est plus utilisé par LLCA.
Il reste utilisé par MediBot (D:\MediBot) — on n'y touche pas.
