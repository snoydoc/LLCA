# Sprint V9-03-BCD — Web Search Auto + HyDE + Doc Retrieval
<!-- AI-READY | LCCA V9 | Sprint V9-03-BCD | Priorité P1 | Effort 2j -->

## Objectif

Trois améliorations RAG groupées :
- **V9-03-B** : Web search auto dans ArchitectAgent (libs externes)
- **V9-03-C** : HyDE (Hypothetical Document Embedding) pour MemoryEngine
- **V9-03-D** : Enrichissement de réflexion ReviewerAgent avec doc officielle (lcca_failures en premier)

---

## V9-03-B — Web Search Auto dans ArchitectAgent

### Fichiers cibles

| # | Fichier | Opération |
|---|---------|-----------|
| 1 | `core/agents/architect_agent.py` | PATCH — `_detect_external_libs` + intégration |
| 2 | `tests/test_v8_03.py` | PATCH — 3 tests |

### Spécification

```python
# core/agents/architect_agent.py — constantes module-level

_LCCA_INTERNAL_KEYWORDS = frozenset({
    "transaction", "ast", "mcp", "sandbox", "memory", "spec", "orchestrator",
    "agent", "skill", "llm", "ollama", "chromadb", "libcst", "nlp",
    "patch", "commit", "rollback", "wal", "receipt", "bus",
    "lcca", "coder", "reviewer", "tester", "observer", "architect",
})


def _detect_external_libs(intent: str) -> list[str]:
    """
    Détecte les bibliothèques Python externes mentionnées dans l'intent.

    Heuristique :
    - Cherche les tokens snake_case/kebab-case (pattern lib Python)
    - Exclut les mots-clés LCCA internes
    - Retourne max 3 libs (pour ne pas surcharger la recherche web)

    Returns:
        list[str] — noms de libs candidates (peut être vide)
    """
    import re
    candidates = re.findall(r'\b([a-z][a-z0-9_-]{2,})\b', intent.lower())
    external = [
        c for c in candidates
        if c not in _LCCA_INTERNAL_KEYWORDS
        and not any(kw in c for kw in _LCCA_INTERNAL_KEYWORDS)
        and len(c) > 3
    ]
    seen, result = set(), []
    for e in external:
        if e not in seen:
            seen.add(e); result.append(e)
    return result[:3]
```

Intégration dans `ArchitectAgent.run_task` (après décomposition des sous-contrats) :

```python
# V9-03-B : enrichissement web si lib externe détectée
web_context = ""
if getattr(config, "ARCHITECT_WEB_SEARCH_ENABLED", True):
    external_libs = _detect_external_libs(contract.intent)
    if external_libs:
        try:
            from core.web_search import WebSearchEngine
            query  = f"{external_libs[0]} python usage examples 2025"
            result = WebSearchEngine().search(query)
            if result.synthesis and len(result.synthesis) > 50:
                web_context = (
                    f"## Documentation web : `{external_libs[0]}`\n\n"
                    + result.synthesis[:1500]
                )
                log.info("[architect] web context fetched lib=%s", external_libs[0])
        except Exception as exc:
            log.debug("[architect] web_search: %s", exc)

for sub in sub_contracts:
    if web_context:
        sub.context["web_documentation"] = web_context
```

### Tests

```python
class TestDetectExternalLibs:
    def test_known_lib_detected(self):
        result = _detect_external_libs("intègre httpx pour les requêtes HTTP")
        assert "httpx" in result

    def test_lcca_internal_excluded(self):
        result = _detect_external_libs("fix bug in transaction_manager commit patch")
        assert result == []

    def test_max_3_libs(self):
        result = _detect_external_libs("utilise pydantic fastapi sqlalchemy boto3 redis")
        assert len(result) <= 3
```

---

## V9-03-C — HyDE (Hypothetical Document Embedding)

### Fichiers cibles

| # | Fichier | Opération |
|---|---------|-----------|
| 1 | `core/memory_engine.py` | PATCH — `search_hyde(query, wing, n, generator)` |
| 2 | `tests/test_memory_engine.py` | PATCH — 2 tests |

### Spécification `MemoryEngine.search_hyde`

**Règle critique** : `generator` est **toujours fourni par l'appelant**. Jamais instancié en interne.

