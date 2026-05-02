# Sprint 13 — V7 McpEditBatch + MemoryEngine + Cache LLM v7
<!-- AI-READY | Sprint V7.0 | Phase 2/5 | 2026-04-17 -->

## 🎯 Objectif
Implémenter les deux composants cœur de la couche MCP :
1. `core/mcp_edit_batch.py` — Façade transactionnelle AtomicBatch sur le TX Manager V5
2. `core/memory_engine.py` — Moteur mémoire V7 (4 collections MemPalace)
3. Upgrade `core/llm_generator.py` — Cache versionné par modèle (correctif V7)
4. Script `scripts/migrate_cache_v6_to_v7.py` — Migration one-shot legacy cache

**Résultat attendu** : ≥ 261 + ~35 nouveaux tests PASSED, 0 FAILED.

---

## 📋 TÂCHES

### TASK-13-01 — `core/mcp_edit_batch.py` : Façade transactionnelle

**Fichier** : `D:\LLMCodeAgent\core\mcp_edit_batch.py` *(nouveau)*

```python
# -*- coding: utf-8-sig -*-
"""
mcp_edit_batch.py — LCCA V7
Façade transactionnelle exposée via le MCP Server.

McpEditBatch est un adaptateur entre le protocole MCP et le cœur V5 :
- Valide les arguments (paths, nb fichiers, workspace containment)
- Délègue à TransactionManager + SmartPatcher pour les patches ACID
- Évalue la qualité via CodeEvaluator (informatif V7.0, bloquant V7.1)
- Ne contourne JAMAIS le système de snapshot/WAL V5

Sprint 13 — TASK-13-01
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import WORKSPACE_DIR, MAX_FILES_PER_TX, FILE_ENCODING
from core.transaction_manager import TransactionManager, OpType
from core.smart_patcher import SmartPatcher
from core.code_evaluator import CodeEvaluator
from utils.safe_path import safe_path, PathSecurityError

log = logging.getLogger("lcca.mcp_edit_batch")


class McpEditBatch:
    """
    Façade MCP pour l'application atomique d'un batch de modifications.

    Garantit :
    - MAX_FILES_PER_TX respecté (config.py)
    - Workspace containment via safe_path()
    - ACID complet via TransactionManager V5
    - SmartPatcher retourne str (jamais n'écrit seul)
    - Rollback automatique en cas d'erreur

    Args:
        tx_manager : Instance injectée (test) ou créée automatiquement.
        patcher    : Instance SmartPatcher injectée ou créée automatiquement.
        evaluator  : Instance CodeEvaluator injectée ou créée automatiquement.
        workspace  : Répertoire workspace (défaut WORKSPACE_DIR).
    """

    def __init__(
        self,
        tx_manager: Optional[TransactionManager] = None,
        patcher:    Optional[SmartPatcher]        = None,
        evaluator:  Optional[CodeEvaluator]       = None,
        workspace:  Optional[Path]                = None,
    ) -> None:
        self.workspace  = workspace or WORKSPACE_DIR
        self.tx_manager = tx_manager or TransactionManager()
        self.patcher    = patcher    or SmartPatcher(workspace=self.workspace)
        self.evaluator  = evaluator  or CodeEvaluator(threshold=60)

    # ── Interface publique ──────────────────────────────────────────────────

    def apply(self, files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Applique un batch de modifications de manière atomique.

        Args:
            files: Liste de dicts :
                {
                    "path":       "relative/path.py",   # Obligatoire
                    "patch_type": "add_function",        # Obligatoire sauf action=create
                    "action":     "create",              # Optionnel
                    "symbol":     "function_name",       # Optionnel
                    "code":       "def foo(): ...",      # Optionnel
                }

        Returns:
            {"success": True, "tx_id": str, "evaluations": [...]}
            {"success": False, "error": str, "rolled_back": bool}
        """
        # ── Validation pré-TX ────────────────────────────────────────────
        if not files:
            return {"success": False, "error": "Liste de fichiers vide", "rolled_back": False}

        if len(files) > MAX_FILES_PER_TX:
            return {
                "success":    False,
                "error":      f"Trop de fichiers ({len(files)} > {MAX_FILES_PER_TX})",
                "rolled_back": False,
            }

        # Validation workspace containment via safe_path()
        validated_paths: List[Path] = []
        for f in files:
            try:
                full_path = safe_path(f["path"], workspace=self.workspace)
                validated_paths.append(full_path)
            except (PathSecurityError, ValueError) as exc:
                return {"success": False, "error": str(exc), "rolled_back": False}
            except KeyError:
                return {"success": False, "error": "Champ 'path' manquant", "rolled_back": False}

        # ── Transaction ──────────────────────────────────────────────────
        tx_id = self.tx_manager.begin(
            dsl_input="mcp_edit_batch",
            project="lcca_v7",
            intent=f"batch_{len(files)}_files",
        )

        evaluations: List[Dict] = []
        try:
            for op, full_path in zip(files, validated_paths):
                action = op.get("action", "patch")

                if action == "create":
                    new_code = op.get("code", "")
                    if not new_code.strip():
                        raise ValueError(f"Code vide pour création : {op['path']}")

                    eval_result = self.evaluator.evaluate(new_code, filename=op["path"])
                    evaluations.append(eval_result.to_dict() if hasattr(eval_result, "to_dict") else {})

                    def _do_create(_path=full_path, _code=new_code):
                        _path.parent.mkdir(parents=True, exist_ok=True)
                        _path.write_text(_code, encoding=FILE_ENCODING)

                    self.tx_manager.log_operation(
                        target_path=full_path,
                        op_type=OpType.CREATE_FILE,
                        execute_func=_do_create,
                        metadata={"action": "create", "symbol": op.get("symbol")},
                    )

                else:
                    # Patch via SmartPatcher (retourne str, n'écrit PAS)
                    new_code = self.patcher.apply_patch(
                        file_path=op["path"],
                        patch_type=op.get("patch_type", "add_function"),
                        code=op.get("code"),
                        name=op.get("symbol"),
                    )

                    eval_result = self.evaluator.evaluate(new_code, filename=op["path"])
                    evaluations.append(eval_result.to_dict() if hasattr(eval_result, "to_dict") else {})

                    # V7.0 : informatif uniquement (score bas = warning, pas blocage)
                    if hasattr(eval_result, "score") and eval_result.score < 40:
                        log.warning(
                            "Qualité faible pour %s : %d/100",
                            op["path"], eval_result.score
                        )

                    def _do_patch(_path=full_path, _code=new_code):
                        _path.write_text(_code, encoding=FILE_ENCODING)

                    self.tx_manager.log_operation(
                        target_path=full_path,
                        op_type=OpType.PATCH_FILE,
                        execute_func=_do_patch,
                        metadata={
                            "patch_type":    op.get("patch_type"),
                            "symbol":        op.get("symbol"),
                            "quality_score": getattr(eval_result, "score", -1),
                        },
                    )

            # Validation syntaxe post-patch (double garde)
            self._validate_batch_syntax(validated_paths)

            self.tx_manager.commit()
            log.info("McpEditBatch committed — tx_id=%s files=%d", tx_id, len(files))
            return {"success": True, "tx_id": tx_id, "evaluations": evaluations}

        except Exception as exc:
            log.error("McpEditBatch rollback — %s", exc)
            self.tx_manager.rollback(reason=str(exc))
            return {"success": False, "error": str(exc), "rolled_back": True}

    # ── Helpers privés ──────────────────────────────────────────────────────

    def _validate_batch_syntax(self, paths: List[Path]) -> None:
        """Valide la syntaxe de chaque fichier modifié (compile())."""
        for path in paths:
            if path.exists():
                source = path.read_text(encoding=FILE_ENCODING)
                compile(source, str(path), "exec")   # SyntaxError → déclenche rollback
```

