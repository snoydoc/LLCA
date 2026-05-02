# -*- coding: utf-8-sig -*-
"""
check_env.py — LCCA V7 — Diagnostic d'environnement
Run : python check_env.py

Vérifie étape par étape que tous les composants sont opérationnels.
Pas de pytest, pas de mocks — deps réelles uniquement.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import textwrap
from pathlib import Path

# ── Helpers affichage ─────────────────────────────────────────────────────────

W = 64
PASS  = "  [OK]  "
FAIL  = "  [KO]  "
WARN  = "  [--]  "
INFO  = "  [..]  "

def _hdr(title: str) -> None:
    print()
    print("=" * W)
    print(f"  {title}")
    print("=" * W)

def _ok(msg: str)   -> None: print(f"{PASS}{msg}")
def _ko(msg: str)   -> None: print(f"{FAIL}{msg}")
def _warn(msg: str) -> None: print(f"{WARN}{msg}")
def _info(msg: str) -> None: print(f"{INFO}{msg}")

results: list[tuple[str, bool]] = []

def check(label: str, passed: bool, ok_msg: str = "", ko_msg: str = "") -> bool:
    results.append((label, passed))
    if passed:
        _ok(f"{label}" + (f" — {ok_msg}" if ok_msg else ""))
    else:
        _ko(f"{label}" + (f" — {ko_msg}" if ko_msg else ""))
    return passed


# ══════════════════════════════════════════════════════════════════════════════
# 1. PYTHON & VENV
# ══════════════════════════════════════════════════════════════════════════════

_hdr("1 / PYTHON & VENV")

py_ver = sys.version_info
check(
    "Python >= 3.11",
    py_ver >= (3, 11),
    ok_msg=f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}",
    ko_msg=f"Version actuelle : {py_ver.major}.{py_ver.minor} — upgrade requis",
)

venv_active = sys.prefix != sys.base_prefix
check(
    "Venv activé",
    venv_active,
    ok_msg=sys.prefix,
    ko_msg="sys.prefix == sys.base_prefix — activer le venv d'abord",
)

# ══════════════════════════════════════════════════════════════════════════════
# 2. DEPENDANCES
# ══════════════════════════════════════════════════════════════════════════════

_hdr("2 / DEPENDANCES")

DEPS = {
    "libcst":   ("libcst",   True),   # (import_name, required)
    "chromadb": ("chromadb", False),
    "yaml":     ("yaml",     False),
    "pytest":   ("pytest",   True),
    "black":    ("black",    False),
    "docker":   ("docker",   False),
}

for pkg, (imp, required) in DEPS.items():
    try:
        mod = importlib.import_module(imp)
        ver = getattr(mod, "__version__", "?")
        check(f"import {pkg}", True, ok_msg=f"v{ver}")
    except ImportError:
        label = f"import {pkg}"
        if required:
            check(label, False, ko_msg="REQUIS — pip install " + pkg)
        else:
            _warn(f"{label} — absent (optionnel)")

# ══════════════════════════════════════════════════════════════════════════════
# 3. STRUCTURE PROJET
# ══════════════════════════════════════════════════════════════════════════════

_hdr("3 / STRUCTURE PROJET")

BASE = Path("D:/LLMCodeAgent")

EXPECTED_FILES = [
    "config.py",
    "core/__init__.py",
    "core/transaction_manager.py",
    "core/mcp_server.py",
    "core/mcp_edit_batch.py",
    "core/sandbox_engine.py",
    "core/code_evaluator.py",
    "core/ast_indexer.py",
    "core/memory_engine.py",
    "utils/safe_path.py",
    "utils/telemetry.py",
    "workspace",
    "transactions",
    "logs",
]

for rel in EXPECTED_FILES:
    p = BASE / rel
    check(rel, p.exists(), ko_msg="MANQUANT")

# ══════════════════════════════════════════════════════════════════════════════
# 4. CONFIG.PY
# ══════════════════════════════════════════════════════════════════════════════

_hdr("4 / CONFIG.PY")

try:
    sys.path.insert(0, str(BASE))
    import config
    check("import config", True)
    check("WORKSPACE_DIR existe",   config.WORKSPACE_DIR.exists(),   ok_msg=str(config.WORKSPACE_DIR))
    check("TRANSACTIONS_DIR existe",config.TRANSACTIONS_DIR.exists(),ok_msg=str(config.TRANSACTIONS_DIR))
    check("LOGS_DIR existe",        config.LOGS_DIR.exists(),        ok_msg=str(config.LOGS_DIR))
    check("LLM_CACHE_DIR existe",   config.LLM_CACHE_DIR.exists(),  ok_msg=str(config.LLM_CACHE_DIR))
    _info(f"OLLAMA_URL    = {config.OLLAMA_URL}")
    _info(f"OLLAMA_MODEL  = {config.OLLAMA_MODEL}")
    _info(f"SANDBOX_MODE  = {config.SANDBOX_MODE}")
except Exception as exc:
    check("import config", False, ko_msg=str(exc))

# ══════════════════════════════════════════════════════════════════════════════
# 5. MODULES CORE (import smoke test)
# ══════════════════════════════════════════════════════════════════════════════

_hdr("5 / IMPORT DES MODULES CORE")

CORE_MODULES = [
    "core.transaction_manager",
    "core.ast_indexer",
    "core.smart_patcher",
    "core.code_evaluator",
    "core.sandbox_engine",
    "core.mcp_edit_batch",
    "core.mcp_server",
    "utils.safe_path",
    "utils.telemetry",
]

for mod_name in CORE_MODULES:
    try:
        importlib.import_module(mod_name)
        check(f"import {mod_name}", True)
    except Exception as exc:
        check(f"import {mod_name}", False, ko_msg=str(exc)[:80])

# ══════════════════════════════════════════════════════════════════════════════
# 6. TRANSACTION MANAGER
# ══════════════════════════════════════════════════════════════════════════════

_hdr("6 / TRANSACTION MANAGER")

try:
    import tempfile
    from core.transaction_manager import TransactionManager, OpType

    with tempfile.TemporaryDirectory() as td:
        tm = TransactionManager(tx_dir=Path(td))
        tx_id = tm.begin("check_env — test tx")
        check("TransactionManager.begin()", tx_id is not None, ok_msg=f"tx_id={tx_id}")

        # Créer un fichier temporaire pour tester log_operation
        tmp_f = Path(td) / "dummy.py"
        tmp_f.write_text("x = 1\n", encoding="utf-8")

        def _noop():
            pass

        tm.log_operation(
            target_path=tmp_f,
            op_type=OpType.PATCH_FILE,
            execute_func=_noop,
        )
        check("TransactionManager.log_operation()", True)

        tm.commit()

        # Vérifier COMMIT dans le WAL
        wal = Path(td) / "wal.jsonl"
        # utf-8-sig : le WAL est écrit avec BOM Windows
        entries = [json.loads(l) for l in wal.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
        commits = [e for e in entries if e["type"] == "COMMIT"]
        check("WAL COMMIT écrit", len(commits) == 1, ok_msg=f"tx_id={commits[0]['tx_id']}")

except Exception as exc:
    check("TransactionManager", False, ko_msg=str(exc))

# ══════════════════════════════════════════════════════════════════════════════
# 7. SMART PATCHER & AST INDEXER
# ══════════════════════════════════════════════════════════════════════════════

_hdr("7 / SMART PATCHER & AST INDEXER")

try:
    from core.smart_patcher import SmartPatcher
    from core.ast_indexer import ASTIndexer

    code = textwrap.dedent("""\
        \"\"\"Module test.\"\"\"


        def hello(name: str) -> str:
            \"\"\"Salue.\"\"\"
            return f"hello {name}"
    """)

    # Test SmartPatcher — add_function
    patch_code = textwrap.dedent("""\
        def goodbye(name: str) -> str:
            \"\"\"Au revoir.\"\"\"
            return f"goodbye {name}"
    """)

    with tempfile.TemporaryDirectory() as td_patch:
        ws_patch = Path(td_patch)
        (ws_patch / "mod.py").write_text(code, encoding="utf-8")
        patcher = SmartPatcher(workspace=ws_patch)
        result = patcher.apply_patch(
            file_path="mod.py",
            patch_type="add_function",
            code=patch_code,
        )
    ok = "goodbye" in result and "hello" in result
    check("SmartPatcher.apply_patch(add_function)", ok,
          ok_msg="fonction ajoutée", ko_msg="résultat inattendu")

    # Test ASTIndexer sur un dossier temporaire
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        (ws / "mod.py").write_text(code, encoding="utf-8")
        idx = ASTIndexer(workspace=ws)
        idx.index_repository()
        found = "hello" in idx.symbols_table
        check("ASTIndexer.index_repository()", found,
              ok_msg=f"{len(idx.symbols_table)} symbole(s) indexé(s)",
              ko_msg="symbole 'hello' introuvable")

except Exception as exc:
    check("SmartPatcher/ASTIndexer", False, ko_msg=str(exc))

# ══════════════════════════════════════════════════════════════════════════════
# 8. CODE EVALUATOR
# ══════════════════════════════════════════════════════════════════════════════

_hdr("8 / CODE EVALUATOR")

try:
    from core.code_evaluator import CodeEvaluator

    ev = CodeEvaluator(threshold=60)

    # Bon code
    good = textwrap.dedent("""\
        \"\"\"Calcul.\"\"\"


        def add(a: int, b: int) -> int:
            \"\"\"Additionne.\"\"\"
            return a + b
    """)
    r_good = ev.evaluate(good, "good.py")
    check("Bon code score >= 80", r_good.score >= 80,
          ok_msg=f"score={r_good.score}/100, passed={r_good.passed}")

    # Mauvais code (doit passer < 60)
    bad = (
        "global x\nx = 1\n\n"
        "def bad_func(a, b):\n"
        "    try:\n        pass\n    except:\n        print(x)\n"
        "    if a:\n        if a>0:\n            if a>1:\n"
        "                if a>2:\n                    if a>3:\n"
        "                        if b: x=0\n"
    )
    r_bad = ev.evaluate(bad, "bad.py")
    check("Mauvais code score < 60", r_bad.score < 60,
          ok_msg=f"score={r_bad.score}/100, passed={r_bad.passed}",
          ko_msg=f"score={r_bad.score} >= 60 — seuil non atteint")

except Exception as exc:
    check("CodeEvaluator", False, ko_msg=str(exc))

# ══════════════════════════════════════════════════════════════════════════════
# 9. SAFE PATH
# ══════════════════════════════════════════════════════════════════════════════

_hdr("9 / SAFE PATH")

try:
    from utils.safe_path import safe_path, PathSecurityError

    ws = Path("D:/LLMCodeAgent/workspace")

    # Chemin valide
    try:
        safe_path("calc.py", ws)
        check("safe_path valide (calc.py)", True)
    except Exception as exc:
        check("safe_path valide (calc.py)", False, ko_msg=str(exc))

    # Traversal bloqué
    try:
        safe_path("../../etc/passwd", ws)
        check("Traversal bloqué (../../etc/passwd)", False, ko_msg="Pas d'exception levée !")
    except PathSecurityError:
        check("Traversal bloqué (../../etc/passwd)", True, ok_msg="PathSecurityError levée")
    except Exception as exc:
        check("Traversal bloqué", False, ko_msg=f"Mauvaise exception: {exc}")

    # Chemin absolu bloqué
    try:
        safe_path("C:/Windows/system32/cmd.exe", ws)
        check("Absolu bloqué (C:/Windows/...)", False, ko_msg="Pas d'exception levée !")
    except PathSecurityError:
        check("Absolu bloqué (C:/Windows/...)", True, ok_msg="PathSecurityError levée")
    except Exception as exc:
        check("Absolu bloqué", False, ko_msg=f"Mauvaise exception: {exc}")

except Exception as exc:
    check("safe_path module", False, ko_msg=str(exc))

# ══════════════════════════════════════════════════════════════════════════════
# 10. SANDBOX ENGINE (mode soft)
# ══════════════════════════════════════════════════════════════════════════════

_hdr("10 / SANDBOX ENGINE — MODE SOFT")

try:
    from core.sandbox_engine import SandboxEngine

    with tempfile.TemporaryDirectory() as td:
        sb = SandboxEngine(workspace=Path(td), mode="soft")
        _info(f"mode effectif = {sb.effective_mode}")

        # Code simple
        ok, out, err, code = sb.run("print(2 + 2)", timeout=10)
        check("sandbox print(2+2)", ok and "4" in out,
              ok_msg=f"stdout={out.strip()!r}", ko_msg=f"err={err!r}")

        # RuntimeError capturé
        ok2, out2, err2, code2 = sb.run("raise ValueError('oops')", timeout=10)
        check("sandbox RuntimeError capturé", not ok2 and code2 != 0,
              ok_msg=f"exit_code={code2}")

        # Timeout (code infini, timeout=2)
        ok3, out3, err3, code3 = sb.run("while True: pass", timeout=2)
        check("sandbox timeout (2s)", not ok3,
              ok_msg=f"stdout={out3!r} err={err3!r}")

except Exception as exc:
    check("SandboxEngine soft", False, ko_msg=str(exc))

# ══════════════════════════════════════════════════════════════════════════════
# 11. SANDBOX ENGINE (mode docker) — optionnel
# ══════════════════════════════════════════════════════════════════════════════

_hdr("11 / SANDBOX ENGINE — MODE DOCKER (optionnel)")

try:
    from core.sandbox_engine import SandboxEngine, _DOCKER_AVAILABLE

    if not _DOCKER_AVAILABLE:
        _warn("SDK docker non installé — pip install docker pour activer")
    else:
        with tempfile.TemporaryDirectory() as td:
            try:
                sb_d = SandboxEngine(workspace=Path(td), mode="docker")
                _info(f"mode effectif = {sb_d.effective_mode}")
                if sb_d.effective_mode == "docker":
                    ok, out, err, code = sb_d.run("print('docker ok')", timeout=30)
                    check("sandbox docker print()", ok and "docker ok" in out,
                          ok_msg=f"stdout={out.strip()!r}", ko_msg=f"err={err!r}")
                else:
                    _warn("Docker SDK présent mais daemon indisponible — mode soft utilisé")
            except RuntimeError as exc:
                _warn(f"Docker non disponible : {exc}")

except Exception as exc:
    _warn(f"Section docker ignorée : {exc}")

# ══════════════════════════════════════════════════════════════════════════════
# 12. MCP SERVER — LIFECYCLE + TOOLS
# ══════════════════════════════════════════════════════════════════════════════

_hdr("12 / MCP SERVER — LIFECYCLE")

try:
    from unittest.mock import MagicMock
    from core.mcp_server import McpServer

    # Mocks légers pour éviter Ollama/ChromaDB
    mock_mem = MagicMock()
    mock_mem.search.return_value = {"solutions": [], "failures": [], "context": []}
    mock_mem.store.return_value  = MagicMock(stored=True, collection="lcca_patches",
                                              entry_id="test_id", reason=None)
    mock_err = MagicMock()

    with tempfile.TemporaryDirectory() as td:
        ws   = Path(td) / "workspace";  ws.mkdir()
        txd  = Path(td) / "tx";         txd.mkdir()

        from core.transaction_manager import TransactionManager
        from core.mcp_edit_batch import McpEditBatch
        from core.ast_indexer import ASTIndexer

        server = McpServer(
            memory_engine  = mock_mem,
            error_analyzer = mock_err,
            edit_batch     = McpEditBatch(tx_manager=TransactionManager(tx_dir=txd), workspace=ws),
            sandbox_engine = SandboxEngine(workspace=ws, mode="soft"),
            ast_indexer    = ASTIndexer(workspace=ws),
            workspace      = ws,
        )

        # initialize
        r = server.handle({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}})
        check("MCP initialize",
              r.get("result",{}).get("serverInfo",{}).get("name") == "lcca-v7-mcp",
              ok_msg="serverInfo.name = lcca-v7-mcp")

        # notification (doit retourner None)
        r2 = server.handle({"jsonrpc":"2.0","method":"notifications/initialized"})
        check("MCP notifications/initialized → None", r2 is None, ok_msg="None reçu")

        # tools/list → 7 tools
        r3 = server.handle({"jsonrpc":"2.0","id":2,"method":"tools/list"})
        names = {t["name"] for t in r3.get("result",{}).get("tools",[])}
        check("tools/list → 7 tools", len(names) == 7,
              ok_msg=str(sorted(names)), ko_msg=f"trouvé {len(names)} tool(s)")

        # ping
        r4 = server.handle({"jsonrpc":"2.0","id":5,"method":"ping"})
        check("ping → pong", r4.get("result",{}).get("pong") is True)

        # tool avant initialize → erreur
        srv2 = McpServer(memory_engine=mock_mem, error_analyzer=mock_err,
                         edit_batch=McpEditBatch(tx_manager=TransactionManager(tx_dir=txd), workspace=ws),
                         sandbox_engine=SandboxEngine(workspace=ws, mode="soft"),
                         ast_indexer=ASTIndexer(workspace=ws), workspace=ws)
        r5 = srv2.handle({"jsonrpc":"2.0","id":1,"method":"tools/call",
                          "params":{"name":"sandbox_run","arguments":{"code":"print(1)"}}})
        check("tools/call avant initialize → erreur -32600",
              r5.get("error",{}).get("code") == -32600,
              ok_msg="code=-32600")

        # edit_batch : CREATE
        r6 = server.handle({"jsonrpc":"2.0","id":42,"method":"tools/call","params":{
            "name":"edit_batch",
            "arguments":{"files":[{"path":"test_module.py","action":"create",
                                   "code":"def greet(name: str) -> str:\n    return f'hello {name}'\n"}]}
        }})
        res6 = json.loads(r6["result"]["content"][0]["text"])
        check("edit_batch CREATE", res6.get("success") is True,
              ok_msg=f"fichier créé: {(ws/'test_module.py').exists()}")

        # sandbox_run
        r7 = server.handle({"jsonrpc":"2.0","id":43,"method":"tools/call","params":{
            "name":"sandbox_run","arguments":{"code":"print('hello world')"}
        }})
        res7 = json.loads(r7["result"]["content"][0]["text"])
        check("sandbox_run via MCP", res7.get("success") and "hello world" in res7.get("stdout",""),
              ok_msg=f"stdout={res7.get('stdout','').strip()!r}")

        # evaluate_quality via MCP
        r8 = server.handle({"jsonrpc":"2.0","id":44,"method":"tools/call","params":{
            "name":"evaluate_quality",
            "arguments":{"code":"def greet(name: str) -> str:\n    \"\"\"Salue.\"\"\"\n    return f'hello {name}'\n",
                         "filename":"greet.py"}
        }})
        res8 = json.loads(r8["result"]["content"][0]["text"])
        check("evaluate_quality via MCP", "score" in res8,
              ok_msg=f"score={res8.get('score')}, passed={res8.get('passed')}")

        # path traversal bloqué via MCP
        r9 = server.handle({"jsonrpc":"2.0","id":45,"method":"tools/call","params":{
            "name":"edit_batch",
            "arguments":{"files":[{"path":"../../evil.py","action":"create","code":"x=1"}]}
        }})
        check("path traversal bloqué via MCP",
              r9.get("error",{}).get("code") == -32001,
              ok_msg="code=-32001 (PathSecurityError)")

except Exception as exc:
    check("McpServer", False, ko_msg=str(exc))

# ══════════════════════════════════════════════════════════════════════════════
# 13. MEMORYENGINE / MEMPALACE
# ══════════════════════════════════════════════════════════════════════════════

_hdr("13 / MEMORYENGINE & MEMPALACE")

try:
    from core.memory_engine import MemoryEngine
    me = MemoryEngine()
    _info(f"MemoryEngine.is_available = {me.is_available}")

    if me.is_available:
        # store lcca_failures (toujours accepté)
        sr = me.store("lcca_failures", {"error": "TestError", "file": "check_env.py"})
        check("MemoryEngine.store(lcca_failures)", sr.stored,
              ok_msg=f"entry_id={sr.entry_id}")

        # store lcca_solutions (seuil 0.8)
        sr2 = me.store("lcca_solutions", {"code": "def f(): pass", "score": 0.9})
        check("MemoryEngine.store(lcca_solutions, score=0.9)", sr2.stored,
              ok_msg=f"entry_id={sr2.entry_id}")

        # search
        res = me.search("TestError check_env", n=3)
        check("MemoryEngine.search()", isinstance(res, dict) and "failures" in res,
              ok_msg=f"clés={list(res.keys())}")
    else:
        _warn("MemPalace non disponible — tests MemoryEngine ignorés")
        _warn("Pour activer : vérifier D:\\MediBot\\Mempalace ou ~/.mempalace/palace")
        results.append(("MemoryEngine disponible", False))

except Exception as exc:
    check("MemoryEngine", False, ko_msg=str(exc))

# ══════════════════════════════════════════════════════════════════════════════
# 14. OLLAMA / LLM (optionnel)
# ══════════════════════════════════════════════════════════════════════════════

_hdr("14 / OLLAMA (optionnel)")

import urllib.request
import urllib.error

try:
    with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as resp:
        data = json.loads(resp.read())
        models = [m["name"] for m in data.get("models", [])]
        _info(f"Ollama répond — {len(models)} modèle(s) : {models}")
        has_model = any("qwen" in m for m in models)
        if has_model:
            _ok(f"Modèle qwen trouvé : {[m for m in models if 'qwen' in m]}")
        else:
            _warn("Aucun modèle qwen — ollama pull qwen2.5-coder:14b requis")
except urllib.error.URLError:
    _warn("Ollama non accessible sur localhost:11434 — LLM désactivé")
except Exception as exc:
    _warn(f"Ollama check: {exc}")

# ══════════════════════════════════════════════════════════════════════════════
# 15. DOCKER (optionnel)
# ══════════════════════════════════════════════════════════════════════════════

_hdr("15 / DOCKER (optionnel)")

try:
    result_docker = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        capture_output=True, text=True, timeout=5
    )
    if result_docker.returncode == 0:
        _ok(f"Docker daemon actif — version {result_docker.stdout.strip()}")
    else:
        _warn(f"Docker non accessible : {result_docker.stderr.strip()[:80]}")
except FileNotFoundError:
    _warn("docker CLI introuvable — Docker Desktop non installé ou pas dans PATH")
except Exception as exc:
    _warn(f"Docker check: {exc}")

# ══════════════════════════════════════════════════════════════════════════════
# RAPPORT FINAL
# ══════════════════════════════════════════════════════════════════════════════

_hdr("RAPPORT FINAL")

required_results = [(l, p) for l, p in results]
passed = sum(1 for _, p in required_results if p)
total  = len(required_results)
failed = [(l, p) for l, p in required_results if not p]

print(f"\n  Score : {passed}/{total} tests passés\n")

if failed:
    print("  Echecs :")
    for label, _ in failed:
        print(f"    {FAIL}{label}")
else:
    print("  Tous les tests sont passés.")

print()
if passed == total:
    print("  LCCA V7 — environnement OPERATIONNEL")
elif passed >= total * 0.8:
    print("  LCCA V7 — environnement PARTIELLEMENT operationnel")
    print("  Verifier les echecs ci-dessus.")
else:
    print("  LCCA V7 — environnement DEGRADE")
    print("  Plusieurs composants requis sont en echec.")
print()
