# Sprint 12 — V7 Fondations MCP : config, safe_path, telemetry, OpType.CREATE_FILE
<!-- AI-READY | Sprint V7.0 | Phase 1/5 | 2026-04-17 -->

## 🎯 Objectif
Poser les fondations V7 sans toucher à la logique métier V5 :
1. Étendre `config.py` avec les constantes MCP/Sandbox
2. Créer `utils/safe_path.py` — validation anti-path-traversal
3. Créer `utils/telemetry.py` — métriques JSONL avec rotation
4. Étendre `core/transaction_manager.py` avec `OpType.CREATE_FILE` + rollback amélioré + cleanup WAL
5. Mettre à jour `core/__init__.py` + `__version__`

**Résultat attendu** : ≥ 237 + ~25 nouveaux tests PASSED, 0 FAILED.

---

## 📋 TÂCHES

### TASK-12-01 — `config.py` : Constantes V7
**Fichier** : `D:\LLMCodeAgent\config.py`
**Opération** : Append section V7 en fin de fichier

```python
import os  # Ajouter si absent

# ════════════════════════════════════════════════════════
# V7 — MCP Server
# ════════════════════════════════════════════════════════
MCP_SERVER_STDIO       = True
MCP_PROTOCOL_VERSION   = "2025-06-18"           # Draft MCP 2025
MCP_SERVER_NAME        = "lcca-v7-mcp"
MCP_SERVER_VERSION     = "7.0.0"

# V7 — Sandbox
SANDBOX_MODE           = os.getenv("LCCA_SANDBOX_MODE",    "auto")   # soft|docker|auto
SANDBOX_TIMEOUT        = int(os.getenv("LCCA_SANDBOX_TIMEOUT", "30"))
SANDBOX_MEMORY_LIMIT   = "512m"
SANDBOX_CPU_LIMIT      = 1.0
SANDBOX_IMAGE          = "python:3.11-slim"

# V7 — Collections mémoire MCP
MCP_MEMORY_COLLECTIONS = {
    "solutions": "lcca_solutions",
    "failures":  "lcca_failures",
    "context":   "lcca_context",
    "patches":   "lcca_patches",
}

# V7 — Audit
MCP_AUDIT_LOG          = TRANSACTIONS_DIR / "mcp_audit.jsonl"

# V7 — Nettoyage automatique TX
TX_AUTO_CLEANUP_DAYS   = int(os.getenv("LCCA_TX_CLEANUP_DAYS",    "7"))
WAL_AUTO_ARCHIVE_DAYS  = int(os.getenv("LCCA_WAL_ARCHIVE_DAYS",  "30"))
```

**Règles** :
- `import os` doit être ajouté EN TÊTE si non présent
- Aucune constante V5 ne doit être modifiée
- Toutes les nouvelles constantes sont en BAS du fichier, après `LLM_CACHE_DIR`

---

### TASK-12-02 — `utils/safe_path.py` : Validation anti-traversal

**Fichier** : `D:\LLMCodeAgent\utils\safe_path.py` *(nouveau)*

```python
# -*- coding: utf-8-sig -*-
"""
safe_path.py — LCCA V7
Utilitaire de validation de chemins contre les path traversal attacks.
Chaque tool MCP exposant un chemin DOIT utiliser safe_path().

Sprint 12 — TASK-12-02
"""
from __future__ import annotations

from pathlib import Path


class PathSecurityError(Exception):
    """Levée quand un chemin tente de sortir du workspace."""


def safe_path(relative_path: str, workspace: Path | None = None) -> Path:
    """
    Résout un chemin relatif et vérifie qu'il reste dans le workspace.

    Args:
        relative_path : Chemin relatif fourni par le client MCP.
        workspace     : Répertoire de confinement (défaut : WORKSPACE_DIR depuis config).

    Returns:
        Path absolu résolu, garanti dans le workspace.

    Raises:
        PathSecurityError : Si path traversal détecté ou chemin absolu.
        ValueError        : Si relative_path est vide.
    """
    if not relative_path or not str(relative_path).strip():
        raise ValueError("relative_path ne peut pas être vide")

    # Import ici pour éviter les imports circulaires
    if workspace is None:
        from config import WORKSPACE_DIR
        workspace = WORKSPACE_DIR

    rel = Path(str(relative_path).strip())

    # 1. Rejeter les chemins absolus (Windows et Unix)
    if rel.is_absolute():
        raise PathSecurityError(f"Chemin absolu interdit : {relative_path}")

    # 2. Défense en profondeur : rejeter '..' explicite
    if ".." in rel.parts:
        raise PathSecurityError(f"Séquence '..' interdite : {relative_path}")

    # 3. Résolution + vérification containment
    workspace_resolved = workspace.resolve()
    full = (workspace / rel).resolve()

    try:
        full.relative_to(workspace_resolved)
    except ValueError:
        raise PathSecurityError(
            f"Path traversal détecté : {relative_path!r} → {full} "
            f"hors de {workspace_resolved}"
        )

    return full
```

