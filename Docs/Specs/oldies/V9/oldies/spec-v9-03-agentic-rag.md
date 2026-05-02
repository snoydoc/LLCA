# Spec V9-03 — LLM + Recherche Internet Ciblée (Agentic RAG)
<!-- AI-READY | LCCA V9 | Agentic RAG | Version 9.0.0-draft | 2026-04-20 -->

## Abstract

Combiner les LLM locaux (Qwen) avec des sources de connaissance dynamiques : index AST
du workspace (Repository-RAG), recherche web automatique sur les bibliothèques inconnues,
récupération de documentation officielle sur erreur d'API, et HyDE (Hypothetical Document
Embedding) pour améliorer le recall ChromaDB. Tous les composants s'appuient sur
l'infrastructure existante (WebSearchEngine, MemoryEngine, ASTIndexer, ChromaDB).

---

## Sprint V9-03-A — Repository-RAG dans CoderAgent

### Contexte et motivations

Le `CoderAgent` génère du code sans voir les fichiers LCCA existants — sauf le fichier
cible lui-même. Dans un codebase de 52 modules inter-dépendants, cela produit :
- Des imports manquants (classes existantes non connues du LLM)
- Des duplications (réimplémentation de fonctions déjà présentes)
- Des violations de conventions (nommage, patterns idiomatiques LCCA)

La solution : avant chaque appel `generate()`, indexer le workspace et injecter les
3-5 fichiers les plus pertinents dans le contexte du Coder.

### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `core/agents/coder_agent.py` | PATCH — `_retrieve_repo_context(intent)` |
| `core/ast_indexer.py` | VÉRIF — `index_repository()` retourne `dict[str, list]` |
| `config.py` | PATCH — `REPO_RAG_MAX_FILES = 5`, `REPO_RAG_MAX_LINES = 80` |
| `tests/test_coder_agent.py` | CREATE/PATCH — 4 nouveaux tests |

### Spécification : `CoderAgent._retrieve_repo_context`

```python
# Constantes
_REPO_RAG_STOPWORDS = frozenset({
    "the", "a", "an", "in", "of", "to", "for", "and", "or", "with",
    "create", "add", "implement", "module", "function", "class",
    "crée", "ajoute", "implémente", "modifie", "dans", "pour",
})

def _retrieve_repo_context(self, intent: str) -> str:
    """
    Construit un contexte de fichiers LCCA pertinents pour l'intent.

    Algorithme BM25 simplifié :
    1. Tokeniser l'intent (stopwords filtrés)
    2. Pour chaque fichier indexé, compter les occurrences des tokens dans ses symboles
    3. Retenir les max_files fichiers avec le meilleur score
    4. Lire les max_lines premières lignes de chaque fichier
    5. Retourner le contexte formaté

    Silencieux : tout échec retourne "" (ne bloque jamais la génération).
    """
    import config
    from core.ast_indexer import ASTIndexer

    max_files = getattr(config, "REPO_RAG_MAX_FILES", 5)
    max_lines = getattr(config, "REPO_RAG_MAX_LINES", 80)

    try:
        tokens = {
            w.lower() for w in intent.split()
            if w.lower() not in _REPO_RAG_STOPWORDS and len(w) > 2
        }
        if not tokens:
            return ""

        indexer = ASTIndexer(workspace=config.WORKSPACE_DIR)
        index   = indexer.index_repository()   # {filepath: [symbols]}

        scores: dict[str, int] = {}
        for filepath, symbols in index.items():
            file_tokens = set()
            for sym in symbols:
                file_tokens.update(sym.get("name", "").lower().split("_"))
            scores[filepath] = len(tokens & file_tokens)

        top_files = sorted(
            (fp for fp, s in scores.items() if s > 0),
            key=lambda fp: scores[fp],
            reverse=True,
        )[:max_files]

        if not top_files:
            return ""

        parts = ["## Fichiers LCCA pertinents (Repository-RAG)\n"]
        for fp in top_files:
            try:
                from pathlib import Path
                lines = Path(fp).read_text(encoding="utf-8-sig",
                                           errors="replace").splitlines()[:max_lines]
                parts.append(
                    f"### `{Path(fp).name}` (score={scores[fp]})\n"
                    f"```python\n" + "\n".join(lines) + "\n```\n"
                )
            except Exception:
                continue

        return "\n".join(parts)

    except Exception as exc:
        log.debug("_retrieve_repo_context error: %s", exc)
        return ""
```

