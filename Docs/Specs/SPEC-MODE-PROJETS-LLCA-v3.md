# SPEC — MODE PROJETS LLCA (Adham)
**Version** : 3.0 — 2026-04-23
**Statut** : Version finale — prête pour validation avant génération de code
**Auteurs** : Claude Sonnet 4.6 (v1+v2) · Kimi K2.6 (addendum v2) · analyse critique (addendum v3) · arbitrages Claude Sonnet 4.6

---

## Changelog v2 → v3

| Section | Modification | Arbitrage |
|---|---|---|
| §2.5 | Double namespace legacy (`lcca_*` + `project_legacy_*`) — pas de copie | ✅ Accepté tel quel |
| §2.5 | Réécriture chemins absolus via `_rewrite_paths()` string simple | ✅ Accepté, libcst refusé (over-engineered sur Markdown) |
| §2.6 | Heartbeat dans `%TEMP%`, `.lock` projet minimal | ✅ Accepté tel quel |
| §3.5 | Seuil fixe 10 MB, fréquence de vérification adaptative | ⚠️ Formule dynamique refusée — voir §3.5 |
| §3.5 | Compaction manuelle via MCP tool `project_compact_history` | ✅ Accepté |
| §4.3 | Snapshot WAL : seuil 10 entrées + filet hebdomadaire | ⚠️ Fusionné v2 + v3 |
| §5.2 | 3 idées max offline, déduplication Jaccard (ObserverAgent) | ⚠️ Cosine refusé — Jaccard cohérent avec codebase |
| §5.2 | Fallback templates JSON si LLM échoue | ✅ Accepté |
| §7.2 | `MCP_TOOLS_COUNT` constante centrale dans `mcp_tools_schema.py` | ✅ Accepté |
| §7.2 | Tools `project_compact_history` + `project_healthcheck` | ✅ Accepté |
| §10 | Checklist étendue avec nouveaux items | ✅ Intégré |

---

## 0. Périmètre & Philosophie

Le Mode Projets transforme LLCA d'un agent de session unique en un **agent à mémoire longue, multi-projets, apprenant**. Chaque projet est un contexte isolé et complet. L'utilisateur est accueilli personnellement dès le lancement, avec la continuité comme comportement par défaut.

Deux dimensions orthogonales coexistent :

| Dimension | Rôle | Coût token |
|---|---|---|
| **Contexte Projet** | Mémoire technique, specs, skills, ChromaDB | Prioritaire, illimité |
| **Contexte Utilisateur** | Préférences, ton, habitudes, shortcuts UX | Léger, capé (< 800 tokens injectés) |

> **Règle d'or** : Le contexte utilisateur ne doit jamais entrer en conflit avec le contexte projet. Il s'applique uniquement à la **couche de communication**. Il n'influence pas la logique technique.

**Contraintes fondamentales LLCA** :
- 100% offline/local. Tout pipeline dépendant du réseau doit avoir un fallback offline fonctionnel.
- Lenovo P50 — 16 GB RAM, Quadro M2000M 4 GB VRAM. ChromaDB shared par défaut.
- Modèle actif : `qwen2.5-coder:3b`. Pas de modèle créatif dédié — les prompts compensent.

---

## 1. Expérience au Lancement (Welcome Flow)

### 1.1 Écran de démarrage — `ProjectWelcomeScreen`

Remplacement / extension du `WelcomeScreen` existant.

**Séquence de chargement** :
1. `ProjectManager.list_projects()` scanne `projects/*/` → reconstruit index en mémoire
2. `UserContextLoader` lit `projects/.llca/user_context.json` + replay WAL
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
│   │  + 4 autres archivés...                     │   │
│   └─────────────────────────────────────────────┘   │
│                                                     │
│   ┌──────────────┐  ┌──────────────────────────┐   │
│   │  + Nouveau   │  │  💡 Générer des idées     │   │
│   │    projet    │  │     (mode Inspiration)    │   │
│   └──────────────┘  └──────────────────────────┘   │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Comportement** :
- Click `▶ Reprendre` → vérifie lock → charge projet → résumé de reprise si > 1h
- Click `+ Nouveau projet` → `ProjectCreationModal`
- Click `💡 Générer des idées` → `InspirationMode`
- Projet récent (< 30 min) → ouverture directe sans confirmation

