# Spec 09 — MemPalace (Client + Context Assembler + Adapter)
> **Modules** : `core/mempalace_client.py`, `core/context_assembler.py`, `core/mempalace_adapter.py`
> **Sprint** : 05 + 08 | **Statut** : ✅ VALIDÉ

---

## 1. Vue d'ensemble

Le système MemPalace est la **couche mémoire vectorielle** de LCCA. Il se compose de trois modules :

| Module | Rôle |
|--------|------|
| `MemPalaceClient` | Stockage + recherche ChromaDB (4 layers) + filesystem hiérarchique |
| `ContextAssembler` | Assemble un prompt contexte LLM dans le budget tokens |
| `ExistingMemPalaceAdapter` | Connexion en lecture au MemPalace MediBot existant |

---

## 2. MemPalaceClient

### Architecture 4 Layers

| Layer | Collection ChromaDB | Contenu | Taille cible |
|-------|---------------------|---------|-------------|
| 0 | `layer_0_identity` | Identité LCCA (prompt système fixe) | ~170 tokens |
| 1 | `layer_1_compressed` | Résumé projet AAAK (connaissances compressées) | ~500 tokens |
| 2 | `layer_2_scoped` | Contexte session active | ~2000 tokens |
| 3 | `layer_3_deep` | Historique complet, illimité | illimité |

### `MemoryEntry` (dataclass)
```python
@dataclass
class MemoryEntry:
    content:      str
    wing:         Optional[str]   # Domaine fonctionnel ("lcca", "medibot")
    room:         Optional[str]   # Sous-domaine ("sprint_05")
    hall:         Optional[str]   # Sous-sous-domaine ("ast_patcher")
    source:       str             # Origine ("system", "lcca", ...)
    metadata:     Dict[str, Any]
    layer:        int             # 0-3
    embedding_id: Optional[str]   # ID MD5 12-chars
```

### API publique

```python
class MemPalaceClient:
    def __init__(self, palace_path: str = "~/.mempalace/palace") -> None

    def mine_content(content, wing, room, hall, source, metadata, layer) → str
    # Stocke dans ChromaDB + filesystem JSON. Retourne entry_id (MD5 12-chars).

    def get_by_id(entry_id: str) → Optional[MemoryEntry]
    # Cherche dans les 4 layers.

    def search_memories(query, wing, room, hall, layer, n_results=5) → List[MemoryEntry]
    # Recherche sémantique ChromaDB avec filtres hiérarchiques optionnels.

    def wake_up(wing, room) → Dict[str, Any]
    # Contexte de démarrage : identity (L0) + compressed (L1) + recent (L2).
```

### Stockage filesystem (complément ChromaDB)

```
palace_path/
├── wings/
│   └── {wing}/
│       └── rooms/
│           └── {room}/
│               └── {entry_id}.json    # Payload complet
├── halls/
└── chroma_db/                         # Données ChromaDB
```

### Génération des IDs
```python
entry_id = hashlib.md5(f"{content}{time.time_ns()}".encode()).hexdigest()[:12]
```

### Filtres ChromaDB (`_build_where`)
```python
# Filtre wing seul :
{"wing": {"$eq": "lcca"}}

# Filtre wing + room :
{"$and": [{"wing": {"$eq": "lcca"}}, {"room": {"$eq": "sprint_05"}}]}
```

---

## 3. ContextAssembler

### Rôle
Assemble le prompt contexte LLM en respectant `MAX_CONTEXT_TOKENS = 8000`.

### Ordre de priorité (jamais tronqué → optionnel)
```
1. Identity Layer 0        — CRITIQUE (jamais tronqué)
2. Intent + fichiers cibles — CRITIQUE
3. Contenu des fichiers     — TRONQUÉ si budget dépassé
4. Souvenirs MemPalace      — OPTIONNEL (ajoutés si budget restant > 200 tokens)
```

### `assemble(intent, target_files, file_contents, wing, room) → str`

Algorithme :
1. `palace.wake_up(wing, room)` → identité
2. Estimation tokens sections critiques
3. `_format_files()` avec budget = total - critique
4. `_format_memories()` avec budget restant
5. Hard truncate si dépassement malgré tout

### Estimation tokens
```python
def estimate_tokens(text: str) -> int:
    return max(0, len(text) // 4)   # ~4 chars = 1 token
```

### `truncate_to_fit(sections: List[Tuple[str, int]], budget: int) → str`
Sections avec priorité ≥ 10 = critiques (jamais omises).
Sections avec priorité < 10 = optionnelles (omises si budget dépassé).

---

## 4. ExistingMemPalaceAdapter (Sprint 08)

### Rôle
Connexion **en lecture** au MemPalace MediBot existant (`D:\MediBot\Mempalace`).
Les écritures LCCA vont dans des collections préfixées `lcca_*` pour isolation totale.

### Détection automatique du palace
```python
POSSIBLE_PATHS = [
    Path(r"D:\MediBot\Mempalace\memory_palace"),
    Path(r"D:\MediBot\Mempalace"),
    Path.home() / ".mempalace" / "palace",
]
```

Accepte : `chroma.sqlite3`, `chroma_db/chroma.sqlite3`, ou `identity.txt` (tests).

### Collections LCCA isolées
```python
_LCCA_COLLECTION_NAMES = ("lcca_transactions", "lcca_ast_index", "lcca_sessions")
```

### API publique

```python
class ExistingMemPalaceAdapter:
    @property
    def is_available(self) -> bool

    @property
    def specs(self) -> List[Dict[str, str]]   # [{name, content}, ...]

    @property
    def identity(self) -> str

    @property
    def lcca_collections(self) -> Dict[str, Any]

    def wake_up_medi(wing="medibot", room=None) → Dict[str, Any]
    # identity + specs + compressed_knowledge + recent_activity

    def search(query, wing, n_results) → List[MemoryEntry]

    def find_relevant_specs(keywords, max_specs=2) → str
    # Retourne extract des specs pertinentes pour les keywords
```

### Format `wake_up_medi()`
```python
{
    "identity":            str,           # identity.txt
    "compressed_knowledge": List[str],   # Layer 1 ChromaDB
    "recent_activity":     List[str],    # Layer 2 ChromaDB
    "specs":               List[dict],   # [{name, content}, ...]
    "palace_path":         str | None,
    "timestamp":           str,          # ISO UTC
}
```

---

## 5. Contraintes AI-Ready

- ChromaDB importé **tard** (`import chromadb` dans `__init__`) → pas de crash si absent
- `ExistingMemPalaceAdapter.is_available` → toujours vérifier avant usage
- Docstrings avec chemins Windows → `r"""..."""` (raw string, évite DeprecationWarning)
- Tests conditionnels : `if not adapter.is_available: pytest.skip()`
- Python 3.14+ : ChromaDB incompatible → `pytest.mark.skipif(sys.version_info >= (3, 14), ...)`