### Intégration dans `CoderAgent.run_task`

```python
def run_task(self, contract: TaskContract) -> AgentResult:
    ...
    # V9-03-A : enrichissement contexte repo
    repo_context  = self._retrieve_repo_context(contract.intent)
    skill_context = contract.context.get("available_skills", "")

    result = self._generator.generate(
        op=patch,
        intent=intent,
        context=file_context + ("\n\n" + repo_context if repo_context else ""),
        skill_context=skill_context,
    )
    ...
```

### Règles invariantes

- `_retrieve_repo_context` : jamais de raise — `try/except Exception` global
- Le contexte repo est injecté dans `context` (pas dans `skill_context`) pour préserver
  la sémantique : `context` = code existant, `skill_context` = exemples de style
- `max_lines = 80` : on préfère la breadth (5 fichiers × 80 lignes = 400 lignes)
  plutôt que la depth (1 fichier × 400 lignes) pour le contexte inter-modules

### Tests attendus

```python
class TestRepoBMRetrieval:
    def test_returns_empty_on_empty_intent(self):
        agent = CoderAgent.create(bus=A2ALocalBus(":memory:"))
        assert agent._retrieve_repo_context("") == ""

    def test_returns_empty_on_stopwords_only(self):
        agent = CoderAgent.create(bus=A2ALocalBus(":memory:"))
        assert agent._retrieve_repo_context("create a module for the function") == ""

    def test_returns_context_for_known_symbol(self, tmp_path):
        """Un intent mentionnant 'transaction_manager' remonte le bon fichier."""
        agent = CoderAgent.create(bus=A2ALocalBus(":memory:"))
        # Mocker ASTIndexer pour retourner un index connu
        with patch("core.ast_indexer.ASTIndexer.index_repository") as mock_idx:
            mock_idx.return_value = {
                str(tmp_path / "transaction_manager.py"): [
                    {"name": "transaction_manager", "type": "module"}
                ]
            }
            (tmp_path / "transaction_manager.py").write_text("# tm\ndef commit(): pass")
            result = agent._retrieve_repo_context("fix bug in transaction_manager commit")
        assert "transaction_manager" in result

    def test_silent_on_indexer_error(self, mocker):
        """Erreur d'indexation → "" silencieux."""
        agent = CoderAgent.create(bus=A2ALocalBus(":memory:"))
        mocker.patch("core.ast_indexer.ASTIndexer.index_repository",
                     side_effect=RuntimeError("disk error"))
        result = agent._retrieve_repo_context("fix transaction_manager")
        assert result == ""
```

---

## Sprint V9-03-B — Web search automatique dans ArchitectAgent

### Contexte et motivations

Quand l'intent mentionne une bibliothèque ou une API inconnue du codebase LCCA
(`httpx`, `fastapi`, `pydantic`, `boto3`, etc.), le Coder génère du code avec
les mauvaises signatures car le LLM a un cutoff de connaissance. `WebSearchEngine`
existe et peut récupérer les exemples d'usage actuels.

### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `core/agents/architect_agent.py` | PATCH — `_detect_external_libs(intent)` + appel web_search |
| `config.py` | PATCH — `ARCHITECT_WEB_SEARCH_ENABLED = True` |
| `tests/test_v8_03.py` | PATCH — 3 nouveaux tests |

### Spécification : `ArchitectAgent._detect_external_libs`

