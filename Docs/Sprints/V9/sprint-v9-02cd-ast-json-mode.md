# Sprint V9-02-CD — AST Context SpecGenerator + JSON Mode Ollama
<!-- AI-READY | LCCA V9 | Sprint V9-02-CD | Priorité P1 | Effort 1j -->

## Objectif

Deux améliorations de qualité indépendantes groupées dans un même sprint :
- **V9-02-C** : Injecter les signatures AST réelles dans `SpecGenerator` (specs ancrées)
- **V9-02-D** : Forcer `"format": "json"` pour les patterns structurés (validation plus fiable)

## Fichiers cibles

| # | Fichier | Opération |
|---|---------|-----------|
| 1 | `core/spec_generator.py` | PATCH — `_build_ast_context(query)` + intégration |
| 2 | `core/llm_generator.py` | PATCH — `OllamaClient.generate()` param `response_format` |
| 3 | `core/cognitive_patterns.py` | PATCH — `SpecValidatorPattern.run()` passe `response_format="json"` |
| 4 | `tests/test_spec_layer.py` | PATCH — 2+1 tests |

---

## V9-02-C : AST Context dans SpecGenerator

### Spécification `SpecGeneratorService._build_ast_context`

```python
def _build_ast_context(self, query: str) -> str:
    """
    Construit un contexte de signatures AST filtré par pertinence pour la query.

    Algorithme :
    1. Indexer le workspace via self._indexer.index_repository()
    2. Pour chaque symbole, scorer = nb de mots de la query présents dans nom/fichier
    3. Retenir les SPEC_AST_MAX_SYMBOLS meilleures entrées
    4. Formater en blocs ```python avec signature

    Returns:
        str — contexte formaté, "" si aucun résultat ou erreur.
    """
    import config
    max_symbols = getattr(config, "SPEC_AST_MAX_SYMBOLS", 20)
    query_words = set(query.lower().split())

    try:
        index = self._indexer.index_repository()
    except Exception as exc:
        log.debug("_build_ast_context: indexer error %s", exc)
        return ""

    relevant: list[dict] = []
    for file_path, symbols in index.items():
        fp_lower = file_path.lower()
        for sym in symbols:
            name_lower = sym.get("name", "").lower()
            score = sum(1 for w in query_words if w in name_lower or w in fp_lower)
            if score > 0:
                relevant.append({**sym, "_score": score, "_file": file_path})

    relevant.sort(key=lambda s: s["_score"], reverse=True)
    top = relevant[:max_symbols]

    if not top:
        return ""

    lines = ["## Symboles LCCA pertinents (index AST)\n"]
    for sym in top:
        kind = sym.get("type", "function")
        name = sym.get("name", "?")
        sig  = sym.get("signature", f"def {name}(...)")
        src  = sym.get("_file", "?")
        from pathlib import Path
        lines.append(
            f"### `{name}` ({kind}) — `{Path(src).name}`\n"
            f"```python\n{sig}\n```\n"
        )

    return "\n".join(lines)
```

### Intégration dans `SpecGeneratorService.generate`

Localiser la construction de `spec_context` (ou `_build_technical_context`) et ajouter :

```python
tech_context = self._build_technical_context()
ast_context  = self._build_ast_context(intent)        # V9-02-C
spec_context = "\n\n".join(filter(None, [tech_context, ast_context, rag_context]))
body_md = self._direct_pattern.run(intent, context=spec_context)
```

### Tests V9-02-C

```python
class TestASTContext:
    def test_returns_empty_on_empty_index(self, mocker):
        from core.spec_generator import SpecGeneratorService
        svc = SpecGeneratorService.__new__(SpecGeneratorService)
        svc._indexer = MagicMock()
        svc._indexer.index_repository.return_value = {}
        result = svc._build_ast_context("transaction rollback")
        assert result == ""

    def test_returns_relevant_symbols(self, mocker):
        from core.spec_generator import SpecGeneratorService
        svc = SpecGeneratorService.__new__(SpecGeneratorService)
        svc._indexer = MagicMock()
        svc._indexer.index_repository.return_value = {
            "core/transaction_manager.py": [
                {"name": "commit_transaction", "type": "function",
                 "signature": "def commit_transaction(tx_id: str) -> bool"}
            ]
        }
        result = svc._build_ast_context("transaction commit")
        assert "commit_transaction" in result
        assert "```python" in result
```

---

## V9-02-D : JSON Mode Ollama

### Spécification `OllamaClient.generate` — param `response_format`

```python
def generate(
    self,
    system          : str,
    user            : str,
    response_format : "str | None" = None,   # V9-02-D : "json" | None
) -> str:
    url    = f"{self.base_url}/api/generate"
    prompt = f"{system}\n\nUtilisateur: {user}\nAssistant:"
    payload: dict = {
        "model":      self.model,
        "prompt":     prompt,
        "stream":     True,
        "keep_alive": self.keep_alive,
        "options": {
            "num_predict": self.max_tokens,
            "num_thread":  getattr(config, "OLLAMA_THREADS", 4),
        },
    }
    if response_format == "json":
        payload["format"] = "json"   # V9-02-D — Ollama >= 0.1.14
    # ... reste inchangé ...
```

### Spécification `SpecValidatorPattern.run` — utilise JSON mode

```python
class SpecValidatorPattern(CognitivePattern):
    def run(self, prompt: str, context: str = "") -> str:
        user = "Spec à valider :\n" + prompt
        ollama = getattr(self._generator, "ollama", None)
        if ollama is not None and callable(getattr(ollama, "generate", None)):
            try:
                # V9-02-D : JSON mode pour garantir un retour parseable
                result = ollama.generate(self._SYSTEM, user, response_format="json")
                return result if isinstance(result, str) else ""
            except Exception:
                pass
        return self._call_llm(self._SYSTEM, user)
```

### Test V9-02-D

```python
class TestJsonMode:
    def test_response_format_json_in_payload(self, mocker):
        from core.llm_generator import OllamaClient
        import json
        client = OllamaClient("http://localhost:11434", "qwen", 60, 512, keep_alive="5m")
        mock_urlopen = mocker.patch("urllib.request.urlopen")
        # ... setup mock ...
        client.generate("sys", "user", response_format="json")
        body = json.loads(mock_urlopen.call_args[0][0].data)
        assert body.get("format") == "json"
```

## Critères d'acceptation

### V9-02-C
- [ ] `_build_ast_context("")` retourne `""`
- [ ] `_build_ast_context("transaction")` retourne string contenant "```python"
  (si indexer retourne des symboles avec "transaction" dans le nom)
- [ ] `_build_ast_context("xyz_inexistant")` retourne `""`
- [ ] Erreur de l'indexer → retourne `""` silencieusement
- [ ] Intégration dans `generate()` : `ast_context` concaténé avec `tech_context`

### V9-02-D
- [ ] `OllamaClient.generate("s", "u", response_format="json")` → payload contient `"format": "json"`
- [ ] `OllamaClient.generate("s", "u")` → payload N'a PAS `"format"`
- [ ] `SpecValidatorPattern.run()` passe `response_format="json"` à Ollama

## Protocole d'exécution

```
1. filesystem:read_text_file core/spec_generator.py     → repérer generate() + _build_technical_context
2. filesystem:edit_file core/spec_generator.py          → ajouter _build_ast_context
3. filesystem:edit_file core/spec_generator.py          → intégration dans generate()
4. filesystem:read_text_file core/llm_generator.py      → repérer OllamaClient.generate()
5. filesystem:edit_file core/llm_generator.py           → ajouter response_format param
6. filesystem:read_text_file core/cognitive_patterns.py → repérer SpecValidatorPattern
7. filesystem:edit_file core/cognitive_patterns.py      → passer response_format="json"
8. filesystem:edit_file tests/test_spec_layer.py        → ajouter TestASTContext + TestJsonMode
9. bash: python -c "from core.spec_generator import SpecGeneratorService; print('OK')"
10. bash: python -m pytest tests/test_spec_layer.py -v -k "TestAST or TestJson"
11. bash: python -m pytest tests/ -x -q
```

## Mise à jour skills

- **001** : patterns "V9-02-C — _build_ast_context BM25" + "V9-02-D — response_format='json' Ollama"
- **004** : V9-02-CD TERMINÉ
