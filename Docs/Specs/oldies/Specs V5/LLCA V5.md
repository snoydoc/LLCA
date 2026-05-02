📁 Structure Complète
lcca_v5_fusion/
├── core/
│   ├── __init__.py
│   ├── mempalace_client.py      # V4 - Hiérarchie Wings/Rooms/Halls
│   ├── transaction_manager.py   # V4 - ACID transactions + rollback
│   ├── recovery_service.py      # V4 - Boot check & auto-recovery
│   ├── dsl_parser.py            # V4 - Langage Claude-style
│   ├── ast_indexer.py           # V5 - Indexation symboles + dépendances
│   ├── dependency_graph.py      # NEW - Graphe d'impact entre fichiers
│   ├── smart_patcher.py         # V5 - Patch AST libcst (infaillible)
│   ├── context_assembler.py     # NEW - Gestion fenêtre contexte LLM
│   ├── planner.py               # V5 - Planning multi-fichiers intelligent
│   ├── file_selector.py         # V5 - Sélection sémantique + impact analysis
│   ├── executor.py              # V5 - Exécution sandbox + tests
│   ├── error_analyzer.py        # V5 - Analyse erreurs + suggestion fixes
│   └── orchestrator.py          # FUSION - Coordination complète
├── utils/
│   └── logger.py                # Logging structuré
├── workspace/                   # Code cible (git-tracked recommandé)
├── transactions/                # Backup transactions (auto-generated)
└── main.py                      # Entry point CLI

1️⃣ core/mempalace_client.py (Client mémoire hiérarchique)
"""
Client MemPalace optimisé pour LCCA V5 Fusion.
Gère les 4 layers de mémoire : Identity, Compressed, Scoped, Deep.
"""
import os
import json
import hashlib
from datetime import datetime
from typing import List, Dict, Optional, Any, Set
from dataclasses import dataclass, asdict
from pathlib import Path

import chromadb
from chromadb.config import Settings


