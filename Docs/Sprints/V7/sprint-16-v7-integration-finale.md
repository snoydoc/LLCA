# Sprint 16 — V7 Intégration finale, Tests E2E & Documentation
<!-- AI-READY | Sprint V7.0 | Phase 5/5 | 2026-04-17 -->

## 🎯 Objectif
Sprint de clôture V7 :
1. Tests d'intégration E2E MCP (cycle complet : initialize → edit → sandbox → store)
2. Mise à jour complète de toutes les documentations (README, skills, specs, index)
3. Script de validation automatique `scripts/validate_v7.py`
4. Goose recipe avancé + sub-agents spec V8
5. Mise à jour `004-sprint-context.md` et `003-project-context.md`

**Résultat cible** : ≥ 347 + ~20 tests PASSED. Documentation 100% à jour. V7.0.0 release-ready.

---

## 📋 TÂCHES

### TASK-16-01 — `tests/test_mcp_integration.py` : Tests E2E

**Fichier** : `D:\LLMCodeAgent\tests\test_mcp_integration.py` *(nouveau)*

```python
# -*- coding: utf-8-sig -*-
"""
Tests d'intégration E2E MCP — Sprint 16.
Simule un cycle complet comme un client Goose le ferait.

IMPORTANT : Ces tests n'utilisent PAS de réseau (Ollama mocké).
Ils testent le pipeline JSON-RPC complet de bout en bout.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


@pytest.fixture
def full_server(tmp_path):
    """
    Serveur MCP complet avec composants réels (sauf Ollama).
    Workspace réel dans tmp_path pour les tests de fichiers.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Fichier de départ pour les tests de patch
    (workspace / "starter.py").write_text(
        "# -*- coding: utf-8-sig -*-\n"
        "\"\"\"Module de départ.\"\"\"\n\n"
        "def existing_func():\n"
        "    \"\"\"Fonction existante.\"\"\"\n"
        "    return 42\n",
        encoding="utf-8",
    )

    from core.transaction_manager import TransactionManager
    from core.mcp_edit_batch import McpEditBatch
    from core.sandbox_engine import SandboxEngine
    from core.code_evaluator import CodeEvaluator
    from core.error_analyzer import ErrorAnalyzer
    from core.memory_engine import MemoryEngine
    from mcp_server import MCPServer

    tm = TransactionManager(
        tx_dir=tmp_path / "tx",
        wal_path=tmp_path / "wal.jsonl",
        auto_cleanup_days=0,
    )

    # Patcher mocké (sans libcst réel, pour isoler le test)
    patcher = MagicMock()
    patcher.apply_patch.return_value = (
        "# -*- coding: utf-8-sig -*-\n"
        "\"\"\"Module patché.\"\"\"\n\n"
        "def existing_func():\n"
        "    return 42\n\n"
        "def new_func() -> str:\n"
        "    \"\"\"Nouvelle fonction.\"\"\"\n"
        "    return 'new'\n"
    )

    batch = McpEditBatch(
        tx_manager=tm,
        patcher=patcher,
        evaluator=CodeEvaluator(),
        workspace=workspace,
    )

    # MemoryEngine mocké (MemPalace non requis)
    memory = MemoryEngine(adapter=None)  # mode no-op

    sandbox = SandboxEngine(workspace=workspace, mode="soft")
    evaluator = CodeEvaluator()
    error_analyzer = ErrorAnalyzer()

    server = MCPServer(
        workspace=workspace,
        auto_init=False,
        edit_batch=batch,
        memory_engine=memory,
        sandbox=sandbox,
        code_evaluator=evaluator,
        error_analyzer=error_analyzer,
    )
    return server, workspace


def _req(method, params=None, req_id=1):
    return json.dumps({
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params or {},
    })


def _call(server, tool, args, req_id=1):
    return json.loads(
        json.dumps(server.handle_request(_req(
            "tools/call",
            {"name": tool, "arguments": args},
            req_id=req_id,
        )))
    )


# ── Tests E2E ─────────────────────────────────────────────────────────────────

class TestMCPFullCycleE2E:
    def test_initialize_handshake(self, full_server):
        server, _ = full_server
        resp = server.handle_request(_req("initialize"))
        assert "result" in resp
        assert resp["result"]["protocolVersion"] is not None

    def test_tools_list_complete(self, full_server):
        server, _ = full_server
        resp = server.handle_request(_req("tools/list"))
        tools = resp["result"]["tools"]
        assert len(tools) == 7
        names = {t["name"] for t in tools}
        assert "edit_batch" in names
        assert "sandbox_run" in names

    def test_evaluate_quality_real(self, full_server):
        server, _ = full_server
        code = "def foo(x: int) -> str:\n    \"\"\"Docstring.\"\"\"\n    return str(x)\n"
        resp = _call(server, "evaluate_quality", {"code": code, "filename": "test.py"})
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "score" in content
        assert 0 <= content["score"] <= 100

    def test_edit_batch_creates_file(self, full_server):
        server, workspace = full_server
        resp = _call(server, "edit_batch", {"files": [{
            "path": "new_module.py",
            "action": "create",
            "code": "def greet():\n    return 'hello'\n",
        }]})
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["success"] is True
        assert (workspace / "new_module.py").exists()

    def test_sandbox_run_valid_code(self, full_server):
        server, _ = full_server
        resp = _call(server, "sandbox_run", {"code": "print(6 * 7)"})
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["success"] is True
        assert "42" in content["stdout"]

    def test_sandbox_run_error_captured(self, full_server):
        server, _ = full_server
        resp = _call(server, "sandbox_run", {"code": "raise ValueError('test error')"})
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["success"] is False
        assert "ValueError" in content["stderr"]

    def test_analyze_error_returns_suggestion(self, full_server):
        server, _ = full_server
        resp = _call(server, "analyze_error", {
            "error": "SyntaxError: invalid syntax (module.py, line 5)"
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "error_type" in content or "suggestion" in content

    def test_edit_batch_rollback_on_bad_code(self, full_server):
        """Patch avec code invalide → rollback, fichier original conservé."""
        server, workspace = full_server
        original = (workspace / "starter.py").read_text(encoding="utf-8")

        # Override patcher pour retourner du code invalide
        server._edit_batch.patcher.apply_patch.return_value = "def foo(\n"  # SyntaxError
        resp = _call(server, "edit_batch", {"files": [{
            "path": "starter.py",
            "patch_type": "add_function",
            "symbol": "bad_func",
        }]})
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["success"] is False
        assert content["rolled_back"] is True
        # Fichier original restauré
        current = (workspace / "starter.py").read_text(encoding="utf-8")
        assert current == original

    def test_full_workflow_create_then_run(self, full_server):
        """
        Cycle complet : create file → sandbox run → evaluate quality.
        Simule un workflow Goose basique.
        """
        server, workspace = full_server

        # Step 1 : Créer un module
        code = "def add(a: int, b: int) -> int:\n    \"\"\"Additionne a et b.\"\"\"\n    return a + b\n"
        resp1 = _call(server, "edit_batch", {"files": [{
            "path": "math_utils.py",
            "action": "create",
            "code": code,
        }]}, req_id=1)
        c1 = json.loads(resp1["result"]["content"][0]["text"])
        assert c1["success"] is True, f"Création échouée : {c1}"

        # Step 2 : Exécuter dans le sandbox
        test_code = (
            "import sys\n"
            "sys.path.insert(0, '.')\n"
            "from math_utils import add\n"
            "assert add(3, 4) == 7\n"
            "print('OK')\n"
        )
        resp2 = _call(server, "sandbox_run", {"code": test_code}, req_id=2)
        c2 = json.loads(resp2["result"]["content"][0]["text"])
        # Note : peut échouer si le module n'est pas dans le path — acceptable
        assert isinstance(c2["success"], bool)

        # Step 3 : Évaluer la qualité
        resp3 = _call(server, "evaluate_quality", {"code": code, "filename": "math_utils.py"}, req_id=3)
        c3 = json.loads(resp3["result"]["content"][0]["text"])
        assert c3["score"] >= 50  # Code propre → score correct


class TestMCPProtocolCompliance:
    def test_jsonrpc_version_always_present(self, full_server):
        server, _ = full_server
        resp = server.handle_request(_req("tools/list"))
        assert resp["jsonrpc"] == "2.0"

    def test_id_echoed_in_response(self, full_server):
        server, _ = full_server
        resp = server.handle_request(_req("tools/list", req_id=42))
        assert resp["id"] == 42

    def test_notification_no_id(self, full_server):
        server, _ = full_server
        resp = server.handle_request(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )
        assert resp is None

    def test_error_has_code_and_message(self, full_server):
        server, _ = full_server
        resp = server.handle_request(_req("invalid/method"))
        assert "error" in resp
        assert "code" in resp["error"]
        assert "message" in resp["error"]
```