```python
_HYDE_SYSTEM = (
    "Tu es un expert en architecture LCCA. "
    "Génère un court extrait de documentation (100-150 mots) décrivant idéalement "
    "la solution ou le module répondant à cette requête. "
    "Écris directement le document, sans introduction."
)

def search_hyde(
    self,
    query     : str,
    wing      : str = "lcca",
    n         : int = 5,
    generator        = None,    # LLMGenerator fourni par l'appelant
) -> dict:
    """
    Variante HyDE de search() :
    1. Si MEMORY_HYDE_ENABLED=False ou generator=None → fallback search() standard
    2. Génère un document hypothétique via generator.generate_text()
    3. Utilise ce document comme vecteur de recherche ChromaDB

    Note : jamais d'instanciation LLMGenerator interne (coût + risque RAM)
    """
    import config
    if not getattr(config, "MEMORY_HYDE_ENABLED", False):
        return self.search(query, wing, n)
    if not self._available:
        return self.search(query, wing, n)
    if generator is None:
        log.debug("HyDE: aucun générateur fourni → fallback standard")
        return self.search(query, wing, n)

    try:
        hyde_doc = generator.generate_text(_HYDE_SYSTEM, f"Requête : {query}")
        if not isinstance(hyde_doc, str) or len(hyde_doc) < 20:
            log.debug("HyDE: document hypothétique vide → fallback")
            return self.search(query, wing, n)
        log.debug("HyDE: document généré %d chars", len(hyde_doc))
    except Exception as exc:
        log.debug("HyDE: erreur génération (%s) → fallback", exc)
        return self.search(query, wing, n)

    return self.search(hyde_doc, wing, n)
```

### Tests

```python
class TestSearchHyde:
    def test_disabled_by_default_uses_standard_search(self, monkeypatch, mocker):
        import config
        monkeypatch.setattr(config, "MEMORY_HYDE_ENABLED", False)
        from core.memory_engine import MemoryEngine
        engine = MemoryEngine()
        spy = mocker.spy(engine, "search")
        engine.search_hyde("test query", generator=MagicMock())
        spy.assert_called_once()

    def test_no_generator_fallback_silent(self, monkeypatch, mocker):
        import config
        monkeypatch.setattr(config, "MEMORY_HYDE_ENABLED", True)
        from core.memory_engine import MemoryEngine
        engine = MemoryEngine()
        spy = mocker.spy(engine, "search")
        engine.search_hyde("test query", generator=None)   # Pas de LLMGenerator interne
        spy.assert_called_once()
```

---

## V9-03-D — Doc Retrieval sur Erreur d'API dans ReviewerAgent

### Fichiers cibles

| # | Fichier | Opération |
|---|---------|-----------|
| 1 | `core/agents/reviewer_agent.py` | PATCH — `_enrich_reflection_with_docs` + intégration |
| 2 | `tests/test_reviewer_agent.py` | PATCH — 3 tests |

### Spécification

```python
# core/agents/reviewer_agent.py — constantes module-level

_API_ERROR_PATTERNS = [
    r"AttributeError: (?:module '(\w+)'|'(\w+)' object) has no attribute '(\w+)'",
    r"TypeError: (\w+)\(\) got an unexpected keyword argument '(\w+)'",
    r"ImportError: cannot import name '(\w+)' from '(\w+)'",
    r"ModuleNotFoundError: No module named '(\w+)'",
]


def _enrich_reflection_with_docs(reflection: str, code: str) -> str:
    """
    Si la réflexion contient une erreur d'API connue, enrichit avec de la documentation.

    Stratégie :
    1. Chercher d'abord dans lcca_failures (ChromaDB, < 100ms)
    2. Si rien trouvé, chercher sur le web (WebSearchEngine)

    Toujours silencieux — retourne reflection originale en cas d'erreur.
    """
    import re
    for pattern in _API_ERROR_PATTERNS:
        match = re.search(pattern, reflection)
        if match:
            lib_name = next((g for g in match.groups() if g), None)
            if not lib_name:
                continue

            # 1. Recherche locale dans lcca_failures
            try:
                from core.memory_engine import MemoryEngine
                results = MemoryEngine().search(f"{lib_name} error", n=3)
                failures = results.get("failures", [])
                if failures:
                    doc = failures[0].content[:600] if hasattr(failures[0], "content") else ""
                    if doc:
                        return (
                            reflection
                            + f"\n\n## Erreur similaire dans lcca_failures : `{lib_name}`\n\n"
                            + doc
                        )
            except Exception:
                pass

            # 2. Fallback web
            try:
                from core.web_search import WebSearchEngine
                result = WebSearchEngine().search(
                    f"{lib_name} python official documentation API"
                )
                if result.synthesis and len(result.synthesis) > 50:
                    return (
                        reflection
                        + f"\n\n## Documentation officielle : `{lib_name}`\n\n"
                        + result.synthesis[:800]
                        + "\n\nCorrige le code en utilisant la bonne API."
                    )
            except Exception as exc:
                log.debug("[reviewer] doc enrichment web failed: %s", exc)
            break   # Une seule lib traitée par réflexion

    return reflection
```