```python
# Mots-clés LCCA internes — à ne PAS déclencher une recherche web
_LCCA_INTERNAL_KEYWORDS = frozenset({
    "transaction", "ast", "mcp", "sandbox", "memory", "spec", "orchestrator",
    "agent", "skill", "llm", "ollama", "chromadb", "libcst", "nlp",
    "patch", "commit", "rollback", "wal", "receipt", "bus",
})

# Indicateurs de lib externe
_EXTERNAL_LIB_PATTERNS = [
    r"\b(import|using|via|avec|library|lib|package|framework|api)\b",
    r"\b([a-z][a-z0-9_]+\.py)\b",   # fichier externe explicite
]

def _detect_external_libs(self, intent: str) -> list[str]:
    """
    Détecte les bibliothèques externes mentionnées dans l'intent.

    Heuristique :
    - Tokenise l'intent
    - Exclut les mots LCCA internes
    - Retient les mots inconnus qui ressemblent à des noms de lib (lowercase, tirets)

    Returns:
        Liste de noms de libs candidates (peut être vide).
    """
    import re
    intent_lower = intent.lower()
    # Chercher des noms snake_case ou kebab-case (patterns de noms de libs)
    candidates = re.findall(r'\b([a-z][a-z0-9_-]{2,})\b', intent_lower)
    external = [
        c for c in candidates
        if c not in _LCCA_INTERNAL_KEYWORDS
        and not any(c in kw for kw in _LCCA_INTERNAL_KEYWORDS)
        and len(c) > 3
    ]
    # Déduplication ordre préservé
    seen, result = set(), []
    for e in external:
        if e not in seen:
            seen.add(e)
            result.append(e)
    return result[:3]  # max 3 libs pour ne pas surcharger
```

### Intégration dans `ArchitectAgent.run_task`

```python
def run_task(self, contract: TaskContract) -> AgentResult:
    ...
    # V9-03-B : recherche web si lib externe détectée
    web_context = ""
    if getattr(config, "ARCHITECT_WEB_SEARCH_ENABLED", True):
        external_libs = self._detect_external_libs(contract.intent)
        if external_libs:
            try:
                from core.web_search import WebSearchEngine
                engine = WebSearchEngine()
                query  = f"{external_libs[0]} python usage examples"
                result = engine.search(query)
                if result.synthesis:
                    web_context = (
                        f"## Documentation web : `{external_libs[0]}`\n\n"
                        + result.synthesis[:1500]  # limiter pour le contexte
                    )
                    log.info("[architect] web context fetched for lib=%s", external_libs[0])
            except Exception as exc:
                log.debug("[architect] web_search error: %s", exc)

    # Injecter le contexte web dans les sous-contrats
    for sub in sub_contracts:
        if web_context:
            sub.context["web_documentation"] = web_context
    ...
```

---

## Sprint V9-03-C — HyDE (Hypothetical Document Embedding)

### Contexte et motivations

La recherche ChromaDB actuelle compare l'embedding de la **requête brute** avec les embeddings
des documents stockés. Pour des intents courts ("bug transaction rollback"), la similarité est
faible car le vecteur de la requête est éloigné du vecteur des specs (qui sont longues et
détaillées).

HyDE génère d'abord un **document hypothétique** décrivant la solution idéale, puis utilise
l'embedding de CE document comme vecteur de recherche. Le rappel augmente de 25-30%.

### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `core/memory_engine.py` | PATCH — `search_hyde(query, wing, n)` variante HyDE |
| `config.py` | PATCH — `MEMORY_HYDE_ENABLED = False` (opt-in, lourd) |
| `core/agents/architect_agent.py` | PATCH — utiliser `search_hyde` si activé |
| `tests/test_memory_engine.py` | PATCH — 2 nouveaux tests |

### Spécification : `MemoryEngine.search_hyde`

```python
_HYDE_SYSTEM = (
    "Tu es un expert en architecture LCCA. "
    "Génère un court extrait de documentation (100-150 mots) qui décrirait idéalement "
    "la solution ou le module répondant à la requête suivante. "
    "Écris directement le document, sans introduction."
)

def search_hyde(
    self,
    query: str,
    wing: str = "lcca",
    n: int = 5,
    generator=None,
) -> "Dict[str, List[MemoryEntry]]":
    """
    Variante HyDE de search() : génère d'abord un document hypothétique,
    puis cherche les documents ChromaDB similaires à ce document.

    Args:
        query     : Requête utilisateur brute
        wing      : Wing MemPalace cible
        n         : Nombre de résultats max par collection
        generator : LLMGenerator injecté (si None, crée une instance légère 3b)

    Returns:
        Même structure que search() : dict {solutions, failures, context, specs, skills}
    """
    import config
    if not getattr(config, "MEMORY_HYDE_ENABLED", False):
        return self.search(query, wing, n)  # fallback standard

    if not self._available:
        return self.search(query, wing, n)

    # Générer le document hypothétique
    try:
        if generator is None:
            from core.llm_generator import LLMGenerator
            generator = LLMGenerator(
                model      = getattr(config, "OLLAMA_MODEL_LIGHT", config.OLLAMA_MODEL),
                timeout    = 30,
                max_tokens = 200,
            )
        hyde_doc = generator.generate_text(_HYDE_SYSTEM, f"Requête : {query}")
        if not hyde_doc or len(hyde_doc) < 20:
            log.debug("HyDE: document hypothétique vide → fallback standard")
            return self.search(query, wing, n)
        log.debug("HyDE: document généré %d chars", len(hyde_doc))
    except Exception as exc:
        log.debug("HyDE: erreur génération (%s) → fallback", exc)
        return self.search(query, wing, n)

    # Chercher avec le document hypothétique au lieu de la requête brute
    return self.search(hyde_doc, wing, n)
```