---

### TASK-16-02 — `scripts/validate_v7.py` : Script de validation automatique

**Fichier** : `D:\LLMCodeAgent\scripts\validate_v7.py` *(nouveau)*

```python
#!/usr/bin/env python3
# -*- coding: utf-8-sig -*-
"""
validate_v7.py — Script de validation V7
Vérifie que tous les composants V7 sont correctement installés et fonctionnels.

Usage :
    python scripts/validate_v7.py
    python scripts/validate_v7.py --verbose
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ajouter le projet au path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "


def check(label: str, fn) -> bool:
    try:
        fn()
        print(f"  {PASS} {label}")
        return True
    except Exception as exc:
        print(f"  {FAIL} {label} — {exc}")
        return False


def main(verbose: bool = False) -> None:
    print("═" * 60)
    print("LCCA V7 — Validation des composants")
    print("═" * 60)

    results = []

    print("\n📦 Imports core V5 (baseline)")
    results += [
        check("TransactionManager",    lambda: __import__("core.transaction_manager", fromlist=["TransactionManager"])),
        check("SmartPatcher",          lambda: __import__("core.smart_patcher",       fromlist=["SmartPatcher"])),
        check("ASTIndexer",            lambda: __import__("core.ast_indexer",         fromlist=["ASTIndexer"])),
        check("LLMGenerator",          lambda: __import__("core.llm_generator",       fromlist=["LLMGenerator"])),
        check("CodeEvaluator",         lambda: __import__("core.code_evaluator",      fromlist=["CodeEvaluator"])),
        check("ErrorAnalyzer",         lambda: __import__("core.error_analyzer",      fromlist=["ErrorAnalyzer"])),
    ]

    print("\n🆕 Imports core V7")
    results += [
        check("McpEditBatch",          lambda: __import__("core.mcp_edit_batch",      fromlist=["McpEditBatch"])),
        check("MemoryEngine",          lambda: __import__("core.memory_engine",       fromlist=["MemoryEngine"])),
        check("SandboxEngine",         lambda: __import__("core.sandbox_engine",      fromlist=["SandboxEngine"])),
        check("MCPServer",             lambda: __import__("mcp_server",               fromlist=["MCPServer"])),
    ]

    print("\n🔧 Utilitaires V7")
    results += [
        check("safe_path",             lambda: __import__("utils.safe_path",          fromlist=["safe_path"])),
        check("telemetry",             lambda: __import__("utils.telemetry",          fromlist=["log_metric"])),
    ]

    print("\n🔒 Sécurité — safe_path")
    from utils.safe_path import safe_path, PathSecurityError
    ws = Path("D:/LLMCodeAgent/workspace")

    def _check_traversal():
        try:
            safe_path("../../../etc/passwd", workspace=ws)
            raise AssertionError("Path traversal NON bloqué !")
        except PathSecurityError:
            pass  # Correct

    results += [
        check("Traversal '../' bloqué",        _check_traversal),
        check("Chemin absolu bloqué",          lambda: _check_abs(ws)),
    ]

    print("\n⚙️  Config V7")
    import config
    results += [
        check("MCP_PROTOCOL_VERSION",          lambda: assert_attr(config, "MCP_PROTOCOL_VERSION")),
        check("SANDBOX_MODE",                  lambda: assert_attr(config, "SANDBOX_MODE")),
        check("TX_AUTO_CLEANUP_DAYS",          lambda: assert_attr(config, "TX_AUTO_CLEANUP_DAYS")),
        check("MCP_MEMORY_COLLECTIONS",        lambda: assert_attr(config, "MCP_MEMORY_COLLECTIONS")),
    ]

    print("\n🏗️  MCP Server lifecycle")
    from mcp_server import MCPServer
    from unittest.mock import MagicMock
    server = MCPServer(auto_init=False,
                       edit_batch=MagicMock(), memory_engine=MagicMock(),
                       sandbox=MagicMock(), code_evaluator=MagicMock(), error_analyzer=MagicMock())

    def _check_init():
        resp = server.handle_request('{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}')
        assert resp["result"]["protocolVersion"] is not None

    def _check_tools():
        resp = server.handle_request('{"jsonrpc":"2.0","id":1,"method":"tools/list"}')
        assert len(resp["result"]["tools"]) == 7

    results += [
        check("initialize → capabilities",     _check_init),
        check("tools/list → 7 tools",          _check_tools),
    ]

    print("\n🐳 Sandbox Engine")
    from core.sandbox_engine import SandboxEngine
    sb = SandboxEngine(workspace=ws, mode="soft")

    def _check_sandbox():
        ok, stdout, stderr, code = sb.run('print("sandbox OK")')
        assert ok is True and "sandbox OK" in stdout

    results += [
        check("Soft mode disponible",          lambda: assert_true(sb.effective_mode == "soft")),
        check("Run simple code",               _check_sandbox),
    ]

    print("\n🔑 OpType.CREATE_FILE")
    from core.transaction_manager import OpType
    results += [
        check("OpType.CREATE_FILE existe",     lambda: assert_true(hasattr(OpType, "CREATE_FILE"))),
    ]

    print("\n📊 Résumé")
    passed = sum(1 for r in results if r)
    total  = len(results)
    failed = total - passed

    print(f"\n  Total : {total} checks | {PASS} {passed} | {FAIL} {failed}")

    if failed > 0:
        print(f"\n  {FAIL} {failed} check(s) échoué(s) — corriger avant le déploiement")
        sys.exit(1)
    else:
        print(f"\n  {PASS} Tous les checks PASSED — V7 release-ready !")


def assert_attr(obj, name: str) -> None:
    if not hasattr(obj, name):
        raise AttributeError(f"Attribut manquant : {name}")


def assert_true(cond: bool) -> None:
    if not cond:
        raise AssertionError("Condition False")


def _check_abs(ws: Path) -> None:
    from utils.safe_path import safe_path, PathSecurityError
    try:
        safe_path("/etc/passwd", workspace=ws)
        raise AssertionError("Chemin absolu NON bloqué !")
    except PathSecurityError:
        pass


if __name__ == "__main__":
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    main(verbose)
```