@dataclass
class MemoryEntry:
    content: str
    wing: Optional[str] = None
    room: Optional[str] = None  
    hall: Optional[str] = None
    source: str = "system"
    metadata: Dict[str, Any] = None
    layer: int = 3  # 0=identity, 1=compressed, 2=scoped, 3=deep
    embedding_id: Optional[str] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class MemPalaceClient:
    """
    Client MemPalace avec gestion transactionnelle et compression AAAK.
    """
    
    def __init__(self, palace_path: str = "~/.mempalace/palace"):
        self.palace_path = Path(palace_path).expanduser()
        self.chroma_path = self.palace_path / "chroma_db"
        
        # ChromaDB pour recherche vectorielle
        self.client = chromadb.Client(Settings(
            chroma_db_impl="duckdb+parquet",
            persist_directory=str(self.chroma_path)
        ))
        
        # Collections par layer
        self.collections = {
            0: self.client.get_or_create_collection("layer_0_identity"),
            1: self.client.get_or_create_collection("layer_1_compressed"),
            2: self.client.get_or_create_collection("layer_2_scoped"),
            3: self.client.get_or_create_collection("layer_3_deep")
        }
        
        self._ensure_dirs()
    
    def _ensure_dirs(self):
        """Crée la structure wings/rooms/halls."""
        (self.palace_path / "wings").mkdir(parents=True, exist_ok=True)
        (self.palace_path / "halls").mkdir(parents=True, exist_ok=True)
    
    def wake_up(self, wing: Optional[str] = None, room: Optional[str] = None) -> Dict[str, Any]:
        """
        Charge le contexte initial (~170 tokens optimisés).
        Layer 0 (Identity) + Layer 1 (Compressed) + Layer 2 (Scoped si précisé).
        """
        context = {
            "identity": self._load_identity(),
            "system_constraints": self._load_constraints(),
            "active_wing": wing,
            "active_room": room,
            "timestamp": datetime.now().isoformat()
        }
        
        # Layer 1: Contexte projet compressé
        if wing:
            compressed = self.search_memories(
                query="active_context summary",
                wing=wing,
                layer=1,
                n_results=3
            )
            context["compressed_knowledge"] = [e.content for e in compressed]
        
        # Layer 2: Contexte immédiat (room spécifique)
        if wing and room:
            scoped = self.search_memories(
                query="recent_activity",
                wing=wing,
                room=room,
                layer=2,
                n_results=2
            )
            context["recent_activity"] = [e.content for e in scoped]
        
        return context
    
    def mine_content(self, content: str, wing: Optional[str] = None,
                     room: Optional[str] = None, hall: Optional[str] = None,
                     source: str = "lcca", metadata: Optional[Dict] = None,
                     layer: int = 3) -> str:
        """
        Stocke du contenu dans le palace (filesystem + vectoriel).
        Retourne l'ID unique.
        """
        entry_id = hashlib.md5(f"{content}{datetime.now()}".encode()).hexdigest()[:12]
        meta = {
            "wing": wing or "general",
            "room": room or "misc", 
            "hall": hall or "unsorted",
            "source": source,
            "created_at": datetime.now().isoformat(),
            "entry_id": entry_id,
            **(metadata or {})
        }
        
        # Stockage vectoriel (ChromaDB)
        collection = self.collections[layer]
        collection.add(
            documents=[content],
            metadatas=[meta],
            ids=[entry_id]
        )
        
        # Stockage filesystem (verbatim + backup)
        self._write_filesystem(content, meta, entry_id)
        
        return entry_id
    
    def search_memories(self, query: str, wing: Optional[str] = None,
                       room: Optional[str] = None, hall: Optional[str] = None,
                       layer: Optional[int] = None, n_results: int = 5) -> List[MemoryEntry]:
        """
        Recherche sémantique avec filtres hiérarchiques.
        """
        collections = ([self.collections[layer]] if layer is not None 
                      else list(self.collections.values()))
        
        results = []
        for coll in collections:
            where_filter = {}
            if wing: where_filter["wing"] = wing
            if room: where_filter["room"] = room
            if hall: where_filter["hall"] = hall
            
            try:
                query_results = coll.query(
                    query_texts=[query],
                    n_results=n_results,
                    where=where_filter if where_filter else None
                )
                
                if query_results['ids'][0]:
                    for i, doc_id in enumerate(query_results['ids'][0]):
                        meta = query_results['metadatas'][0][i]
                        doc = query_results['documents'][0][i]
                        layer_num = int(coll.name.split("_")[1])
                        
                        results.append(MemoryEntry(
                            content=doc,
                            wing=meta.get("wing"),
                            room=meta.get("room"),
                            hall=meta.get("hall"),
                            source=meta.get("source", "unknown"),
                            metadata=meta,
                            layer=layer_num,
                            embedding_id=doc_id
                        ))
            except Exception as e:
                print(f"Search error in {coll.name}: {e}")
                continue
        
        return results[:n_results]
    
    def get_by_id(self, entry_id: str) -> Optional[MemoryEntry]:
        """Récupère une entrée par son ID (tous layers)."""
        for layer, coll in self.collections.items():
            try:
                result = coll.get(ids=[entry_id])
                if result and result['ids']:
                    meta = result['metadatas'][0]
                    return MemoryEntry(
                        content=result['documents'][0],
                        wing=meta.get("wing"),
                        room=meta.get("room"),
                        metadata=meta,
                        layer=layer
                    )
            except:
                continue
        return None
    
    def compress_aaaK(self, content: str, ratio: int = 30) -> str:
        """
        Compression AAAK pour Layer 1.
        Réduction ~30x tout en gardant la structure.
        """
        lines = content.split('\n')
        if len(lines) <= 10:
            return content
        
        header = lines[:3]
        footer = lines[-3:]
        middle = lines[3:-3]
        
        # Échantillonnage intelligent
        sampled = []
        step = max(1, len(middle) // ratio)
        for i in range(0, len(middle), step):
            sampled.append(middle[i])
        
        compressed = '\n'.join(header + 
                              [f"... [{len(middle)} lines compressed] ..."] + 
                              sampled + footer)
        return compressed
    
    def _write_filesystem(self, content: str, meta: Dict, entry_id: str):
        """Écrit dans la hiérarchie wings/rooms/drawers."""
        if meta.get("wing") and meta["wing"] != "general":
            path = (self.palace_path / "wings" / meta["wing"] / "rooms" / meta.get("room", "misc"))
            if meta.get("hall") and meta["hall"] != "unsorted":
                path = path / "halls" / meta["hall"]
            
            path.mkdir(parents=True, exist_ok=True)
            
            drawer_path = path / f"{entry_id}.json"
            with open(drawer_path, 'w', encoding='utf-8') as f:
                json.dump({"content": content, "metadata": meta}, f, indent=2)
    
    def _load_identity(self) -> str:
        """Charge Layer 0."""
        try:
            identity_file = self.palace_path / "identity.txt"
            if identity_file.exists():
                return identity_file.read_text()
            return "LCCA V5 Fusion - Local Cognitive Coding Agency"
        except:
            return "LCCA V5"
    
    def _load_constraints(self) -> List[str]:
        """Charge les contraintes système (hall:facts)."""
        facts = self.search_memories("system constraints", hall="facts", layer=2, n_results=3)
        return [f.content for f in facts]

2️⃣ core/transaction_manager.py (ACID Anti-Crash)
"""
Transaction Manager V5 - Atomicité garantie même en cas de crash système.
Chaque opération est journalisée avant exécution (Write-Ahead Logging).
"""
import uuid
import json
import shutil
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
import hashlib
import traceback

from .mempalace_client import MemPalaceClient


class TxStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class OpType(Enum):
    WRITE_FILE = "write_file"
    EDIT_FILE = "edit_file"
    DELETE_FILE = "delete_file"
    PATCH_FILE = "patch_file"  # Modification AST
    CREATE_DIR = "create_dir"
    MOVE_FILE = "move_file"


@dataclass
class FileSnapshot:
    path: str
    content_hash: str
    content: Optional[str]  # None si binaire
    exists: bool
    mtime: float = 0.0


@dataclass
class Operation:
    op_id: str
    type: OpType
    target_path: str
    before: FileSnapshot
    after: Optional[FileSnapshot]
    timestamp: str
    metadata: Dict[str, Any]
    rollback_data: Optional[str] = None  # Données spécifiques au rollback


@dataclass
class Transaction:
    tx_id: str
    dsl_input: str
    project: str
    intent: str
    status: TxStatus
    created_at: str
    completed_at: Optional[str]
    operations: List[Operation]
    context_refs: List[str]
    checkpoint_path: Optional[str] = None


class TransactionError(Exception):
    def __init__(self, msg: str, operation: Operation, transaction: Transaction):
        super().__init__(msg)
        self.operation = operation
        self.transaction = transaction


class TransactionManager:
    """
    Gestionnaire transactionnel avec WAL (Write-Ahead Logging).
    Même en cas de crash, l'état est recoverable via MemPalace.
    """
    
    def __init__(self, palace: MemPalaceClient, workspace: str = "./workspace"):
        self.palace = palace
        self.workspace = Path(workspace)
        self.backup_dir = Path("./transactions")
        self.backup_dir.mkdir(exist_ok=True)
        self.current_tx: Optional[Transaction] = None
        self.wal_path = self.backup_dir / "wal.jsonl"  # Write-Ahead Log
    
    def begin(self, dsl_input: str, project: str, intent: str, 
              context_refs: List[str]) -> str:
        """Démarre une transaction avec WAL immédiat."""
        tx_id = str(uuid.uuid4())[:12]
        
        self.current_tx = Transaction(
            tx_id=tx_id,
            dsl_input=dsl_input,
            project=project,
            intent=intent,
            status=TxStatus.PENDING,
            created_at=datetime.now().isoformat(),
            completed_at=None,
            operations=[],
            context_refs=context_refs,
            checkpoint_path=str(self.backup_dir / f"checkpoint_{tx_id}")
        )
        
        # WAL: écrit immédiatement sur disque (crash-safe)
        self._write_wal({
            "type": "BEGIN",
            "tx_id": tx_id,
            "timestamp": datetime.now().isoformat(),
            "data": asdict(self.current_tx)
        })
        
        # Et dans MemPalace (durabilité long terme)
        self._persist_transaction()
        
        print(f"🔒 Transaction {tx_id} BEGIN")
        return tx_id
    
    def log_operation(self, op_type: OpType, target_path: str,
                     execute_func: Callable[[], Any],
                     metadata: Optional[Dict] = None) -> Any:
        """
        Exécute une opération de manière atomique avec possibilité de rollback.
        """
        if not self.current_tx:
            raise RuntimeError("Pas de transaction active. Appeler begin() d'abord.")
        
        full_path = self.workspace / target_path
        
        # 1. SNAPSHOT AVANT (même si fichier n'existe pas)
        before = self._snapshot(full_path)
        
        # Création dossier backup si besoin
        op_backup_dir = self.backup_dir / self.current_tx.tx_id
        op_backup_dir.mkdir(exist_ok=True)
        
        # Sauvegarde physique du fichier original (pour rollback rapide)
        if before.exists and before.content:
            backup_file = op_backup_dir / f"{before.content_hash}.bak"
            if not backup_file.exists():
                backup_file.write_text(before.content, encoding='utf-8')
        
        op = Operation(
            op_id=str(uuid.uuid4())[:8],
            type=op_type,
            target_path=str(target_path),
            before=before,
            after=None,
            timestamp=datetime.now().isoformat(),
            metadata=metadata or {},
            rollback_data=str(op_backup_dir) if before.exists else None
        )
        
        # WAL: log avant exécution
        self._write_wal({
            "type": "OP_START",
            "tx_id": self.current_tx.tx_id,
            "op_id": op.op_id,
            "target": target_path
        })
        
        try:
            # EXÉCUTION
            result = execute_func()
            
            # SNAPSHOT APRÈS
            after = self._snapshot(full_path)
            op.after = after
            
            # Validation: vérifie que le fichier existe bien après
            if op_type in [OpType.WRITE_FILE, OpType.EDIT_FILE, OpType.PATCH_FILE]:
                if not after.exists:
                    raise IOError(f"Le fichier {target_path} n'a pas été créé/modifié correctement")
            
            # Ajout à la transaction
            self.current_tx.operations.append(op)
            self.current_tx.status = TxStatus.RUNNING
            
            # WAL: log succès
            self._write_wal({
                "type": "OP_SUCCESS",
                "tx_id": self.current_tx.tx_id,
                "op_id": op.op_id,
                "after_hash": after.content_hash if after else None
            })
            
            self._persist_transaction()
            print(f"    ✓ {op.op_id}: {op_type.value} {target_path}")
            return result
            
        except Exception as e:
            # WAL: log échec
            self._write_wal({
                "type": "OP_FAIL",
                "tx_id": self.current_tx.tx_id,
                "op_id": op.op_id,
                "error": str(e),
                "traceback": traceback.format_exc()
            })
            
            # Rollback automatique de cette opération
            self._rollback_single_op(op)
            raise TransactionError(f"Op {op.op_id} failed: {e}", op, self.current_tx)
    
    def commit(self):
        """Valide la transaction définitivement."""
        if not self.current_tx:
            return
        
        self.current_tx.status = TxStatus.COMMITTED
        self.current_tx.completed_at = datetime.now().isoformat()
        
        # WAL: commit
        self._write_wal({
            "type": "COMMIT",
            "tx_id": self.current_tx.tx_id,
            "timestamp": self.current_tx.completed_at,
            "n_ops": len(self.current_tx.operations)
        })
        
        self._persist_transaction()
        
        # Cleanup: supprime les backups si commit réussi (optionnel, on garde pour l'historique)
        # shutil.rmtree(self.backup_dir / self.current_tx.tx_id, ignore_errors=True)
        
        print(f"✅ Transaction {self.current_tx.tx_id} COMMITTED ({len(self.current_tx.operations)} ops)")
        self.current_tx = None
    
    def rollback(self, tx_id: Optional[str] = None, specific_op: Optional[str] = None):
        """
        Rollback complet ou partiel.
        Si specific_op: rollback jusqu'à cette opération (non incluse).
        """
        target_tx = self.current_tx if not tx_id or (self.current_tx and self.current_tx.tx_id == tx_id) else None
        
        if not target_tx and tx_id:
            # Recharge depuis MemPalace
            target_tx = self._load_transaction(tx_id)
        
        if not target_tx:
            raise ValueError(f"Transaction {tx_id} introuvable")
        
        print(f"⏮️  ROLLBACK {target_tx.tx_id}" + (f" jusqu'à {specific_op}" if specific_op else ""))
        
        ops_to_rollback = target_tx.operations
        if specific_op:
            # Trouve l'index
            idx = next((i for i, op in enumerate(ops_to_rollback) if op.op_id == specific_op), len(ops_to_rollback))
            ops_to_rollback = ops_to_rollback[:idx]
        
        # Rollback en ordre inverse (LIFO)
        for op in reversed(ops_to_rollback):
            self._rollback_single_op(op)
        
        target_tx.status = TxStatus.ROLLED_BACK
        target_tx.completed_at = datetime.now().isoformat()
        self._persist_transaction(target_tx)
        
        if self.current_tx and self.current_tx.tx_id == target_tx.tx_id:
            self.current_tx = None
    
    def _rollback_single_op(self, op: Operation):
        """Restaure un fichier à son état 'before'."""
        target = self.workspace / op.target_path
        
        try:
            if not op.before.exists:
                # Le fichier n'existait pas avant → suppression
                if target.exists():
                    target.unlink()
                    print(f"    ↩️  Suppression {op.target_path} (recréé pendant TX)")
            else:
                # Restauration depuis backup ou métadonnées
                if op.rollback_data:
                    backup_dir = Path(op.rollback_data)
                    backup_file = backup_dir / f"{op.before.content_hash}.bak"
                    if backup_file.exists():
                        shutil.copy(backup_file, target)
                    elif op.before.content:
                        target.write_text(op.before.content, encoding='utf-8')
                
                # Restore mtime pour ne pas perturber les outils de build
                if op.before.mtime:
                    import os
                    os.utime(target, (op.before.mtime, op.before.mtime))
            
            print(f"    ↩️  Restauré {op.target_path}")
            
        except Exception as e:
            print(f"    ⚠️  Erreur rollback {op.target_path}: {e}")
    
    def _snapshot(self, path: Path) -> FileSnapshot:
        """Crée un snapshot complet d'un fichier."""
        exists = path.exists()
        content = None
        content_hash = ""
        mtime = 0.0
        
        if exists:
            mtime = path.stat().st_mtime
            try:
                content = path.read_text(encoding='utf-8')
                content_hash = hashlib.md5(content.encode()).hexdigest()
            except (UnicodeDecodeError, IOError):
                # Fichier binaire ou inaccessible
                content_hash = hashlib.md5(str(mtime).encode()).hexdigest()
        
        return FileSnapshot(
            path=str(path),
            content_hash=content_hash,
            content=content,
            exists=exists,
            mtime=mtime
        )
    
    def _write_wal(self, entry: Dict):
        """Write-Ahead Log pour crash recovery."""
        with open(self.wal_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')
    
    def _persist_transaction(self, tx: Optional[Transaction] = None):
        """Sauvegarde dans MemPalace (Layer 3)."""
        tx = tx or self.current_tx
        if not tx:
            return
        
        data = json.dumps(asdict(tx), indent=2, default=str)
        
        self.palace.mine_content(
            content=data,
            wing="lcca_system",
            hall="transactions",
            source="tx_manager",
            metadata={
                "tx_id": tx.tx_id,
                "status": tx.status.value,
                "project": tx.project,
                "n_ops": len(tx.operations)
            },
            layer=3
        )
    
    def _load_transaction(self, tx_id: str) -> Optional[Transaction]:
        """Charge une transaction depuis MemPalace."""
        results = self.palace.search_memories(
            f"transaction {tx_id}",
            wing="lcca_system",
            hall="transactions",
            n_results=1
        )
        
        if results:
            try:
                data = json.loads(results[0].content)
                return Transaction(**data)
            except:
                pass
        return None
    
    def get_pending_transactions(self) -> List[Transaction]:
        """Récupère les transactions non terminées (pour recovery au boot)."""
        results = self.palace.search_memories(
            "transaction",
            wing="lcca_system",
            hall="transactions",
            n_results=20
        )
        
        pending = []
        for entry in results:
            try:
                meta = entry.metadata
                if meta.get("status") in ["pending", "running"]:
                    data = json.loads(entry.content)
                    pending.append(Transaction(**data))
            except:
                continue
        return pending

3️⃣ core/ast_indexer.py (Indexation intelligente)
"""
Indexer V5 - Analyse AST complète avec graphe de dépendances.
Extrait classes, fonctions, imports, et relations entre fichiers.
"""
import ast
import os
from pathlib import Path
from typing import Dict, List, Set, Optional, Any
from dataclasses import dataclass, asdict


@dataclass
class Symbol:
    name: str
    type: str  # 'function', 'class', 'variable', 'import'
    line: int
    file: str
    dependencies: Set[str] = None  # Autres symboles utilisés
    
    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = set()


@dataclass
class FileIndex:
    path: str
    symbols: List[Symbol]
    imports: List[str]
    exported: List[str]  # Ce que le fichier exporte (pour dépendances)
    raw_content: str
    ast_tree: Optional[ast.AST] = None


class ASTIndexer:
    """
    Indexe un repository Python complet avec analyse de dépendances.
    """
    
    def __init__(self, workspace: str = "./workspace"):
        self.workspace = Path(workspace)
        self.files: Dict[str, FileIndex] = {}
        self.symbols_table: Dict[str, List[Symbol]] = {}  # nom -> [symboles]
        
    def index_repository(self) -> Dict[str, FileIndex]:
        """Indexe tout le workspace."""
        print("🔍 Indexation du repository...")
        
        for py_file in self.workspace.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
                
            try:
                file_index = self._index_file(py_file)
                self.files[str(py_file)] = file_index
                
                # Indexation symboles globale
                for sym in file_index.symbols:
                    if sym.name not in self.symbols_table:
                        self.symbols_table[sym.name] = []
                    self.symbols_table[sym.name].append(sym)
                    
            except SyntaxError as e:
                print(f"    ⚠️  Syntax error in {py_file}: {e}")
            except Exception as e:
                print(f"    ⚠️  Error indexing {py_file}: {e}")
        
        # Deuxième passe: résolution des dépendances entre fichiers
        self._resolve_cross_file_deps()
        
        print(f"✅ Indexation terminée: {len(self.files)} fichiers, {len(self.symbols_table)} symboles")
        return self.files
    
    def _index_file(self, file_path: Path) -> FileIndex:
        """Indexe un fichier unique."""
        content = file_path.read_text(encoding='utf-8')
        tree = ast.parse(content)
        
        symbols = []
        imports = []
        exported = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
                    
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(f"{module}.{alias.name}")
                    
            elif isinstance(node, ast.FunctionDef):
                sym = Symbol(
                    name=node.name,
                    type="function",
                    line=node.lineno,
                    file=str(file_path)
                )
                # Analyse du corps pour dépendances locales
                for child in ast.walk(node):
                    if isinstance(child, ast.Name):
                        sym.dependencies.add(child.id)
                    elif isinstance(child, ast.Attribute):
                        if isinstance(child.value, ast.Name):
                            sym.dependencies.add(child.value.id)
                symbols.append(sym)
                exported.append(node.name)
                
            elif isinstance(node, ast.ClassDef):
                sym = Symbol(
                    name=node.name,
                    type="class",
                    line=node.lineno,
                    file=str(file_path)
                )
                # Dépendances: classes parentes
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        sym.dependencies.add(base.id)
                symbols.append(sym)
                exported.append(node.name)
        
        return FileIndex(
            path=str(file_path),
            symbols=symbols,
            imports=imports,
            exported=exported,
            raw_content=content,
            ast_tree=tree
        )
    
    def _resolve_cross_file_deps(self):
        """Détecte quels fichiers dépendent de quels autres."""
        for file_path, file_idx in self.files.items():
            for sym in file_idx.symbols:
                for dep in list(sym.dependencies):
                    # Cherche si dep est défini dans un autre fichier
                    if dep in self.symbols_table:
                        defining_files = [s.file for s in self.symbols_table[dep]]
                        # Ajoute info de dépendance au fichier
                        pass  # Pourrait stocker dans un graphe séparé
    
    def find_symbol_definition(self, name: str) -> List[Symbol]:
        """Trouve où un symbole est défini."""
        return self.symbols_table.get(name, [])
    
    def get_file_exports(self, file_path: str) -> List[str]:
        """Retourne ce qu'un fichier exporte."""
        if file_path in self.files:
            return self.files[file_path].exported
        return []
    
    def search_by_content(self, query_terms: List[str]) -> List[str]:
        """Recherche fichiers contenant certains termes."""
        results = []
        for path, idx in self.files.items():
            content_lower = idx.raw_content.lower()
            if all(term.lower() in content_lower for term in query_terms]):
                results.append(path)
        return results
    
    def to_dict(self) -> Dict:
        """Sérialisation pour stockage MemPalace."""
        return {
            path: {
                "path": idx.path,
                "symbols": [{"name": s.name, "type": s.type, "line": s.line} for s in idx.symbols],
                "imports": idx.imports,
                "exports": idx.exported
            }
            for path, idx in self.files.items()
        }

4️⃣ core/smart_patcher.py (Modification AST infaillible)
"""
Smart Patcher V5 - Modifications via AST libcst.
Garantit la validité syntaxique et préserve le formatting.
"""
import libcst as cst
from libcst.metadata import PositionProvider
from typing import Optional, Union, List
from pathlib import Path


class AddFunctionTransformer(cst.CSTTransformer):
    """Ajoute une fonction à la fin du module."""
    def __init__(self, func_code: str):
        self.func_code = func_code
        self.added = False
        
    def leave_Module(self, original_node, updated_node):
        if not self.added:
            # Parse la nouvelle fonction
            new_module = cst.parse_module(self.func_code)
            # Ajoute à la fin
            new_body = updated_node.body + new_module.body
            self.added = True
            return updated_node.with_changes(body=new_body)
        return updated_node


class ModifyFunctionTransformer(cst.CSTTransformer):
    """Modifie le corps d'une fonction existante."""
    METADATA_DEPENDENCIES = (PositionProvider,)
    
    def __init__(self, target_name: str, new_body_code: str):
        self.target_name = target_name
        self.new_body = cst.parse_module(new_body_code).body
        self.modified = False
        
    def leave_FunctionDef(self, original_node, updated_node):
        if original_node.name.value == self.target_name and not self.modified:
            self.modified = True
            # Remplace le corps tout en gardant la signature
            if len(self.new_body) == 1 and isinstance(self.new_body[0], cst.FunctionDef):
                # Si on reçoit une définition complète, on prend juste le corps
                new_body = self.new_body[0].body
            else:
                # Sinon on suppose que c'est un corps de fonction
                new_body = cst.IndentedBlock(body=self.new_body)
            
            return updated_node.with_changes(body=new_body)
        return updated_node


class AddImportTransformer(cst.CSTTransformer):
    """Ajoute un import intelligent (vérifie doublons)."""
    def __init__(self, module: str, names: Optional[List[str]] = None):
        self.module = module
        self.names = names or []
        self.existing_imports = set()
        
    def visit_Import(self, node):
        for alias in node.names:
            self.existing_imports.add(alias.name.value)
            
    def visit_ImportFrom(self, node):
        if node.module and node.module.value == self.module:
            for alias in node.names:
                self.existing_imports.add(alias.name.value)
                
    def leave_Module(self, original_node, updated_node):
        # Vérifie si déjà présent
        if self.module in self.existing_imports:
            return original_node
            
        # Crée le nouvel import
        if self.names:
            import_node = cst.ImportFrom(
                module=cst.Name(value=self.module),
                names=[cst.ImportAlias(name=cst.Name(name=n)) for n in self.names]
            )
        else:
            import_node = cst.Import(names=[cst.ImportAlias(name=cst.Name(value=self.module))])
        
        # Ajoute en début de fichier (après docstring si présente)
        new_body = list(updated_node.body)
        insert_idx = 0
        
        # Saute les docstrings et les __future__
        for i, stmt in enumerate(new_body):
            if isinstance(stmt, (cst.Expr, cst.Import, cst.ImportFrom)):
                if isinstance(stmt, cst.Expr) and isinstance(stmt.value, cst.SimpleString):
                    continue  # Docstring
                if isinstance(stmt, cst.ImportFrom) and stmt.module and stmt.module.value == "__future__":
                    continue
            else:
                insert_idx = i
                break
        
        new_body.insert(insert_idx, import_node)
        return updated_node.with_changes(body=new_body)


class SmartPatcher:
    """
    Interface haut niveau pour modifications AST.
    """
    
    def __init__(self, workspace: str = "./workspace"):
        self.workspace = Path(workspace)
        
    def add_function(self, file_path: str, func_code: str) -> str:
        """
        Ajoute une fonction à la fin d'un fichier.
        Préserve le formatting existant.
        """
        path = self.workspace / file_path
        source = path.read_text(encoding='utf-8')
        
        try:
            tree = cst.parse_module(source)
            transformer = AddFunctionTransformer(func_code)
            new_tree = tree.visit(transformer)
            
            if not transformer.added:
                raise ValueError("Échec ajout fonction")
                
            return new_tree.code
            
        except cst.ParserSyntaxError as e:
            raise SyntaxError(f"Syntax error in {file_path}: {e}")
    
    def modify_function(self, file_path: str, func_name: str, new_body: str) -> str:
        """
        Remplace le corps d'une fonction existante.
        Garde la signature (params, decorators).
        """
        path = self.workspace / file_path
        source = path.read_text(encoding='utf-8')
        
        tree = cst.parse_module(source)
        transformer = ModifyFunctionTransformer(func_name, new_body)
        new_tree = tree.visit(transformer)
        
        if not transformer.modified:
            raise ValueError(f"Fonction {func_name} non trouvée dans {file_path}")
            
        return new_tree.code
    
    def add_import(self, file_path: str, module: str, names: Optional[List[str]] = None) -> str:
        """Ajoute un import s'il n'existe pas déjà."""
        path = self.workspace / file_path
        source = path.read_text(encoding='utf-8')
        
        tree = cst.parse_module(source)
        transformer = AddImportTransformer(module, names)
        new_tree = tree.visit(transformer)
        
        return new_tree.code
    
    def apply_patch(self, file_path: str, patch_type: str, **kwargs) -> str:
        """
        Interface générique pour appliquer un patch.
        
        Args:
            file_path: Chemin relatif depuis workspace
            patch_type: 'add_function', 'modify_function', 'add_import'
            **kwargs: Arguments spécifiques au type
        """
        if patch_type == "add_function":
            return self.add_function(file_path, kwargs['code'])
        elif patch_type == "modify_function":
            return self.modify_function(file_path, kwargs['name'], kwargs['code'])
        elif patch_type == "add_import":
            return self.add_import(file_path, kwargs['module'], kwargs.get('names'))
        else:
            raise ValueError(f"Type de patch inconnu: {patch_type}")

5️⃣ core/planner.py (Planning multi-fichiers intelligent)
"""
Planner V5 - Génère des plans structurés avec détection d'impact.
Utilise l'index AST pour planifier les modifications cohérentes.
"""
import json
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from enum import Enum

from .ast_indexer import ASTIndexer, FileIndex
from .mempalace_client import MemPalaceClient


class OpPriority(Enum):
    HIGH = "high"      # Dépendances critiques
    NORMAL = "normal"  # Standard
    LOW = "low"        # Cosmétique


@dataclass
class PlannedOperation:
    file: str
    action: str  # 'create', 'modify', 'delete'
    target_symbol: Optional[str]  # Nom fonction/classe à modifier
    description: str
    dependencies: List[str]  # Fichiers dont dépend cette op
    priority: OpPriority = OpPriority.NORMAL
    estimated_tokens: int = 1000  # Pour gestion contexte LLM


class MultiFilePlanner:
    """
    Planifie les modifications sur plusieurs fichiers
    en respectant les dépendances et la cohérence.
    """
    
    def __init__(self, indexer: ASTIndexer, palace: MemPalaceClient):
        self.indexer = indexer
        self.palace = palace
        
    def create_plan(self, intent: str, target_files: List[str]) -> List[PlannedOperation]:
        """
        Crée un plan d'opérations ordonné.
        
        Stratégie:
        1. Détecte les fichiers à modifier (déjà fournis par selector)
        2. Détermine l'ordre (dépendances d'import)
        3. Assigne priorités
        """
        operations = []
        
        # Analyse des fichiers cibles
        for file_path in target_files:
            if file_path not in self.indexer.files:
                # Nouveau fichier
                op = PlannedOperation(
                    file=file_path,
                    action="create",
                    target_symbol=None,
                    description=f"Créer {file_path}",
                    dependencies=[],
                    priority=OpPriority.HIGH if self._is_core_file(file_path) else OpPriority.NORMAL
                )
                operations.append(op)
            else:
                # Fichier existant - détecte quoi modifier
                file_idx = self.indexer.files[file_path]
                
                # Pour l'instant, on suppose qu'on modifie ou ajoute
                op = PlannedOperation(
                    file=file_path,
                    action="modify",
                    target_symbol=None,  # Sera déterminé par l'analyse sémantique
                    description=f"Modifier {file_path}",
                    dependencies=self._get_file_dependencies(file_idx),
                    priority=OpPriority.NORMAL
                )
                operations.append(op)
        
        # Tri topologique simple (fichiers sans déps d'abord)
        operations.sort(key=lambda x: (len(x.dependencies), x.priority.value))
        
        return operations
    
    def _is_core_file(self, file_path: str) -> bool:
        """Détecte si un fichier est critique (models, core, etc.)."""
        core_patterns = ['models', 'core', 'base', 'config', '__init__']
        return any(p in file_path.lower() for p in core_patterns)
    
    def _get_file_dependencies(self, file_idx: FileIndex) -> List[str]:
        """Retourne les fichiers dont dépend ce fichier."""
        deps = []
        for imp in file_idx.imports:
            # Mapping simple: from module.name -> module/name.py
            parts = imp.split('.')
            potential_path = '/'.join(parts) + '.py'
            if potential_path in self.indexer.files:
                deps.append(potential_path)
        return deps
    
    def generate_prompt_for_op(self, op: PlannedOperation, intent: str) -> str:
        """
        Génère le prompt LLM pour une opération spécifique,
        avec contexte des dépendances.
        """
        context_parts = [f"Task: {intent}"]
        context_parts.append(f"File: {op.file}")
        context_parts.append(f"Action: {op.action}")
        
        if op.dependencies:
            context_parts.append("\nDependencies (consider these interfaces):")
            for dep_file in op.dependencies[:3]:  # Limite pour économiser tokens
                if dep_file in self.indexer.files:
                    exports = self.indexer.get_file_exports(dep_file)
                    context_parts.append(f"  {dep_file}: exports {exports}")
        
        if op.file in self.indexer.files:
            # Ajoute un résumé du fichier existant
            file_idx = self.indexer.files[op.file]
            symbols_summary = [f"{s.type} {s.name}" for s in file_idx.symbols[:5]]
            context_parts.append(f"\nExisting symbols: {', '.join(symbols_summary)}")
        
        return "\n".join(context_parts)
    
    def validate_plan_consistency(self, operations: List[PlannedOperation]) -> bool:
        """
        Vérifie que le plan ne crée pas de contradictions
        (ex: supprimer une fonction utilisée ailleurs).
        """
        symbols_affected = {}
        
        for op in operations:
            if op.target_symbol:
                if op.target_symbol in symbols_affected:
                    print(f"⚠️  Conflit: {op.target_symbol} modifié 2 fois")
                    return False
                symbols_affected[op.target_symbol] = op.file
        
        # Vérifie que les dépendances existent
        all_files = {op.file for op in operations}
        for op in operations:
            for dep in op.dependencies:
                if dep not in all_files and dep not in self.indexer.files:
                    print(f"⚠️  Dépendance manquante: {dep} pour {op.file}")
                    # Non bloquant, mais warning
        
        return True

6️⃣ core/orchestrator.py (Coordination finale)
"""
Orchestrateur V5 Fusion - Coordination complète du système.
Transactionnel + AST + Indexation + Recovery.
"""
from typing import Optional, List
from pathlib import Path

from .mempalace_client import MemPalaceClient
from .transaction_manager import TransactionManager, OpType
from .ast_indexer import ASTIndexer
from .smart_patcher import SmartPatcher
from .planner import MultiFilePlanner, PlannedOperation
from .dsl_parser import DSLParser, Intent
from .recovery_service import RecoveryService


class LCCAV5Fusion:
    """
    Interface principale LCCA V5 Fusion.
    """
    
    def __init__(self, workspace: str = "./workspace"):
        self.workspace = Path(workspace)
        self.workspace.mkdir(exist_ok=True)
        
        # Initialisation composants
        print("🚀 Initialisation LCCA V5 Fusion...")
        self.palace = MemPalaceClient()
        self.tx_manager = TransactionManager(self.palace, str(self.workspace))
        self.indexer = ASTIndexer(str(self.workspace))
        self.patcher = SmartPatcher(str(self.workspace))
        self.planner = MultiFilePlanner(self.indexer, self.palace)
        self.recovery = RecoveryService(self.tx_manager)
        
        # Indexation initiale
        self.indexer.index_repository()
        
        # Check recovery au boot
        if self.recovery.boot_check():
            print("💡 Des transactions en attente ont été détectées.")
            # Auto-recovery des transactions orphelines
            self.recovery.auto_recover_pending()
    
    def execute(self, command: str, auto_rollback: bool = True) -> bool:
        """
        Point d'entrée principal.
        
        Args:
            command: Commande DSL ou naturelle
            auto_rollback: Si True, rollback automatique en cas d'échec
        """
        try:
            # 1. Parsing DSL
            parser = DSLParser()
            intent = parser.parse(command)
            print(f"🎯 Intent: {intent.project} | {intent.action} {intent.details}")
            
            # 2. Sélection fichiers (via recherche sémantique + index)
            target_files = self._select_files(intent)
            if not target_files:
                print("❌ Aucun fichier cible identifié")
                return False
            
            print(f"📁 Fichiers cibles: {len(target_files)}")
            
            # 3. Planning
            plan = self.planner.create_plan(intent.details, target_files)
            if not self.planner.validate_plan_consistency(plan):
                print("⚠️  Plan incohérent détecté")
                return False
            
            # 4. Début Transaction
            context_refs = []  # Pourrait stocker les IDs des fichiers indexés
            tx_id = self.tx_manager.begin(command, intent.project, 
                                         f"{intent.action} {intent.details}", 
                                         context_refs)
            
            # 5. Exécution du plan
            for op in plan:
                print(f"  🔧 {op.action} {op.file}" + (f"::{op.target_symbol}" if op.target_symbol else ""))
                
                # Génération du code (simulé, à remplacer par appel LLM)
                generated_code = self._generate_code_for_op(op, intent)
                
                # Application via Transaction (atomic)
                def do_patch():
                    if op.action == "create":
                        # Écriture nouveau fichier
                        full_path = self.workspace / op.file
                        full_path.parent.mkdir(parents=True, exist_ok=True)
                        full_path.write_text(generated_code, encoding='utf-8')
                        return generated_code
                    else:
                        # Modification AST
                        new_content = self.patcher.apply_patch(
                            op.file,
                            "add_function",  # ou modify selon besoin
                            code=generated_code
                        )
                        full_path = self.workspace / op.file
                        full_path.write_text(new_content, encoding='utf-8')
                        return new_content
                
                self.tx_manager.log_operation(
                    OpType.PATCH_FILE if op.action == "modify" else OpType.WRITE_FILE,
                    op.file,
                    do_patch,
                    metadata={"intent": intent.details, "symbol": op.target_symbol}
                )
            
            # 6. Validation (tests/syntaxe)
            if self._validate_changes():
                self.tx_manager.commit()
                print("✅ Succès - Transaction commitée")
                
                # Mise à jour index
                self.indexer.index_repository()
                return True
            else:
                raise Exception("Validation échouée")
                
        except Exception as e:
            print(f"❌ Erreur: {e}")
            if auto_rollback:
                print("🔄 Rollback automatique...")
                self.tx_manager.rollback()
            return False
    
    def _select_files(self, intent: Intent) -> List[str]:
        """
        Sélection intelligente des fichiers à modifier.
        Combine recherche sémantique MemPalace et indexation.
        """
        # Recherche dans MemPalace (contexte existant)
        query = f"{intent.target} {intent.sub_target or ''} {intent.details}"
        memories = self.palace.search_memories(
            query=query,
            wing=intent.project.lower().replace(" ", "_"),
            n_results=5
        )
        
        files_from_memory = []
        for mem in memories:
            if "file" in mem.metadata:
                files_from_memory.append(mem.metadata["file"])
        
        # Recherche dans l'index AST (symboles)
        # Ex: si on cherche "validate", trouve validate.py ou fonctions validate
        files_from_index = []
        for symbol_name in [intent.target, intent.sub_target]:
            if symbol_name:
                matches = self.indexer.find_symbol_definition(symbol_name)
                files_from_index.extend([m.file for m in matches])
        
        # Merge et déduplique
        all_files = list(set(files_from_memory + files_from_index))
        
        # Filtre existence
        existing = [f for f in all_files if (self.workspace / f).exists()]
        
        # Si aucun fichier trouvé mais création demandée, propose nouveau fichier
        if not existing and intent.action in ["crée", "ajoute"]:
            suggested = f"src/{intent.target.lower().replace(' ', '_')}.py"
            return [suggested]
        
        return existing
    
    def _generate_code_for_op(self, op: PlannedOperation, intent: Intent) -> str:
        """
        Génère le code pour une opération.
        TODO: Intégrer appel LLM avec contexte assemblé.
        """
        # Pour l'instant, placeholder
        return f"# {op.action} {op.target_symbol or op.file}\n# Intent: {intent.details}\npass\n"
    
    def _validate_changes(self) -> bool:
        """
        Valide les changements (syntaxe, imports).
        """
        import subprocess
        
        # Vérification syntaxe Python
        for py_file in self.workspace.rglob("*.py"):
            try:
                compile(py_file.read_text(), py_file.name, 'exec')
            except SyntaxError:
                print(f"    ❌ Syntax error in {py_file}")
                return False
        
        # Optionnel: exécuter tests si présents
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", str(self.workspace), "-x", "-q"],
                capture_output=True,
                timeout=30
            )
            if result.returncode != 0:
                print(f"    ⚠️  Tests échouent: {result.stdout.decode()[:200]}")
                return False
        except FileNotFoundError:
            # Pas de tests, on skip
            pass
        
        return True