---

### TASK-13-02 — `core/memory_engine.py` : Moteur mémoire V7

**Fichier** : `D:\LLMCodeAgent\core\memory_engine.py` *(nouveau)*

```python
# -*- coding: utf-8-sig -*-
"""
memory_engine.py — LCCA V7
Moteur mémoire 4 collections : solutions, failures, context, patches.

Mappe les 4 collections V7 sur l'architecture existante MemPalace V5 :
- lcca_solutions : code validé et fonctionnel (seuil ≥ 0.8)
- lcca_failures  : erreurs + correctifs (toujours stocker)
- lcca_context   : snippets récents (seuil ≥ 0.6)
- lcca_patches   : historique complet TX (toujours stocker)

Sprint 13 — TASK-13-02
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config import MCP_MEMORY_COLLECTIONS

log = logging.getLogger("lcca.memory_engine")


@dataclass
class MemoryEntry:
    """Entrée mémoire cross-collection."""
    collection: str
    content:    str
    metadata:   Dict[str, Any] = field(default_factory=dict)
    score:      float = 0.0
    entry_id:   str = ""


class MemoryEngine:
    """
    Interface unifiée vers les 4 collections MemPalace V7.

    Args:
        adapter : ExistingMemPalaceAdapter V5 (injection pour tests).

    Note:
        Si le MemPalace est indisponible, toutes les opérations sont no-op
        silencieux (l'agent peut fonctionner sans mémoire persistante).
    """

    # Seuils de stockage par collection
    STORE_THRESHOLDS: Dict[str, Optional[float]] = {
        "lcca_solutions": 0.8,    # Qualité haute requise
        "lcca_failures":  None,   # Toujours stocker (apprentissage par échec)
        "lcca_context":   0.6,    # Qualité moyenne acceptable
        "lcca_patches":   None,   # Toujours stocker (audit complet)
    }

    def __init__(self, adapter=None) -> None:
        self._adapter = adapter
        if adapter is None:
            try:
                from core.mempalace_adapter import ExistingMemPalaceAdapter
                self._adapter = ExistingMemPalaceAdapter()
            except Exception as exc:
                log.warning("MemPalace indisponible : %s — mode no-op", exc)
                self._adapter = None

        # ContextAssembler V5 réutilisé
        self._context_assembler = None
        try:
            from core.context_assembler import ContextAssembler
            self._context_assembler = ContextAssembler()
        except Exception:
            pass

    @property
    def is_available(self) -> bool:
        """True si le MemPalace est accessible."""
        return self._adapter is not None and getattr(self._adapter, "is_available", False)

    # ── Recherche ──────────────────────────────────────────────────────────

    def search(
        self,
        query:  str,
        wing:   str = "lcca",
        n:      int = 5,
        collections: Optional[List[str]] = None,
    ) -> Dict[str, List[MemoryEntry]]:
        """
        Recherche cross-collection.

        Args:
            query       : Texte de recherche sémantique.
            wing        : Aile MemPalace (défaut "lcca").
            n           : Nombre de résultats par collection.
            collections : Sous-ensemble de collections à interroger
                          (défaut : toutes sauf lcca_patches).

        Returns:
            Dict {"solutions": [...], "failures": [...], "context": [...]}
        """
        if not self.is_available:
            return {"solutions": [], "failures": [], "context": []}

        targets = collections or ["lcca_solutions", "lcca_failures", "lcca_context"]
        results: Dict[str, List[MemoryEntry]] = {}

        for col in targets:
            key = col.replace("lcca_", "")
            try:
                raw = self._adapter.search(col, query, wing=wing, n=n)
                results[key] = [self._to_entry(col, r) for r in (raw or [])]
            except Exception as exc:
                log.debug("Recherche %s échouée : %s", col, exc)
                results[key] = []

        return results

    # ── Stockage ───────────────────────────────────────────────────────────

    def store(self, collection: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Stocke dans une collection avec application du seuil de qualité.

        Args:
            collection : Nom de collection (ex: "lcca_solutions").
            payload    : Dict avec au minimum {"content": str}.
                         "score" optionnel pour filtrage par seuil.

        Returns:
            {"stored": True, "entry_id": str}
            {"stored": False, "reason": str}
        """
        if not self.is_available:
            return {"stored": False, "reason": "MemPalace indisponible"}

        threshold = self.STORE_THRESHOLDS.get(collection)

        # Application du seuil de qualité
        if threshold is not None:
            score = payload.get("score", 0.0)
            if isinstance(score, (int, float)) and score < threshold:
                return {
                    "stored": False,
                    "reason": f"score {score:.2f} < seuil {threshold:.2f} pour {collection}",
                }

        try:
            entry_id = self._adapter.store(collection, payload)
            return {"stored": True, "entry_id": entry_id or ""}
        except Exception as exc:
            log.warning("Stockage %s échoué : %s", collection, exc)
            return {"stored": False, "reason": str(exc)}

    # ── Store helpers sémantiques ──────────────────────────────────────────

    def store_solution(self, code: str, score: float, metadata: Dict = None) -> Dict:
        """Raccourci pour stocker dans lcca_solutions."""
        return self.store("lcca_solutions", {
            "content": code, "score": score, **(metadata or {})
        })

    def store_failure(self, error: str, context: str = "", metadata: Dict = None) -> Dict:
        """Raccourci pour stocker dans lcca_failures. Toujours stocké."""
        return self.store("lcca_failures", {
            "content": f"ERROR: {error}\nCONTEXT: {context}", **(metadata or {})
        })

    def store_patch(self, tx_id: str, patch_summary: str, metadata: Dict = None) -> Dict:
        """Raccourci pour stocker dans lcca_patches. Toujours stocké."""
        return self.store("lcca_patches", {
            "content": patch_summary, "tx_id": tx_id, **(metadata or {})
        })

    # ── Privé ──────────────────────────────────────────────────────────────

    def _to_entry(self, collection: str, raw: Any) -> MemoryEntry:
        """Convertit une entrée brute du MemPalace en MemoryEntry."""
        if isinstance(raw, dict):
            return MemoryEntry(
                collection=collection,
                content=raw.get("content", str(raw)),
                metadata=raw.get("metadata", {}),
                score=raw.get("score", 0.0),
                entry_id=raw.get("id", ""),
            )
        return MemoryEntry(collection=collection, content=str(raw))
```