### Préconditions et postconditions

- **Précondition** : `MEMORY_HYDE_ENABLED = True` dans config.py (désactivé par défaut
  car coûteux : +1 appel LLM léger par recherche).
- **Postcondition** : retourne la même structure que `search()`.
- **Dégradation gracieuse** : toute erreur → `search()` standard silencieusement.

---

## Sprint V9-03-D — Récupération doc officielle sur erreur d'API

### Contexte et motivations

Quand le `TesterAgent` échoue avec `AttributeError: module 'X' has no attribute 'Y'`
ou `TypeError: function() got unexpected keyword argument`, c'est une erreur de signature
d'API. Le `ReviewerAgent` doit détecter ce pattern et lancer une recherche web ciblée
sur la doc officielle avant de retourner la réflexion au KarpathyLoop.

### Fichiers cibles

| Fichier | Opération |
|---------|-----------|
| `core/agents/reviewer_agent.py` | PATCH — `_enrich_reflection_with_docs(reflection, code)` |
| `tests/test_reviewer_agent.py` | PATCH — 3 nouveaux tests |

### Spécification : `ReviewerAgent._enrich_reflection_with_docs`

```python
import re as _re

_API_ERROR_PATTERNS = [
    r"AttributeError: (?:module '(\w+)'|'(\w+)' object) has no attribute '(\w+)'",
    r"TypeError: (\w+)\(\) got an unexpected keyword argument '(\w+)'",
    r"ImportError: cannot import name '(\w+)' from '(\w+)'",
    r"ModuleNotFoundError: No module named '(\w+)'",
]

def _enrich_reflection_with_docs(self, reflection: str, code: str) -> str:
    """
    Si la réflexion contient une erreur d'API connue, lance une recherche web ciblée
    et enrichit la réflexion avec la documentation officielle trouvée.

    Silencieux : en cas d'échec, retourne la réflexion originale non modifiée.
    """
    for pattern in _API_ERROR_PATTERNS:
        match = _re.search(pattern, reflection)
        if match:
            groups = [g for g in match.groups() if g]
            lib_name = groups[0] if groups else None
            if not lib_name:
                continue
            try:
                from core.web_search import WebSearchEngine
                engine = WebSearchEngine()
                query  = f"{lib_name} python official documentation API"
                result = engine.search(query)
                if result.synthesis and len(result.synthesis) > 50:
                    doc_snippet = result.synthesis[:800]
                    return (
                        reflection
                        + f"\n\n## Documentation officielle : `{lib_name}`\n\n"
                        + doc_snippet
                        + "\n\nCorrige le code en utilisant la bonne API documentée ci-dessus."
                    )
            except Exception as exc:
                log.debug("[reviewer] doc enrichment failed: %s", exc)
            break  # ne tenter qu'une seule lib par réflexion

    return reflection
```

### Intégration dans `ReviewerAgent.run_task`

```python
def run_task(self, contract: TaskContract) -> AgentResult:
    ...
    if not review_passed:
        reflection = _build_reflection(code, syntax_errors)
        # V9-03-D : enrichir si erreur d'API détectée
        reflection = self._enrich_reflection_with_docs(reflection, code)
        return AgentResult(
            success=False,
            error="Reviewer: syntax or quality rejected",
            payload={"reflection": reflection},
        )
    ...
```