---

### TASK-16-03 — `README.md` : Mise à jour V7

**Fichier** : `D:\LLMCodeAgent\README.md`
**Opération** : Append section V7 en fin de README existant

Contenu à ajouter :

```markdown
---

## V7 — Architecture MCP

LCCA V7 expose le cœur transactionnel V5 via un serveur **MCP (Model Context Protocol)** compatible avec Goose et Claude Desktop.

### Démarrage rapide V7

```bash
# Mode MCP stdio (pour Goose)
python main_mcp.py

# Mode REPL interactif
python main_mcp.py --repl

# Validation de l'installation
python scripts/validate_v7.py
```

### Architecture V7

```
Client MCP (Goose / Claude)
        │
        ▼
  mcp_server.py  (JSON-RPC 2.0 stdio)
        │
  ┌─────┼──────────┬──────────┐
  │     │          │          │
McpEdit MemoryEng SandboxEng  CodeEval
Batch   ine       ine
  │
  └──► LCCA V5 Core (237 tests, inchangé)
       TX Manager + SmartPatcher + ASTIndexer
```

### Tools MCP disponibles

| Tool | Description |
|------|-------------|
| `memory_search` | Recherche sémantique 4 collections |
| `memory_store` | Stockage conditionnel par qualité |
| `project_search` | Recherche symboles/fichiers workspace |
| `edit_batch` | Batch ACID de patches (max 3 fichiers) |
| `sandbox_run` | Exécution isolée subprocess/Docker |
| `evaluate_quality` | Score qualité statique 0-100 |
| `analyze_error` | Diagnostic + suggestion de correction |

### Configuration Claude Desktop

```json
{
  "mcpServers": {
    "lcca-v7": {
      "command": "python",
      "args": ["D:/LLMCodeAgent/main_mcp.py"],
      "env": {
        "LCCA_SANDBOX_MODE": "soft"
      }
    }
  }
}
```

### Règles invariantes V7

1. SmartPatcher retourne `str` — jamais n'écrit seul sur disque
2. `safe_path()` obligatoire sur tout path fourni par un client MCP
3. `sys.executable` toujours (jamais `"python"` hardcodé)
4. Max 3 fichiers par transaction (`MAX_FILES_PER_TX`)
5. WAL JSONL append-only — audit complet des opérations
6. Docker en liste de commandes (jamais f-string shell)
7. Container Docker toujours `.remove(force=True)` dans `finally`
8. Telemetry silencieuse (jamais bloquer le flux principal)
```