---

### TASK-13-03 — `core/llm_generator.py` : Cache versionné par modèle

**Fichier** : `D:\LLMCodeAgent\core\llm_generator.py`
**Opérations** : Modifier 3 méthodes et ajouter `_cache_get_meta`/`_cache_set_meta`

**A. Modifier `_cache_key`** :
```python
def _cache_key(self, system: str, user: str) -> str:
    """Hash MD5 unique par (modèle, system, user) — V7 versionné par modèle."""
    payload = f"{self.ollama.model}\n{system}\n{user}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()
```

**B. Ajouter méthode `_cache_meta_path`** :
```python
def _cache_meta_path(self, key: str) -> Path:
    return self.cache_dir / f"{key}.json"
```

**C. Modifier `_cache_get`** :
```python
def _cache_get(self, key: str) -> Optional[str]:
    """Lit le cache avec validation du modèle (V7)."""
    p = self._cache_path(key)
    if not p.exists():
        return None
    # Validation metadata modèle
    meta_path = self._cache_meta_path(key)
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            cached_model = meta.get("model", "unknown")
            # Invalider si modèle différent OU legacy "unknown" vs modèle réel
            if cached_model == "unknown" and self.ollama.model != "unknown":
                return None
            if cached_model != "unknown" and cached_model != self.ollama.model:
                return None
        except Exception:
            pass  # Metadata corrompue → on fait confiance au .py existant
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None
```

