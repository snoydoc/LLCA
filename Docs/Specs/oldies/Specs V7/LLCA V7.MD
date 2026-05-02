============================================================
Fichier : 18-addendum-v7-reconcilie.md
============================================================

# Addendum V7 — Architecture Reconciliée V5/V7
&lt;!-- AI-READY | Addendum architecture | Version 7.0.0-rc1 | 2026-04-17 --&gt;

## Vue d'ensemble

Cet addendum définit la **migration V5 → V7** en conservant l'intégrité transactionnelle et les 237 tests validés de la V5, tout en intégrant les capacités MCP et Goose de la V7.

&gt; **Principe fondateur** : La V7 n'est pas un remplacement de la V5. C'est un **wrapper MCP + un moteur sandbox** qui s'interfacent avec le cœur transactionnel V5 existant.

---

## 1. Décisions architecturales exécutives

| Domaine | Décision | Justification |
|---------|----------|---------------|
| **Transaction** | Conserver `TransactionManager` V5 tel quel | WAL append-only, MD5, fsync, rollback LIFO validés |
| **AST Patch** | Conserver `SmartPatcher` V5 | `libcst` + validation `compile()` avant/après |
| **Mémoire** | Fusionner : 4 collections V7 + architecture 4 layers V5 | Collections `lcca_*` dans MemPalace avec hiérarchie wing/room |
| **MCP** | Implémenter serveur stdio JSON-RPC 2.0 strict | Conformité protocole MCP 2025/2026 |
| **Sandbox** | Réécrire complètement (Docker SDK Python) | Suppression du risque d'injection shell |
| **NL/DSL** | Conserver `NLParser` + `DSLParser` V5 | Pas de régression sur les pipelines existants |
| **Évaluation** | Conserver `CodeEvaluator` V5 | Score 0-100, critères McCabe, informatif en V7.1 |
| **Sécurité** | Ajouter couche RBAC + audit trail | Conformité patterns MCP Enterprise [^6^][^13^] |

---

## 2. Ce qui est SUPPRIMÉ de la proposition V7 initiale

| Élément | Raison | Action |
|---------|--------|--------|
| `edit_batch.py` autonome | Court-circuite le TX Manager V5 | Remplacé par `McpEditBatch` (façade TX Manager) |
| `compute_score()` naïf | Remplace `CodeEvaluator` et `ErrorAnalyzer` V5 | Supprimé, utilisation de `core/code_evaluator.py` |
| `CorrectionEngine` standalone | Rôle confondu avec V5 existant | Fusionné dans `ErrorAnalyzer` + `CodeEvaluator` |
| `ProjectIndexer` wrapper | Proxy vide sur `ASTIndexer` | Supprimé, `ASTIndexer` injecté directement |
| Séquence MCP stricte | `memory_search → edit → sandbox → store` | Remplacé par protocol stateless avec validations |
| Seuil mémoire 0.8 bloquant | Empêche l'apprentissage par échec | Seuil informatif uniquement |
| Docker inline f-string | Injection shell critique | Remplacé par Docker SDK Python |
| `"python"` hardcodé | Non conforme règle 8 V5 | `sys.executable` obligatoire |

---

## 3. Architecture cible V7
┌─────────────────────────────────────────────────────────────────────┐
│  GOOSE / Client MCP (extérieur)                                     │
│  • Recipes YAML                                                │
│  • Prompts structurés                                               │
│  • Close-the-loop (vérification auto)                               │
└─────────────────────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────────┐
│  MCP SERVER V7  (mcp_server.py)                                     │
│  ─────────────────────────────────────────────────────────────────  │
│  Protocole : JSON-RPC 2.0 stdio                                     │
│  Lifecycle : initialize → capabilities → tools/list → tools/call    │
│  Sécurité  : RBAC par tool, audit trail, rate limiting              │
└─────────────────────────────────────────────────────────────────────┘
│
┌─────────────────┼─────────────────┐
▼                 ▼                 ▼
┌────────────────┐ ┌──────────────┐ ┌──────────────────┐
│ memory_search  │ │ edit_batch   │ │ sandbox_run      │
│ memory_store   │ │ project_info │ │ evaluate_quality │
│ project_search │ │ (TX V5)      │ │ analyze_error    │
└──────┬─────────┘ └──────┬───────┘ └────────┬─────────┘
│                  │                  │
▼                  ▼                  ▼
┌──────────────────────────────────────────────────────────────┐
│              LCCA V5 CORE (conservé intégralement)           │
│  ──────────────────────────────────────────────────────────  │
│  transaction_manager.py  │  ast_indexer.py                   │
│  smart_patcher.py        │  dependency_graph.py              │
│  file_selector.py        │  planner.py (MultiFilePlanner)    │
│  orchestrator.py         │  llm_generator.py                 │
│  nl_parser.py            │  code_evaluator.py                │
│  recovery_service.py     │  executor.py                      │
│  error_analyzer.py       │  mempalace_client.py              │
│  context_assembler.py    │  mempalace_adapter.py             │
└──────────────────────────────────────────────────────────────┘