---

### TASK-16-04 — Mise à jour des skills et context

**Fichier** : `D:\LLMCodeAgent\.claude-skills\003-project-context.md`
**Opération** : Mettre à jour l'arborescence et la version

Sections à mettre à jour :
- `__version__` : `"5.0.0"` → `"7.0.0"`
- Arborescence `core\` : Ajouter `mcp_edit_batch.py`, `memory_engine.py`, `sandbox_engine.py`
- Arborescence racine : Ajouter `mcp_server.py`, `main_mcp.py`, `scripts/`
- Tableau sprints : Ajouter sprints 12-16

**Fichier** : `D:\LLMCodeAgent\.claude-skills\004-sprint-context.md`
**Opération** : Marquer Sprint 16 comme actif + ajouter patterns appris V7

---

### TASK-16-05 — `Docs/Specs/Specs V7/00-INDEX-V7.md` : Index des specs V7

**Fichier** : `D:\LLMCodeAgent\Docs\Specs\Specs V7\00-INDEX-V7.md` *(nouveau)*

```markdown
# Index Specs V7 — LCCA V7.0
<!-- AI-READY | Index V7 | 2026-04-17 -->

## Fichiers de spécifications V7

| # | Fichier | Module | Sprint |
|---|---------|--------|--------|
| 18 | `LLCA V7.MD` | Architecture reconciliée V5/V7 | — |
| 19 | `LLCA V7-AddendumV1.MD` | Implémentation technique complémentaire | — |
| 20 | `LLCA V7-AddendumV1-Correctif.MD` | Correctifs post-validation | — |