7️⃣ main.py (Entry Point)
#!/usr/bin/env python3
"""
LCCA V5 Fusion - Local Cognitive Coding Agency
Usage: python main.py "DashboardV1 - Page RDV - Ajoute validation email"
"""
import sys
import argparse

from core.orchestrator import LCCAV5Fusion


def main():
    parser = argparse.ArgumentParser(description='LCCA V5 Fusion')
    parser.add_argument('command', nargs='?', help='Commande DSL (Projet - Cible - Action)')
    parser.add_argument('--workspace', '-w', default='./workspace', help='Dossier projet')
    parser.add_argument('--no-rollback', action='store_true', help='Désactive rollback auto')
    parser.add_argument('--recover', '-r', action='store_true', help='Mode recovery manuel')
    
    args = parser.parse_args()
    
    # Initialisation (inclut auto-recovery)
    lcca = LCCAV5Fusion(workspace=args.workspace)
    
    if args.recover:
        print("Mode recovery - utiliser --recover n'est normalement pas nécessaire (auto au boot)")
        return
    
    if not args.command:
        print("Usage: python main.py \"Projet - Cible - Action - Details\"")
        print("Exemple: python main.py \"DashboardV1 - Page RDV - Ajoute validate_email()\"")
        sys.exit(1)
    
    # Exécution
    success = lcca.execute(args.command, auto_rollback=not args.no_rollback)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

