# SPEC — MODE PROJETS LLCA (Adham)
**Version** : 1.0 — 2026-04-23
**Statut** : Proposition initiale — à valider avant génération de code

---

## 0. Périmètre & Philosophie

Le Mode Projets transforme LLCA d'un agent de session unique en un **agent à mémoire longue, multi-projets, apprenant**. Chaque projet est un contexte isolé et complet. L'utilisateur est accueilli personnellement dès le lancement, avec la continuité comme comportement par défaut.

Deux dimensions orthogonales coexistent :

| Dimension | Rôle | Coût token |
|---|---|---|
| **Contexte Projet** | Mémoire technique, specs, skills, ChromaDB | Prioritaire, illimité |
| **Contexte Utilisateur** | Préférences, ton, habitudes, shortcuts UX | Léger, capé (< 800 tokens injectés) |

> **Règle d'or** : Le contexte utilisateur ne doit jamais entrer en conflit avec le contexte projet. Il s'applique uniquement à la **couche de communication** (ton, format des réponses, raccourcis UX). Il n'influence pas la logique technique.

---

## 1. Expérience au Lancement (Welcome Flow)

### 1.1 Écran de démarrage — `ProjectWelcomeScreen`

Remplacement / extension du `WelcomeScreen` existant.

**Séquence de chargement** :
1. LLCA lit `projects/index.json` → liste des projets existants
2. LLCA lit `user_context.json` → préférences utilisateur
3. Affichage du `ProjectWelcomeScreen`

**Structure de l'écran** :

