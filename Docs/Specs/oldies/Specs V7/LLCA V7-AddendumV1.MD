============================================================
Fichier : 19-addendum-v7-complementaire-implementation.md
============================================================

# Addendum V7 — Complementaire d'Implementation Technique
&lt;!-- AI-READY | Addendum implementation V7 | Version 7.0.0-rc2 | 2026-04-17 --&gt;

## Vue d'ensemble

Ce document complete l'Addendum V7 Reconcilie (fichier 18) avec les specifications d'implementation detaillees issues de l'analyse technique critique. Il specifie les modifications de code, les nouvelles APIs et les regles de validation necessaires avant passage en production.

&gt; **Principe fondateur** : Aucune modification ci-dessous ne doit invalider les 237 tests V5 existants. Les nouvelles fonctionnalites sont des extensions ou des corrections de failles identifiees.

---

## 1. Cache LLM — Versionnement par modele

### 1.1 Probleme

La cle de cache actuelle (`MD5(system + "\n" + user)`) est aveugle au modele utilise. Un changement de modele (ex: `qwen2.5-coder:14b` → `qwen3:30b-a3b`) peut servir une reponse generee pour l'ancien modele, potentiellement incompatible syntaxiquement ou semantiquement.

### 1.2 Specification

#### Modification : `core/llm_generator.py`

**A. Generation de cle**