---

## 2. Gestion des Projets

### 2.1 Structure sur disque (Filesystem-Context)

`index.cache.json` est un **cache reconstruit dynamiquement**. La source de vérité est le scan filesystem.

```
D:\LLMCodeAgent\projects\
├── .llca\                            # Données globales
│   ├── user_context.json             # Préférences (compacté depuis WAL)
│   ├── user_context.wal.jsonl        # WAL append-only des changements
│   └── index.cache.json             # Cache index (reconstruit au boot)
│
├── {project_slug}\
│   ├── .llca\                        # Données projet (source de vérité)
│   │   ├── project.json             # Métadonnées + config
│   │   ├── .lock                    # Lock minimal (pointe vers %TEMP%)
│   │   └── context_snapshot.json   # Dernier état MCP
│   ├── history.jsonl                # Historique L0 (< 10 MB)
│   ├── history_archive\             # Résumés compactés
│   │   └── YYYY-MM.jsonl
│   ├── skills\                      # Skills locales
│   └── specs\                       # Specs validées
│
└── _archive\                        # Projets archivés (zippés si > 6 mois)
```

> **Mode shared (défaut)** : pas de répertoire `palace/` dans le projet — les collections ChromaDB vivent dans le MemPalace global (`D:\LLMCodeAgent\mempalace\palace\`), préfixées `project_{slug}_*`.
> **Mode isolated** : `projects/{slug}/palace/chroma.sqlite3` — réservé projets sensibles.

### 2.2 `project.json` — schéma

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
  "legacy_namespaces": [],
  "history": {
    "compaction_threshold_mb": 10,
    "compression_strategy": "sliding_window",
    "max_history_tokens": 8000
  },
  "stats": {
    "total_sessions": 42,
    "total_tokens_spent": 1240000,
    "skills_generated": 18,
    "specs_validated": 7,
    "last_healthcheck": null,
    "issues_count": 0
  },
  "migrated_from_v9": false
}
```

**`legacy_namespaces`** : liste de patterns de collections ChromaDB à charger en plus des collections `project_{slug}_*`. Utilisé uniquement pour le projet `legacy` (valeur : `["lcca_*"]`).

### 2.3 `ProjectCreationModal`

Champs :
- **Nom** (requis) · **Description** (optionnel) · **Tags** (auto-suggérés LLM)
- **Dossier cible** (optionnel, ex. `D:\MediBot`)
- **Storage mode** : Shared (défaut) / Isolé
- **Template** : Vide / Cloner / Depuis un mot-clé (→ `InspirationMode`)

À la création :
1. Générer `slug` depuis le nom (ASCII, lowercase, tirets)
2. Créer `projects/{slug}/.llca/project.json`
3. Initialiser collections ChromaDB selon `storage_mode`
4. Reconstruire `index.cache.json`
5. Ouvrir le projet

### 2.4 `ProjectManager` — Scan Filesystem

```python
# core/project_manager.py
class ProjectManager:
    def list_projects(self) -> list[ProjectMeta]:
        """Source de vérité : scan projects/*/. llca/project.json"""
        projects = []
        for path in self._root.glob("*/. llca/project.json"):
            projects.append(self._parse_meta(path))
        self._rebuild_cache(projects)   # écrit index.cache.json
        return sorted(projects, key=lambda p: p.last_opened, reverse=True)
```

`index.cache.json` est persisté pour performance (< 50 ms au boot) mais jamais lu comme source de vérité.

### 2.5 Migration Legacy (PROJ-00)

`MigrationManager` s'exécute au premier lancement du Mode Projets si `projects/` est absent.

**Pipeline** :
1. Détecter absence de `projects/` → mode migration
2. Créer `projects/{slug}/.llca/project.json` pour le projet `legacy` :
   - `storage_mode: "shared"`
   - `legacy_namespaces: ["lcca_*"]`
   - `migrated_from_v9: true`
3. **Double namespace** : `MemPalaceClient` du projet `legacy` charge :
   - Collections `project_legacy_*` (futures écritures)
   - Collections `lcca_*` (historique V9 — lecture seule initiale)
   - À la première écriture, `project_legacy_skills` est créée. Lectures : `project_legacy_*` d'abord, puis `lcca_*` en fallback.
4. Copier skills globaux dans `projects/legacy/skills/` en appliquant `_rewrite_paths()` :
   ```python
   def _rewrite_paths(content: str, project_root: str) -> str:
       return content.replace("D:\\LLMCodeAgent\\", "{PROJECT_ROOT}/")
   ```
   > Simple substitution string — les skills sont du Markdown, pas du code exécutable. libcst n'est pas justifié ici.
5. `history.jsonl` vide (pas de rétroactivité)
6. Créer `projects/.llca/index.cache.json` avec `"default_project": "legacy"`
7. Afficher notice : "Vos données LLCA V9 ont été migrées dans le projet Legacy"

**Règles** :
- Migration non-destructive. Aucune donnée supprimée ou renommée dans ChromaDB.
- Rollback = supprimer `projects/` (les collections `lcca_*` sont intactes).
- ChromaDB ne supporte pas le rename de collection — la copie d'embeddings est évitée délibérément.

### 2.6 Concurrence Multi-Instance (File Locking)

**Structure** :

`projects/{slug}/.llca/.lock` — fichier minimal (< 100 octets), écrit une fois à l'ouverture :
```json
{ "temp_lock": "C:\\Users\\Adham\\AppData\\Local\\Temp\\.llca_lock_medibot_1234.json" }
```

`%TEMP%/.llca_lock_{slug}_{pid}.json` — payload complet, mis à jour toutes les 30s par thread daemon :
```json
{
  "pid": 1234,
  "started_at": "2026-04-23T09:00:00Z",
  "last_heartbeat": "2026-04-23T09:05:30Z",
  "instance_id": "adham-desktop-01"
}
```

**Règles** :
- `project_open()` : lit `.lock` → charge fichier temporaire → vérifie validité
- `project_close()` : supprime `.lock` ET fichier temporaire
- Heartbeat : thread daemon, refresh `last_heartbeat` toutes les 30s dans `%TEMP%` uniquement
- **Stale lock** : fichier temporaire absent OU `last_heartbeat` > 60s OU PID invalide → break lock avec confirmation
- Vérification PID : `psutil.pid_exists(pid)` si disponible (optionnel), sinon fallback heartbeat
- Tests : simuler stale lock en supprimant le fichier `%TEMP%` (pas le `.lock` projet)
- Bénéfice : Windows Defender ne scanne pas `%TEMP%` avec la même agressivité que les répertoires projet

---

## 3. Contexte Projet (`ProjectContext`)

### 3.1 Composants

| Composant | Mode Shared | Mode Isolated |
|---|---|---|
| `SkillLibrary` | `projects/{slug}/skills/` | identique |
| `MemPalaceClient` | Collections `project_{slug}_*` palace global (+ `legacy_namespaces` si applicable) | `projects/{slug}/palace/` |
| `SpecStore` | `projects/{slug}/specs/` | identique |
| `history.jsonl` | `projects/{slug}/history.jsonl` | identique |
| `context_snapshot` | `projects/{slug}/.llca/context_snapshot.json` | identique |

**Factory** : `get_palace(project_id, storage_mode, legacy_namespaces=[])` — seul point d'entrée autorisé. Aucun accès direct au palace d'un autre projet.

### 3.2 Chargement du contexte — `ProjectOrchestrator`

```python
# core/project_orchestrator.py — Hierarchical Manager (< 8 KB)
class ProjectOrchestrator:
    def load_project(self, project_id: str) -> ProjectContext:
        meta    = self._loader.load(project_id)        # ProjectLoader
        context = self._assembler.build(meta)           # ContextAssembler
        context.user_prefix = self._injector.build()    # UserContextInjector (< 800 tokens)
        self._checkpoint.restore(context)               # StateCheckpoint
        return context
```

**Workers** (chacun < 8 KB) :
- `ProjectLoader` : lit `project.json`, vérifie lock, résout `storage_mode`
- `ContextAssembler` : skills + specs + fenêtre `history.jsonl`
- `UserContextInjector` : replay WAL + génération bloc prompt
- `StateCheckpoint` : restaure `context_snapshot.json`

### 3.3 Résumé de reprise

Déclenché si `last_opened` > 1h. Généré via LLM local :

```
─── Reprise du projet MediBot ────────────────────
  Dernière session : hier à 22h30 (1h12 de travail)
  Dernière action  : Correction du handler rdv_cancel
  En cours        : Sprint WA-07 — WebhookRouter
  Prochaine étape : 3 tests échouants à corriger
──────────────────────────────────────────────────
```

### 3.4 Compression de l'historique

Stratégie `sliding_window` (défaut) : garder les N derniers messages en contexte "chaud", résumer les plus anciens dans MemPalace (`project_{slug}_history_summaries`).

Stratégie `summary` (projets longs) : chaque session → résumé structuré dans MemPalace, recherche vectorielle sur l'historique.

### 3.5 History Compaction L0→L1→L2

**Seuil** :
- Fixe à `history.compaction_threshold_mb` (défaut : 10 MB dans `project.json`)
- Seuil minimal absolu : 5 MB (pas de compaction en dessous, même si configuré)
- La **fréquence de vérification** s'adapte : projets actifs (> 5 sessions/semaine) → vérification à chaque fermeture ; projets dormants → vérification hebdomadaire

> La formule dynamique proposée (`max(10, total_sessions * 0.05)`) a été refusée : elle monte le seuil linéairement avec l'activité, laissant grossir indéfiniment les projets très actifs. Mieux vaut un seuil fixe configurable avec une vérification adaptative.

**Déclenchement** : uniquement en fin de session (fermeture du projet) pour ne pas interrompre le travail. Aussi via MCP tool `project_compact_history` (compaction manuelle immédiate).

**Pipeline** :
1. Lire les 50 premiers messages de `history.jsonl` (les plus anciens)
2. LLM local génère résumé structuré :
   ```json
   {
     "session_date": "2026-04-10",
     "topics": ["webhook", "redis"],
     "decisions": ["utiliser Celery pour les tâches async"],
     "next_steps": ["corriger test_webhook_handler"]
   }
   ```
3. Stocker résumé dans MemPalace (collection `project_{slug}_history_summaries`)
4. Supprimer les 50 messages de `history.jsonl` (réécriture fichier)
5. Si le fichier dépasse encore le seuil → répéter (max 5 passes par session)
6. Sessions > 6 mois → archivage dans `history_archive/YYYY-MM.jsonl`

**Tests** : résumé LLM mocké, seuil testé avec tmp_dir, archive testée avec dates mockées.

---

## 4. Contexte Utilisateur (`UserContext`)

### 4.1 Philosophie

> Orthogonal au contexte projet. Couche de communication uniquement. Jamais de code, de chemins absolus, ou de données de session.

**Budget token maximal** : 800 tokens injectés (FIFO sur `learned` si dépassement).
**Localisation** : `projects/.llca/` (partagé entre tous les projets).

### 4.2 `user_context.json` — schéma

```json
{
  "version": 1,
  "identity": { "name": "Adham", "locale": "fr-MA", "timezone": "Africa/Casablanca" },
  "communication": {
    "tone": "casual", "verbosity": "concise",
    "language": "fr", "code_comments_lang": "fr", "prefers_emoji": false
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

### 4.3 WAL UserContext

**Rationale** : remplace l'écriture différée. Réutilise `TransactionManager` (Sprint 12).

**Fichier** : `projects/.llca/user_context.wal.jsonl`

**Format** :
```json
{"timestamp": "...", "field": "communication.tone", "old": "formal", "new": "casual", "source": "user_correction"}
```

**Sources** : `user_correction` | `auto_detected` | `explicit_command`

**Cycle de vie** :
1. Toute modification → append WAL immédiat
2. Au boot : `UserContextLoader` replay WAL → reconstruction état courant
3. **Compaction** : à 10 entrées WAL OU fin de session → merge dans `user_context.json` → truncate WAL
4. **Snapshot de sécurité** : toutes les 7 jours ou 100 entrées WAL accumulées → snapshot forcé même sans fermeture propre (protection contre les longs intervalles sans activité suivis d'un crash)

**Règles** :
- `user_context.json` jamais écrit directement en cours de session
- Champs `identity.*` et `communication.language` → confirmation utilisateur obligatoire avant écriture WAL
- Maximum 3 nouvelles entrées `auto_detected` par session

### 4.4 Injection dans le prompt système

`UserContextInjector` génère un bloc compact, inséré **après** le contexte projet :

```
[USER CONTEXT — 650 tokens max]
- Prénom : Adham | Locale : fr-MA | Ton : casual
- Verbosité : concis | Langue code : fr | Emoji : non
- Style connu : snake_case strict, libcst AST, modules < 10 KB
- Raccourcis : "ms" = make spec, "rt" = run tests
[/USER CONTEXT]
```

---

## 5. Mode Inspiration (`InspirationMode`)

### 5.1 Déclenchement

- Bouton "💡 Générer des idées" depuis `ProjectWelcomeScreen`
- Commande NL : "j'ai besoin d'idées pour..." / "cherche-moi des projets autour de..."
- Template "Depuis un mot-clé" dans `ProjectCreationModal`

### 5.2 Flow (dual pipeline)

```
Utilisateur → mot-clé / phrase / domaine
     ↓
InspirationEngine.generate(keyword, online=settings.online_features_enabled)
     ↓
  [Online — optionnel]                  [Offline — défaut]
  WebSearchEngine                       MemPalaceClient.query()
  DDG + Wikipedia + Brave               Recherche vectorielle
  (troncature 3000 chars/page)          skills/projets existants
          ↓                                     ↓
              LLM local (qwen2.5-coder:3b)
              Génère exactement 3 idées (offline) / 5 idées (online)
                          ↓
              Déduplication Jaccard lexical
              (réutilise ObserverAgent._is_duplicate())
              Seuil : >= 0.85 avec projets existants → rejet
                          ↓
              Filtrage quality_score >= 0.6
                          ↓
              < 1 idée valide → fallback templates
                          ↓
                   InspirationPanel
```

> La déduplication cosine proposée en v3 a été remplacée par Jaccard lexical, cohérent avec `ObserverAgent` (déjà dans le codebase). 0 nouvelle dépendance, même logique.

**Prompt offline (optimisé pour qwen2.5-coder:3b)** :
```
Génère exactement 3 idées de projet en JSON uniquement.
Pour chaque idée : title (<50 chars), description (1 phrase), domain (1 mot),
tech_stack (3-5 techno), difficulty (débutant/intermédiaire/avancé),
estimated_sprints (entier), tags (3 tags), quality_score (0.0-1.0).
Projets existants à éviter : {projets_existants_resumes}
Patterns disponibles : {skills_pertinents}
```

**Fallback templates** (`core/inspiration_templates.json`) :
```json
[
  {"title": "Outil CLI pour {domaine}", "tech_stack": ["Python", "Click", "SQLite"], ...},
  {"title": "Dashboard de suivi {domaine}", "tech_stack": ["Python", "FastAPI", "React"], ...},
  {"title": "Agent conversationnel {domaine}", "tech_stack": ["Python", "Ollama", "ChromaDB"], ...}
]
```
Déclenché si : LLM timeout, réponse invalide, ou 0 idée après filtrage.

### 5.3 `InspirationPanel`

```
┌─────────────────────────────────────────────────────┐
│  💡 Mode Inspiration                    [✕ Fermer]  │
│  "agent médical"                    [⬡ Local/🌐]    │
├─────────────────────────────────────────────────────┤
│  ① Chatbot de triage médical                        │
│     Python · FastAPI · Ollama · WhatsApp            │
│     Difficulté : avancé · ~12 sprints               │
│     [+ Créer ce projet]                             │
│                                                     │
│  ② Agenda médical intelligent                       │
│     Python · SQLite · React · NLP                   │
│     [+ Créer ce projet]                             │
│                                                     │
│  [🔄 Regénérer]   [🔍 Affiner]   [⚙ Seuil qualité] │
└─────────────────────────────────────────────────────┘
```

---

## 6. Apprentissage Global

### 6.1 Contribution des projets

```
projects/{slug}/skills/     → Skills locales
D:\LLMCodeAgent\skills\     → Skills globales
MemPalace (project_global_skills) → Index cross-projets
```

### 6.2 Pipeline `ProjectContributor`

1. `EducatorAgent` scanne skills locales
2. `ObserverAgent` détecte patterns généralisables (Jaccard)
3. Déduplication contre base globale
4. Promotion si score qualité >= seuil ET skill non-confidentiel
5. Indexation `project_global_skills` MemPalace
6. `stats.skills_generated++`

**Règle** : skills contenant des chemins absolus non réécrits (`{PROJECT_ROOT}` absent) → bloqués de la promotion.

---

## 7. Architecture Technique

### 7.1 Backend Python — nouveaux modules

```
core/
├── project_orchestrator.py      # Manager hierarchical (< 8 KB)
├── project_loader.py            # Worker : lecture project.json + lock (< 8 KB)
├── project_context_assembler.py # Worker : skills + specs + history (< 8 KB)
├── project_checkpoint.py        # Worker : context_snapshot (< 8 KB)
├── project_manager.py           # CRUD + scan filesystem + index.cache.json
├── project_contributor.py       # Pipeline contribution locale → globale
├── project_lock.py              # File locking + heartbeat %TEMP%
├── migration_manager.py         # PROJ-00 : migration V9 → V10
├── user_context.py              # Chargement/sauvegarde + WAL
├── user_context_injector.py     # Worker : génération bloc prompt (< 8 KB)
├── inspiration_engine.py        # Dual pipeline online/offline
└── inspiration_templates.json   # Fallback templates (données, pas code)
```

### 7.2 MCP Tools — 10 nouveaux handlers

| Tool MCP | Description |
|---|---|
| `project_list` | Lister les projets |
| `project_open` | Charger un projet |
| `project_create` | Créer un projet |
| `project_archive` | Archiver un projet |
| `project_get_summary` | Résumé de la dernière session |
| `project_compact_history` | Forcer une compaction immédiate |
| `project_healthcheck` | Analyse dette technique (tests manquants, specs orphelines) → `stats.issues_count` |
| `user_context_read` | Lire le contexte utilisateur |
| `user_context_update` | Mettre à jour une préférence (→ WAL) |
| `inspiration_generate` | Lancer le mode inspiration |

**Règle T-01 renforcée** :
- `mcp_tools_schema.py` expose `MCP_TOOLS_COUNT = len(TOOLS_REGISTRY)`
- **Tous** les tests qui comparent le nombre de tools importent `MCP_TOOLS_COUNT` :
  ```python
  from core.mcp_tools_schema import MCP_TOOLS_COUNT
  assert len(tools) == MCP_TOOLS_COUNT
  ```
- Tests d'intégration legacy ne pouvant pas importer la constante : `assert len(tools) >= 13`
- Tout ajout de tool → incrémenter `TOOLS_REGISTRY` en premier, les tests suivent automatiquement

> Compte actuel : 13 tools. Post-PROJ : **23 tools**. Corriger `test_tools_list_*` dans PROJ-04 (règle T-01 — priorité immédiate dès le premier tool ajouté).

### 7.3 Frontend Electron/React

```
src/components/
├── ProjectWelcomeScreen.tsx   src/stores/
├── ProjectCard.tsx             ├── projectStore.ts
├── ProjectCreationModal.tsx    └── userContextStore.ts
├── ProjectSwitcher.tsx
├── InspirationPanel.tsx       electron/
├── IdeaCard.tsx               └── main.ts (+IPC handlers)
└── UserContextBadge.tsx
```

**Règle IPC** : tout nouveau handler = 3 fichiers : `main.ts` + `preload.ts` + composant consommateur.

---

## 8. Extensions V2+

| Feature | Description | Priorité |
|---|---|---|
| **Timeline projet** | Visualisation chronologique (history.jsonl + MemPalace) | P2 |
| **Cross-projet search** | Recherche vectorielle cross-palace | P2 |
| **Shortcuts NL** | "appelle ça build" → alias WAL | P2 |
| **Mode Focus** | Un seul projet visible (user_context) | P2 |
| **Templates intelligents** | Clustering tags + stack | P3 |
| **Export `.llca`** | Archive projet complète | P3 |
| **Collaboration** | ChromaDB distant multi-instance | P4 |

---

## 9. Règles Invariantes

1. **Isolation** : `get_palace(project_id, storage_mode, legacy_namespaces)` = seul point d'entrée.
2. **UserContext non-technique** : jamais de code, chemins absolus, données de session.
3. **Token budget** : `UserContextInjector` ≤ 800 tokens. FIFO sur `learned` si dépassement.
4. **WAL avant tout** : `user_context.json` jamais écrit directement en cours de session.
5. **Non-régression V9** : LLCA sans `projects/` fonctionne exactement comme avant.
6. **Offline-first** : tout pipeline réseau → fallback offline obligatoire.
7. **Tests** : ≥ 12 tests par module `core/project_*.py`. `MCP_TOOLS_COUNT` dans tous les tests de count tools.
8. **Spec validée avant code** : règle invariante LLCA.

---

## 10. Checklist de Validation Avant Code

**Filesystem & Migration**
- [ ] `MigrationManager` : non-destructif, rollback = supprimer `projects/`, testé avec `tmp_dir`
- [ ] Double namespace `legacy` : collections `lcca_*` et `project_legacy_*` accessibles depuis `get_palace()`
- [ ] `_rewrite_paths()` : testé sur skill contenant `D:\LLMCodeAgent\` → `{PROJECT_ROOT}/`
- [ ] Scan filesystem `.llca/` : `index.cache.json` reconstruit correctement depuis `tmp_dir`

**Locking**
- [ ] `ProjectLock` : testé avec mock PID + suppression fichier `%TEMP%` (simulation stale)
- [ ] Heartbeat daemon : ne bloque pas le thread principal, supprimé proprement à `project_close()`

**History**
- [ ] `HistoryCompaction` : seuil 5 MB absolu respecté, résumé LLM mocké, archivage daté
- [ ] `project_compact_history` MCP tool : appel manuel fonctionne indépendamment du seuil

**UserContext WAL**
- [ ] Replay WAL au boot : état reconstruit correctement depuis 0 + depuis WAL partiel
- [ ] Compaction à 10 entrées : `user_context.json` mis à jour, WAL tronqué
- [ ] Snapshot hebdomadaire : déclenché après 7j mock, WAL tronqué
- [ ] Champs sensibles (`language`, `identity.*`) : confirmation requise avant écriture WAL

**Inspiration**
- [ ] Fallback offline : 0 appel `urlopen` (conftest.py autouse existant bloque)
- [ ] Déduplication Jaccard : idée similaire (>= 0.85) rejetée, idée originale conservée
- [ ] Fallback templates : déclenché si LLM timeout ou 0 idée valide
- [ ] `quality_score` < 0.6 : idée exclue

**MCP & Tests**
- [ ] `MCP_TOOLS_COUNT` exposé dans `mcp_tools_schema.py` et importé dans tous les tests de count
- [ ] `test_tools_list_*` mis à jour dès PROJ-04 (règle T-01 — 13 → 23 tools)
- [ ] `project_healthcheck` : `stats.issues_count` mis à jour dans `project.json`
- [ ] Workers `ProjectOrchestrator` : chacun < 8 KB, testables en isolation

---

## 11. Sprint Plan (v3)

| Sprint | Contenu | Priorité |
|---|---|---|
| **PROJ-00** | `MigrationManager` + structure `.llca/` + `_rewrite_paths()` | P0 |
| **PROJ-01** | `project_manager.py` + scan filesystem + `index.cache.json` | P0 |
| **PROJ-02** | `project_lock.py` + heartbeat `%TEMP%` + tests mock PID | P0 |
| **PROJ-03** | `ProjectOrchestrator` + 4 workers + tests isolation | P0 |
| **PROJ-04** | 10 MCP tools + `MCP_TOOLS_COUNT` + `test_tools_list_*` (13→23) | P0 |
| **PROJ-05** | `ProjectWelcomeScreen.tsx` + `ProjectCard.tsx` + IPC | P0 |
| **PROJ-06** | `user_context.py` + WAL + replay + compaction + snapshot | P1 |
| **PROJ-07** | `UserContextInjector` + `UserContextStore.ts` + badge | P1 |
| **PROJ-08** | Apprentissage automatique UserContext (fin de session) | P1 |
| **PROJ-09** | `HistoryCompaction` L0→L1→L2 + archivage + compaction manuelle | P1 |
| **PROJ-10** | `InspirationEngine` dual pipeline + templates fallback | P2 |
| **PROJ-11** | `ProjectContributor` — contribution globale | P2 |
| **PROJ-12** | Résumé de reprise (> 1h) + `project_healthcheck` | P2 |

---

*Spec v1+v2 : Claude Sonnet 4.6 | Addendum v2 : Kimi K2.6 | Addendum v3 : analyse critique*
*Arbitrages v3 : Claude Sonnet 4.6 — 2026-04-23*
*Validation par Adham requise avant tout démarrage de code (règle invariante LLCA §9.8)*