```
┌─────────────────────────────────────────────────────┐
│  ⬡ Adham                               [⚙] [✕]     │
├─────────────────────────────────────────────────────┤
│                                                     │
│   Bonjour Adham 👋   [message personnalisé user]    │
│                                                     │
│   ┌─────────────────────────────────────────────┐   │
│   │  CONTINUER UN PROJET                        │   │
│   │                                             │   │
│   │  ● MediBot         [il y a 2h] [▶ Reprendre]│   │
│   │  ● LLCA Core       [hier]      [▶ Reprendre]│   │
│   │  ● Analyse CV      [3j]        [▶ Reprendre]│   │
│   │  + 4 autres projets archivés...             │   │
│   └─────────────────────────────────────────────┘   │
│                                                     │
│   ┌──────────────┐  ┌──────────────────────────┐   │
│   │  + Nouveau   │  │  💡 Générer des idées     │   │
│   │    projet    │  │     (mode Inspiration)    │   │
│   └──────────────┘  └──────────────────────────┘   │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Personnalisation** (depuis `user_context.json`) :
- Prénom / pseudo
- Message de bienvenue adapté (ton formel / casual / technique)
- Heure du jour → "Bonjour" / "Bon après-midi" / "Bonsoir"
- Afficher ou non les projets archivés (préférence mémorisée)

**Comportement** :
- Click `▶ Reprendre` → charge le projet, restaure le contexte, reprend le chat là où il s'était arrêté
- Click `+ Nouveau projet` → `ProjectCreationModal`
- Click `💡 Générer des idées` → `InspirationMode`
- Projet récent (< 30 min) → proposé en ouverture directe sans confirmation

---

## 2. Gestion des Projets

### 2.1 Structure sur disque

```
D:\LLMCodeAgent\projects\
├── index.json                    # Registre global des projets
├── {project_slug}\
│   ├── project.json             # Métadonnées + config
│   ├── history.jsonl            # Historique de chat (append-only)
│   ├── context_snapshot.json    # Dernier snapshot contexte MCP
│   ├── skills\                  # Skills spécifiques au projet
│   │   └── *.md
│   ├── specs\                   # Specs générées/validées
│   │   └── *.json
│   └── palace\                  # ChromaDB isolé du projet
│       └── chroma.sqlite3
```

### 2.2 `project.json` — schéma

```json
{
  "id": "uuid-v4",
  "slug": "medibot",
  "name": "MediBot",
  "description": "Agent médical WhatsApp",
  "created_at": "2026-04-01T10:00:00Z",
  "last_opened": "2026-04-23T08:30:00Z",
  "status": "active",           // active | archived | paused
  "tags": ["python", "médical", "whatsapp"],
  "model_override": null,       // null = modèle global
  "context_config": {
    "max_history_tokens": 8000,
    "compression_strategy": "sliding_window"  // ou "summary"
  },
  "stats": {
    "total_sessions": 42,
    "total_tokens_spent": 1240000,
    "skills_generated": 18,
    "specs_validated": 7
  }
}
```

### 2.3 `projects/index.json` — schéma

```json
{
  "version": 1,
  "projects": [
    { "id": "...", "slug": "medibot", "name": "MediBot", "last_opened": "..." },
    ...
  ],
  "default_project": "medibot"
}
```

### 2.4 `ProjectCreationModal`

Champs :
- **Nom du projet** (requis)
- **Description courte** (optionnel — aide l'IA à contextualiser)
- **Tags** (auto-suggérés par le LLM local)
- **Dossier cible** (optionnel — pour projets liés à un répertoire existant ex. `D:\MediBot`)
- **Template** : Vide / Cloner depuis un projet existant / Depuis un mot-clé (→ `InspirationMode`)

À la création :
1. Générer `slug` depuis le nom
2. Créer l'arborescence `projects/{slug}/`
3. Initialiser `MemPalaceClient` avec `palace_path = projects/{slug}/palace/`
4. Initialiser ChromaDB collection `{slug}_*`
5. Ajouter au `index.json`
6. Ouvrir le projet

---

## 3. Contexte Projet (`ProjectContext`)

### 3.1 Composants

| Composant | Contenu | Persistance |
|---|---|---|
| `SkillLibrary` isolée | Skills `.md` dans `projects/{slug}/skills/` | Disque |
| `MemPalaceClient` isolé | ChromaDB `projects/{slug}/palace/` | Disque |
| `SpecStore` isolé | Specs validées `projects/{slug}/specs/` | Disque |
| `history.jsonl` | Historique de chat compressé | Disque |
| `context_snapshot.json` | Dernier état MCP (fichiers ouverts, TX en cours) | Disque |

### 3.2 Chargement du contexte

Lors de la reprise d'un projet :

```
1. Charger project.json
2. Initialiser MemPalaceClient(palace_path=project/palace/)
3. Charger les dernières N entrées history.jsonl (fenêtre glissante)
4. Restaurer context_snapshot (fichiers ouverts, specs actives)
5. Injecter user_context (< 800 tokens) en prefix système
6. Afficher résumé de session précédente à l'utilisateur
```

### 3.3 Résumé de reprise

Quand un projet est repris après > 1h, LLCA génère automatiquement (via LLM local) :

```
─── Reprise du projet MediBot ───────────────────
  Dernière session : hier à 22h30 (1h12 de travail)
  Dernière action  : Correction du handler rdv_cancel
  En cours        : Sprint WA-07 — WebhookRouter
  Prochaine étape : 3 tests échouants à corriger