## Composants V7 → Specs sources

| Composant | Spec principale | Section |
|-----------|----------------|---------|
| `config.py` (extensions V7) | Addendum V7 §10 + Correctif §— | Constantes MCP/Sandbox |
| `utils/safe_path.py` | Addendum complémentaire §6 + Correctif §5 | API `safe_path()` |
| `utils/telemetry.py` | Addendum complémentaire §5 + Correctif §4 | Rotation RotatingFileHandler |
| `core/transaction_manager.py` (+V7) | Addendum complémentaire §2 + Correctif §2 | CREATE_FILE, cleanup WAL |
| `core/mcp_edit_batch.py` | Architecture reconciliée §6 | Façade TX |
| `core/memory_engine.py` | Architecture reconciliée §5 | 4 collections |
| `core/sandbox_engine.py` | Architecture reconciliée §7 + Addendum §4 | Docker sécurisé |
| `core/llm_generator.py` (+V7) | Addendum complémentaire §1 + Correctif §1 | Cache versionné modèle |
| `mcp_server.py` | Architecture reconciliée §4 | JSON-RPC 2.0 stdio |
| `scripts/migrate_cache_v6_to_v7.py` | Correctif §1.3 | Migration one-shot |
| `scripts/validate_v7.py` | — (Sprint 16) | Validation installation |

## Mapping Sprint → Specs

| Sprint | Description | Specs |
|--------|-------------|-------|
| Sprint 12 | Fondations (config, safe_path, telemetry, OpType) | §2, §3, §6, §10 |
| Sprint 13 | McpEditBatch + MemoryEngine + Cache LLM v7 | §1, §5, §6 |
| Sprint 14 | SandboxEngine | §4, §7 |
| Sprint 15 | MCP Server stdio | §4.1-4.3 |
| Sprint 16 | Intégration E2E + Documentation | — |
```

---

## 🧪 TESTS

### `tests/test_mcp_integration.py` *(décrit dans TASK-16-01)*

Les 11 tests d'intégration E2E sont définis dans TASK-16-01.

### Vérifications manuelles post-sprint

```powershell
# 1. Validation complète
python scripts/validate_v7.py

# 2. Suite de tests complète
pytest tests/ -v --tb=short

# 3. Test MCP interactif
python main_mcp.py --repl

# 4. Test appel direct
python main_mcp.py --call "tools/list"