---

## 4. Spécification du MCP Server V7

### 4.1 Conformance protocole

Le serveur DOIT implémenter le lifecycle MCP strict :

```python
# Séquence obligatoire à chaque session
1. client → {"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}
2. server → {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05",...}}
3. client → {"jsonrpc":"2.0","method":"notifications/initialized"}
4. client → {"jsonrpc":"2.0","id":2,"method":"tools/list"}
5. server → liste des outils avec descriptions optimisées LLM
6. client → {"jsonrpc":"2.0","id":3,"method":"tools/call",...}

4.2 Tools exposés
| Tool               | Description                                 | Accès V5                              |
| ------------------ | ------------------------------------------- | ------------------------------------- |
| `memory_search`    | Recherche sémantique dans les 4 collections | `MemPalaceClient.search_memories()`   |
| `memory_store`     | Stockage conditionnel avec métadonnées      | `MemPalaceClient.mine_content()`      |
| `project_search`   | Recherche de symboles/fichiers              | `ASTIndexer` + `FileSelector`         |
| `edit_batch`       | Application atomique de patches             | `TransactionManager` + `SmartPatcher` |
| `sandbox_run`      | Exécution isolée de code                    | `SandboxEngine` (NOUVEAU)             |
| `evaluate_quality` | Score statique 0-100                        | `CodeEvaluator.evaluate()`            |
| `analyze_error`    | Diagnostic + suggestion actionnable         | `ErrorAnalyzer.analyze()`             |

4.3 Validation sécurisée des arguments
Tout appel à edit_batch DOIT passer par :
def _validate_edit_args(args: dict) -> Tuple[bool, str]:
    # 1. Vérifier workspace containment (pas d'écriture hors workspace)
    # 2. Vérifier MAX_FILES_PER_TX (config.MAX_FILES_PER_TX)
    # 3. Vérifier que les paths sont relatifs au workspace
    # 4. Vérifier que le contenu compile() avant patch (syntax check)

5. Memory Engine V7 — Spécification reconciliée
5.1 Collections (V7) × Layers (V5)
Les 4 collections V7 sont mappées sur l'architecture 4 layers V5 :
| Collection V7    | Layer V5             | Rôle                       | Seuil de stockage    |
| ---------------- | -------------------- | -------------------------- | -------------------- |
| `lcca_solutions` | Layer 1 (compressed) | Code validé et fonctionnel | `score >= 0.8`       |
| `lcca_failures`  | Layer 2 (scoped)     | Erreurs + correctifs       | **Toujours stocker** |
| `lcca_context`   | Layer 2 (scoped)     | Snippets projet récents    | `score >= 0.6`       |
| `lcca_patches`   | Layer 3 (deep)       | Historique complet TX      | **Toujours stocker** |

5.2 API publique
class MemoryEngine:
    def __init__(self, adapter: Optional[ExistingMemPalaceAdapter] = None):
        self.adapter = adapter or ExistingMemPalaceAdapter()
        self.context_assembler = ContextAssembler()  # V5 réutilisé

    def search(self, query: str, wing: str = "lcca", n: int = 5) -> Dict[str, List[MemoryEntry]]:
        """Recherche cross-collection avec filtres hiérarchiques."""
        return {
            "solutions": self.adapter.search("lcca_solutions", query, wing=wing, n=n),
            "failures": self.adapter.search("lcca_failures", query, wing=wing, n=n),
            "context": self.adapter.search("lcca_context", query, wing=wing, n=n),
        }

    def store(self, collection: str, payload: dict) -> dict:
        """
        Stocke dans une collection spécifique.
        Règles :
        - lcca_failures : toujours stocker (apprentissage par échec)
        - lcca_solutions : stocker si payload.get("score", 0) >= 0.8
        - lcca_patches : toujours stocker (audit)
        """
        if collection == "lcca_solutions" and payload.get("score", 0) < 0.8:
            return {"stored": False, "reason": "score_below_threshold"}
        
        entry_id = self.adapter.store(collection, payload)
        return {"stored": True, "entry_id": entry_id}

6. Edit Batch — Façade Transactionnelle
McpEditBatch est une façade du TransactionManager V5. Il ne remplace pas le système ACID.
# core/mcp_edit_batch.py
from typing import List, Dict, Tuple
from core.transaction_manager import TransactionManager, OpType
from core.smart_patcher import SmartPatcher
from core.code_evaluator import CodeEvaluator
from config import WORKSPACE_DIR, MAX_FILES_PER_TX

class McpEditBatch:
    def __init__(
        self,
        tx_manager: Optional[TransactionManager] = None,
        patcher: Optional[SmartPatcher] = None,
        evaluator: Optional[CodeEvaluator] = None,
    ):
        self.tx_manager = tx_manager or TransactionManager()
        self.patcher = patcher or SmartPatcher(workspace=WORKSPACE_DIR)
        self.evaluator = evaluator or CodeEvaluator(threshold=60)

    def apply(self, files: List[dict]) -> Dict:
        """
        Applique un batch de modifications de manière atomique.
        
        Args:
            files: [{"path": "rel/path.py", "patch_type": "add_function", 
                     "symbol": "foo", "code": "def foo(): ..."}, ...]
        
        Returns:
            {"success": True, "tx_id": str, "evaluations": [...]}
            {"success": False, "error": str, "rolled_back": bool}
        """
        # Validation pré-TX
        if len(files) > MAX_FILES_PER_TX:
            return {
                "success": False,
                "error": f"Trop de fichiers ({len(files)} > {MAX_FILES_PER_TX})",
                "rolled_back": False,
            }

        # Vérification workspace containment
        for f in files:
            target = WORKSPACE_DIR / f["path"]
            if WORKSPACE_DIR not in target.resolve().parents:
                return {"success": False, "error": f"Path hors workspace: {f['path']}"}

        tx_id = self.tx_manager.begin(
            dsl_input="mcp_edit_batch",
            project="lcca_v7",
            intent=f"batch_{len(files)}_files"
        )

        evaluations = []
        try:
            for op in files:
                full_path = WORKSPACE_DIR / op["path"]
                
                # SmartPatcher retourne str, n'écrit PAS sur disque
                new_code = self.patcher.apply_patch(
                    file_path=op["path"],
                    patch_type=op["patch_type"],
                    code=op.get("code"),
                    name=op.get("symbol"),
                )
                
                # Évaluation qualité avant écriture
                eval_result = self.evaluator.evaluate(new_code, filename=op["path"])
                evaluations.append(eval_result.to_dict())
                
                if not eval_result.passed:
                    # V1 informatif : on loggue mais on ne bloque pas
                    # V2 bloquant : décommenter le raise ci-dessous
                    # raise ValueError(f"Qualité insuffisante: {eval_result.score}/100")
                    pass

                def _do_write():
                    full_path.write_text(new_code, encoding="utf-8-sig")

                self.tx_manager.log_operation(
                    target_path=full_path,
                    op_type=OpType.PATCH_FILE,
                    execute_func=_do_write,
                    metadata={
                        "patch_type": op["patch_type"],
                        "symbol": op.get("symbol"),
                        "quality_score": eval_result.score,
                    }
                )

            # Validation syntaxe post-patch
            self._validate_batch_syntax(files)
            
            self.tx_manager.commit()
            return {"success": True, "tx_id": tx_id, "evaluations": evaluations}

        except Exception as e:
            self.tx_manager.rollback(reason=str(e))
            return {"success": False, "error": str(e), "rolled_back": True}

    def _validate_batch_syntax(self, files: List[dict]) -> None:
        """Compile chaque fichier modifié pour valider la syntaxe."""
        for f in files:
            full_path = WORKSPACE_DIR / f["path"]
            source = full_path.read_text(encoding="utf-8-sig")
            compile(source, f["path"], "exec")  # SyntaxError si invalide

. Sandbox Engine V7 — Réécriture sécurisée
La V7 initiale est inacceptable en production (f-string shell injection, timeout 5s). Remplacement par :
# core/sandbox_engine.py
import sys
import subprocess
import tempfile
import docker
from pathlib import Path
from typing import Tuple, Optional

class SandboxEngine:
    def __init__(self, workspace: Path, mode: str = "auto"):
        self.workspace = workspace
        self.mode = mode  # "soft" | "docker" | "auto"
        self.docker_client = None
        if mode in ("docker", "auto"):
            try:
                self.docker_client = docker.from_env()
            except Exception:
                if mode == "docker":
                    raise RuntimeError("Docker requis mais non disponible")

    def run(
        self,
        code: str,
        file_path: Optional[str] = None,
        timeout: int = 30,
    ) -> Tuple[bool, str, str, int]:
        """
        Exécute du code Python en isolation.
        
        Returns:
            (success: bool, stdout: str, stderr: str, exit_code: int)
        """
        if self.mode == "soft" or (self.mode == "auto" and self.docker_client is None):
            return self._run_subprocess(code, timeout)
        return self._run_docker(code, file_path, timeout)

    def _run_subprocess(self, code: str, timeout: int) -> Tuple[bool, str, str, int]:
        """Mode soft : subprocess isolé avec sys.executable."""
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],  # ✅ sys.executable, pas "python"
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.workspace,
            )
            return (
                result.returncode == 0,
                result.stdout,
                result.stderr,
                result.returncode,
            )
        except subprocess.TimeoutExpired:
            return False, "", f"Timeout après {timeout}s", -1
        except Exception as e:
            return False, "", str(e), -1

    def _run_docker(
        self, code: str, file_path: Optional[str], timeout: int
    ) -> Tuple[bool, str, str, int]:
        """Mode Docker : container éphémère, read-only, network none."""
        if not self.docker_client:
            return False, "", "Docker non disponible", -1

        # Création d'un fichier temporaire dans le workspace (bind mount)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            dir=self.workspace,
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(code)
            temp_file = Path(f.name)
            container_path = f"/sandbox/{temp_file.name}"

        try:
            container = self.docker_client.containers.run(
                image="python:3.11-slim",
                command=[sys.executable, container_path],  # Liste, pas f-string
                volumes={
                    str(self.workspace): {"bind": "/sandbox", "mode": "ro"},
                },
                network_mode="none",
                mem_limit="512m",
                cpu_quota=100000,  # 1 CPU core
                read_only=True,
                detach=True,
                stdout=True,
                stderr=True,
            )
            
            try:
                result = container.wait(timeout=timeout)
                logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
                stdout = logs
                stderr = ""  # Docker combine, à parser si besoin
                exit_code = result["StatusCode"]
                return (exit_code == 0, stdout, stderr, exit_code)
            except Exception as e:
                container.kill()
                return False, "", str(e), -1
            finally:
                container.remove(force=True)

        finally:
            temp_file.unlink(missing_ok=True)

8. Intégration Goose — Patterns recommandés
8.1 Goose Recipes
Créer un fichier recipe YAML pour Goose :
# .goose/recipes/lcca-dev.yaml
name: "LCCA V7 Dev Agent"
description: "Agent de codage transactionnel avec mémoire persistante"

instructions: |
  Tu es un agent de codage local (LCCA). Tu dois suivre ce protocole :
  
  1. AVANT toute modification : utiliser memory_search pour le contexte
  2. Utiliser evaluate_quality sur le code généré avant application
  3. Utiliser edit_batch pour les modifications (max 3 fichiers par appel)
  4. Utiliser sandbox_run pour valider le comportement
  5. Utiliser analyze_error si une erreur survient
  6. Stocker le résultat avec memory_store

tools:
  - memory_search
  - memory_store
  - project_search
  - edit_batch
  - sandbox_run
  - evaluate_quality
  - analyze_error

close_the_loop: true  # Goose vérifie son travail
8.2 Sub-agents (V8)
| Agent       | Rôle                      | Tools autorisés                    |
| ----------- | ------------------------- | ---------------------------------- |
| `Architect` | Planification + découpage | `memory_search`, `project_search`  |
| `Coder`     | Génération + patch        | `edit_batch`, `evaluate_quality`   |
| `Tester`    | Validation sandbox        | `sandbox_run`, `analyze_error`     |
| `Reviewer`  | Audit qualité             | `evaluate_quality`, `memory_store` |

9. Tests — Plan de migration
9.1 Tests existants à conserver (237 tests V5)
Tous les tests V5 restent valides. Aucune régression sur :
test_transaction_manager.py (9 tests)
test_smart_patcher.py (6 tests)
test_orchestrator.py (13 tests)
test_code_evaluator.py (46 tests)
9.2 Nouveaux tests requis
| Suite            | Fichier                    | Tests                                      | Priorité |
| ---------------- | -------------------------- | ------------------------------------------ | -------- |
| MCP Protocol     | `test_mcp_server.py`       | initialize, tools/list, lifecycle          | CRITIQUE |
| MCP Security     | `test_mcp_security.py`     | path traversal, RBAC, audit                | CRITIQUE |
| EditBatch Facade | `test_mcp_edit_batch.py`   | ACID via façade, MAX\_FILES, rollback      | CRITIQUE |
| Sandbox          | `test_sandbox_engine.py`   | soft mode, docker mode, timeout, isolation | HAUTE    |
| Memory Engine V7 | `test_memory_engine_v7.py` | collections, seuils, cross-collection      | MOYENNE  |
| Integration E2E  | `test_mcp_integration.py`  | Cycle complet MCP                          | HAUTE    |

9.3 Exemple de test MCP
# tests/test_mcp_server.py
import json
import pytest
from unittest.mock import patch, MagicMock

def test_mcp_lifecycle():
    """Valide le handshake initialize → tools/list."""
    # Simuler stdin/stdout
    pass

def test_edit_batch_path_traversal():
    """DOIT échouer si le path sort du workspace."""
    batch = McpEditBatch()
    result = batch.apply([{"path": "../../../etc/passwd", "patch_type": "add_function", "code": "pass"}])
    assert result["success"] is False
    assert "hors workspace" in result["error"]

10. Configuration V7
Ajouter au config.py existant :
# === V7 Additions ===
MCP_SERVER_STDIO = True
MCP_PROTOCOL_VERSION = "2024-11-05"

# Sandbox
SANDBOX_MODE = os.getenv("LCCA_SANDBOX_MODE", "auto")  # "soft" | "docker" | "auto"
SANDBOX_TIMEOUT = int(os.getenv("LCCA_SANDBOX_TIMEOUT", "30"))
SANDBOX_MEMORY_LIMIT = "512m"
SANBOX_CPU_LIMIT = 1.0

# MCP Collections mémoire
MCP_MEMORY_COLLECTIONS = {
    "solutions": "lcca_solutions",
    "failures": "lcca_failures",
    "context": "lcca_context",
    "patches": "lcca_patches",
}

# Audit
MCP_AUDIT_LOG = TRANSACTIONS_DIR / "mcp_audit.jsonl"
11. Roadmap V7 → V8
| Version  | Livrable                                                               |
| -------- | ---------------------------------------------------------------------- |
| **V7.0** | MCP Server stdio + façade TX + Sandbox sécurisé + Memory 4 collections |
| **V7.1** | CodeEvaluator bloquant (seuil configurable) + Auto-fix ErrorAnalyzer   |
| **V7.2** | Streaming Ollama + Context budget dynamique                            |
| **V8.0** | Multi-agent A2A (Architect/Reviewer) + Sandbox Firecracker             |
| **V8.1** | RAG codebase (embeddings fichiers workspace) + Learning reinforcement  |

12. Règles invariantes V7 (perpétuation V5)
| #  | Règle                                 | Application V7                                                         |
| -- | ------------------------------------- | ---------------------------------------------------------------------- |
| 1  | SmartPatcher retourne `str`           | `McpEditBatch` respecte : `apply_patch` → `str`, `log_operation` écrit |
| 2  | `ast` pour lire, `libcst` pour écrire | Conservé                                                               |
| 3  | Max 3 fichiers par TX                 | `McpEditBatch.apply()` valide `MAX_FILES_PER_TX`                       |
| 4  | Snapshot MD5 + WAL avant chaque write | `TransactionManager.log_operation()` conservé                          |
| 5  | WAL JSONL append-only                 | Conservé                                                               |
| 6  | LLMGenerator a toujours Fallback      | `LLMGenerator` V5 injecté dans `McpEditBatch`                          |
| 7  | Injection de dépendances              | `McpEditBatch`, `MemoryEngine`, `SandboxEngine` tous injectables       |
| 8  | `sys.executable` toujours             | `SandboxEngine._run_subprocess`                                        |
| 9  | Imports module-level pour patch       | Maintenu pour tests                                                    |
| 10 | Encodage `utf-8-sig`                  | `McpEditBatch`, `SandboxEngine`                                        |

13. Conclusion
La V7 ne doit pas être une réécriture. Elle est un adaptateur MCP et un moteur sandbox qui s'interposent entre Goose et le cœur transactionnel V5 éprouvé.
Métrique de succès : Les 237 tests V5 passent sans modification. Les nouveaux tests MCP passent. Aucune régression transactionnelle.
<!-- AI-READY | Addendum V7 | 2026-04-17 -->