─────────────────────────────────────────────────
```

### 3.4 Compression de l'historique

Stratégie `sliding_window` (défaut) :
- Garder les N derniers messages dans le contexte "chaud"
- Messages plus anciens → résumés via LLM et stockés dans MemPalace
- Seuil configurable par projet dans `project.json`

Stratégie `summary` (projets longs) :
- Chaque session → résumé structuré stocké dans MemPalace
- Recherche vectorielle sur l'historique pour retrouver des décisions passées

---

## 4. Contexte Utilisateur (`UserContext`)

### 4.1 Philosophie

> Le contexte utilisateur est **orthogonal** au contexte projet. Il ne touche pas à la logique technique. Il améliore uniquement la qualité de la communication entre LLCA et l'utilisateur.

**Budget token maximal** : 800 tokens injectés en prefix système (non compressibles).

### 4.2 `user_context.json` — schéma

```json
{
  "version": 1,
  "identity": {
    "name": "Adham",
    "locale": "fr-MA",
    "timezone": "Africa/Casablanca"
  },
  "communication": {
    "tone": "casual",             // formal | casual | technical
    "verbosity": "concise",       // verbose | normal | concise
    "language": "fr",
    "code_comments_lang": "fr",
    "prefers_emoji": false
  },
  "workflow": {
    "preferred_model": null,
    "auto_resume_threshold_min": 30,  // < 30min → reprise sans confirmation
    "show_archived_projects": false,
    "default_compression": "sliding_window"
  },
  "shortcuts": {
    "favorite_commands": ["run tests", "commit", "générer spec"],
    "aliases": { "ms": "make spec", "rt": "run tests" }
  },
  "learned": {
    "coding_style": ["snake_case strict", "libcst pour modifications AST", "pas de regex sur du code"],
    "pain_points": ["oubli de relire après edit_file", "write_file sur existant"],
    "preferred_file_size": "< 10KB par module",
    "last_updated": "2026-04-23T09:00:00Z"
  }
}
```

### 4.3 Apprentissage progressif

LLCA enrichit `user_context.json` automatiquement et silencieusement :

| Trigger | Action apprise |
|---|---|
| L'utilisateur corrige le ton d'une réponse | Ajuster `communication.tone` |
| L'utilisateur dit "trop long / trop court" | Ajuster `communication.verbosity` |
| L'utilisateur utilise un raccourci implicite ("ms" → "make spec") | Ajouter à `shortcuts.aliases` |
| Pattern d'erreur répété (ex. write_file sans lecture) | Ajouter à `learned.pain_points` |
| Préférence de style détectée dans les corrections | Enrichir `learned.coding_style` |

**Règles d'apprentissage** :
- Écriture sur disque uniquement en fin de session (pas de write à chaque échange)
- Toute modification doit être confirmée si elle change un champ sensible (`tone`, `language`)
- Maximum 3 nouvelles entrées par session dans `learned`
- Jamais de données de session ou de code dans le contexte utilisateur

### 4.4 Injection dans le prompt système

Le `UserContextInjector` génère un bloc compact :

```
[USER CONTEXT — 650 tokens max]
- Prénom : Adham | Locale : fr-MA | Ton : casual
- Verbosité : concis | Langue code : fr | Emoji : non
- Style connu : snake_case strict, libcst AST, modules < 10 KB
- Raccourcis : "ms" = make spec, "rt" = run tests
[/USER CONTEXT]
```

Ce bloc est inséré **après** le contexte projet dans le prompt système, jamais avant.

---

## 5. Mode Inspiration (`InspirationMode`)

### 5.1 Déclenchement

- Bouton "💡 Générer des idées" depuis `ProjectWelcomeScreen`
- Commande NL : "j'ai besoin d'idées pour..." / "cherche-moi des projets autour de..."
- Lors de la création d'un nouveau projet via template "Depuis un mot-clé"

### 5.2 Flow

```
Utilisateur → mot-clé / phrase / domaine
     ↓
[WebSearchEngine] DDG + Wikipedia + Brave
     ↓
[LLM local — mode Exploration]
     ↓
Génération de 5 à 10 idées de projet structurées
     ↓
Affichage dans InspirationPanel
     ↓