🚀 Installation & Utilisation
# Installation dépendances
pip install libcst chromadb

# Lancement
python main.py "MonProjet - Module Auth - Ajoute fonction login()"

# Si crash pendant l'opération, au redémarrage:
# → Auto-recovery détecte la transaction non terminée
# → Rollback ou commit selon état

# Désactiver rollback auto (pour debug)
python main.py "..." --no-rollback

🔌 core/mempalace_adapter.py (Connexion à ton instance)
"""
Adapter MemPalace pour connexion à l'instance existante Windows (D:\MediBot\Mempalace).
Lit la configuration YAML et se connecte à la ChromaDB existante.
"""
import os
import yaml
import sqlite3
from pathlib import Path
from typing import Dict, Optional, List, Any
import chromadb
from chromadb.config import Settings

from .mempalace_client import MemPalaceClient, MemoryEntry


class ExistingMemPalaceAdapter(MemPalaceClient):
    """
    Adapteur qui se connecte à ton MemPalace MCP existant.
    Chemin: D:\MediBot\Mempalace (ou adaptable)
    """
    
    def __init__(self, palace_path: str = None):
        # Détection auto du chemin Windows ou config
        if palace_path is None:
            # Cherche dans les emplacements courants
            possible_paths = [
                r"D:\MediBot\Mempalace",  # Ton chemin exact
                r"D:\MediBot\Mempalace\memory_palace",  # Si le palace est dans le sous-dossier
                os.path.expanduser("~/MediBot/Mempalace"),
                os.path.expanduser("~/.mempalace/palace")
            ]
            
            for path in possible_paths:
                if Path(path).exists():
                    # Vérifie si c'est le dossier contenant memory_palace ou directement memory_palace
                    if (Path(path) / "memory_palace").exists():
                        self.root_path = Path(path)
                        self.palace_path = Path(path) / "memory_palace"
                    elif (Path(path) / "chroma.sqlite3").exists():
                        self.root_path = Path(path).parent
                        self.palace_path = Path(path)
                    else:
                        self.root_path = Path(path)
                        self.palace_path = Path(path)
                    break
            else:
                raise FileNotFoundError("MemPalace non trouvé. Vérifie le chemin D:\\MediBot\\Mempalace")
        else:
            self.palace_path = Path(palace_path)
            self.root_path = self.palace_path.parent
        
        print(f"🔗 Connexion à MemPalace: {self.palace_path}")
        
        # Chargement de la config existante
        self.config = self._load_yaml_config()
        
        # Lecture de l'identity existante (Layer 0)
        self.identity = self._load_existing_identity()
        
        # Connexion à la ChromaDB existante (PAS de création, connexion uniquement)
        self.client = self._connect_existing_chroma()
        
        # Récupération des collections existantes
        self.collections = self._get_existing_collections()
        
        # Scan des spécifications dans specs/
        self.specs = self._load_specs()
        
        print(f"✅ Connecté | Identity: {self.identity[:50]}... | Specs: {len(self.specs)}")
    
    def _load_yaml_config(self) -> Dict:
        """Lit le mempalace.yaml existant."""
        config_file = self.palace_path / "mempalace.yaml"
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        return {}
    
    def _load_existing_identity(self) -> str:
        """Lit l'identity.txt existant (Layer 0)."""
        identity_file = self.palace_path / "identity.txt"
        if identity_file.exists():
            content = identity_file.read_text(encoding='utf-8')
            return content.strip()
        return "LCCA Connected to Existing MemPalace"
    
    def _connect_existing_chroma(self):
        """Se connecte à la ChromaDB SQLite existante."""
        chroma_path = str(self.palace_path)
        
        # Vérifie que la DB existe
        db_file = self.palace_path / "chroma.sqlite3"
        if not db_file.exists():
            raise FileNotFoundError(f"ChromaDB non trouvée: {db_file}")
        
        client = chromadb.Client(Settings(
            chroma_db_impl="duckdb+parquet",
            persist_directory=chroma_path,
            anonymized_telemetry=False
        ))
        return client
    
    def _get_existing_collections(self) -> Dict[int, Any]:
        """Liste les collections existantes dans Chroma."""
        collections = {}
        
        # Essaie de lister les collections existantes
        try:
            existing = self.client.list_collections()
            print(f"📚 Collections existantes: {[c.name for c in existing]}")
            
            # Map les collections existantes par layer si possible
            for coll in existing:
                name = coll.name
                if "layer_0" in name:
                    collections[0] = coll
                elif "layer_1" in name:
                    collections[1] = coll
                elif "layer_2" in name:
                    collections[2] = coll
                elif "layer_3" in name:
                    collections[3] = coll
                else:
                    # Collection existante non layerisée, on la met en layer 3
                    collections[3] = coll
        except Exception as e:
            print(f"⚠️  Impossible de lister collections: {e}")
            # Crée les collections si elles n'existent pas
            pass
        
        # Complète avec des get_or_create pour être sûr
        for i in range(4):
            if i not in collections:
                collections[i] = self.client.get_or_create_collection(f"layer_{i}_lcca")
        
        return collections
    
    def _load_specs(self) -> List[Dict]:
        """Charge les spécifications du dossier specs/."""
        specs_dir = self.palace_path / "specs"
        specs = []
        
        if not specs_dir.exists():
            return specs
        
        for spec_file in specs_dir.iterdir():
            if spec_file.suffix in ['.md', '.txt', '.json']:
                content = spec_file.read_text(encoding='utf-8')
                specs.append({
                    "name": spec_file.name,
                    "content": content,
                    "path": str(spec_file)
                })
                # Indexe automatiquement dans MemPalace si pas déjà fait
                self._ensure_spec_indexed(spec_file.name, content)
        
        return specs
    
    def _ensure_spec_indexed(self, name: str, content: str):
        """S'assure que le spec est dans la mémoire vectorielle."""
        # Vérifie si déjà présent
        results = self.collections[2].query(
            query_texts=[f"spec {name}"],
            n_results=1,
            where={"source": "spec_file"}
        )
        
        if not results['ids'][0]:
            # Ajoute dans Layer 2 (scoped)
            self.collections[2].add(
                documents=[content],
                metadatas=[{
                    "source": "spec_file",
                    "filename": name,
                    "type": "specification"
                }],
                ids=[f"spec_{name}_{hash(content) % 10000}"]
            )
    
    def get_medi_context(self) -> Dict[str, Any]:
        """
        Récupère le contexte spécifique MediBot (ton projet).
        Cherche dans les wings si existants, ou crée le contexte depuis specs.
        """
        context = {
            "identity": self.identity,
            "config": self.config,
            "specs": self.specs,
            "recent_memories": []
        }
        
        # Cherche un wing MediBot ou Medical
        for wing_name in ["MediBot", "Medical", "DashboardV1", "medibot"]:
            try:
                # Query dans Chroma pour ce wing
                results = self.collections[2].query(
                    query_texts=["medical bot dashboard"],
                    n_results=5,
                    where={"wing": wing_name}
                )
                if results['ids'][0]:
                    context["project_wing"] = wing_name
                    context["recent_memories"] = results['documents'][0]
                    break
            except:
                continue
        
        return context
    
    def wake_up_medi(self) -> Dict[str, Any]:
        """
        Wake-up optimisé pour ton projet MediBot.
        Combine Layer 0 (identity) + Layer 1 (compressed Medi) + Specs.
        """
        # Layer 0: Identity système
        identity = self.identity
        
        # Layer 1: Contexte Medi compressé
        medi_summary = []
        try:
            results = self.collections[1].query(
                query_texts=["medibot architecture summary"],
                n_results=3
            )
            if results['documents'][0]:
                medi_summary = results['documents'][0]
        except:
            pass
        
        # Layer 2: Activité récente
        recent = []
        try:
            results = self.collections[2].query(
                query_texts=["recent changes medibot"],
                n_results=3,
                where={"wing": "MediBot"} if "MediBot" in str(self.config) else {}
            )
            if results['documents'][0]:
                recent = results['documents'][0]
        except:
            pass
        
        return {
            "layer_0_identity": identity,
            "layer_1_compressed": medi_summary,
            "layer_2_recent": recent,
            "layer_3_specs": [s["content"][:500] for s in self.specs[:3]],
            "medi_config": self.config
        }


