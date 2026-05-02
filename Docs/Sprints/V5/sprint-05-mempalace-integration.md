# 🧠 Sprint 05 — MemPalace Integration

> **Durée estimée** : 4 jours  
> **Statut** : ⚪ À FAIRE  
> **Priorité** : 🟠 Haute  
> **Dépend de** : Sprint 01 (venv, config), Sprint 02 (TX Manager), Sprint 04 (Orchestrateur)  
> **Objectif** : Intégrer le client MemPalace (ChromaDB + filesystem hiérarchique) pour la mémoire persistante et le contexte LLM.

---

## 🎯 Objectifs du Sprint

LCCA V5 Fusion utilise MemPalace comme **mémoire long terme** : chaque transaction commitée est persistée, l'index AST est mémorisé entre les sessions, et les specs projet sont indexées vectoriellement pour alimenter le contexte LLM.

Ce sprint implémente deux composants :
- `core/mempalace_client.py` : client générique pour ChromaDB + filesystem hiérarchique
- `core/context_assembler.py` : gestion de la fenêtre de contexte LLM (max 8000 tokens)

### Architecture mémoire (4 Layers) :
| Layer | Nom | Taille | Contenu |
|-------|-----|--------|---------|
| 0 | Identity | ~170 tokens | Qui est LCCA, règles absolues |
| 1 | Compressed | ~500 tokens | Résumé projet compressé AAAK |
| 2 | Scoped | ~2000 tokens | Contexte session active (wing/room) |
| 3 | Deep | illimité | Tout l'historique (ChromaDB) |

---

## 📋 Tâches

### TASK-05-01 — `MemPalaceClient` — Initialisation et collections
**Priorité** : 🔴 Critique  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `core/mempalace_client.py`

**Description** :  
Initialiser le client ChromaDB avec les 4 collections layerisées et la structure de dossiers `wings/rooms/halls`.

**Dataclass MemoryEntry** :
```python
@dataclass
class MemoryEntry:
    content: str
    wing: Optional[str] = None
    room: Optional[str] = None
    hall: Optional[str] = None
    source: str = "system"
    metadata: Dict[str, Any] = field(default_factory=dict)
    layer: int = 3
    embedding_id: Optional[str] = None
```

**Initialisation** :
```python
class MemPalaceClient:
    def __init__(self, palace_path: str = "~/.mempalace/palace"):
        self.palace_path = Path(palace_path).expanduser()
        self.chroma_path = self.palace_path / "chroma_db"
        
        self.client = chromadb.PersistentClient(path=str(self.chroma_path))
        
        self.collections = {
            0: self.client.get_or_create_collection("layer_0_identity"),
            1: self.client.get_or_create_collection("layer_1_compressed"),
            2: self.client.get_or_create_collection("layer_2_scoped"),
            3: self.client.get_or_create_collection("layer_3_deep")
        }
        
        self._ensure_dirs()
        self._init_identity()
```

> ⚠️ **Note API ChromaDB ≥ 0.4** : Utiliser `chromadb.PersistentClient(path=...)` — l'ancienne API `Settings(chroma_db_impl=...)` est dépréciée.