Sélection → ProjectCreationModal pré-rempli
```

### 5.3 Modèle utilisé

Le mode Inspiration utilise le **meilleur modèle disponible** selon la priorité suivante :
1. Si un modèle cloud est configuré (future option) → l'utiliser
2. Sinon → `qwen2.5-coder:3b` local (modèle actif par défaut LLCA)

> Note : l'ajout d'un modèle dédié à l'Inspiration (ex. modèle de raisonnement plus puissant) est une évolution future. Le choix du modèle doit rester configurable dans `settings.json` sans modification de code.

### 5.4 Structure d'une idée générée

```json
{
  "title": "Gestionnaire de tâches CLI avec IA",
  "description": "Un outil en ligne de commande qui priorise automatiquement les tâches...",
  "domain": "productivité",
  "tech_stack": ["Python", "Click", "SQLite", "Ollama"],
  "difficulty": "intermédiaire",
  "estimated_sprints": 8,
  "tags": ["cli", "ia", "productivité"],
  "sources": ["wikipedia/task_management", "ddg/cli+python+ai"]
}
```

### 5.5 `InspirationPanel` (composant React)

```
┌─────────────────────────────────────────────────────┐
│  💡 Mode Inspiration                    [✕ Fermer]  │
│  Mot-clé : "agent médical"                          │
├─────────────────────────────────────────────────────┤
│  ① Chatbot de triage médical                        │
│     Python · FastAPI · Ollama · WhatsApp            │
│     Difficulté : avancé · ~12 sprints               │
│     [+ Créer ce projet]                             │
│                                                     │
│  ② Agenda médical intelligent                       │
│     Python · SQLite · React · NLP                   │
│     Difficulté : intermédiaire · ~8 sprints         │
│     [+ Créer ce projet]                             │
│                                                     │
│  ...                                                │
│                                                     │
│  [🔄 Regénérer]    [🔍 Affiner la recherche]        │
└─────────────────────────────────────────────────────┘
```

---

## 6. Apprentissage Global — Contribution des Projets

### 6.1 Principe

Chaque projet contribue à enrichir la `SkillLibrary` **globale** de LLCA, qui est distincte des skills locales au projet.

```
projects/{slug}/skills/     → Skills locales (contexte projet)
D:\LLMCodeAgent\skills\     → Skills globales (base de connaissance LLCA)
```

### 6.2 Pipeline de contribution (`ProjectContributor`)

Déclenché en fin de session ou manuellement :

```
1. EducatorAgent scanne les skills locales du projet
2. Détection de patterns généralisables (via ObserverAgent)
3. Déduplication contre la base globale (Jaccard lexical)
4. Promotion vers skills globales si score qualité >= seuil
5. Indexation dans le MemPalace global (ChromaDB global)
6. Mise à jour des stats projet (stats.skills_generated++)
```

### 6.3 Règles de promotion

- Un skill local n'est promu en global que s'il n'est pas spécifique au projet (pas de noms de fichiers locaux, pas de chemins absolus)
- La promotion est non-destructive : le skill reste dans le projet
- L'utilisateur peut marquer un skill comme "confidentiel" pour bloquer la promotion
- Les skills promus gardent une référence au projet source

### 6.4 Bénéfice cross-projet

Quand un nouveau projet est créé ou repris :
- LLCA effectue une recherche vectorielle dans le MemPalace global
- Les skills pertinents sont suggérés ou auto-injectés dans le contexte projet
- L'historique des décisions passées (via MemPalace) alimente les specs du nouveau projet

---

## 7. Nouveaux Composants — Vue d'Ensemble Architecture

### 7.1 Backend Python (nouveaux modules)

```
core/
├── project_manager.py        # CRUD projets, index.json, slug generation
├── project_context.py        # Chargement/sauvegarde contexte projet complet
├── project_contributor.py    # Pipeline contribution skills locaux → globaux
├── user_context.py           # Chargement/sauvegarde/apprentissage UserContext
├── user_context_injector.py  # Génération du bloc prompt système (< 800 tokens)
└── inspiration_engine.py     # Pipeline InspirationMode (search + LLM + structure)
```

### 7.2 MCP Tools — Nouveaux handlers

| Tool MCP | Description |
|---|---|
| `project_list` | Lister les projets (filtre status) |
| `project_open` | Charger un projet et son contexte |
| `project_create` | Créer un nouveau projet |
| `project_archive` | Archiver un projet |
| `project_get_summary` | Résumé de la dernière session |
| `user_context_read` | Lire le contexte utilisateur |
| `user_context_update` | Mettre à jour une préférence |
| `inspiration_generate` | Lancer le mode inspiration |

> Règle existante : tout ajout de tool MCP → mettre à jour `mcp_tools_schema.py` + tests `test_tools_list_*`

### 7.3 Frontend Electron/React (nouveaux composants)

```
src/components/
├── ProjectWelcomeScreen.tsx    # Remplacement WelcomeScreen (avec projets)
├── ProjectCard.tsx             # Carte projet dans la liste
├── ProjectCreationModal.tsx    # Modal de création
├── ProjectSwitcher.tsx         # Sidebar : switcher de projet actif
├── InspirationPanel.tsx        # Panel Mode Inspiration
├── IdeaCard.tsx                # Carte d'une idée générée
└── UserContextBadge.tsx        # Indicateur contexte user (ton, préférences)

src/stores/
├── projectStore.ts             # État global des projets
└── userContextStore.ts         # Préférences utilisateur