```python
import hashlib
import json
from pathlib import Path
from config import LLM_CACHE_DIR

class LLMGenerator:
    # ... existing init ...
    
    def _cache_key(self, system: str, user: str, model: str) -&gt; str:
        """
        Cle de cache unique par (modele, system, user).
        Inclusion du nom de modele dans le hash.
        """
        payload = f"{model}\n{system}\n{user}"
        return hashlib.md5(payload.encode("utf-8")).hexdigest()
    
    def _cache_get(self, key: str) -&gt; Optional[str]:
        """Lit le fichier cache et son metadata associe."""
        cache_file = LLM_CACHE_DIR / f"{key}.py"
        meta_file = LLM_CACHE_DIR / f"{key}.json"
        
        if not cache_file.exists():
            return None
            
        # Validation metadata (defense en profondeur)
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                if meta.get("model") != self.ollama.model:
                    return None  # Modele different, invalider
            except Exception:
                pass  # Metadata corrompu, on continue quand meme
                
        return cache_file.read_text(encoding="utf-8")
    
    def _cache_set(self, key: str, code: str, model: str) -&gt; None:
        """Ecrit le code et son metadata."""
        try:
            cache_file = LLM_CACHE_DIR / f"{key}.py"
            meta_file = LLM_CACHE_DIR / f"{key}.json"
            
            cache_file.write_text(code, encoding="utf-8")
            meta_file.write_text(
                json.dumps({
                    "model": model,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "version": "7.0"
                }, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception:
            pass  # Cache silencieux en cas d'erreur disque

B. Integration dans generate()
def generate(self, op, intent, context="") -> GenerationResult:
    system, user = self.builder.build(op, intent, context)
    model = self.ollama.model  # ex: "qwen2.5-coder:14b"
    key = self._cache_key(system, user, model)
    
    cached = self._cache_get(key)
    if cached is not None:
        return GenerationResult(
            code=cached,
            model=model,
            from_cache=True,
            duration_ms=0
        )
    
    # ... appel Ollama ...
    
    self._cache_set(key, code, model)
    return GenerationResult(
        code=code,
        model=model,
        from_cache=False,
        duration_ms=...
    )
1.3 Migration donnees existantes
Les anciens fichiers .py sans metadata .json restent valides (fallback silencieux). L'invalideur par metadata ne s'applique que si le fichier .json existe.
2. Gestion des snapshots pour fichiers crees
2.1 Probleme
Le TransactionManager V5 gere les fichiers existants (snapshot MD5 + backup .bak). Cependant, une operation CREATE_FILE (ou PATCH_FILE sur un fichier inexistant) ne possede pas de snapshot "avant". En cas de rollback, le fichier cree doit etre supprime pour retablir l'etat exact d'avant transaction.
2.2 Specification
Modification : core/transaction_manager.py
A. Nouveau champ dans FileSnapshot
@dataclass
class FileSnapshot:
    path: str
    content_hash: Optional[str]   # MD5 du contenu (None si fichier absent)
    content: Optional[str]
    exists: bool                  # True si fichier existait avant l'op
    mtime: Optional[float]        # None si fichier absent

B. Modification _snapshot()
def _snapshot(self, path: Path) -> FileSnapshot:
    if not path.exists():
        return FileSnapshot(
            path=str(path),
            content_hash=None,
            content=None,
            exists=False,
            mtime=None
        )
    
    content = path.read_text(encoding="utf-8-sig")
    return FileSnapshot(
        path=str(path),
        content_hash=hashlib.md5(content.encode("utf-8-sig")).hexdigest(),
        content=content,
        exists=True,
        mtime=path.stat().st_mtime
    )

C. Modification _backup()
def _backup(self, tx_id: str, path: Path) -> Optional[str]:
    """
    Retourne le chemin du backup si cree, None si le fichier n'existait pas.
    """
    if not path.exists():
        return None  # Marqueur implicite : pas de backup = fichier inexistant avant
    
    backup_dir = self.tx_dir / tx_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    op_id = secrets.token_hex(4)
    bak_path = backup_dir / f"{path.name}_{op_id}.bak"
    shutil.copy2(path, bak_path)
    return str(bak_path)

D. Modification rollback()
def rollback(self, reason="") -> str:
    if self.current_tx is None:
        raise TransactionError("Aucune transaction active")
    
    ops = reversed(self.current_tx.operations)  # LIFO
    
    for op in ops:
        if op.rollback_data is not None:
            # Fichier existant avant : restauration depuis .bak
            src = Path(op.rollback_data)
            dst = Path(op.target_path)
            if src.exists():
                shutil.copy2(src, dst)
        else:
            # Aucun backup = fichier cree pendant la TX : suppression
            dst = Path(op.target_path)
            if dst.exists():
                dst.unlink()
        
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
    self.current_tx = None
    return self.current_tx.tx_id

E. Nouveau type d'operation
class OpType(Enum):
    WRITE_FILE = "write_file"
    EDIT_FILE = "edit_file"
    DELETE_FILE = "delete_file"
    PATCH_FILE = "patch_file"
    CREATE_FILE = "create_file"   # NOUVEAU — fichier inexistant avant
    CREATE_DIR = "create_dir"
    MOVE_FILE = "move_file"

2.3 Integration McpEditBatch
# Dans McpEditBatch.apply()
for op in files:
    full_path = WORKSPACE_DIR / op["path"]
    
    if not full_path.exists() and op.get("action") == "create":
        # Fichier inexistant : snapshot retournera exists=False
        new_code = op["code"]  # Pas de SmartPatcher pour creation brute
        
        def _do_create():
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(new_code, encoding="utf-8-sig")
        
        self.tx_manager.log_operation(
            target_path=full_path,
            op_type=OpType.CREATE_FILE,  # Nouveau type
            execute_func=_do_create,
            metadata={"action": "create", "symbol": op.get("symbol")}
        )
    else:
        # Modification classique via SmartPatcher
        # ...

3. Politique de retention snapshots et WAL
3.1 Probleme
Les repertoires transactions/{tx_id}/ et le fichier wal.jsonl croissent indefiniment. L'archivage existe (archive_old_wal_entries) mais n'est pas automatise.
3.2 Specification
A. TransactionManager — Nettoyage automatique
# Ajouter dans TransactionManager
import shutil
from datetime import datetime, timedelta

class TransactionManager:
    def __init__(self, tx_dir=None, wal_path=None, auto_cleanup_days=7):
        self.tx_dir = tx_dir or TRANSACTIONS_DIR
        self.wal_path = wal_path or (self.tx_dir / "wal.jsonl")
        self.auto_cleanup_days = auto_cleanup_days
        
        # Nettoyage au demarrage (non bloquant)
        try:
            self.cleanup_old_snapshots(days=self.auto_cleanup_days)
            self.archive_old_wal_entries(days=self.auto_cleanup_days * 2)
        except Exception:
            pass  # Ne jamais bloquer le boot sur le nettoyage

    def cleanup_old_snapshots(self, days: int = 7) -> int:
        """
        Supprime les repertoires tx_id de plus de N jours
        dont le statut est COMMITTED ou ROLLED_BACK.
        """
        cutoff = datetime.now().timestamp() - (days * 86400)
        removed = 0
        
        for tx_dir in self.tx_dir.iterdir():
            if not tx_dir.is_dir() or tx_dir.name == ".llm_cache":
                continue
                
            # Verification : la TX est finalisee
            wal_entries = self._read_wal_for_tx(tx_dir.name)
            if not any(e["type"] in ("COMMIT", "ROLLBACK") for e in wal_entries):
                continue  # TX potentiellement incomplete, ne pas toucher
            
            # Verification date (mtime du repertoire)
            if tx_dir.stat().st_mtime < cutoff:
                shutil.rmtree(tx_dir)
                removed += 1
                
        return removed
    
    def _read_wal_for_tx(self, tx_id: str) -> List[dict]:
        """Extrait les entrees WAL pour un tx_id specifique."""
        entries = []
        if not self.wal_path.exists():
            return entries
        
        for line in self.wal_path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
                if entry.get("tx_id") == tx_id:
                    entries.append(entry)
            except Exception:
                continue
        return entries

B. Configuration
# config.py
TX_AUTO_CLEANUP_DAYS = int(os.getenv("LCCA_TX_CLEANUP_DAYS", "7"))
WAL_AUTO_ARCHIVE_DAYS = int(os.getenv("LCCA_WAL_ARCHIVE_DAYS", "30"))

4. Detection robuste Docker pour le sandbox
4.1 Probleme
docker.from_env() leve une exception si Docker est installe mais l'utilisateur n'a pas les droits (groupe docker). Le mode auto doit basculer silencieusement vers soft.
4.2 Specification
# core/sandbox_engine.py
import docker
import logging

log = logging.getLogger("lcca.sandbox_engine")

class SandboxEngine:
    def __init__(self, workspace: Path, mode: str = "auto"):
        self.workspace = workspace
        self.docker_client = None
        self.effective_mode = mode
        
        if mode in ("docker", "auto"):
            self.docker_client = self._try_docker()
            if self.docker_client is None and mode == "docker":
                raise RuntimeError("Mode docker explicitement demande mais Docker indisponible")
            if self.docker_client is None and mode == "auto":
                self.effective_mode = "soft"
                log.warning("Docker indisponible (droits ou service), fallback mode soft")
    
    def _try_docker(self) -> Optional[docker.DockerClient]:
        """Test silencieux de connexion Docker."""
        try:
            client = docker.from_env()
            client.ping()  # Verification effective
            return client
        except Exception as e:
            log.debug("Docker non disponible : %s", e)
            return None
        
5. Observabilite minimale — Logs structures
5.1 Specification
Fichier dedie : utils/telemetry.py
# utils/telemetry.py
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from config import LOGS_DIR

TELEMETRY_PATH = LOGS_DIR / "telemetry.jsonl"

def log_metric(name: str, value: float, labels: dict = None):
    """Ecrit une metrique en JSON Lines."""
    entry = {
        "_ts": datetime.now(timezone.utc).isoformat(),
        "metric": name,
        "value": value,
        "labels": labels or {}
    }
    try:
        with open(TELEMETRY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
    except Exception:
        pass

class MetricTimer:
    """Context manager pour mesurer une duree."""
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

5.2 Integration
# Dans mcp_server.py
from utils.telemetry import MetricTimer, log_metric

def handle_request(req):
    method = req.get("method")
    
    with MetricTimer("mcp_request_duration", {"method": method}):
        if method == "tools/call":
            name = req["params"]["name"]
            result = dispatch_tool(name, req["params"]["arguments"])
            
            log_metric("mcp_tool_calls_total", 1, {"tool": name, "success": result.get("success", True)})
            return result

# Dans McpEditBatch.apply()
with MetricTimer("edit_batch_duration", {"n_files": len(files)}):
    # ... logique existante ...
    log_metric("code_evaluator_score_avg", sum(e["score"] for e in evaluations)/len(evaluations))

6. Validation des chemins — Utilitaire global
6.1 Specification
# utils/safe_path.py
from pathlib import Path
from config import WORKSPACE_DIR

class PathSecurityError(Exception):
    """Leve quand un chemin tente de sortir du workspace."""

def safe_path(relative_path: str, workspace: Path = WORKSPACE_DIR) -> Path:
    """
    Resout un chemin relatif et verifie qu'il reste dans le workspace.
    
    Raises:
        PathSecurityError: Si le chemin resolve sort du workspace.
        ValueError: Si le chemin contient des composants suspects.
    """
    # Normalisation basique
    rel = Path(str(relative_path).strip())
    
    # Rejeter les chemins absolus
    if rel.is_absolute():
        raise PathSecurityError(f"Chemin absolu interdit: {relative_path}")
    
    # Rejeter les sequences dangereuses explicites
    # (Path.resolve() gere .., mais defense en profondeur)
    if ".." in rel.parts:
        raise PathSecurityError(f"Sequence '..' interdite: {relative_path}")
    
    full = (workspace / rel).resolve()
    workspace_resolved = workspace.resolve()
    
    # Verification containment
    try:
        full.relative_to(workspace_resolved)
    except ValueError:
        raise PathSecurityError(
            f"Path traversal detecte: {relative_path} -> {full} hors de {workspace_resolved}"
        )
    
    return full

6.2 Application obligatoire
Tous les outils MCP DOIVENT utiliser safe_path :
# McpEditBatch
from utils.safe_path import safe_path, PathSecurityError

def apply(self, files):
    for f in files:
        try:
            full_path = safe_path(f["path"])
        except PathSecurityError as e:
            return {"success": False, "error": str(e)}

# SandboxEngine
def _run_subprocess(self, code, file_path=None):
    if file_path:
        safe_path(file_path)  # Validation
    # ...

# MCP Server project_search
def handle_project_search(args):
    if "file_path" in args:
        safe_path(args["file_path"])  # Validation

7. Mise a jour protocole MCP
7.1 Specification
# config.py
MCP_PROTOCOL_VERSION = "2025-06-18"  # Mise a jour depuis 2024-11-05

# mcp_server.py
def handle_initialize(params):
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {
            "tools": {"listChanged": True},
            "resources": {"subscribe": False, "listChanged": False},
            "prompts": {"listChanged": False}
        },
        "serverInfo": {
            "name": "lcca-v7-mcp",
            "version": "7.0.0"
        }
    }

8. Streaming Ollama (V7.2)
8.1 Specification (optionnel, future proofing)
# core/llm_generator.py

class OllamaClient:
    def generate_stream(self, system: str, user: str):
        """
        Genere un flux de tokens. Yield chaque chunk.
        A utiliser pour les longues generations (modele 14B+).
        """
        payload = {
            "model": self.model,
            "stream": True,
            "options": {
                "num_predict": self.max_tokens,
                "temperature": 0.2
            },
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ]
        }
        
        req = request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        
        with request.urlopen(req, timeout=self.timeout) as response:
            for line in response:
                line = line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if "message" in data and "content" in data["message"]:
                        yield data["message"]["content"]
                    if data.get("done"):
                        break
                except Exception:
                    continue
                
Note : Le support streaming dans le MCP Server necessitera soit une connexion SSE (Server-Sent Events) soit un buffer progressif. Pour V7.0, garder stream=False par defaut.
9. Matrice de priorite et dependances
| Priorite    | Fichier(s) modifies                                                    | Effort | Blocage V7.0                  |
| ----------- | ---------------------------------------------------------------------- | ------ | ----------------------------- |
| **HAUTE**   | `core/llm_generator.py` (\_cache\_key, metadata)                       | 2h     | Non                           |
| **HAUTE**   | `core/transaction_manager.py` (snapshot exists=False, rollback unlink) | 4h     | **OUI** — regression rollback |
| **HAUTE**   | `utils/safe_path.py` + integration                                     | 1h     | Non                           |
| **MOYENNE** | `core/sandbox_engine.py` (Docker robuste)                              | 2h     | Non                           |
| **MOYENNE** | `core/transaction_manager.py` (cleanup)                                | 2h     | Non                           |
| **MOYENNE** | `utils/telemetry.py` + integration                                     | 2h     | Non                           |
| **FAIBLE**  | `config.py` (MCP version)                                              | 15min  | Non                           |
| **V7.2**    | `core/llm_generator.py` (streaming)                                    | 4h     | Non                           |

10. Tests requis complementaires
| Suite     | Fichier                       | Cas test                                                                            | Priorite |
| --------- | ----------------------------- | ----------------------------------------------------------------------------------- | -------- |
| Cache     | `test_llm_generator.py`       | `test_cache_key_includes_model` — meme prompt, modele different = cle differente    | HAUTE    |
| Cache     | `test_llm_generator.py`       | `test_cache_metadata_validation` — metadata modele mismatch = cache miss            | HAUTE    |
| TX        | `test_transaction_manager.py` | `test_rollback_created_file_removed` — CREATE\_FILE puis rollback = fichier absent  | HAUTE    |
| TX        | `test_transaction_manager.py` | `test_snapshot_nonexistent_file` — snapshot avant creation retourne exists=False    | HAUTE    |
| Securite  | `test_safe_path.py`           | `test_path_traversal_blocked` — `../../../etc/passwd` leve PathSecurityError        | HAUTE    |
| Securite  | `test_safe_path.py`           | `test_absolute_path_blocked` — `/etc/passwd` leve PathSecurityError                 | HAUTE    |
| Sandbox   | `test_sandbox_engine.py`      | `test_docker_unavailable_fallback_soft` — docker.from\_env echoue, mode=auto → soft | MOYENNE  |
| Cleanup   | `test_transaction_manager.py` | `test_cleanup_old_snapshots` — vieux COMMITTED supprime, recent/incomplete conserve | MOYENNE  |
| Telemetry | `test_telemetry.py`           | `test_log_metric_jsonl` — fichier append, format JSON valide                        | MOYENNE  |

11. Checklist validation AI
[ ] Aucun hardcoded 3 pour MAX_FILES_PER_TX (utiliser config.MAX_FILES_PER_TX)
[ ] sys.executable utilise partout (jamais "python")
[ ] Encodage utf-8-sig pour tous les fichiers Python ecrits
[ ] safe_path appele dans chaque tool MCP exposant un path
[ ] Rollback CREATE_FILE supprime le fichier (pas de fichier orphelin)
[ ] Cache LLM inclut le modele dans la cle
[ ] Docker detection silencieuse avec fallback soft
[ ] Telemetry n'interrompt jamais le flux principal (try/except silencieux)
[ ] WAL conserve le format append-only JSONL
[ ] Tests V5 existants (237) toujours PASS sans modification de leur logique
<!-- AI-READY | Addendum complementaire V7 | 2026-04-17 -->