============================================================
Fichier : 20-addendum-v7-correctif-validation.md
============================================================

# Addendum V7 — Correctif Post-Validation Technique
&lt;!-- AI-READY | Correctif implementation V7 | Version 7.0.0-rc3 | 2026-04-17 --&gt;

## Vue d'ensemble

Ce document formalise les corrections exactes aux 4 points de vigilance soulevés par la validation technique de l'addendum complementaire (fichier 19). Il sert de specification d'implementation bloquante avant merge dans la branche V7.

&gt; **Principe fondateur** : Chaque correction est retrocompatible, testable unitairement, et ne modifie pas la logique metier des 237 tests V5.

---

## 1. Point de vigilance #1 — Migration des caches legacy

### 1.1 Probleme

Les entrees de cache existantes (fichiers `{hash}.py` sans `{hash}.json`) ne seront jamais invalidees lors d'un changement de modele, car l'absence de metadata est traitee comme un fallback silencieux.

### 1.2 Decision

**Non bloquant pour V7.0**, mais un script de migration one-shot est fourni pour assurer la propreté du depot.

### 1.3 Implementation

Fichier : `scripts/migrate_cache_v6_to_v7.py`

```python
#!/usr/bin/env python3
"""
Script one-shot : genere les fichiers metadata JSON manquants pour le cache LLM.
A executer une seule fois apres mise a jour vers V7.
"""
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from config import LLM_CACHE_DIR

def migrate():
    migrated = 0
    skipped = 0
    
    for py_file in LLM_CACHE_DIR.glob("*.py"):
        meta_file = py_file.with_suffix(".json")
        if meta_file.exists():
            skipped += 1
            continue
        
        # Generer metadata avec modele "unknown"
        meta = {
            "model": "unknown",
            "migrated_at": datetime.now(timezone.utc).isoformat(),
            "note": "Cache genere avant versionnement par modele (V7 migration)"
        }
        meta_file.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        migrated += 1
    
    print(f"Migration terminee : {migrated} metadata creees, {skipped} deja presents.")

if __name__ == "__main__":
    migrate()

1.4 Regle d'invalidation post-migration
Modifier LLMGenerator._cache_get() pour traiter "unknown" comme une invalidation forcee si le modele courant n'est pas "unknown" :
def _cache_get(self, key: str) -> Optional[str]:
    cache_file = LLM_CACHE_DIR / f"{key}.py"
    meta_file = LLM_CACHE_DIR / f"{key}.json"
    
    if not cache_file.exists():
        return None
    
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            cached_model = meta.get("model", "unknown")
            # Invalider si modele mismatch OU cache legacy non migre
            if cached_model == "unknown" and self.ollama.model != "unknown":
                return None
            if cached_model != self.ollama.model:
                return None
        except Exception:
            pass
    
    return cache_file.read_text(encoding="utf-8")

2. Point de vigilance #2 — Rollback mixte (CREATE_FILE + PATCH_FILE)
2.1 Probleme
Si une transaction cree un fichier (CREATE_FILE) puis le modifie (PATCH_FILE), le rollback LIFO doit :
Restaurer le fichier dans son etat post-creation (via le .bak du PATCH_FILE)
Puis le supprimer completement (car il n'existait pas avant la transaction)
La specification precedente ne formalisait pas explicitement la regle de decision pour ce cas mixte.
2.2 Specification corrigee
La regle de rollback LIFO est :
if op.type == OpType.CREATE_FILE or op.rollback_data is None:
    # Le fichier n'existait pas avant cette operation : suppression
    dst = Path(op.target_path)
    if dst.exists():
        dst.unlink()
else:
    # Le fichier existait : restauration depuis le backup
    src = Path(op.rollback_data)
    dst = Path(op.target_path)
    if src.exists():
        shutil.copy2(src, dst)

2.3 Implementation dans TransactionManager
# core/transaction_manager.py

def rollback(self, reason="") -> str:
    if self.current_tx is None:
        raise TransactionError("Aucune transaction active")
    
    ops = reversed(self.current_tx.operations)
    
    for op in ops:
        dst = Path(op.target_path)
        
        if op.type == OpType.CREATE_FILE or op.rollback_data is None:
            # Scenario A : fichier cree dans cette TX → suppression
            if dst.exists():
                dst.unlink()
        else:
            # Scenario B : fichier existant avant → restauration .bak
            src = Path(op.rollback_data)
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        
        self._write_wal({
            "type": "OP_ROLLBACK",
            "tx_id": self.current_tx.tx_id,
            "op_id": op.op_id,
            "target": op.target_path,
            "reason": reason
        })
    
    self._write_wal({
        "type": "ROLLBACK",
        "tx_id": self.current_tx.tx_id,
        "reason": reason
    })
    
    self.current_tx.status = TxStatus.ROLLED_BACK
    tx_id = self.current_tx.tx_id
    self.current_tx = None
    return tx_id

2.4 Integration dans McpEditBatch
Pour garantir que PATCH_FILE sur un fichier fraichement cree genere bien un backup (afin que le rollback LIFO restaure l'etat initial du fichier avant de le supprimer) :
# Dans McpEditBatch.apply()
for op in files:
    full_path = WORKSPACE_DIR / op["path"]
    
    if not full_path.exists() and op.get("action") == "create":
        # Operation CREATE_FILE
        # ... log_operation avec OpType.CREATE_FILE ...
    else:
        # Operation PATCH_FILE ou WRITE_FILE
        # SmartPatcher retourne le nouveau contenu
        new_code = self.patcher.apply_patch(
            file_path=op["path"],
            patch_type=op["patch_type"],
            code=op.get("code"),
            name=op.get("symbol"),
        )
        
        def _do_patch():
            # Si le fichier n'existait pas (creation implicite),
            # write_text le creera. Le snapshot "avant" sera exists=False.
            full_path.write_text(new_code, encoding="utf-8-sig")
        
        self.tx_manager.log_operation(
            target_path=full_path,
            op_type=OpType.PATCH_FILE,
            execute_func=_do_patch,
            metadata={"patch_type": op["patch_type"], "symbol": op.get("symbol")}
        )

3. Point de vigilance #3 — Nettoyage des snapshots par date WAL
3.1 Probleme
cleanup_old_snapshots() utilisait tx_dir.stat().st_mtime qui peut etre modifie par des ecritures tardives (logs, touch) et ne reflete pas la date reelle de finalisation de la transaction.
3.2 Specification corrigee
La date de reference pour le nettoyage est la date du dernier enregistrement COMMIT ou ROLLBACK dans le WAL pour ce tx_id.
3.3 Implementation
# core/transaction_manager.py

def _get_tx_completion_timestamp(self, tx_id: str) -> Optional[float]:
    """
    Extrait le timestamp de completion (COMMIT ou ROLLBACK) depuis le WAL.
    Retourne None si la TX n'est pas finalisee.
    """
    if not self.wal_path.exists():
        return None
    
    last_timestamp = None
    
    for line in self.wal_path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
            if entry.get("tx_id") == tx_id and entry.get("type") in ("COMMIT", "ROLLBACK"):
                ts_str = entry.get("_ts") or entry.get("timestamp")
                if ts_str:
                    from datetime import datetime
                    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    last_timestamp = dt.timestamp()
        except Exception:
            continue
    
    return last_timestamp

def cleanup_old_snapshots(self, days: int = 7) -> int:
    """
    Supprime les repertoires de transactions finalisees de plus de N jours.
    La date de reference est le timestamp COMMIT/ROLLBACK dans le WAL.
    """
    cutoff = datetime.now().timestamp() - (days * 86400)
    removed = 0
    
    for tx_dir in self.tx_dir.iterdir():
        if not tx_dir.is_dir() or tx_dir.name == ".llm_cache":
            continue
        
        tx_id = tx_dir.name
        completion_ts = self._get_tx_completion_timestamp(tx_id)
        
        if completion_ts is None:
            continue  # TX non finalisee ou orpheline — ne pas toucher
        
        if completion_ts < cutoff:
            shutil.rmtree(tx_dir)
            removed += 1
    
    return removed

4. Point de vigilance #4 — Rotation du fichier telemetry
4.1 Probleme
telemetry.jsonl croit indefiniment sans mecanisme de rotation.
4.2 Specification
Mise en place d'une rotation identique au logger V5 (RotatingFileHandler, 10 MB, 5 backups).
4.3 Implementation
# utils/telemetry.py
import json
import time
import logging
from pathlib import Path
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from config import LOGS_DIR

TELEMETRY_PATH = LOGS_DIR / "telemetry.jsonl"

# Handler rotatif unique (idempotent)
_telemetry_handler = None

def _get_telemetry_handler():
    global _telemetry_handler
    if _telemetry_handler is not None:
        return _telemetry_handler
    
    handler = RotatingFileHandler(
        TELEMETRY_PATH,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter('%(message)s'))
    _telemetry_handler = handler
    return handler

def log_metric(name: str, value: float, labels: dict = None):
    entry = {
        "_ts": datetime.now(timezone.utc).isoformat(),
        "metric": name,
        "value": value,
        "labels": labels or {}
    }
    try:
        handler = _get_telemetry_handler()
        handler.emit(logging.makeLogRecord({
            "msg": json.dumps(entry, ensure_ascii=False),
            "levelno": logging.INFO,
            "levelname": "INFO"
        }))
    except Exception:
        pass

class MetricTimer:
    def __init__(self, name: str, labels: dict = None):
        self.name = name
        self.labels = labels or {}
        self.start = None
        
    def __enter__(self):
        self.start = time.perf_counter()
        return self
        
    def __exit__(self, *args):
        duration_ms = int((time.perf_counter() - self.start) * 1000)
        log_metric(self.name, duration_ms, {**self.labels, "unit": "ms"})

5. Mise a jour des tests (complement fichier 19)
| Suite     | Fichier                       | Cas test supplementaire                                                                                          | Priorite |
| --------- | ----------------------------- | ---------------------------------------------------------------------------------------------------------------- | -------- |
| Cache     | `test_llm_generator.py`       | `test_cache_unknown_model_invalidated` — cle avec metadata "unknown" + modele courant != "unknown" → cache miss  | HAUTE    |
| TX        | `test_transaction_manager.py` | `test_rollback_create_then_patch` — TX avec CREATE\_FILE puis PATCH\_FILE → rollback supprime le fichier         | HAUTE    |
| TX        | `test_transaction_manager.py` | `test_cleanup_uses_wal_timestamp` — mock WAL avec COMMIT date ancienne → cleanup supprime; WAL recent → conserve | MOYENNE  |
| Securite  | `test_safe_path.py`           | `test_safe_path_resolves_dot` — `./file.py` OK; `a/../b` OK si dans workspace                                    | MOYENNE  |
| Telemetry | `test_telemetry.py`           | `test_telemetry_rotation` — ecriture de >10MB declenche rotation `.1`                                            | MOYENNE  |

6. Checklist validation finale (avant merge V7.0)
[ ] Script scripts/migrate_cache_v6_to_v7.py executable et teste
[ ] LLMGenerator._cache_get() invalide les entrees "unknown" si modele courant != "unknown"
[ ] rollback() distingue explicitement OpType.CREATE_FILE vs restauration .bak
[ ] cleanup_old_snapshots() utilise _get_tx_completion_timestamp() (WAL) et non st_mtime
[ ] telemetry.jsonl utilise RotatingFileHandler (10MB, 5 backups)
[ ] Aucune reference a st_mtime pour la logique metier temporelle
[ ] Les 237 tests V5 restent verts (ci: pytest tests/ -v)
[ ] Nouveaux tests des 4 points de vigilance passent
<!-- AI-READY | Addendum correctif V7 | 2026-04-17 -->