**D. Modifier `_cache_set`** :
```python
def _cache_set(self, key: str, code: str) -> None:
    """Écrit le cache + metadata modèle (V7)."""
    try:
        from datetime import datetime, timezone
        self._cache_path(key).write_text(code, encoding="utf-8")
        self._cache_meta_path(key).write_text(
            json.dumps({
                "model":     self.ollama.model,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version":   "7.0",
            }, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception as exc:
        log.warning("Cache write failed: %s", exc)
```

---

### TASK-13-04 — `scripts/migrate_cache_v6_to_v7.py` : Migration one-shot

**Fichier** : `D:\LLMCodeAgent\scripts\migrate_cache_v6_to_v7.py` *(nouveau)*

```python
#!/usr/bin/env python3
# -*- coding: utf-8-sig -*-
"""
migrate_cache_v6_to_v7.py — Script one-shot
Génère les fichiers metadata JSON manquants pour les caches LLM legacy.
A exécuter une seule fois après mise à jour vers V7.

Usage:
    python scripts/migrate_cache_v6_to_v7.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ajouter le projet au path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from config import LLM_CACHE_DIR
except ImportError:
    LLM_CACHE_DIR = Path("D:/LLMCodeAgent/transactions/.llm_cache")


def migrate() -> None:
    if not LLM_CACHE_DIR.exists():
        print(f"Cache dir introuvable : {LLM_CACHE_DIR}")
        return

    migrated = skipped = errors = 0

    for py_file in LLM_CACHE_DIR.glob("*.py"):
        meta_file = py_file.with_suffix(".json")
        if meta_file.exists():
            skipped += 1
            continue
        try:
            meta = {
                "model":        "unknown",
                "migrated_at":  datetime.now(timezone.utc).isoformat(),
                "note":         "Cache généré avant versionnement V7 (migration automatique)",
            }
            meta_file.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            migrated += 1
        except Exception as exc:
            print(f"  ⚠ Erreur {py_file.name}: {exc}")
            errors += 1

    print(
        f"Migration V6→V7 terminée : {migrated} créés, "
        f"{skipped} déjà présents, {errors} erreurs."
    )


if __name__ == "__main__":
    migrate()
```