**Règles** :
- Import `config` en local (évite import circulaire au chargement du module)
- Priorité : chemin absolu → `'..'` → containment — ordre strict
- Ne jamais `os.path.join` avec une entrée non validée

---

### TASK-12-03 — `utils/telemetry.py` : Métriques JSONL

**Fichier** : `D:\LLMCodeAgent\utils\telemetry.py` *(nouveau)*

```python
# -*- coding: utf-8-sig -*-
"""
telemetry.py — LCCA V7
Observabilité minimale : métriques structurées JSONL avec rotation automatique.

Sprint 12 — TASK-12-03

Usage :
    from utils.telemetry import log_metric, MetricTimer

    log_metric("edit_batch_files", 3, {"project": "lcca"})

    with MetricTimer("mcp_request_duration", {"method": "tools/call"}):
        result = dispatch(...)
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# Handler rotatif singleton (idempotent)
_telemetry_handler: Optional[RotatingFileHandler] = None


def _ensure_logs_dir() -> Path:
    """Retourne LOGS_DIR depuis config, crée si absent."""
    try:
        from config import LOGS_DIR
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        return LOGS_DIR
    except ImportError:
        fallback = Path("D:/LLMCodeAgent/logs")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _get_telemetry_handler() -> RotatingFileHandler:
    """Initialise et retourne le handler rotatif (singleton)."""
    global _telemetry_handler
    if _telemetry_handler is not None:
        return _telemetry_handler

    logs_dir = _ensure_logs_dir()
    telemetry_path = logs_dir / "telemetry.jsonl"

    handler = RotatingFileHandler(
        telemetry_path,
        maxBytes=10 * 1024 * 1024,   # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    _telemetry_handler = handler
    return handler


def log_metric(name: str, value: float, labels: dict | None = None) -> None:
    """
    Écrit une métrique en format JSON Lines.

    Args:
        name   : Nom de la métrique (ex: "mcp_request_duration").
        value  : Valeur numérique.
        labels : Dictionnaire de labels (ex: {"method": "tools/call"}).

    Note:
        Silencieux en cas d'erreur disque — ne jamais bloquer le flux principal.
    """
    entry = {
        "_ts":    datetime.now(timezone.utc).isoformat(),
        "metric": name,
        "value":  value,
        "labels": labels or {},
    }
    try:
        handler = _get_telemetry_handler()
        record = logging.LogRecord(
            name="telemetry",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=json.dumps(entry, ensure_ascii=False),
            args=(),
            exc_info=None,
        )
        handler.emit(record)
    except Exception:
        pass   # Observabilité ne doit jamais crasher l'application


class MetricTimer:
    """
    Context manager pour mesurer une durée et l'émettre automatiquement.

    Usage :
        with MetricTimer("llm_generate_ms", {"model": "qwen2.5-coder:14b"}):
            result = llm.generate(...)
    """

    def __init__(self, name: str, labels: dict | None = None) -> None:
        self.name   = name
        self.labels = labels or {}
        self._start: float = 0.0

    def __enter__(self) -> "MetricTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_args) -> None:
        duration_ms = int((time.perf_counter() - self._start) * 1000)
        log_metric(self.name, duration_ms, {**self.labels, "unit": "ms"})
```

---

### TASK-12-04 — `core/transaction_manager.py` : CREATE_FILE + cleanup

