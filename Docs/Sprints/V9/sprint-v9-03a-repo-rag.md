# Sprint V9-03-A — Repository-RAG dans CoderAgent (avec cache AST)
<!-- AI-READY | LCCA V9 | Sprint V9-03-A | Priorité P1 | Effort 1j -->

## Objectif

Injecter les fichiers LCCA les plus pertinents dans le contexte du CoderAgent avant
chaque génération, en utilisant un cache AST TTL 1h pour ne pas payer le coût
d'indexation à chaque itération KarpathyLoop.

**Problème résolu** : sans ce sprint, le CoderAgent ignore les 50+ modules existants
→ imports manquants, duplications, violations conventions.

## Prérequis

- V9-01-B terminé (pool LRU)
- V9-00 terminé (AST_INDEX_CACHE_TTL dans config)

## Fichiers cibles

| # | Fichier | Opération |
|---|---------|-----------|
| 1 | `core/agents/coder_agent.py` | PATCH — `_get_ast_index()` + `_retrieve_repo_context()` |
| 2 | `core/agents/coder_agent.py` | PATCH — intégration dans `run_task()` |
| 3 | `tests/test_coder_agent.py` | PATCH — 4 nouveaux tests |

## Spécification

### Constantes module-level (à ajouter avant la classe)

```python
# core/agents/coder_agent.py

_REPO_RAG_STOPWORDS = frozenset({
    # Anglais
    "the", "a", "an", "in", "of", "to", "for", "and", "or", "with",
    "create", "add", "implement", "module", "function", "class", "fix", "bug",
    # Français
    "crée", "ajoute", "implémente", "modifie", "dans", "pour", "avec", "une",
    "un", "le", "la", "les", "du", "des", "au", "aux",
})
```

### Méthodes à ajouter dans `CoderAgent`

```python
def __init__(self, ...):
    # ... existant ...
    self._ast_index_cache   : Optional[dict]  = None
    self._ast_index_cache_ts: float           = 0.0
    self._last_git_head     : Optional[str]   = None

def _get_ast_index(self) -> dict:
    """
    Retourne l'index AST du workspace, avec cache TTL.

    Cache invalide si :
    - Plus de AST_INDEX_CACHE_TTL secondes depuis le dernier index
    - Un nouveau commit git a eu lieu depuis le dernier index

    Silencieux : toute erreur retourne le cache existant ou {}.
    """
    import subprocess, time
    import config
    from core.ast_indexer import ASTIndexer

    ttl = getattr(config, "AST_INDEX_CACHE_TTL", 3600)

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True,
            cwd=str(config.WORKSPACE_DIR), timeout=5,
        )
        current_head = result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        current_head = None

    now = time.monotonic()
    cache_valid = (
        self._ast_index_cache is not None
        and (now - self._ast_index_cache_ts) < ttl
        and (current_head is None or current_head == self._last_git_head)
    )

    if cache_valid:
        return self._ast_index_cache

    try:
        log.debug("[coder] Reindexing workspace (cache miss)")
        self._ast_index_cache    = ASTIndexer(workspace=config.WORKSPACE_DIR).index_repository()
        self._ast_index_cache_ts = now
        self._last_git_head      = current_head
        log.debug("[coder] Index ready: %d files", len(self._ast_index_cache))
    except Exception as exc:
        log.debug("[coder] _get_ast_index error: %s", exc)
        self._ast_index_cache = self._ast_index_cache or {}

    return self._ast_index_cache


def _retrieve_repo_context(self, intent: str) -> str:
    """
    Construit un contexte de fichiers LCCA pertinents pour l'intent.

    Algorithme BM25 simplifié :
    1. Tokeniser l'intent (stopwords filtrés)
    2. Pour chaque fichier, scorer = nombre de tokens communs avec les noms de symboles
    3. Retenir REPO_RAG_MAX_FILES meilleurs fichiers
    4. Lire les REPO_RAG_MAX_LINES premières lignes de chaque fichier

    Returns:
        str — contexte formaté, "" si aucun résultat ou erreur.
    """
    import config
    from pathlib import Path

    max_files = getattr(config, "REPO_RAG_MAX_FILES", 5)
    max_lines = getattr(config, "REPO_RAG_MAX_LINES", 80)

    try:
        tokens = {
            w.lower() for w in intent.split()
            if w.lower() not in _REPO_RAG_STOPWORDS and len(w) > 2
        }
        if not tokens:
            return ""

        index = self._get_ast_index()
        if not index:
            return ""

        scores: dict[str, int] = {}
        for filepath, symbols in index.items():
            file_tokens: set[str] = set()
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
                content = Path(fp).read_text(encoding="utf-8-sig", errors="replace")
                lines   = content.splitlines()[:max_lines]
                parts.append(
                    f"### `{Path(fp).name}` (score={scores[fp]})\n"
                    f"```python\n" + "\n".join(lines) + "\n```\n"
                )
            except Exception:
                continue

        return "\n".join(parts)

    except Exception as exc:
        log.debug("[coder] _retrieve_repo_context error: %s", exc)
        return ""
```

### Intégration dans `CoderAgent.run_task`