Intégration dans `ReviewerAgent.run_task` :

```python
# Dans le bloc de rejet (review_passed = False) :
reflection = _build_reflection(code, syntax_errors)
reflection = _enrich_reflection_with_docs(reflection, code)   # V9-03-D
return AgentResult(
    success=False,
    error="Reviewer: rejected",
    payload={"reflection": reflection},
)
```

### Tests

```python
class TestEnrichReflectionWithDocs:
    def test_no_api_error_returns_original(self):
        reflection = "Code looks good overall"
        result = _enrich_reflection_with_docs(reflection, "def f(): pass")
        assert result == reflection

    def test_module_not_found_triggers_enrichment(self, mocker):
        reflection = "ModuleNotFoundError: No module named 'httpx'"
        mocker.patch("core.agents.reviewer_agent.MemoryEngine", side_effect=Exception)
        web_result = MagicMock()
        web_result.synthesis = "httpx is a modern HTTP client library"
        mocker.patch("core.agents.reviewer_agent.WebSearchEngine.search",
                     return_value=web_result)
        result = _enrich_reflection_with_docs(reflection, "import httpx")
        assert "httpx" in result
        assert len(result) > len(reflection)

    def test_silent_on_all_failures(self, mocker):
        reflection = "ModuleNotFoundError: No module named 'somelib'"
        mocker.patch("core.agents.reviewer_agent.MemoryEngine", side_effect=Exception)
        mocker.patch("core.agents.reviewer_agent.WebSearchEngine",
                     side_effect=Exception)
        result = _enrich_reflection_with_docs(reflection, "")
        assert result == reflection   # Pas de crash, retour original
```

---

## Critères d'acceptation globaux V9-03-BCD

### V9-03-B
- [ ] `_detect_external_libs("intègre httpx")` → `["httpx"]`
- [ ] `_detect_external_libs("fix transaction commit")` → `[]`
- [ ] `_detect_external_libs("pydantic fastapi sqlalchemy boto3 redis")` → max 3 éléments
- [ ] Intégration ArchitectAgent : `sub.context["web_documentation"]` renseigné si lib détectée
- [ ] Erreur WebSearchEngine → silencieux (log.debug)

### V9-03-C
- [ ] `MEMORY_HYDE_ENABLED=False` → `search_hyde()` = `search()` standard
- [ ] `generator=None` → fallback silencieux (pas de LLMGenerator instancié)
- [ ] Document hypothétique vide → fallback silencieux
- [ ] Erreur `generate_text()` → fallback silencieux

### V9-03-D
- [ ] Pas d'erreur d'API dans reflection → reflection inchangée
- [ ] `ModuleNotFoundError: 'httpx'` → enrichissement avec doc (locale ou web)
- [ ] Erreur MemoryEngine + erreur WebSearch → reflection originale retournée

## Protocole d'exécution

```
# V9-03-B
1. filesystem:read_text_file core/agents/architect_agent.py  → repérer run_task + imports
2. filesystem:edit_file core/agents/architect_agent.py       → ajouter _LCCA_INTERNAL_KEYWORDS + _detect_external_libs
3. filesystem:edit_file core/agents/architect_agent.py       → intégration web search dans run_task
4. filesystem:edit_file tests/test_v8_03.py                  → ajouter TestDetectExternalLibs

# V9-03-C
5. filesystem:read_text_file core/memory_engine.py           → repérer search() + _available
6. filesystem:edit_file core/memory_engine.py                → ajouter _HYDE_SYSTEM + search_hyde()
7. filesystem:edit_file tests/test_memory_engine.py          → ajouter TestSearchHyde

# V9-03-D
8. filesystem:read_text_file core/agents/reviewer_agent.py   → repérer run_task + _build_reflection
9. filesystem:edit_file core/agents/reviewer_agent.py        → ajouter _API_ERROR_PATTERNS + _enrich_reflection_with_docs
10. filesystem:edit_file core/agents/reviewer_agent.py       → intégration dans run_task
11. filesystem:edit_file tests/test_reviewer_agent.py        → ajouter TestEnrichReflectionWithDocs

# Validation
12. bash: python -c "from core.agents.architect_agent import _detect_external_libs; print('OK')"
13. bash: python -c "from core.memory_engine import MemoryEngine; print('OK')"
14. bash: python -c "from core.agents.reviewer_agent import _enrich_reflection_with_docs; print('OK')"
15. bash: python -m pytest tests/ -x -q
```

## Mise à jour skills

- **001** : patterns V9-03-B/C/D
- **004** : V9-03-BCD TERMINÉ