**Fichier** : `D:\LLMCodeAgent\core\transaction_manager.py`
**Opérations** :

**A. Ajouter `CREATE_FILE` dans `OpType`** :
```python
class OpType(Enum):
    WRITE_FILE  = "write_file"
    EDIT_FILE   = "edit_file"
    DELETE_FILE = "delete_file"
    PATCH_FILE  = "patch_file"
    CREATE_FILE = "create_file"   # V7 — fichier inexistant avant TX
    CREATE_DIR  = "create_dir"
    MOVE_FILE   = "move_file"
```

**B. Modifier `FileSnapshot`** : rendre `content_hash` et `mtime` optionnels (déjà OK car `exists=False` possible), ajouter doc.

**C. Modifier `rollback()`** — logique CREATE_FILE explicite :
```python
def rollback(self, reason: str = "") -> str:
    if self.current_tx is None:
        raise RuntimeError("Aucune transaction active à rollbacker.")

    tx = self.current_tx

    for op in reversed(tx.operations):
        dst = Path(op.target_path)

        if op.type == OpType.CREATE_FILE or op.rollback_data is None:
            # Fichier créé pendant la TX → suppression propre
            if dst.exists():
                dst.unlink()
        else:
            # Fichier préexistant → restauration depuis .bak
            src = Path(op.rollback_data)
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                os.utime(dst, (op.before.mtime, op.before.mtime))

        self._write_wal({
            "type":   "OP_ROLLBACK",
            "tx_id":  tx.tx_id,
            "op_id":  op.op_id,
            "target": op.target_path,
            "reason": reason,
        })

    tx.status = TxStatus.ROLLED_BACK
    tx.completed_at = datetime.now(timezone.utc).isoformat()

    self._write_wal({
        "type":   "ROLLBACK",
        "tx_id":  tx.tx_id,
        "reason": reason,
        "n_ops":  len(tx.operations),
    })

    tx_id = tx.tx_id
    self.current_tx = None
    return tx_id
```

**D. Ajouter `cleanup_old_snapshots()` et `_get_tx_completion_timestamp()`** :

```python
def _get_tx_completion_timestamp(self, tx_id: str) -> Optional[float]:
    """Timestamp COMMIT/ROLLBACK WAL pour tx_id. None si non finalisée."""
    if not self.wal_path.exists():
        return None
    last_ts = None
    for line in self.wal_path.read_text(encoding="utf-8-sig").splitlines():
        try:
            entry = json.loads(line)
            if entry.get("tx_id") == tx_id and entry.get("type") in ("COMMIT", "ROLLBACK"):
                ts_str = entry.get("_ts") or entry.get("timestamp")
                if ts_str:
                    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    last_ts = dt.timestamp()
        except Exception:
            continue
    return last_ts

def cleanup_old_snapshots(self, days: int = 7) -> int:
    """
    Supprime les répertoires de TX finalisées de plus de N jours.
    La date de référence est le timestamp COMMIT/ROLLBACK dans le WAL
    (jamais st_mtime qui peut être modifié).
    """
    cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
    removed = 0
    for tx_dir in self.tx_dir.iterdir():
        if not tx_dir.is_dir() or tx_dir.name in (".llm_cache",):
            continue
        completion_ts = self._get_tx_completion_timestamp(tx_dir.name)
        if completion_ts is None:
            continue  # Non finalisée ou orpheline — ne pas toucher
        if completion_ts < cutoff:
            shutil.rmtree(tx_dir)
            removed += 1
    return removed
```

**E. Modifier `__init__`** pour auto-cleanup non bloquant :
```python
def __init__(self, tx_dir=None, wal_path=None, auto_cleanup_days: int = 7) -> None:
    self.tx_dir   = tx_dir   or _TX_DIR
    self.wal_path = wal_path or (self.tx_dir / "wal.jsonl")
    self.auto_cleanup_days = auto_cleanup_days
    self.tx_dir.mkdir(parents=True, exist_ok=True)
    self.current_tx: Optional[Transaction] = None
    # Nettoyage non bloquant au démarrage
    try:
        self.cleanup_old_snapshots(days=self.auto_cleanup_days)
    except Exception:
        pass
```

---

### TASK-12-05 — `core/__init__.py` : Mise à jour version + exports