electron/
└── main.ts                     # +IPC handlers pour project_* et user_context_*
```

### 7.4 IPC Handlers (règle existante : 3 fichiers par handler)

Pour chaque nouveau handler IPC → `main.ts` + `preload.ts` + composant consommateur.

---

## 8. Fonctionnalités Suggérées (Extensions V2)

### 8.1 Timeline de projet (`ProjectTimeline`)
Visualisation chronologique des sessions, sprints, et décisions clés d'un projet. Utilise `history.jsonl` + MemPalace.

### 8.2 Comparaison inter-projets
"Ce pattern que j'ai utilisé dans MediBot, est-ce qu'il s'applique ici ?" → recherche vectorielle cross-palace.

### 8.3 Mode Focus
Masquer tous les projets sauf le projet actif. Le contexte utilisateur mémorise la préférence.

### 8.4 Templates de projet intelligents
Lors de la création, LLCA propose des templates basés sur les projets existants de l'utilisateur (clustering par tags + stack technique).

### 8.5 Healthcheck de projet
Analyse périodique : dettes techniques, tests manquants, specs orphelines → rapport affiché dans `ContextPanel`.

### 8.6 Export de projet
Exporter un projet complet (skills, specs, palace, historique) en archive `.llca` pour partage ou backup.

### 8.7 Collaboration (futur)
Partage d'un palace de projet entre plusieurs instances LLCA (via serveur ChromaDB distant).

### 8.8 Shortcuts utilisateur via NL
"La prochaine fois appelle ça 'build'" → LLCA enregistre l'alias dans `user_context.shortcuts`.

---

## 9. Règles Invariantes du Mode Projets

Ces règles s'ajoutent aux règles existantes des skills LLCA :

1. **Isolation totale** : Le `MemPalaceClient` d'un projet ne peut jamais accéder au palace d'un autre projet. La factory `get_palace(project_id)` est le seul point d'entrée.

2. **Contexte utilisateur non-technique** : `user_context.json` ne contient jamais de code, de chemins de fichiers, ou de données de session. Il ne contient que des préférences de communication et de workflow.

3. **Token budget strict** : Le `UserContextInjector` ne dépasse jamais 800 tokens injectés. Si les préférences apprises dépassent cette limite, les plus anciennes sont tronquées (FIFO).

4. **Écriture différée** : `user_context.json` n'est jamais écrit en cours de session. L'écriture se fait uniquement en fin de session (`project_context.save()`).

5. **Non-régression** : L'ouverture d'un projet sans le Mode Projets activé (LLCA sans `projects/index.json`) doit fonctionner exactement comme avant. Le Mode Projets est une couche additive.

6. **Tests** : tout nouveau module `core/project_*.py` → minimum 12 tests unitaires. Tout nouveau tool MCP → mise à jour de `test_tools_list_*`.

7. **Spec validée avant code** : conformément à la règle existante — aucun code généré avant validation de cette spec.

---

## 10. Sprint Plan Suggéré

| Sprint | Contenu | Priorité |
|---|---|---|
| **PROJ-01** | `project_manager.py` + CRUD `index.json` + tests | P0 |
| **PROJ-02** | `project_context.py` + chargement/sauvegarde + tests | P0 |
| **PROJ-03** | MCP tools `project_list/open/create` + schema + tests | P0 |
| **PROJ-04** | `ProjectWelcomeScreen.tsx` + `ProjectCard.tsx` + IPC | P0 |
| **PROJ-05** | `user_context.py` + `user_context_injector.py` + tests | P1 |
| **PROJ-06** | `UserContextStore.ts` + `UserContextBadge.tsx` | P1 |
| **PROJ-07** | Apprentissage automatique UserContext (fin de session) | P1 |
| **PROJ-08** | `inspiration_engine.py` + `InspirationPanel.tsx` | P2 |
| **PROJ-09** | `project_contributor.py` — pipeline contribution globale | P2 |
| **PROJ-10** | `ProjectTimeline` + Healthcheck + Export `.llca` | P3 |

---

*Spec rédigée par Claude Sonnet 4.6 — basée sur lecture des skills LLCA v11, context v2026-04-23, design system Adham.*
*À valider avec Adham avant tout démarrage de code (règle invariante LLCA).*