```python
def run_task(self, contract: TaskContract) -> AgentResult:
    ...
    file_context  = ...   # lecture du fichier cible existante
    repo_context  = self._retrieve_repo_context(contract.intent)   # V9-03-A
    skill_context = contract.context.get("available_skills", "")

    combined_context = file_context
    if repo_context:
        combined_context += "\n\n" + repo_context

    result = self._generator.generate(
        op=patch,
        intent=intent,
        context=combined_context,      # V9-03-A
        skill_context=skill_context,
    )
    ...
```

## Tests `class TestRepoBMRetrieval`

```python
class TestRepoBMRetrieval:
    def test_returns_empty_on_empty_intent(self):
        bus   = A2ALocalBus(":memory:")
        agent = CoderAgent.create(bus=bus)
        result = agent._retrieve_repo_context("")
        assert result == ""

    def test_returns_empty_on_stopwords_only(self):
        bus   = A2ALocalBus(":memory:")
        agent = CoderAgent.create(bus=bus)
        # Intent avec uniquement des stopwords
        result = agent._retrieve_repo_context("crée un module pour la fonction")
        assert result == ""

    def test_returns_context_for_known_symbol(self, tmp_path, mocker):
        """Intent mentionnant 'transaction_manager' → fichier correspondant remonté."""
        bus   = A2ALocalBus(":memory:")
        agent = CoderAgent.create(bus=bus)
        (tmp_path / "transaction_manager.py").write_text(
            "# tm\ndef commit(): pass", encoding="utf-8"
        )
        mocker.patch.object(
            agent, "_get_ast_index",
            return_value={
                str(tmp_path / "transaction_manager.py"): [
                    {"name": "commit_transaction", "type": "function"}
                ]
            }
        )
        result = agent._retrieve_repo_context("fix bug in transaction_manager commit")
        assert "transaction_manager" in result

    def test_silent_on_indexer_error(self, mocker):
        """Erreur dans _get_ast_index → '' silencieux."""
        bus   = A2ALocalBus(":memory:")
        agent = CoderAgent.create(bus=bus)
        mocker.patch.object(agent, "_get_ast_index", side_effect=RuntimeError("disk"))
        result = agent._retrieve_repo_context("fix transaction_manager")
        assert result == ""

    def test_cache_returns_same_object_within_ttl(self, monkeypatch, mocker):
        """Deux appels rapides → même objet cache retourné."""
        import config
        monkeypatch.setattr(config, "AST_INDEX_CACHE_TTL", 3600)
        bus   = A2ALocalBus(":memory:")
        agent = CoderAgent.create(bus=bus)
        fake_index = {"file.py": [{"name": "foo", "type": "function"}]}
        mock_indexer = mocker.patch("core.agents.coder_agent.ASTIndexer")
        mock_indexer.return_value.index_repository.return_value = fake_index

        idx1 = agent._get_ast_index()
        idx2 = agent._get_ast_index()
        assert idx1 is idx2
        assert mock_indexer.return_value.index_repository.call_count == 1
```

## Critères d'acceptation

- [ ] `_retrieve_repo_context("")` retourne `""`
- [ ] `_retrieve_repo_context("crée un module")` retourne `""` (stopwords only)
- [ ] Intent mentionnant un symbole existant → retourne un contexte non vide
- [ ] `_get_ast_index()` appelé 1 seule fois dans TTL (cache efficace)
- [ ] Erreur indexer → `""` silencieux
- [ ] `run_task()` passe le repo context dans le `context` de `generate()`
- [ ] 0 régression tests V8

## Protocole d'exécution

```
1. filesystem:read_text_file core/agents/coder_agent.py  → lire __init__ + run_task
2. filesystem:edit_file core/agents/coder_agent.py       → ajouter _REPO_RAG_STOPWORDS (module-level)
3. filesystem:edit_file core/agents/coder_agent.py       → ajouter cache attrs dans __init__
4. filesystem:edit_file core/agents/coder_agent.py       → ajouter _get_ast_index()
5. filesystem:edit_file core/agents/coder_agent.py       → ajouter _retrieve_repo_context()
6. filesystem:edit_file core/agents/coder_agent.py       → intégration dans run_task()
7. filesystem:read_text_file tests/test_coder_agent.py   → repérer fin du fichier
8. filesystem:edit_file tests/test_coder_agent.py        → ajouter TestRepoBMRetrieval
9. bash: python -c "from core.agents.coder_agent import CoderAgent; print('OK')"
10. bash: python -m pytest tests/test_coder_agent.py -v -k "TestRepoBM"
11. bash: python -m pytest tests/ -x -q
```

## ⚠️ Points d'attention

- `subprocess.run(["git", "rev-parse", "HEAD"])` → peut échouer si pas de repo git
  → `try/except Exception`, `current_head = None` dans le except
- `ASTIndexer` peut être lent (> 2s sur 50 fichiers) → c'est la raison du cache
- `_get_ast_index` est une méthode d'instance (self) → les attrs `_ast_index_cache`,
  `_ast_index_cache_ts`, `_last_git_head` doivent être initialisés dans `__init__`
- Ne pas modifier `create()` classmethod — initialisation dans `__init__` uniquement

## Mise à jour skills

- **001** : pattern "V9-03-A — _get_ast_index cache TTL + _retrieve_repo_context BM25"
- **003** : `core/agents/coder_agent.py` mis à jour (attrs cache + méthodes RAG)
- **004** : V9-03-A TERMINÉ