Modifier `__version__` de `"5.0.0"` → `"7.0.0"` et ajouter dans `__all__` :
```python
# V7
"PathSecurityError",  # via utils (import explicite dans mcp_server)
```

---

## 🧪 TESTS

### Fichier : `tests/test_safe_path.py` *(nouveau — 12 tests)*

```python
# -*- coding: utf-8-sig -*-
"""Tests unitaires utils/safe_path.py — Sprint 12."""
import pytest
from pathlib import Path
from utils.safe_path import safe_path, PathSecurityError

WORKSPACE = Path("D:/LLMCodeAgent/workspace")

class TestSafePath:
    def test_valid_simple(self):
        p = safe_path("module.py", workspace=WORKSPACE)
        assert p == (WORKSPACE / "module.py").resolve()

    def test_valid_nested(self):
        p = safe_path("sub/module.py", workspace=WORKSPACE)
        assert "sub" in p.parts

    def test_valid_dot_prefix(self):
        # ./file.py est acceptable
        p = safe_path("./file.py", workspace=WORKSPACE)
        assert p.name == "file.py"

    def test_absolute_path_blocked(self):
        with pytest.raises(PathSecurityError, match="absolu"):
            safe_path("/etc/passwd", workspace=WORKSPACE)

    def test_absolute_windows_blocked(self):
        with pytest.raises(PathSecurityError):
            safe_path("C:/Windows/system32/cmd.exe", workspace=WORKSPACE)

    def test_dotdot_blocked(self):
        with pytest.raises(PathSecurityError, match="'\\.\\.'"):
            safe_path("../../../etc/passwd", workspace=WORKSPACE)

    def test_dotdot_nested_blocked(self):
        with pytest.raises(PathSecurityError):
            safe_path("sub/../../../etc/passwd", workspace=WORKSPACE)

    def test_empty_raises_value_error(self):
        with pytest.raises(ValueError):
            safe_path("", workspace=WORKSPACE)

    def test_spaces_only_raises_value_error(self):
        with pytest.raises(ValueError):
            safe_path("   ", workspace=WORKSPACE)

    def test_traversal_after_valid_prefix(self):
        with pytest.raises(PathSecurityError):
            safe_path("valid/../../etc/shadow", workspace=WORKSPACE)

    def test_default_workspace(self, tmp_path, monkeypatch):
        """Test sans workspace explicite (utilise config.WORKSPACE_DIR)."""
        import utils.safe_path as sp_module
        monkeypatch.setattr("config.WORKSPACE_DIR", tmp_path)
        p = safe_path("test.py", workspace=tmp_path)
        assert p.name == "test.py"

    def test_returns_path_object(self):
        p = safe_path("any_file.py", workspace=WORKSPACE)
        assert isinstance(p, Path)
```

### Fichier : `tests/test_telemetry.py` *(nouveau — 8 tests)*