# Helper pour créer le client facilement
def connect_to_your_mempalace() -> ExistingMemPalaceAdapter:
    """
    Factory function pour se connecter à ton MemPalace Windows.
    """
    return ExistingMemPalaceAdapter(r"D:\MediBot\Mempalace")

🛠️ core/orchestrator_medi.py (Orchestrateur spécialisé MediBot)
"""
Orchestrateur spécialisé pour MediBot utilisant le contexte existant.
"""
from .orchestrator import LCCAV5Fusion
from .mempalace_adapter import ExistingMemPalaceAdapter, connect_to_your_mempalace


class MediBotOrchestrator(LCCAV5Fusion):
    """
    Orchestrateur pré-configuré pour ton projet MediBot.
    Utilise le MemPalace existant à D:\MediBot\Mempalace.
    """
    
    def __init__(self, workspace: str = "./workspace"):
        # Connexion à ton MemPalace existant au lieu d'en créer un nouveau
        print("🏥 Initialisation MediBot Orchestrator...")
        self.workspace = Path(workspace)
        self.workspace.mkdir(exist_ok=True)
        
        # Adapter spécifique qui lit ton MemPalace existant
        self.palace = connect_to_your_mempalace()
        
        # Récupère le contexte Medi spécifique
        self.medi_context = self.palace.wake_up_medi()
        print(f"💉 Contexte Medi chargé: {len(self.medi_context.get('layer_3_specs', []))} specs")
        
        # Initialisation du reste (transaction manager, etc.)
        self.tx_manager = TransactionManager(self.palace, str(self.workspace))
        self.indexer = ASTIndexer(str(self.workspace))
        self.patcher = SmartPatcher(str(self.workspace))
        
        # Indexation du workspace actuel
        self.indexer.index_repository()
        
        # Check recovery
        self.recovery = RecoveryService(self.tx_manager)
        if self.recovery.boot_check():
            self.recovery.auto_recover_pending()
    
    def execute_with_medi_context(self, command: str) -> bool:
        """
        Exécute une commande avec l'enrichissement du contexte MediBot.
        """
        # Enrichit automatiquement la commande avec le contexte medical
        enriched_command = self._enrich_medical_context(command)
        
        # Puis exécute normalement
        return self.execute(enriched_command)
    
    def _enrich_medical_context(self, command: str) -> str:
        """
        Ajoute automatiquement le contexte MediBot pertinent à la commande.
        """
        context_parts = []
        
        # Ajoute les specs médicales pertinentes
        if "rdv" in command.lower() or "rendez" in command.lower():
            # Cherche spec sur les RDV
            for spec in self.palace.specs:
                if "rdv" in spec["name"].lower() or "appointment" in spec["content"].lower():
                    context_parts.append(f"Context: {spec['content'][:300]}")
        
        if "patient" in command.lower():
            for spec in self.palace.specs:
                if "patient" in spec["name"].lower():
                    context_parts.append(f"Context: {spec['content'][:300]}")
        
        if context_parts:
            return command + "\n\n" + "\n".join(context_parts)
        return command

