# SPEC — MODE PROJETS LLCA (Adham)
**Version** : 2.0 — 2026-04-23
**Statut** : Proposition révisée — intègre addendum Kimi K2.6 — à valider avant génération de code

---

## Changelog v1 → v2

| Section | Modification | Source |
|---|---|---|
| §2.1 | Filesystem-Context `.llca/` — index.json devient cache | A.8 Kimi |
| §2.5 | `MigrationManager` PROJ-00 ajouté | A.4 Kimi |
| §2.6 | `ProjectLock` — file locking multi-instance | A.5 Kimi |
| §3.1 | `storage_mode: shared \| isolated` sur ChromaDB | A.1 Kimi ✓ arbitrage |
| §3.5 | History Compaction L0→L1→L2 | A.6 Kimi |
| §4.3 | WAL UserContext via `TransactionManager` | A.2 Kimi ✓ arbitrage |
| §5.2 | InspirationEngine fallback offline | A.3 Kimi |
| §7.1 | `ProjectOrchestrator` hierarchical pattern | A.7 Kimi |
| §9 | Checklist de validation étendue | A.checklist Kimi |

---

## 0. Périmètre & Philosophie

Le Mode Projets transforme LLCA d'un agent de session unique en un **agent à mémoire longue, multi-projets, apprenant**. Chaque projet est un contexte isolé et complet. L'utilisateur est accueilli personnellement dès le lancement, avec la continuité comme comportement par défaut.

Deux dimensions orthogonales coexistent :

| Dimension | Rôle | Coût token |
|---|---|---|
| **Contexte Projet** | Mémoire technique, specs, skills, ChromaDB | Prioritaire, illimité |
| **Contexte Utilisateur** | Préférences, ton, habitudes, shortcuts UX | Léger, capé (< 800 tokens injectés) |

> **Règle d'or** : Le contexte utilisateur ne doit jamais entrer en conflit avec le contexte projet. Il s'applique uniquement à la **couche de communication** (ton, format des réponses, raccourcis UX). Il n'influence pas la logique technique.

**Contrainte fondamentale LLCA** : 100% offline/local. Toute fonctionnalité dépendant d'une API cloud doit avoir un fallback offline fonctionnel.

---

## 1. Expérience au Lancement (Welcome Flow)

### 1.1 Écran de démarrage — `ProjectWelcomeScreen`

Remplacement / extension du `WelcomeScreen` existant.

**Séquence de chargement** :
1. LLCA scanne `projects/*/` → reconstruit l'index en mémoire (A.8)
2. LLCA lit `projects/.llca/user_context.json` + replay WAL (A.2)
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
- Click `▶ Reprendre` → vérifie lock → charge le projet, restaure le contexte, reprend le chat
- Click `+ Nouveau projet` → `ProjectCreationModal`
- Click `💡 Générer des idées` → `InspirationMode`
- Projet récent (< 30 min) → proposé en ouverture directe sans confirmation

---

## 2. Gestion des Projets

### 2.1 Structure sur disque (v2 — Filesystem-Context)

`index.json` est désormais un **cache** reconstruit dynamiquement. La source de vérité est le scan du filesystem.

```
D:\LLMCodeAgent\projects\
├── .llca\                        # Répertoire caché — données globales
│   ├── user_context.json         # Préférences utilisateur (compacté depuis WAL)
│   ├── user_context.wal.jsonl    # WAL append-only des changements user
│   └── index.cache.json          # Cache index (reconstruit au boot)
│
├── {project_slug}\
│   ├── .llca\                    # Répertoire caché — données projet
│   │   ├── project.json          # Métadonnées + config (SOURCE DE VÉRITÉ)
│   │   ├── .lock                 # File lock (présent si instance active)
│   │   └── context_snapshot.json # Dernier état MCP (fichiers ouverts, TX)
│   ├── history.jsonl             # Historique de chat L0 (append-only, < 10 MB)
│   ├── history_archive\          # Sessions compactées (résumés L1/L2)
│   │   └── YYYY-MM.jsonl
│   ├── skills\                   # Skills spécifiques au projet
│   │   └── *.md
│   ├── specs\                    # Specs générées/validées
│   │   └── *.json
│   └── palace\                   # ChromaDB isolé (si storage_mode: isolated)
│       └── chroma.sqlite3
```