```python
# -*- coding: utf-8-sig -*-
"""Tests unitaires utils/telemetry.py — Sprint 12."""
import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch


class TestLogMetric:
    def test_writes_jsonl(self, tmp_path):
        from utils import telemetry as tel
        tel._telemetry_handler = None
        with patch("utils.telemetry._ensure_logs_dir", return_value=tmp_path):
            from utils.telemetry import log_metric
            log_metric("test_metric", 42.0, {"env": "test"})
            tel._telemetry_handler.stream.flush()

        entries = list(tmp_path.glob("*.jsonl"))
        assert entries, "Fichier telemetry non créé"
        lines = entries[0].read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1
        data = json.loads(lines[-1])
        assert data["metric"] == "test_metric"
        assert data["value"] == 42.0
        assert data["labels"]["env"] == "test"

    def test_has_timestamp(self, tmp_path):
        from utils import telemetry as tel
        tel._telemetry_handler = None
        with patch("utils.telemetry._ensure_logs_dir", return_value=tmp_path):
            from utils.telemetry import log_metric
            log_metric("ts_test", 1.0)
            tel._telemetry_handler.stream.flush()

        lines = list(tmp_path.glob("*.jsonl"))[0].read_text().strip().splitlines()
        data = json.loads(lines[-1])
        assert "_ts" in data

    def test_silent_on_error(self):
        """log_metric ne lève jamais d'exception."""
        from utils.telemetry import log_metric
        with patch("utils.telemetry._get_telemetry_handler", side_effect=OSError("disk full")):
            log_metric("fail_metric", 0.0)  # ne doit pas lever

    def test_metric_timer_measures_duration(self, tmp_path):
        from utils import telemetry as tel
        tel._telemetry_handler = None
        with patch("utils.telemetry._ensure_logs_dir", return_value=tmp_path):
            from utils.telemetry import MetricTimer
            with MetricTimer("sleep_duration", {"unit": "ms"}):
                time.sleep(0.05)
            tel._telemetry_handler.stream.flush()

        lines = list(tmp_path.glob("*.jsonl"))[0].read_text().strip().splitlines()
        data = json.loads(lines[-1])
        assert data["metric"] == "sleep_duration"
        assert data["value"] >= 40   # 50ms - tolérance 20%

    def test_metric_timer_no_exception_on_error(self):
        from utils.telemetry import MetricTimer
        with patch("utils.telemetry.log_metric", side_effect=RuntimeError("boom")):
            with MetricTimer("test"):
                pass  # Ne doit pas lever

    def test_labels_empty_default(self, tmp_path):
        from utils import telemetry as tel
        tel._telemetry_handler = None
        with patch("utils.telemetry._ensure_logs_dir", return_value=tmp_path):
            from utils.telemetry import log_metric
            log_metric("no_labels", 1.0)
            tel._telemetry_handler.stream.flush()

        lines = list(tmp_path.glob("*.jsonl"))[0].read_text().strip().splitlines()
        data = json.loads(lines[-1])
        assert data["labels"] == {}

    def test_multiple_metrics(self, tmp_path):
        from utils import telemetry as tel
        tel._telemetry_handler = None
        with patch("utils.telemetry._ensure_logs_dir", return_value=tmp_path):
            from utils.telemetry import log_metric
            for i in range(5):
                log_metric(f"metric_{i}", float(i))
            tel._telemetry_handler.stream.flush()

        lines = list(tmp_path.glob("*.jsonl"))[0].read_text().strip().splitlines()
        assert len(lines) == 5

    def test_json_valid_per_line(self, tmp_path):
        from utils import telemetry as tel
        tel._telemetry_handler = None
        with patch("utils.telemetry._ensure_logs_dir", return_value=tmp_path):
            from utils.telemetry import log_metric
            log_metric("valid_json", 99.9, {"check": True})
            tel._telemetry_handler.stream.flush()

        for line in list(tmp_path.glob("*.jsonl"))[0].read_text().strip().splitlines():
            json.loads(line)  # Ne doit pas lever
```

### Fichier : `tests/test_transaction_manager.py` — Ajout 4 tests

Ajouter dans la classe existante `TestTransactionManager` :