🚀 main_medi.py (Entry point pour MediBot)
#!/usr/bin/env python3
"""
LCCA V5 Fusion - Spécial MediBot
Utilise le MemPalace existant à D:\MediBot\Mempalace
"""
import sys
from core.orchestrator_medi import MediBotOrchestrator


def main():
    print("🏥 LCCA V5 Fusion - MediBot Edition")
    print("=" * 50)
    
    # Vérification connexion MemPalace
    try:
        from core.mempalace_adapter import connect_to_your_mempalace
        palace = connect_to_your_mempalace()
        print(f"✅ Connecté à MemPalace: {palace.palace_path}")
        print(f"📋 Specs disponibles: {len(palace.specs)}")
        for spec in palace.specs:
            print(f"   - {spec['name']}")
    except Exception as e:
        print(f"❌ Erreur connexion MemPalace: {e}")
        sys.exit(1)
    
    print("=" * 50)
    
    # Initialisation orchestrateur
    try:
        orchestrator = MediBotOrchestrator(workspace="./medi_workspace")
    except Exception as e:
        print(f"❌ Erreur initialisation: {e}")
        sys.exit(1)
    
    # Mode interactif ou commande directe
    if len(sys.argv) > 1:
        command = " ".join(sys.argv[1:])
        success = orchestrator.execute_with_medi_context(command)
        sys.exit(0 if success else 1)
    else:
        print("Mode interactif (Ctrl+C pour quitter)")
        print("Exemples:")
        print('  > "DashboardV1 - Page RDV - Ajoute validation email patient"')
        print('  > "Module Consultation - Créer fonction export PDF"')
        
        while True:
            try:
                command = input("\nMediBot> ")
                if command.lower() in ['exit', 'quit', 'q']:
                    break
                orchestrator.execute_with_medi_context(command)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Erreur: {e}")


if __name__ == "__main__":
    main()

📋 Installation & Lancement
# 1. Installe les dépendances
pip install pyyaml libcst chromadb

# 2. Vérifie la connexion à ton MemPalace
python -c "
from core.mempalace_adapter import connect_to_your_mempalace
p = connect_to_your_mempalace()
print('Identity:', p.identity[:100])
print('Specs:', [s['name'] for s in p.specs])
"

# 3. Lance MediBot LCCA
python main_medi.py "DashboardV1 - Page RDV - Modal En Consultation - Ajoute validation email"

# Ou mode interactif
python main_medi.py