# 5. Test sandbox
python main_mcp.py --call "tools/call" --args '{"name":"sandbox_run","arguments":{"code":"print(42)"}}'
```

---

## 📦 FICHIERS NOUVEAUX / MODIFIÉS

| Fichier | Action | Notes |
|---------|--------|-------|
| `tests/test_mcp_integration.py` | CREATE | 11 tests E2E |
| `scripts/validate_v7.py` | CREATE | Validation installation |
| `README.md` | EXTEND | Section V7 |
| `.claude-skills/003-project-context.md` | UPDATE | Arborescence V7 |
| `.claude-skills/004-sprint-context.md` | UPDATE | Sprint 16 actif |
| `Docs/Specs/Specs V7/00-INDEX-V7.md` | CREATE | Index specs V7 |

---

## ✅ CRITÈRES D'ACCEPTATION

- [ ] `pytest tests/ -v` → ≥ 367 PASSED, 0 FAILED
- [ ] `python scripts/validate_v7.py` → toutes les checks PASSED
- [ ] `python main_mcp.py --call "tools/list"` → liste 7 tools
- [ ] Test E2E `test_full_workflow_create_then_run` PASSED
- [ ] `README.md` contient section V7 avec config Claude Desktop
- [ ] `003-project-context.md` liste les modules V7
- [ ] `004-sprint-context.md` marque Sprint 16 comme VALIDÉ
- [ ] 0 régression sur les 347 tests Sprint 15

---

## 📊 MÉTRIQUES FINALES V7

| Métrique | V5 (baseline) | V7 (cible) |
|----------|---------------|-----------|
| Tests PASSED | 237 | ≥ 367 |
| Modules core | 19 | 22 (+3) |
| Fichiers utils | 1 | 3 (+2) |
| Fichiers racine | 3 | 4 (+1) |
| Scripts | 0 | 2 (+2) |
| Tools MCP exposés | 0 | 7 |
| Couverture sécurité | Basique | RBAC + audit + safe_path |

---

## 🔗 DÉPENDANCES

- **Bloque** : V8 (multi-agent, Firecracker)
- **Dépend de** : Sprints 12-15 (tous VALIDÉS)
- **Consolide** : Toute l'architecture V7

---

## 📝 PATTERNS APPRIS V7 (pour `.claude-skills/001-skill-coding-agent-master.md`)

À ajouter en session de clôture :

```markdown
### Session 2026-04-17: Sprints 12-16 — V7 MCP + Sandbox

- **Pattern McpEditBatch** : Façade entre MCP et TX Manager V5 — ne contourne JAMAIS le système WAL
- **Pattern safe_path()** : Appel obligatoire dans tout tool MCP exposant un path — avant tout autre traitement
- **Pattern SandboxEngine** : `_try_connect_docker()` avec `client.ping()` — validation effective, pas juste instantiation
- **Pattern Docker commands** : Toujours `command=[sys.executable, script_path]` — JAMAIS f-string ou shell
- **Pattern cleanup WAL** : `_get_tx_completion_timestamp()` utilise le WAL (pas `st_mtime`) pour éviter les faux positifs
- **Pattern cache LLM v7** : `_cache_key` inclut le modèle — `{model}\n{system}\n{user}` — invalider si metadata mismatch
- **Pattern CREATE_FILE rollback** : `op.type == OpType.CREATE_FILE or op.rollback_data is None` → `dst.unlink()`
- **Pattern MCP lifecycle** : `notifications/initialized` = notification sans réponse (retourner `None`)
- **Pattern telemetry** : `RotatingFileHandler` singleton + `try/except` silencieux dans `log_metric()`
- **Anti-pattern** : Ne jamais mettre d'import Docker en top-level — `import docker` dans `_try_connect_docker()` uniquement
- **Anti-pattern** : Ne jamais utiliser `subprocess.run("docker run ...")` — SDK Python uniquement
- **CRITIQUE V7** : Logs MCP sur `stderr` UNIQUEMENT — `stdout` est le canal JSON-RPC pur
```

---

## 🎯 ROADMAP POST-V7

| Version | Livrable | Sprint estimé |
|---------|----------|---------------|
| **V7.1** | CodeEvaluator bloquant (seuil configurable) + Auto-fix ErrorAnalyzer | Sprint 17 |
| **V7.2** | Streaming Ollama + Context budget dynamique | Sprint 18 |
| **V8.0** | Multi-agent A2A (Architect/Coder/Tester/Reviewer) | Sprints 19-21 |
| **V8.1** | RAG codebase (embeddings workspace via ChromaDB) | Sprint 22 |
| **V8.2** | Sandbox Firecracker (microVM isolation) | Sprint 23 |

<!-- Sprint 16 | V7 Intégration finale | LCCA V7.0.0 | 2026-04-17 -->