---

### TASK-13-05 — `core/__init__.py` : Exports V7

Ajouter imports dans `core/__init__.py` :
```python
# Sprint 13 — V7
from .mcp_edit_batch import McpEditBatch
from .memory_engine import MemoryEngine, MemoryEntry as MemoryEntryV7
```

Et dans `__all__` :
```python
# Sprint 13
"McpEditBatch",
"MemoryEngine",
"MemoryEntryV7",
```

---

## 🧪 TESTS

### `tests/test_mcp_edit_batch.py` *(nouveau — 18 tests)*

```python
# -*- coding: utf-8-sig -*-
"""Tests unitaires core/mcp_edit_batch.py — Sprint 13."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def batch(workspace):
    from core.transaction_manager import TransactionManager
    from core.mcp_edit_batch import McpEditBatch
    from unittest.mock import MagicMock
    tm = TransactionManager(
        tx_dir=workspace.parent / "tx",
        wal_path=workspace.parent / "wal.jsonl"
    )
    patcher = MagicMock()
    patcher.apply_patch.return_value = "def foo():\n    pass\n"
    evaluator = MagicMock()
    ev = MagicMock()
    ev.score = 80
    ev.to_dict.return_value = {"score": 80}
    evaluator.evaluate.return_value = ev
    return McpEditBatch(tx_manager=tm, patcher=patcher, evaluator=evaluator, workspace=workspace)


class TestMcpEditBatchValidation:
    def test_empty_files_fails(self, batch):
        result = batch.apply([])
        assert result["success"] is False

    def test_too_many_files_fails(self, batch):
        files = [{"path": f"f{i}.py", "patch_type": "add_function"} for i in range(10)]
        result = batch.apply(files)
        assert result["success"] is False
        assert "Trop de fichiers" in result["error"]

    def test_path_traversal_blocked(self, batch):
        result = batch.apply([{"path": "../../../etc/passwd", "patch_type": "add_function"}])
        assert result["success"] is False
        assert result.get("rolled_back") is False  # Pas de TX ouverte

    def test_absolute_path_blocked(self, batch):
        result = batch.apply([{"path": "/etc/passwd", "patch_type": "add_function"}])
        assert result["success"] is False

    def test_missing_path_field(self, batch):
        result = batch.apply([{"patch_type": "add_function"}])
        assert result["success"] is False


class TestMcpEditBatchSuccess:
    def test_patch_commits(self, batch, workspace):
        (workspace / "existing.py").write_text("x = 1\n", encoding="utf-8")
        result = batch.apply([{
            "path": "existing.py",
            "patch_type": "add_function",
            "symbol": "foo",
            "code": "def foo():\n    pass\n",
        }])
        assert result["success"] is True
        assert "tx_id" in result
        assert result["tx_id"].startswith("tx_")

    def test_evaluations_in_result(self, batch, workspace):
        (workspace / "m.py").write_text("x = 1\n", encoding="utf-8")
        result = batch.apply([{"path": "m.py", "patch_type": "add_function"}])
        assert result["success"] is True
        assert isinstance(result["evaluations"], list)

    def test_create_file_action(self, batch, workspace):
        result = batch.apply([{
            "path": "new_module.py",
            "action": "create",
            "code": "def hello():\n    pass\n",
        }])
        assert result["success"] is True
        assert (workspace / "new_module.py").exists()

    def test_create_rollback_removes_file(self, workspace):
        """CREATE + erreur → rollback supprime le fichier."""
        from core.transaction_manager import TransactionManager
        from core.mcp_edit_batch import McpEditBatch
        tm = TransactionManager(
            tx_dir=workspace.parent / "tx",
            wal_path=workspace.parent / "wal.jsonl"
        )
        # Patcher qui lève une exception
        patcher = MagicMock()
        patcher.apply_patch.side_effect = RuntimeError("patch error")
        evaluator = MagicMock()
        ev = MagicMock()
        ev.score = 80
        ev.to_dict.return_value = {}
        evaluator.evaluate.return_value = ev
        batch = McpEditBatch(tm, patcher, evaluator, workspace)

        new_file = workspace / "will_be_removed.py"
        # Le fichier sera créé puis la 2ème opération échoue
        result = batch.apply([
            {"path": "will_be_removed.py", "action": "create", "code": "x = 1\n"},
            {"path": "bad.py", "patch_type": "add_function"},
        ])
        assert result["success"] is False
        assert result["rolled_back"] is True
        assert not new_file.exists()


class TestMcpEditBatchRollback:
    def test_rollback_on_syntax_error(self, workspace):
        from core.transaction_manager import TransactionManager
        from core.mcp_edit_batch import McpEditBatch
        tm = TransactionManager(
            tx_dir=workspace.parent / "tx",
            wal_path=workspace.parent / "wal.jsonl"
        )
        patcher = MagicMock()
        # Code invalide → _validate_batch_syntax lève SyntaxError
        patcher.apply_patch.return_value = "def foo(\n"
        evaluator = MagicMock()
        ev = MagicMock()
        ev.score = 80
        ev.to_dict.return_value = {}
        evaluator.evaluate.return_value = ev

        target = workspace / "target.py"
        target.write_text("x = 1\n", encoding="utf-8")
        batch = McpEditBatch(tm, patcher, evaluator, workspace)
        result = batch.apply([{"path": "target.py", "patch_type": "add_function"}])
        assert result["success"] is False
        assert result["rolled_back"] is True
        # Le fichier original doit être restauré
        assert target.read_text(encoding="utf-8") == "x = 1\n"


class TestLLMCacheVersioned:
    def test_cache_key_includes_model(self):
        from core.llm_generator import LLMGenerator
        gen = LLMGenerator.__new__(LLMGenerator)
        from unittest.mock import MagicMock
        gen.ollama = MagicMock()
        gen.ollama.model = "model-a"
        key_a = gen._cache_key("sys", "user")
        gen.ollama.model = "model-b"
        key_b = gen._cache_key("sys", "user")
        assert key_a != key_b, "Clés identiques pour modèles différents !"

    def test_cache_miss_on_model_mismatch(self, tmp_path):
        import json
        from core.llm_generator import LLMGenerator
        gen = LLMGenerator.__new__(LLMGenerator)
        from unittest.mock import MagicMock
        gen.ollama = MagicMock()
        gen.ollama.model = "new-model"
        gen.cache_dir = tmp_path
        key = "aabbccdd1234"
        (tmp_path / f"{key}.py").write_text("def foo(): pass", encoding="utf-8")
        (tmp_path / f"{key}.json").write_text(
            json.dumps({"model": "old-model", "version": "7.0"}), encoding="utf-8"
        )
        result = gen._cache_get(key)
        assert result is None, "Cache hit attendu comme miss (modèle différent)"

    def test_cache_unknown_model_invalidated(self, tmp_path):
        import json
        from core.llm_generator import LLMGenerator
        gen = LLMGenerator.__new__(LLMGenerator)
        from unittest.mock import MagicMock
        gen.ollama = MagicMock()
        gen.ollama.model = "real-model"
        gen.cache_dir = tmp_path
        key = "ccddeeff5678"
        (tmp_path / f"{key}.py").write_text("x = 1", encoding="utf-8")
        (tmp_path / f"{key}.json").write_text(
            json.dumps({"model": "unknown"}), encoding="utf-8"
        )
        result = gen._cache_get(key)
        assert result is None

    def test_cache_hit_same_model(self, tmp_path):
        import json
        from core.llm_generator import LLMGenerator
        gen = LLMGenerator.__new__(LLMGenerator)
        from unittest.mock import MagicMock
        gen.ollama = MagicMock()
        gen.ollama.model = "qwen2.5-coder:14b"
        gen.cache_dir = tmp_path
        key = "11223344aabb"
        (tmp_path / f"{key}.py").write_text("def bar(): pass", encoding="utf-8")
        (tmp_path / f"{key}.json").write_text(
            json.dumps({"model": "qwen2.5-coder:14b", "version": "7.0"}), encoding="utf-8"
        )
        result = gen._cache_get(key)
        assert result == "def bar(): pass"
```