> **Source de vérité** : `projects/{slug}/.llca/project.json` — jamais `index.cache.json`.
> `ProjectManager.list_projects()` scanne `projects/*/` et parse `.llca/project.json`.
> `index.cache.json` est persisté uniquement pour performance au démarrage (< 50 ms).

### 2.2 `project.json` — schéma (v2)

```json
{
  "id": "uuid-v4",
  "slug": "medibot",
  "name": "MediBot",
  "description": "Agent médical WhatsApp",
  "created_at": "2026-04-01T10:00:00Z",
  "last_opened": "2026-04-23T08:30:00Z",
  "status": "active",
  "tags": ["python", "médical", "whatsapp"],
  "model_override": null,
  "storage_mode": "shared",
  "context_config": {
    "max_history_tokens": 8000,
    "compression_strategy": "sliding_window"
  },
  "stats": {
    "total_sessions": 42,
    "total_tokens_spent": 1240000,
    "skills_generated": 18,
    "specs_validated": 7
  },
  "migrated_from_v9": false
}
```

**`storage_mode`** :
- `"shared"` (défaut) : collections ChromaDB préfixées `project_{slug}_*` dans le MemPalace global (`D:\LLMCodeAgent\mempalace\palace\`). Recommandé sur Lenovo P50 (16 GB RAM).
- `"isolated"` : ChromaDB dans `projects/{slug}/palace/chroma.sqlite3`. Réservé aux projets sensibles ou aux machines > 32 GB RAM.

### 2.3 `ProjectCreationModal`

Champs :
- **Nom du projet** (requis)
- **Description courte** (optionnel)
- **Tags** (auto-suggérés par LLM local)
- **Dossier cible** (optionnel, ex. `D:\MediBot`)
- **Storage mode** : Shared (défaut) / Isolé
- **Template** : Vide / Cloner / Depuis un mot-clé (→ `InspirationMode`)

À la création :
1. Générer `slug` depuis le nom
2. Créer `projects/{slug}/.llca/project.json`
3. Selon `storage_mode` : initialiser collections `project_{slug}_*` (shared) ou ChromaDB local (isolated)
4. Reconstruire `index.cache.json`
5. Ouvrir le projet

### 2.4 `ProjectCreationModal`

Idem v1 — voir §2.3.

### 2.5 Migration Legacy (PROJ-00) ← nouveau

`MigrationManager` s'exécute au premier lancement du Mode Projets si `projects/index.cache.json` est absent.

**Pipeline** :
1. Détecter absence de `projects/` → mode migration
2. Créer projet `legacy` (slug: `legacy`, `migrated_from_v9: true`)
3. Copier skills globaux dans `projects/legacy/skills/`
4. Lier MemPalace global en `storage_mode: "shared"` (pas de copie)
5. `history.jsonl` vide (pas de rétroactivité)
6. Créer `projects/.llca/index.cache.json` avec `"default_project": "legacy"`
7. Afficher notice : "Vos données LLCA V9 ont été migrées dans le projet Legacy"

**Règle** : migration non-destructive. Aucune donnée supprimée. Rollback = supprimer `projects/`.

### 2.6 Concurrence Multi-Instance (File Locking) ← nouveau

Évite la corruption de `history.jsonl` sur ouverture simultanée.

**Structure du lock** : `projects/{slug}/.llca/.lock`
```json
{
  "pid": 1234,
  "started_at": "2026-04-23T09:00:00Z",
  "last_heartbeat": "2026-04-23T09:05:30Z",
  "instance_id": "adham-desktop-01"
}
```

**Règles** :
- `project_open()` : vérifie `.lock`. Si présent et valide → `ProjectAlreadyOpenError`
- `project_close()` : supprime `.lock`
- Heartbeat : refresh `last_heartbeat` toutes les 30s (thread daemon)
- Stale lock : PID mort OU `last_heartbeat` > 60s → break lock avec confirmation utilisateur
- Tests : mock de PID + simulation crash (suppression forcée du heartbeat)

---

## 3. Contexte Projet (`ProjectContext`)

### 3.1 Composants (v2 — storage_mode aware)

| Composant | Mode Shared | Mode Isolated |
|---|---|---|
| `SkillLibrary` | `projects/{slug}/skills/` | identique |
| `MemPalaceClient` | Collections `project_{slug}_*` palace global | `projects/{slug}/palace/` |
| `SpecStore` | `projects/{slug}/specs/` | identique |
| `history.jsonl` | `projects/{slug}/history.jsonl` | identique |
| `context_snapshot` | `projects/{slug}/.llca/context_snapshot.json` | identique |

**Factory** : `get_palace(project_id, storage_mode)` — seul point d'entrée. Aucun accès direct au palace d'un autre projet.

### 3.2 Chargement du contexte via `ProjectOrchestrator`

```python
# core/project_orchestrator.py — Hierarchical Manager pattern
class ProjectOrchestrator:
    def load_project(self, project_id: str) -> ProjectContext:
        meta    = self._loader.load(project_id)       # ProjectLoader
        context = self._assembler.build(meta)          # ContextAssembler
        context.user_prefix = self._injector.build()   # UserContextInjector (< 800 tokens)
        self._checkpoint.restore(context)              # StateCheckpoint
        return context
```

**Workers** (chacun < 8 KB, règle REFACTO LLCA) :
- `ProjectLoader` : lit `project.json`, vérifie lock, vérifie storage_mode
- `ContextAssembler` : skills + specs + fenêtre history.jsonl
- `UserContextInjector` : replay WAL + génération bloc prompt (< 800 tokens)
- `StateCheckpoint` : restaure `context_snapshot.json`

### 3.3 Résumé de reprise

Quand un projet est repris après > 1h, LLCA génère (via LLM local) :

```
─── Reprise du projet MediBot ────────────────────
  Dernière session : hier à 22h30 (1h12 de travail)
  Dernière action  : Correction du handler rdv_cancel
  En cours        : Sprint WA-07 — WebhookRouter
  Prochaine étape : 3 tests échouants à corriger
──────────────────────────────────────────────────
```

### 3.4 Compression de l'historique

Stratégie `sliding_window` (défaut) :
- Garder les N derniers messages dans le contexte "chaud"
- Messages plus anciens → résumés via LLM et stockés dans MemPalace collection `project_{slug}_history`
- Seuil configurable dans `project.json`

Stratégie `summary` (projets longs) :
- Chaque session → résumé structuré stocké dans MemPalace
- Recherche vectorielle sur l'historique pour retrouver des décisions passées

### 3.5 History Compaction L0→L1→L2 ← nouveau

**Seuils** :
- `history.jsonl` > 10 MB OU > 100 sessions → compaction automatique

**Pipeline** :
1. Lire les 50 premiers messages de `history.jsonl`
2. LLM local génère résumé structuré :
   ```json
   {
     "session_date": "2026-04-10",
     "topics": ["webhook", "redis"],
     "decisions": ["utiliser Celery pour les tâches async"],
     "next_steps": ["corriger test_webhook_handler"]
   }
   ```
3. Stocker résumé dans MemPalace (collection `project_{slug}_history`)
4. Tronquer `history.jsonl` → garder 20 derniers messages (L0 chaud)
5. Archiver les résumés > 6 mois dans `history_archive/YYYY-MM.jsonl`

**Tests** : résumé LLM mocké, threshold testé avec fixtures tmp_dir.

---

## 4. Contexte Utilisateur (`UserContext`)

### 4.1 Philosophie

> Le contexte utilisateur est **orthogonal** au contexte projet. Il ne touche pas à la logique technique. Il améliore uniquement la qualité de la communication entre LLCA et l'utilisateur.

**Budget token maximal** : 800 tokens injectés en prefix système (non compressibles).
**Localisation** : `projects/.llca/user_context.json` (partagé entre tous les projets).

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
    "tone": "casual",
    "verbosity": "concise",
    "language": "fr",
    "code_comments_lang": "fr",
    "prefers_emoji": false
  },
  "workflow": {
    "preferred_model": null,
    "auto_resume_threshold_min": 30,
    "show_archived_projects": false,
    "default_compression": "sliding_window"
  },
  "shortcuts": {
    "favorite_commands": ["run tests", "commit", "générer spec"],
    "aliases": { "ms": "make spec", "rt": "run tests" }
  },
  "learned": {
    "coding_style": ["snake_case strict", "libcst pour modifications AST"],
    "pain_points": ["oubli de relire après edit_file"],
    "preferred_file_size": "< 10KB par module",
    "last_updated": "2026-04-23T09:00:00Z"
  }
}
```

### 4.3 WAL UserContext ← remplace "écriture différée" (v2)

**Rationale** : L'écriture différée risque la perte de données sur crash. Le WAL existant de `TransactionManager` (Sprint 12) est réutilisé.

**Fichier WAL** : `projects/.llca/user_context.wal.jsonl`

**Format d'une entrée** :
```json
{
  "timestamp": "2026-04-23T09:15:00Z",
  "field": "communication.tone",
  "old": "formal",
  "new": "casual",
  "source": "user_correction"
}
```

**Sources** : `user_correction` | `auto_detected` | `explicit_command`

**Cycle de vie** :
1. Toute modification → append WAL immédiat (pas d'écriture dans `user_context.json`)
2. Au boot : `UserContextLoader` replay WAL → reconstruction de l'état courant
3. Compaction : toutes les 10 entrées WAL OU en fin de session → merge dans `user_context.json` → truncate WAL

**Réutilisation** : Utiliser `TransactionManager` (Sprint 12) pour la logique WAL. Pas de nouveau module WAL from scratch.

### 4.4 Apprentissage progressif

LLCA enrichit le WAL automatiquement et silencieusement :

| Trigger | Action apprise | Source WAL |
|---|---|---|
| L'utilisateur corrige le ton | Ajuster `communication.tone` | `user_correction` |
| "trop long / trop court" | Ajuster `communication.verbosity` | `user_correction` |
| Raccourci implicite détecté | Ajouter à `shortcuts.aliases` | `auto_detected` |
| Pattern d'erreur répété | Ajouter à `learned.pain_points` | `auto_detected` |

**Règles** :
- Maximum 3 nouvelles entrées `auto_detected` par session
- Champs `identity.*` et `communication.language` → confirmation utilisateur obligatoire
- Jamais de code, de chemins, ou de données de session dans ce fichier

### 4.5 Injection dans le prompt système

Le `UserContextInjector` (worker de `ProjectOrchestrator`) génère un bloc compact :

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
- Template "Depuis un mot-clé" dans `ProjectCreationModal`

### 5.2 Flow (v2 — dual pipeline Online/Offline)

LLCA est 100% offline. Le pipeline online est optionnel.

```
Utilisateur → mot-clé / phrase / domaine
     ↓
InspirationEngine.generate(keyword, online=settings.online_features_enabled)
     ↓
  [Online]                          [Offline — défaut]
  WebSearchEngine                   MemPalaceClient.query()
  DDG + Wikipedia + Brave           Recherche vectorielle sur
     ↓                              skills/projets existants
  Résultats web                          ↓
                                    Patterns analogues détectés
     ↓                                   ↓
              LLM local (qwen2.5-coder:3b)
              Génération 5-10 idées structurées
                          ↓
                   InspirationPanel
```

**Prompt offline** :
```
Voici les patterns et stacks techniques des projets existants :
{skills_pertinents}
Génère 5 idées de projet qui réutilisent ces patterns dans un domaine différent.
Réponds uniquement en JSON.
```

**Prompt online** : identique mais enrichi des résultats web (troncature 3000 chars/page max — règle web_search existante).

**Sécurité offline** : test autouse conftest.py existant bloque `urlopen` accidentel si `online=False`.

### 5.3 Structure d'une idée générée

```json
{
  "title": "Gestionnaire de tâches CLI avec IA",
  "description": "Un outil en ligne de commande qui priorise automatiquement...",
  "domain": "productivité",
  "tech_stack": ["Python", "Click", "SQLite", "Ollama"],
  "difficulty": "intermédiaire",
  "estimated_sprints": 8,
  "tags": ["cli", "ia", "productivité"],
  "sources": ["palace:skill_planner_v3", "palace:skill_cli_patterns"]
}
```

### 5.4 `InspirationPanel` (composant React)

```
┌─────────────────────────────────────────────────────┐
│  💡 Mode Inspiration                    [✕ Fermer]  │
│  Mot-clé : "agent médical"          [🌐 En ligne]   │
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
│  [🔄 Regénérer]    [🔍 Affiner]    [🌐/⬡ Mode]     │
└─────────────────────────────────────────────────────┘
```

---

## 6. Apprentissage Global — Contribution des Projets

### 6.1 Principe

```
projects/{slug}/skills/     → Skills locales (contexte projet)
D:\LLMCodeAgent\skills\     → Skills globales (base de connaissance LLCA)
MemPalace global            → Index vectoriel cross-projets (mode shared)
```

### 6.2 Pipeline de contribution (`ProjectContributor`)

Déclenché en fin de session ou manuellement :

```
1. EducatorAgent scanne les skills locales du projet
2. Détection de patterns généralisables (ObserverAgent — Jaccard lexical)
3. Déduplication contre base globale
4. Promotion vers skills globales si score qualité >= seuil
5. Indexation MemPalace global (collection project_global_skills)
6. stats.skills_generated++ dans project.json
```

### 6.3 Règles de promotion

- Un skill local n'est promu en global que si générique (pas de chemins absolus, pas de noms de fichiers locaux)
- Non-destructive : le skill reste dans le projet
- L'utilisateur peut marquer un skill `"confidential": true` → bloque la promotion
- Les skills promus gardent `source_project: slug` dans leur métadonnée

---

## 7. Architecture Technique

### 7.1 Backend Python — nouveaux modules

```
core/
├── project_orchestrator.py    # Hierarchical manager (< 8 KB) — Workers :
├── project_loader.py          #   lecture project.json + lock (< 8 KB)
├── project_context_assembler.py # skills + specs + history window (< 8 KB)
├── project_checkpoint.py      #   restauration context_snapshot (< 8 KB)
├── project_manager.py         # CRUD projets, scan filesystem, index.cache.json
├── project_contributor.py     # Pipeline contribution skills locaux → globaux
├── project_lock.py            # File locking + heartbeat daemon
├── migration_manager.py       # PROJ-00 : migration V9 → V10
├── user_context.py            # Chargement/sauvegarde UserContext + WAL
├── user_context_injector.py   # Génération bloc prompt (< 800 tokens) — worker
└── inspiration_engine.py      # Pipeline InspirationMode (dual online/offline)
```

> Règle REFACTO LLCA : tout module > 10 KB = candidat à découpage. La décomposition en workers de `ProjectOrchestrator` est anticipée dès la conception.

### 7.2 MCP Tools — 8 nouveaux handlers

| Tool MCP | Description |
|---|---|
| `project_list` | Lister les projets (filtre status) |
| `project_open` | Charger un projet et son contexte |
| `project_create` | Créer un nouveau projet |
| `project_archive` | Archiver un projet |
| `project_get_summary` | Résumé de la dernière session |
| `user_context_read` | Lire le contexte utilisateur |
| `user_context_update` | Mettre à jour une préférence (→ WAL) |
| `inspiration_generate` | Lancer le mode inspiration |

> Règle T-01 : tout ajout de tool MCP → mettre à jour `mcp_tools_schema.py` + `test_tools_list_*` immédiatement.
> Compte actuel : 13 tools. Post-PROJ : 21 tools. Mettre à jour tous les tests qui pinnent "== 13".

### 7.3 Frontend Electron/React

```
src/components/
├── ProjectWelcomeScreen.tsx    # Remplace WelcomeScreen
├── ProjectCard.tsx             # Carte projet dans la liste
├── ProjectCreationModal.tsx    # Modal de création
├── ProjectSwitcher.tsx         # Sidebar : switcher projet actif
├── InspirationPanel.tsx        # Panel Mode Inspiration
├── IdeaCard.tsx                # Carte d'une idée générée
└── UserContextBadge.tsx        # Indicateur contexte user

src/stores/
├── projectStore.ts             # État global des projets
└── userContextStore.ts         # Préférences utilisateur

electron/
└── main.ts                     # +IPC handlers project_* + user_context_*
```

**Règle IPC** : tout nouveau handler = 3 fichiers : `main.ts` + `preload.ts` + composant consommateur.

---

## 8. Fonctionnalités Extensions V2+

| Feature | Description | Priorité |
|---|---|---|
| **Timeline projet** | Visualisation chronologique sessions + décisions (history.jsonl + MemPalace) | P2 |
| **Comparaison cross-projets** | Recherche vectorielle cross-palace pour réutilisation de patterns | P2 |
| **Mode Focus** | Masquer tous les projets sauf l'actif (mémorisé dans user_context) | P2 |
| **Templates intelligents** | Clustering tags + stack pour suggestions de templates | P3 |
| **Healthcheck projet** | Dettes techniques, tests manquants, specs orphelines → rapport ContextPanel | P3 |
| **Export `.llca`** | Archive projet complète pour backup ou partage | P3 |
| **Collaboration** | Palace partagé via ChromaDB distant (multi-instance réseau) | P4 |
| **Shortcuts NL** | "la prochaine fois appelle ça build" → alias enregistré en WAL | P2 |

---

## 9. Règles Invariantes du Mode Projets

Ces règles s'ajoutent aux règles existantes des skills LLCA (001-master.md) :

1. **Isolation totale** : `get_palace(project_id, storage_mode)` est le seul point d'entrée. Aucun module n'accède directement au palace d'un autre projet.

2. **Contexte utilisateur non-technique** : `user_context.json` ne contient jamais de code, de chemins absolus, ou de données de session. Préférences de communication et workflow uniquement.

3. **Token budget strict** : `UserContextInjector` ne dépasse jamais 800 tokens. Si `learned` dépasse la limite → FIFO sur les entrées les plus anciennes.

4. **WAL avant tout** : toute modification de `user_context` → WAL append immédiat. `user_context.json` n'est jamais écrit directement en cours de session.

5. **Non-régression V9** : LLCA sans `projects/` doit fonctionner exactement comme avant. Le Mode Projets est une couche additive. Le `MigrationManager` se déclenche uniquement si l'utilisateur active le Mode Projets.

6. **Offline-first** : Tout pipeline qui utilise `WebSearchEngine` doit avoir un fallback offline fonctionnel. `settings.online_features_enabled` est le seul interrupteur.

7. **Tests** : minimum 12 tests par module `core/project_*.py`. Tout nouveau tool MCP → `mcp_tools_schema.py` + `test_tools_list_*` mis à jour immédiatement (règle T-01).

8. **Spec validée avant code** : conformément à la règle existante — aucun code généré avant validation de cette spec par Adham.

---

## 10. Checklist de Validation Avant Code

- [ ] **PROJ-00** `MigrationManager` : non-destructif, testé avec tmp_dir, rollback documenté
- [ ] **§2.6** `ProjectLock` : testé avec mock PID + simulation crash (heartbeat supprimé)
- [ ] **§3.1** `storage_mode` : `get_palace()` factory testée en mode shared ET isolated
- [ ] **§3.5** `HistoryCompaction` : résumé LLM mocké, threshold testé, archivage vérifié
- [ ] **§4.3** `UserContextWAL` : replay WAL testé, compaction 10 entrées testée, `TransactionManager` réutilisé (pas de code WAL dupliqué)
- [ ] **§5.2** `InspirationEngine` : fallback offline testé sans `urlopen` (conftest.py existant)
- [ ] **§7.1** Workers `ProjectOrchestrator` : chacun < 8 KB, testables en isolation
- [ ] **§7.2** MCP Tools : `mcp_tools_schema.py` mis à jour (13 → 21 tools), `test_tools_list_*` corrigés (règle T-01 — priorité immédiate)
- [ ] **§2.1** Scan filesystem `.llca/` : testé avec `tmp_dir`, `index.cache.json` reconstruit correctement
- [ ] **Offline** : aucun test ne fait d'appel réseau réel (conftest.py autouse bloque `urlopen`)

---

## 11. Sprint Plan Révisé (v2)

| Sprint | Contenu | Priorité |
|---|---|---|
| **PROJ-00** | `MigrationManager` + structure filesystem `.llca/` | P0 |
| **PROJ-01** | `project_manager.py` + scan filesystem + `index.cache.json` + tests | P0 |
| **PROJ-02** | `ProjectLock` + heartbeat daemon + tests mock PID | P0 |
| **PROJ-03** | `ProjectOrchestrator` + 4 workers + tests isolation | P0 |
| **PROJ-04** | MCP tools `project_list/open/create/archive` + schema 21 tools + tests | P0 |
| **PROJ-05** | `ProjectWelcomeScreen.tsx` + `ProjectCard.tsx` + IPC | P0 |
| **PROJ-06** | `user_context.py` + WAL + replay + compaction (via TransactionManager) + tests | P1 |
| **PROJ-07** | `UserContextInjector` + `UserContextStore.ts` + `UserContextBadge.tsx` | P1 |
| **PROJ-08** | Apprentissage automatique UserContext (fin de session) | P1 |
| **PROJ-09** | `HistoryCompaction` L0→L1→L2 + archivage + tests | P1 |
| **PROJ-10** | `InspirationEngine` (dual pipeline) + `InspirationPanel.tsx` | P2 |
| **PROJ-11** | `ProjectContributor` — pipeline contribution globale | P2 |
| **PROJ-12** | Résumé de reprise automatique (> 1h) | P2 |

---

*Spec v1 rédigée par Claude Sonnet 4.6 — 2026-04-23*
*Addendum intégré depuis Kimi K2.6 — analyse patterns multi-agent 2026*
*Spec validée par Adham requise avant tout démarrage de code (règle invariante LLCA §9.8)*