```python
def test_create_file_optype_exists(self):
    from core.transaction_manager import OpType
    assert OpType.CREATE_FILE.value == "create_file"

def test_rollback_created_file_removed(self, tmp_path):
    """CREATE_FILE puis rollback → le fichier doit être supprimé."""
    from core.transaction_manager import TransactionManager, OpType
    tm = TransactionManager(tx_dir=tmp_path / "tx", wal_path=tmp_path / "wal.jsonl")
    new_file = tmp_path / "new_module.py"

    tm.begin(dsl_input="test_create", project="test")
    def _create():
        new_file.write_text("def foo(): pass\n", encoding="utf-8")
    tm.log_operation(new_file, OpType.CREATE_FILE, _create)
    tm.rollback(reason="test")

    assert not new_file.exists(), "Le fichier créé devrait être supprimé par le rollback"

def test_rollback_create_then_patch_removes_file(self, tmp_path):
    """CREATE puis PATCH sur même fichier → rollback doit supprimer le fichier."""
    from core.transaction_manager import TransactionManager, OpType
    tm = TransactionManager(tx_dir=tmp_path / "tx", wal_path=tmp_path / "wal.jsonl")
    target = tmp_path / "new.py"

    tm.begin(dsl_input="create_patch", project="test")

    def _create():
        target.write_text("x = 1\n", encoding="utf-8")
    tm.log_operation(target, OpType.CREATE_FILE, _create)

    def _patch():
        target.write_text("x = 2\n", encoding="utf-8")
    tm.log_operation(target, OpType.PATCH_FILE, _patch)

    tm.rollback(reason="test mixed")
    assert not target.exists()

def test_cleanup_uses_wal_timestamp(self, tmp_path):
    """cleanup_old_snapshots supprime si WAL COMMIT ancien, conserve si récent."""
    from core.transaction_manager import TransactionManager
    import json
    from datetime import datetime, timezone, timedelta

    wal = tmp_path / "wal.jsonl"
    tx_old = "tx_aabbccdd0001"
    tx_new = "tx_aabbccdd0002"

    # TX ancienne (30 jours ago)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    wal.write_text(
        json.dumps({"type": "COMMIT", "tx_id": tx_old, "_ts": old_ts}) + "\n" +
        json.dumps({"type": "COMMIT", "tx_id": tx_new, "_ts": datetime.now(timezone.utc).isoformat()}) + "\n",
        encoding="utf-8"
    )
    (tmp_path / tx_old).mkdir()
    (tmp_path / tx_new).mkdir()

    tm = TransactionManager(tx_dir=tmp_path, wal_path=wal, auto_cleanup_days=0)
    # auto_cleanup_days=0 → pas de cleanup au __init__
    removed = tm.cleanup_old_snapshots(days=7)
    assert removed == 1
    assert not (tmp_path / tx_old).exists()
    assert (tmp_path / tx_new).exists()
```

---

## 📦 FICHIERS NOUVEAUX / MODIFIÉS

| Fichier | Action | Tests impactés |
|---------|--------|----------------|
| `config.py` | Extend (append) | Aucun |
| `utils/safe_path.py` | CREATE | `test_safe_path.py` (12 tests) |
| `utils/telemetry.py` | CREATE | `test_telemetry.py` (8 tests) |
| `core/transaction_manager.py` | PATCH (OpType + rollback + cleanup) | `test_transaction_manager.py` (+4) |
| `core/__init__.py` | PATCH (__version__) | `test_smoke.py` |
| `tests/test_safe_path.py` | CREATE | — |
| `tests/test_telemetry.py` | CREATE | — |

---

## ✅ CRITÈRES D'ACCEPTATION

- [ ] `pytest tests/ -v` → ≥ 261 PASSED (237 + 24 nouveaux), 0 FAILED
- [ ] `OpType.CREATE_FILE` accessible depuis `core.transaction_manager`
- [ ] `rollback()` d'une TX avec `CREATE_FILE` supprime le fichier cible
- [ ] `cleanup_old_snapshots()` utilise le timestamp WAL (pas `st_mtime`)
- [ ] `safe_path("../../../etc/passwd")` → `PathSecurityError`
- [ ] `log_metric("x", 1.0)` ne lève jamais d'exception même si disque plein
- [ ] `__version__` = `"7.0.0"` dans `core/__init__.py`
- [ ] 0 régression sur les 237 tests V5

---

## 🔗 DÉPENDANCES

- **Bloque** : Sprint 13 (McpEditBatch), Sprint 14 (SandboxEngine), Sprint 15 (MCP Server)
- **Dépend de** : Rien (fondations)
- **Ne touche pas** : `orchestrator.py`, `llm_generator.py`, `smart_patcher.py`

---

## 📝 NOTES D'IMPLÉMENTATION

### Ordre d'application des patches (CRITIQUE)
1. `config.py` en premier (les autres modules l'importent)
2. `utils/safe_path.py` (autonome, import local de config)
3. `utils/telemetry.py` (autonome, import local de config)
4. `transaction_manager.py` (OpType d'abord, puis rollback, puis cleanup, puis __init__)
5. `core/__init__.py` (en dernier)

### Vérification syntaxe obligatoire
Après chaque patch `libcst`, valider avec `compile()` avant d'écrire sur disque.

### Encodage
Tous les nouveaux fichiers Python : `# -*- coding: utf-8-sig -*-` en première ligne.

<!-- Sprint 12 | V7 Fondations | LCCA V7.0.0-rc1 | 2026-04-17 -->