**Critères d'acceptation** :
- [ ] `MemPalaceClient()` s'initialise sans erreur
- [ ] 4 collections créées dans ChromaDB
- [ ] Dossiers `wings/`, `halls/` créés
- [ ] Ré-initialisation idempotente (2e appel = pas d'erreur)

---

### TASK-05-02 — `mine_content()` — Stockage mémoire
**Priorité** : 🔴 Critique  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Stocker du contenu dans le palace : vectoriellement (ChromaDB pour recherche sémantique) ET sur le filesystem (backup verbatim, consultable sans ChromaDB).

**Signature** :
```python
def mine_content(
    self,
    content: str,
    wing: Optional[str] = None,
    room: Optional[str] = None,
    hall: Optional[str] = None,
    source: str = "lcca",
    metadata: Optional[Dict] = None,
    layer: int = 3
) -> str:
    """Retourne l'entry_id (MD5 12 chars)."""
```

**Logique** :
1. Générer `entry_id = md5(content + timestamp)[:12]`
2. Stocker dans ChromaDB (collection du layer)
3. Écrire `wings/{wing}/rooms/{room}/{entry_id}.json` sur filesystem
4. Retourner `entry_id`

**Critères d'acceptation** :
- [ ] `entry_id` unique pour chaque appel
- [ ] Contenu retrouvable via `get_by_id(entry_id)`
- [ ] Fichier JSON créé dans la hiérarchie wings/rooms
- [ ] `content` vide → `ValueError` levée

---

### TASK-05-03 — `search_memories()` — Recherche sémantique
**Priorité** : 🔴 Critique  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Recherche vectorielle dans les collections ChromaDB avec filtres hiérarchiques (wing, room, hall, layer).

**Signature** :
```python
def search_memories(
    self,
    query: str,
    wing: Optional[str] = None,
    room: Optional[str] = None,
    hall: Optional[str] = None,
    layer: Optional[int] = None,
    n_results: int = 5
) -> List[MemoryEntry]:
```

**Logique** :
- Si `layer` spécifié → recherche dans cette collection uniquement
- Sinon → recherche dans les 4 collections, merge, sort par score
- Filtres `where` ChromaDB si wing/room/hall spécifiés

**Critères d'acceptation** :
- [ ] Retourne les souvenirs les plus pertinents sémantiquement
- [ ] Filtre `wing` fonctionne (ne retourne que ce wing)
- [ ] Collection vide → liste vide, pas d'erreur
- [ ] `n_results` respecté

---

### TASK-05-04 — `wake_up()` — Chargement contexte initial
**Priorité** : 🟠 Haute  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Description** :  
Charger le contexte de démarrage optimisé (~170 tokens Layer 0 + résumé Layer 1 + activité récente Layer 2 si wing/room précisés).

```python
def wake_up(
    self,
    wing: Optional[str] = None,
    room: Optional[str] = None
) -> Dict[str, Any]:
    """
    Retourne un dict avec:
    - identity: str (Layer 0 — toujours présent)
    - compressed_knowledge: List[str] (Layer 1 — si wing spécifié)
    - recent_activity: List[str] (Layer 2 — si wing+room spécifiés)
    - timestamp: str
    """
```

**Critères d'acceptation** :
- [ ] `wake_up()` sans args → retourne uniquement Layer 0 identity
- [ ] `wake_up(wing="lcca")` → Layer 0 + Layer 1 compressé
- [ ] `wake_up(wing="lcca", room="sprint_05")` → Layer 0 + 1 + 2
- [ ] Durée < 500ms (pas de requête lente au démarrage)

---

### TASK-05-05 — `ContextAssembler` — Gestion fenêtre contexte LLM
**Priorité** : 🟠 Haute  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `core/context_assembler.py`

**Description** :  
Assembler le contexte LLM en respectant la limite de tokens. Priorise les éléments les plus utiles si la fenêtre déborde.

**Interface** :
```python
MAX_CONTEXT_TOKENS = 8000  # depuis config.py

class ContextAssembler:
    def __init__(self, palace: MemPalaceClient, max_tokens: int = MAX_CONTEXT_TOKENS):
        self.palace = palace
        self.max_tokens = max_tokens
    
    def assemble(
        self,
        intent: Intent,
        target_files: List[str],
        file_contents: Dict[str, str]
    ) -> str:
        """
        Assemble le prompt contexte pour le LLM.
        Respecte max_tokens en tronquant intelligemment.
        
        Ordre de priorité (du plus au moins important):
        1. Identity (Layer 0) — jamais tronqué
        2. Intent + fichiers cibles — jamais tronqué
        3. Contenu des fichiers modifiés — tronqué si besoin
        4. Souvenirs MemPalace pertinents — optionnels, derniers ajoutés
        """
    
    def estimate_tokens(self, text: str) -> int:
        """Estimation rapide: ~4 chars = 1 token."""
        return len(text) // 4
    
    def truncate_to_fit(self, sections: List[Tuple[str, int]], budget: int) -> str:
        """
        Assemble les sections en respectant le budget.
        Les sections sont (contenu, priorité) — priorité haute = jamais tronqué.
        """
```

**Format de sortie (prompt assemblé)** :
```
# LCCA V5 — Context
## Identity
{layer_0_identity}

## Task
Project: {intent.project}
Target: {intent.target} / {intent.sub_target}
Action: {intent.action} {intent.details}

## Files to modify
### {file_path_1}
```python
{content_truncated}
```

## Relevant memories
- {memory_1}
- {memory_2}
```

**Critères d'acceptation** :
- [ ] Sortie < `max_tokens` tokens estimés
- [ ] Identity et Task toujours présents
- [ ] Contenu fichier tronqué proprement (pas au milieu d'une ligne)
- [ ] Log warning si troncature > 20%

---

### TASK-05-06 — `ExistingMemPalaceAdapter` — Connexion au MemPalace existant
**Priorité** : 🟡 Normale  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `core/mempalace_adapter.py`

**Description** :  
Adapter qui se connecte au MemPalace MCP existant à `D:\MediBot\Mempalace` au lieu d'en créer un nouveau. Charge la config YAML, lit l'identity existante, et accède à la ChromaDB existante.

**Logique de détection auto** :
```python
POSSIBLE_PATHS = [
    Path(r"D:\MediBot\Mempalace\memory_palace"),
    Path(r"D:\MediBot\Mempalace"),
    Path.home() / ".mempalace" / "palace"
]

def _detect_palace_path(self) -> Path:
    for p in POSSIBLE_PATHS:
        if p.exists() and (p / "chroma.sqlite3").exists():
            return p
    raise FileNotFoundError("MemPalace non trouvé. Vérifier D:\\MediBot\\Mempalace")
```

**Critères d'acceptation** :
- [ ] Connexion réussie à `D:\MediBot\Mempalace` si existant
- [ ] Fallback vers `~/.mempalace/palace` si non trouvé
- [ ] `_load_specs()` charge les fichiers `.md` et `.txt` du dossier `specs/`
- [ ] `wake_up_medi()` retourne contexte MediBot enrichi
- [ ] Ne crée rien si le palace n'existe pas (pas de side effects)

---

### TASK-05-07 — Tests unitaires MemPalace
**Priorité** : 🟠 Haute  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `tests/test_mempalace_client.py`

**Tests** :
```python
def test_mine_and_retrieve():
    """mine_content() puis get_by_id() retourne le même contenu."""

def test_search_returns_relevant():
    """Stocker 3 souvenirs, chercher → retourne le plus pertinent."""

def test_wing_filter_isolates():
    """Souvenir wing='A' non retourné si on cherche dans wing='B'."""

def test_wake_up_no_args():
    """wake_up() sans args retourne au moins l'identity."""

def test_context_assembler_respects_limit():
    """Contexte assemblé < max_tokens."""

def test_context_assembler_always_includes_intent():
    """Même si contexte plein, l'intent est présent."""
```

**Critères d'acceptation** :
- [ ] `pytest tests/test_mempalace_client.py` → 6/6 tests passent
- [ ] Tests s'exécutent en < 5 secondes (ChromaDB en mémoire pour les tests)

---

## 📊 Récapitulatif Sprint 05

| Task | Description | Effort | Statut |
|------|------------|--------|--------|
| TASK-05-01 | MemPalaceClient init + collections | 0.5j | ⚪ |
| TASK-05-02 | `mine_content()` | 0.5j | ⚪ |
| TASK-05-03 | `search_memories()` | 0.5j | ⚪ |
| TASK-05-04 | `wake_up()` | 0.5j | ⚪ |
| TASK-05-05 | ContextAssembler | 1j | ⚪ |
| TASK-05-06 | ExistingMemPalaceAdapter | 1j | ⚪ |
| TASK-05-07 | Tests unitaires | 0.5j | ⚪ |
| **TOTAL** | | **4.5j** | |

---

## ✅ Définition of Done (Sprint 05)

- [ ] `pytest tests/test_mempalace_client.py` → 0 erreur
- [ ] `MemPalaceClient().mine_content("test")` → entry_id retourné, persisté
- [ ] Contexte assemblé respecte le budget tokens
- [ ] `ExistingMemPalaceAdapter` se connecte à `D:\MediBot\Mempalace` (si existant)
- [ ] `004-sprint-context.md` mis à jour

---

## ⚠️ Contraintes & Risques

| Risque | Probabilité | Mitigation |
|--------|------------|------------|
| API ChromaDB ≥ 0.4 brisée vs exemple spec | Haute | Utiliser `PersistentClient`, tester avec `chromadb --version` |
| ChromaDB lente au démarrage (embedding model) | Moyenne | Désactiver les embeddings ML, utiliser distance cosine sur hashes |
| MemPalace MediBot incompatible schema | Faible | Adapter lit uniquement, n'écrit pas dans le palace existant |

---

## 🔗 Navigation

⬅️ [Sprint 04 — Planner & Orchestrateur](sprint-04-planner-orchestrator.md)  
➡️ [Sprint 06 — Recovery Service & Validation](sprint-06-recovery-validation.md)