### `tests/test_memory_engine.py` *(nouveau — 12 tests)*

```python
# -*- coding: utf-8-sig -*-
"""Tests unitaires core/memory_engine.py — Sprint 13."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_adapter():
    adapter = MagicMock()
    adapter.is_available = True
    adapter.search.return_value = [{"content": "code...", "score": 0.9, "id": "e1"}]
    adapter.store.return_value = "entry_001"
    return adapter


@pytest.fixture
def engine(mock_adapter):
    from core.memory_engine import MemoryEngine
    return MemoryEngine(adapter=mock_adapter)


class TestMemoryEngineAvailability:
    def test_available_with_adapter(self, engine):
        assert engine.is_available is True

    def test_unavailable_without_adapter(self):
        from core.memory_engine import MemoryEngine
        eng = MemoryEngine.__new__(MemoryEngine)
        eng._adapter = None
        eng._context_assembler = None
        assert eng.is_available is False


class TestMemoryEngineSearch:
    def test_search_returns_dict(self, engine):
        result = engine.search("add_function validate")
        assert isinstance(result, dict)
        assert "solutions" in result

    def test_search_unavailable_returns_empty(self):
        from core.memory_engine import MemoryEngine
        eng = MemoryEngine.__new__(MemoryEngine)
        eng._adapter = None
        eng._context_assembler = None
        result = eng.search("query")
        assert result == {"solutions": [], "failures": [], "context": []}

    def test_search_calls_adapter(self, engine, mock_adapter):
        engine.search("query", n=3)
        assert mock_adapter.search.called

    def test_search_handles_adapter_exception(self, engine, mock_adapter):
        mock_adapter.search.side_effect = RuntimeError("MemPalace down")
        result = engine.search("query")
        # Ne doit pas lever, retourner listes vides
        for v in result.values():
            assert isinstance(v, list)


class TestMemoryEngineStore:
    def test_store_solution_above_threshold(self, engine):
        result = engine.store("lcca_solutions", {"content": "code", "score": 0.9})
        assert result["stored"] is True

    def test_store_solution_below_threshold(self, engine):
        result = engine.store("lcca_solutions", {"content": "code", "score": 0.5})
        assert result["stored"] is False
        assert "seuil" in result["reason"]

    def test_store_failure_always(self, engine):
        """lcca_failures : toujours stocker, peu importe le score."""
        result = engine.store("lcca_failures", {"content": "error", "score": 0.0})
        assert result["stored"] is True

    def test_store_patches_always(self, engine):
        result = engine.store("lcca_patches", {"content": "patch_summary", "score": 0.0})
        assert result["stored"] is True

    def test_store_unavailable(self):
        from core.memory_engine import MemoryEngine
        eng = MemoryEngine.__new__(MemoryEngine)
        eng._adapter = None
        eng._context_assembler = None
        result = eng.store("lcca_failures", {"content": "x"})
        assert result["stored"] is False

    def test_store_solution_helper(self, engine):
        r = engine.store_solution("def foo(): pass", score=0.85)
        assert r["stored"] is True

    def test_store_failure_helper(self, engine):
        r = engine.store_failure("TypeError", context="line 42")
        assert r["stored"] is True

    def test_store_patch_helper(self, engine):
        r = engine.store_patch("tx_abc123", "patch résumé")
        assert r["stored"] is True
```

---

## 📦 FICHIERS NOUVEAUX / MODIFIÉS

| Fichier | Action | Tests |
|---------|--------|-------|
| `core/mcp_edit_batch.py` | CREATE | `test_mcp_edit_batch.py` (18 tests) |
| `core/memory_engine.py` | CREATE | `test_memory_engine.py` (12 tests) |
| `core/llm_generator.py` | PATCH (3 méthodes + 1 ajout) | `test_llm_generator.py` (+4) |
| `core/__init__.py` | PATCH (exports) | `test_smoke.py` |
| `scripts/migrate_cache_v6_to_v7.py` | CREATE | Manuel |
| `tests/test_mcp_edit_batch.py` | CREATE | — |
| `tests/test_memory_engine.py` | CREATE | — |

---

## ✅ CRITÈRES D'ACCEPTATION

- [ ] `pytest tests/ -v` → ≥ 295 PASSED, 0 FAILED
- [ ] `McpEditBatch.apply()` avec path traversal → `success: False`, `rolled_back: False`
- [ ] `McpEditBatch.apply()` avec CREATE_FILE + erreur → fichier supprimé par rollback
- [ ] `MemoryEngine.store("lcca_solutions", {"score": 0.5})` → `stored: False`
- [ ] `MemoryEngine.store("lcca_failures", {"score": 0.0})` → `stored: True`
- [ ] `LLMGenerator._cache_key` inclut le nom du modèle
- [ ] Cache miss si modèle metadata ≠ modèle courant
- [ ] 0 régression sur les 261 tests Sprint 12

---

## 🔗 DÉPENDANCES

- **Bloque** : Sprint 14 (SandboxEngine), Sprint 15 (MCP Server)
- **Dépend de** : Sprint 12 (safe_path, telemetry, OpType.CREATE_FILE)
- **Réutilise** : `TransactionManager`, `SmartPatcher`, `CodeEvaluator`, `ExistingMemPalaceAdapter`

<!-- Sprint 13 | V7 McpEditBatch + MemoryEngine | LCCA V7.0.0-rc1 | 2026-04-17 -->
